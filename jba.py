# ============================================================
# scrapers/jba.py
#
# JBA car-auction scraper, NO login required.
#
# Strategy
# --------
# 1. Fetch https://www.jba.co.id/id/jadwal-lelang to collect
#    upcoming-session IDs from links like /id/lelang-mobil/detail/{id}.
#
# 2. Bootstrap: scrape page 1 of the first few jadwal sessions and
#    collect every session ID that appears in the recommendations
#    section (cross-session vehicle links). This reliably discovers
#    TODAY'S active sessions even when they're not yet listed in jadwal.
#
# 3. For each unique session ID, page through
#    /id/lelang-mobil/detail/{session_id}/page/{n}
#    until no vehicle cards are found.
#
# 4. Parse each card with BeautifulSoup + regex (no browser needed).
#
# All target pages are server-rendered — requests + BeautifulSoup only.
# ============================================================

import re
import time
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://www.jba.co.id"

# Known label strings that appear in the detail page spec/document tables.
_DETAIL_LABELS = {
    "Merk", "Jenis", "Tahun", "Transmisi",
    "Kapasitas Mesin (cc)", "Bahan Bakar", "Odometer",
    "Nomor Rangka", "Nomor Mesin",
    "Nomor Polisi", "Warna", "STNK", "Masa Berlaku STNK",
    "BPKB", "Faktur",
    "Foto Kopi KTP", "Kwitansi Blanko", "Form A", "SPH", "KEUR",
}


_STOP_WORDS = {
    # Transmission / drivetrain
    "CVT", "AT", "MT", "AMT", "AGS", "DCT",
    "FWD", "AWD", "4WD", "4X4", "RWD",
    # Engine / tech
    "VTEC", "MIVEC", "DOHC", "SOHC", "TURBO", "HYBRID",
    "HEV", "PHEV", "EV", "MHEV",
    # Common variant / trim names (multi-letter, so not caught by len==1 rule)
    "RS", "SE", "LS", "GS", "GT", "GL",
    "PRESTIGE", "SPORT", "SPORTY", "LUXURY", "URBAN", "ACTIVE",
    "ELEGANT", "TREND", "DELUXE", "EXCLUSIVE", "CLASSIC", "PREMIUM",
    "SPECIAL", "LIMITED", "ANNIVERSARY", "EDITION",
    "VELOZ", "VENTURER", "ZENIX", "SENSING",
    "PACKAGE", "MAESTRO",
}
# Keep old name as alias so nothing else breaks
_POWERTRAIN_STOPS = _STOP_WORDS


def _extract_series(jenis: str) -> str:
    """
    Extract model-family name from the Jenis/vehicle-name string,
    stopping before variant/grade/powertrain codes.

    "TERIOS X 1.5"           → "TERIOS"
    "CR-V PRESTIGE 1.5"      → "CR-V"
    "KIJANG INNOVA 2.0 G"    → "KIJANG INNOVA"
    "JAZZ RS CVT"            → "JAZZ"
    "AVANZA VELOZ 1.5"       → "AVANZA"
    "ALPHARD G SC PACKAGE"   → "ALPHARD"
    """
    words = jenis.upper().split()
    series_words: list[str] = []
    for word in words:
        if re.match(r'^\d', word):    # starts with digit → cc/variant code
            break
        if len(word) == 1:            # single letter → grade (G, E, X, V…)
            break
        if word in _STOP_WORDS:       # known powertrain/variant/trim word
            break
        series_words.append(word)
    return " ".join(series_words) if series_words else (words[0] if words else "")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Referer": "https://www.jba.co.id/id/jadwal-lelang",
}


class JBAScraper:
    """
    Scrapes JBA car-auction listings without login.

    Returns a list of dicts conforming to the RAW_COLUMNS schema
    defined in sheets.py.
    """

    SOURCE = "JBA"

    def __init__(self, config: dict):
        self.config = config
        self.delay = float(config.get("REQUEST_DELAY", 1.0))
        self.max_pages = int(config.get("MAX_PAGES", 20))
        self.session = requests.Session()
        self.session.headers.update(_HEADERS)

    # Public entry point

    def run(self) -> list[dict]:
        sessions = self._discover_sessions()
        logger.info(f"[JBA] Discovered {len(sessions)} sessions to scrape.")

        rows: list[dict] = []
        seen_vehicle_ids: set[str] = set()

        for sid, meta in sessions.items():
            session_rows = self._scrape_session(sid, meta, seen_vehicle_ids)
            logger.info(
                f"[JBA] Session {sid} ({meta.get('auction_location', '?')}): "
                f"{len(session_rows)} vehicles."
            )
            rows.extend(session_rows)

        logger.info(f"[JBA] Grand total: {len(rows)} vehicles.")
        return rows

    # Session discovery

    def _discover_sessions(self) -> dict[str, dict]:
        """
        Returns {session_id: meta_dict} for all sessions to scrape.

        Sources (in order):
        1. /id/jadwal-lelang — upcoming/scheduled sessions.
        2. Bootstrap: scrape page 1 of the first few jadwal sessions to
           collect cross-session IDs from the recommendations section.
           This catches today's LIVE sessions that may not appear in jadwal.
        """
        sessions: dict[str, dict] = {}

        # Source 1: jadwal-lelang page 
        jadwal_soup = self._fetch(f"{BASE_URL}/id/jadwal-lelang")
        if jadwal_soup:
            for a in jadwal_soup.find_all(
                "a", href=re.compile(r"/id/lelang-mobil/detail/(\d+)$")
            ):
                sid = re.search(r"/detail/(\d+)$", a["href"]).group(1)
                if sid not in sessions:
                    sessions[sid] = self._meta_from_jadwal_link(a, sid)

        logger.info(f"[JBA] jadwal-lelang gave {len(sessions)} session IDs.")

        # Cap jadwal sessions to the nearest N 
        # jadwal lists ALL upcoming sessions (40+ is common). Sessions beyond
        # the next day or two have no vehicles yet. Since jadwal is ordered
        # nearest-first, just take the first MAX_JADWAL_SESSIONS entries.
        max_jadwal = int(self.config.get("MAX_JADWAL_SESSIONS", 8))
        if len(sessions) > max_jadwal:
            trimmed_keys = list(sessions.keys())[:max_jadwal]
            sessions = {k: sessions[k] for k in trimmed_keys}
            logger.info(f"[JBA] Capped to {max_jadwal} nearest jadwal sessions.")

        # Source 2: bootstrap from first few jadwal sessions
        # The recommendation section on each session page cross-references
        # vehicles from OTHER active sessions — this is how we find today's
        # live sessions that may not yet appear in jadwal.
        bootstrap_sids: set[str] = set()
        for sid in list(sessions.keys())[:5]:   # check up to 5 jadwal sessions
            page_soup = self._fetch(
                f"{BASE_URL}/id/lelang-mobil/detail/{sid}/page/1"
            )
            if not page_soup:
                continue
            for a in page_soup.find_all(
                "a",
                href=re.compile(r"/id/lelang-mobil/detail-vehicle/(\d+)/\d+"),
            ):
                cross_sid = re.search(
                    r"/detail-vehicle/(\d+)/", a["href"]
                ).group(1)
                if cross_sid not in sessions:
                    bootstrap_sids.add(cross_sid)

        if bootstrap_sids:
            logger.info(
                f"[JBA] Bootstrap discovered {len(bootstrap_sids)} extra sessions: "
                + ", ".join(sorted(bootstrap_sids))
            )
            for sid in bootstrap_sids:
                sessions[sid] = {
                    "session_id":       sid,
                    "auction_location": f"JBA - SESSION {sid}",
                    "auction_date":     "",
                }

        return sessions

    def _meta_from_jadwal_link(self, a_tag, sid: str) -> dict:
        """Extract auction location and date from a jadwal anchor tag."""
        text = a_tag.get_text(" ", strip=True)
        # e.g. "Belum Mulai Jakarta Raya - Mobil 12 May 2026 13:00 WIB"
        meta = {"session_id": sid, "auction_location": "", "auction_date": ""}

        city_m = re.search(
            r'(?:Mulai|LIVE|Selesai)\s+(.+?)\s+\d{1,2}\s+\w+\s+\d{4}',
            text,
            re.IGNORECASE,
        )
        if city_m:
            meta["auction_location"] = f"JBA - {city_m.group(1).upper()}"

        date_m = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', text)
        if date_m:
            meta["auction_date"] = date_m.group(1)

        return meta

    # Session scraping

    def _scrape_session(
        self,
        session_id: str,
        meta: dict,
        seen_vehicle_ids: set,
    ) -> list[dict]:
        rows: list[dict] = []

        for page_num in range(1, self.max_pages + 1):
            if page_num == 1:
                url = f"{BASE_URL}/id/lelang-mobil/detail/{session_id}"
            else:
                url = (
                    f"{BASE_URL}/id/lelang-mobil/detail/{session_id}"
                    f"/page/{page_num}"
                )

            soup = self._fetch(url)
            if not soup:
                break

            # Enrich meta from the session heading on page 1
            if page_num == 1:
                meta = self._enrich_meta_from_session_page(soup, session_id, meta)

            cards = self._parse_page(soup, session_id, meta, seen_vehicle_ids)
            if not cards:
                logger.debug(
                    f"[JBA] Session {session_id} page {page_num}: "
                    f"0 cards — stopping."
                )
                break

            rows.extend(cards)
            logger.debug(
                f"[JBA] Session {session_id} page {page_num}: {len(cards)} cards."
            )

            if not self._has_next_page(soup, session_id, page_num):
                break

        return rows

    def _enrich_meta_from_session_page(
        self, soup: BeautifulSoup, session_id: str, meta: dict
    ) -> dict:
        """
        Pull auction location and date from the session detail page heading.
        e.g. 'Daftar Mobil Lelang - Jakarta Raya - Mobil' + '09 June 2026'
        """
        h2 = soup.find("h2")
        if h2:
            h2_text = h2.get_text(" ", strip=True)
            loc_m = re.search(r'Lelang\s*-\s*(.+)', h2_text, re.IGNORECASE)
            if loc_m:
                meta["auction_location"] = f"JBA - {loc_m.group(1).strip().upper()}"

        if not meta.get("auction_date"):
            full_text = soup.get_text(" ")
            date_m = re.search(
                r'\b(\d{1,2})\s+'
                r'(January|February|March|April|May|June|July|August|'
                r'September|October|November|December|'
                r'Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|'
                r'September|Oktober|November|Desember)'
                r'\s+(\d{4})\b',
                full_text,
                re.IGNORECASE,
            )
            if date_m:
                meta["auction_date"] = date_m.group(0)

        return meta

    def _has_next_page(
        self, soup: BeautifulSoup, session_id: str, current_page: int
    ) -> bool:
        next_page = current_page + 1
        return bool(
            soup.find(
                "a",
                href=re.compile(
                    rf"/id/lelang-mobil/detail/{session_id}/page/{next_page}"
                ),
            )
        )

    # Page parsing

    def _parse_page(
        self,
        soup: BeautifulSoup,
        session_id: str,
        meta: dict,
        seen_vehicle_ids: set,
    ) -> list[dict]:
        rows: list[dict] = []

        vehicle_anchors = soup.find_all(
            "a",
            href=re.compile(
                rf"/id/lelang-mobil/detail-vehicle/{session_id}/(\d+)"
            ),
        )

        for a in vehicle_anchors:
            href = a.get("href", "")
            vid_m = re.search(r"/detail-vehicle/\d+/(\d+)", href)
            if not vid_m:
                continue
            vehicle_id = vid_m.group(1)

            # Global dedup — recommendations repeat vehicles across sessions/pages
            if vehicle_id in seen_vehicle_ids:
                continue
            seen_vehicle_ids.add(vehicle_id)

            lot_no = self._find_lot_no(a)
            card_text = a.get_text("\n", strip=True)
            row = self._parse_card_text(card_text, meta)
            if not row:
                continue

            row["lot"]          = lot_no
            row["listing_url"]  = BASE_URL + href
            row["unit_id"]      = vehicle_id
            row["source"]       = self.SOURCE
            row["date_scraped"] = datetime.now().strftime("%Y-%m-%d")

            # Enrich from detail page
            if self.config.get("SCRAPE_DETAILS", False):
                detail = self._fetch_vehicle_detail(session_id, vehicle_id)
                if detail:
                    row.update(detail)   # detail values override card values

            rows.append(row)

        return rows

    def _find_lot_no(self, anchor_tag) -> str:
        """
        Walk up the DOM tree (up to 6 levels) looking for 'LOT No. X'
        in a sibling or parent element of this anchor.
        """
        parent = anchor_tag.parent
        for _ in range(6):
            if parent is None:
                break
            for child in parent.children:
                if child is anchor_tag:
                    continue
                t = (
                    child.get_text(" ", strip=True)
                    if hasattr(child, "get_text")
                    else str(child).strip()
                )
                m = re.search(r'LOT\s*No\.?\s*(\d+)', t, re.IGNORECASE)
                if m:
                    return m.group(1)
            parent = parent.parent
        return ""

    # Card text parser

    def _parse_card_text(self, text: str, meta: dict) -> Optional[dict]:
        """
        Parse the get_text("\\n") output of a vehicle anchor tag.

        Typical structure (each line = one HTML element):
            veicle picture          <- img alt text (ignored)
            Harga Dasar Rp 190.000.000
            TOYOTA INNOVA G 2.0
            126 2                   <- watcher / bid counts (ignored)
            JBA - JAKARTA RAYA
            Batas Pelunasan ...     (ignored)
            Info Kendaraan 2020 AT 83,645 B 2988 BRJ Bensin 25/01/2027
            Grade KendaraanCMesin CExterior BInterior
        """
        if not text or "Harga Dasar" not in text:
            return None

        row: dict = {}

        # Starting price
        price_m = re.search(r'Harga Dasar\s+Rp\s*([\d.,]+)', text)
        if price_m:
            raw = price_m.group(1).replace(".", "").replace(",", "")
            row["starting_price"] = int(raw) if raw.isdigit() else None
        else:
            row["starting_price"] = None

        # Vehicle name 
        # The vehicle name is the non-numeric line immediately after the price line.
        # Card HTML often emits the price value as TWO separate elements:
        #   "Harga Dasar Rp 108.000.000"  (label+value merged in one block)
        #   "Rp 108.000.000"              (standalone value badge)
        #   "DAIHATSU TERIOS X 1.5"       ← actual name
        # We must skip the standalone price line too.
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        vehicle_name = ""
        after_price = False
        for line in lines:
            if re.match(r'Harga Dasar', line, re.IGNORECASE):
                after_price = True
                continue
            if after_price:
                # Skip pure-number lines (bid/watcher counts)
                if re.match(r'^[\d\s]+$', line):
                    continue
                # Skip image alt text
                if "veicle picture" in line.lower() or "gambar" in line.lower():
                    continue
                # Skip standalone price value lines: "Rp 108.000.000"
                if re.match(r'^Rp\s*[\d.,]+$', line, re.IGNORECASE):
                    continue
                vehicle_name = line.strip()
                break

        # Fallback: first ALLCAPS multi-word line that isn't a location/label
        if not vehicle_name:
            for line in lines:
                if (
                    re.match(r'^[A-Z][A-Z0-9 \-./]+$', line)
                    and not line.startswith("JBA")
                    and not line.startswith("INFO")
                    and not line.startswith("GRADE")
                    and not line.startswith("BATAS")
                    and len(line.split()) >= 2
                ):
                    vehicle_name = line
                    break

        # Build brand + series, then vehicle_name = brand + series (no variant)
        name_parts = vehicle_name.split(" ", 1)
        brand  = name_parts[0].strip() if name_parts else ""
        series = _extract_series(name_parts[1]) if len(name_parts) > 1 else ""
        row["brand"]        = brand
        row["series"]       = series
        row["vehicle_name"] = f"{brand} {series}".strip() if series else brand

        # Auction location
        loc_m = re.search(r'(JBA\s*-\s*[A-Za-z][A-Za-z\s\-]+?)(?:\n|Batas)', text)
        if loc_m:
            row["auction_location"] = loc_m.group(1).strip().upper()
        else:
            loc_m2 = re.search(r'JBA\s*-\s*([A-Z ]+)', text)
            row["auction_location"] = (
                f"JBA - {loc_m2.group(1).strip()}"
                if loc_m2
                else meta.get("auction_location", "")
            )

        # Info Kendaraan 
        # Format: Info Kendaraan {year} {trans} {mileage} {plate} {fuel} {tax_date}
        # Trans:  AT | MT | Lain-lain
        # Fuel:   Bensin | Solar | Listrik | Hybrid | Lain-lain
        info_m = re.search(
            r'Info Kendaraan\s+'
            r'(\d{4})\s+'                                            # year
            r'(AT|MT|Lain-lain)\s+'                                 # transmission
            r'([\d,]+)\s+'                                           # mileage
            r'([A-Z]{1,3}\s+\d+\s+[A-Z]{1,4})\s+'                 # plate
            r'(Bensin|Solar|Listrik|Hybrid|Lain-lain)\s*'           # fuel
            r'(\d{2}/\d{2}/\d{4}|-)?',                             # tax date (opt)
            text,
        )
        if info_m:
            row["year"]          = int(info_m.group(1))
            trans_raw            = info_m.group(2)
            row["transmission"]  = None if trans_raw == "Lain-lain" else trans_raw
            row["mileage_km"]    = int(info_m.group(3).replace(",", ""))
            row["plate"]         = info_m.group(4).strip()
            fuel_raw             = info_m.group(5)
            row["fuel"]          = None if fuel_raw == "Lain-lain" else fuel_raw
            tax_raw              = (info_m.group(6) or "").strip()
            row["stnk_tax_date"] = tax_raw if tax_raw else None
            # Derive stnk status from tax date (detail page will override if fetched)
            row["stnk"]          = "Ada" if (tax_raw and tax_raw != "-") else "Tidak Ada"
        else:
            # Looser fallback — grab year only
            year_m = re.search(r'Info Kendaraan\s+(\d{4})', text)
            row["year"]          = int(year_m.group(1)) if year_m else None
            row["transmission"]  = None
            row["mileage_km"]    = None
            row["plate"]         = None
            row["fuel"]          = None
            row["stnk_tax_date"] = None
            row["stnk"]          = None

        # Grades
        # The card renders grade letters BEFORE the label ("C Mesin C Exterior C Interior").
        # Search for each label independently so the order in the text doesn't matter.
        # Handles both "C Mesin" (grade-before) and "Mesin C" (grade-after) layouts.
        for _label, _col in [
            ("Mesin",    "engine_grade"),
            ("Exterior", "exterior_grade"),
            ("Interior", "interior_grade"),
        ]:
            _m = re.search(rf'([A-E])\s*{_label}', text)   # grade before label
            if not _m:
                _m = re.search(rf'{_label}\s*([A-E])', text)  # grade after label
            row[_col] = _m.group(1) if _m else None

        # Auction date from session meta
        row["auction_date"] = meta.get("auction_date", "")

        # Fields not available in listing preview
        row["color"]      = None
        row["stnk"]       = None
        row["bpkb"]       = None
        row["faktur"]     = None
        row["chassis_no"] = None
        row["engine_no"]  = None
        row["engine_cc"]  = None

        # JBA charges auction fee — flag True so profitability.py applies it
        row["ppn_flag"] = True

        return row

    # Vehicle detail page

    def _parse_detail_kv(self, soup: BeautifulSoup) -> dict:
        """
        The detail page renders spec/document tables as alternating label/value
        lines in the rendered text:
            Merk
            DAIHATSU
            Jenis
            TERIOS X 1.5
            ...
        We match each line against the known label set and take the next
        non-empty, non-label line as the value.
        """
        lines = [ln.strip() for ln in soup.get_text("\n").split("\n") if ln.strip()]
        kv: dict = {}
        for i, line in enumerate(lines):
            if line in _DETAIL_LABELS and i + 1 < len(lines):
                val = lines[i + 1]
                if val not in _DETAIL_LABELS:   # skip if next line is also a label
                    kv[line] = val
        return kv

    def _fetch_vehicle_detail(self, session_id: str, vehicle_id: str) -> dict:
        """
        Fetch /id/lelang-mobil/detail-vehicle/{session_id}/{vehicle_id} and
        return a dict of enriched fields to merge into the card row.

        Fields returned (all optional, only set when found):
          brand, series, vehicle_name, year, transmission, fuel, mileage_km,
          engine_cc, chassis_no, engine_no, plate, color,
          stnk, stnk_tax_date, bpkb, faktur,
          auction_date (DD/MM/YYYY), lot
        """
        url = f"{BASE_URL}/id/lelang-mobil/detail-vehicle/{session_id}/{vehicle_id}"
        soup = self._fetch(url)
        if not soup:
            return {}

        kv   = self._parse_detail_kv(soup)
        text = soup.get_text(" ")
        out: dict = {}

        # Brand / series / vehicle name 
        merk  = kv.get("Merk",  "").strip().upper()
        jenis = kv.get("Jenis", "").strip().upper()
        if merk:
            out["brand"] = merk
        if jenis:
            out["series"]       = _extract_series(jenis)
            out["vehicle_name"] = f"{merk} {out['series']}".strip()

        # Numeric / coded spec fields 
        tahun = kv.get("Tahun", "")
        if tahun.isdigit():
            out["year"] = int(tahun)

        trans = kv.get("Transmisi", "")
        if trans and trans != "Lain-lain":
            out["transmission"] = trans

        cc_m = re.search(r'(\d+)', kv.get("Kapasitas Mesin (cc)", ""))
        if cc_m:
            out["engine_cc"] = int(cc_m.group(1))

        fuel = kv.get("Bahan Bakar", "")
        if fuel and fuel != "Lain-lain":
            out["fuel"] = fuel

        odo_m = re.search(r'([\d,]+)', kv.get("Odometer", ""))
        if odo_m:
            out["mileage_km"] = int(odo_m.group(1).replace(",", ""))

        # Identity fields 
        for src_key, dst_key in [
            ("Nomor Rangka", "chassis_no"),
            ("Nomor Mesin",  "engine_no"),
            ("Nomor Polisi", "plate"),
            ("Warna",        "color"),
            ("BPKB",         "bpkb"),
            ("Faktur",       "faktur"),
        ]:
            val = kv.get(src_key, "").strip()
            if val and val != "—":
                out[dst_key] = val

        # STNK
        stnk_val = kv.get("STNK", "").strip()
        if stnk_val:
            out["stnk"] = stnk_val          # "Ada" or "Tidak Ada"

        stnk_date = kv.get("Masa Berlaku STNK", "").strip()
        out["stnk_tax_date"] = stnk_date if stnk_date else None

        # Auction date (DD/MM/YYYY) from sidebar 
        date_m = re.search(r'Tanggal Lelang[:\s]*(\d{2}/\d{2}/\d{4})', text)
        if date_m:
            out["auction_date"] = date_m.group(1)

        # Lot number 
        lot_m = re.search(r'\bLOT\s+(?:No\.?\s*)?(\d+)\b', text, re.IGNORECASE)
        if lot_m:
            out["lot"] = lot_m.group(1)

        return out

    # HTTP helper 

    def _fetch(self, url: str) -> Optional[BeautifulSoup]:
        time.sleep(self.delay)
        try:
            resp = self.session.get(url, timeout=25)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            if code == 404:
                logger.debug(f"[JBA] 404 — session not found: {url}")
            else:
                logger.error(f"[JBA] HTTP {code} fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"[JBA] Failed to fetch {url}: {e}")
            return None
