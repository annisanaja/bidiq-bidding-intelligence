# ============================================================
# scrapers/smartbid.py
# SmartBID is server-side rendered, uses requests + BeautifulSoup.
# No login required for public listings.
# ============================================================

import re
import time
import logging
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_LIST_URL = "https://smartbid.co.id/unit-lelang/smartbid"
BASE_DETAIL_URL = "https://smartbid.co.id/detail-unit/{}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}


def _clean_price(text: str) -> Optional[int]:
    """Extract integer IDR from 'Mulai dari Rp177.000.000' style strings."""
    m = re.search(r"Rp[\s]*([\d.,]+)", text.replace("\xa0", " "))
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _clean_km(text: str) -> Optional[int]:
    """Extract integer from '64,344 KM' or '64.344 KM'."""
    m = re.search(r"([\d.,]+)\s*KM", text, re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace(".", "")
    try:
        return int(raw)
    except ValueError:
        return None


class SmartBidScraper:
    def __init__(self, config: dict):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # Listing page

    def _parse_listing_card(self, anchor) -> Optional[dict]:
        """Parse one <a> card from the listing page."""
        try:
            href = anchor.get("href", "")
            if "/detail-unit/" not in href:
                return None

            unit_id = href.rstrip("/").split("/")[-1]
            text = anchor.get_text(" ", strip=True)

            # LOT number
            lot_m = re.search(r"LOT\s+(\d+)", text)
            lot = lot_m.group(1) if lot_m else ""

            # Starting price
            starting_price = _clean_price(text)

            # Year — last (YYYY) group
            year_m = re.findall(r"\((\d{4})\)", text)
            year = int(year_m[-1]) if year_m else None

            # Mileage
            mileage = _clean_km(text)

            # Grades
            ext_m = re.search(r"Eksterior\s+([A-F\-]+)", text)
            int_m = re.search(r"Interior\s+([A-F\-]+)", text)
            eng_m = re.search(r"Engine\s+([A-F\-]+)", text)

            exterior_grade = ext_m.group(1) if ext_m else ""
            interior_grade = int_m.group(1) if int_m else ""
            engine_grade   = eng_m.group(1) if eng_m else ""

            # Transmission / fuel
            transmission = "Matic" if "Matic" in text else ("Manual" if "Manual" in text else "")
            fuel = "Solar" if "Solar" in text else ("Bensin" if "Bensin" in text else "")

            # PPN flag
            ppn_flag = "PPN 1.1%" in text or "Dikenakan PPN" in text

            # Extract vehicle name (brand + model) — rough heuristic
            # "Mulai dari RpXXX BRAND MODEL ... (YEAR)"
            name_m = re.search(r"Rp[\d.,]+\s+([A-Z][A-Z\s\d]+?)\s+(?:[A-Z]{1,2}\s+\d{4}|\()", text)
            vehicle_name = name_m.group(1).strip() if name_m else ""

            # License plate  e.g. "B 1234 ABC"
            plate_m = re.search(r"\b([A-Z]{1,2}\s+\d{1,4}\s+[A-Z]{1,3})\b", text)
            plate = plate_m.group(1) if plate_m else ""

            # Auction location — text between "Support By :" and plate/year
            loc_m = re.search(r"Support By\s*:\s*([A-Z][A-Z\s\-\d]+?)(?:\s+[A-Z]{1,2}\s+\d{4}|\s+\()", text)
            auction_location = loc_m.group(1).strip() if loc_m else ""

            return {
                "source": "SMARTBID",
                "unit_id": unit_id,
                "listing_url": href if href.startswith("http") else f"https://smartbid.co.id{href}",
                "lot": lot,
                "vehicle_name": vehicle_name,
                "plate": plate,
                "year": year,
                "mileage_km": mileage,
                "transmission": transmission,
                "fuel": fuel,
                "exterior_grade": exterior_grade,
                "interior_grade": interior_grade,
                "engine_grade": engine_grade,
                "starting_price": starting_price,
                "ppn_flag": ppn_flag,
                "auction_location": auction_location,
                "date_scraped": datetime.now().strftime("%Y-%m-%d"),
            }
        except Exception as e:
            logger.warning(f"Card parse error: {e}")
            return None

    def scrape_listings(self) -> list[dict]:
        """Scrape all listing pages and return raw row dicts."""
        results = []
        page = 1
        max_pages = self.config.get("MAX_PAGES", 20)
        delay = self.config.get("REQUEST_DELAY", 1.5)

        while page <= max_pages:
            url = f"{BASE_LIST_URL}?page={page}"
            logger.info(f"[SmartBID] Fetching listing page {page}: {url}")
            try:
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"[SmartBID] Request failed on page {page}: {e}")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            anchors = soup.find_all("a", href=re.compile(r"/detail-unit/\d+"))

            if not anchors:
                logger.info(f"[SmartBID] No more listings at page {page}.")
                break

            page_results = [r for a in anchors if (r := self._parse_listing_card(a))]
            results.extend(page_results)
            logger.info(f"[SmartBID] Page {page}: {len(page_results)} listings")

            # Check for next page link
            next_link = soup.find("a", string=re.compile(r"^>$"))
            if not next_link:
                break

            page += 1
            time.sleep(delay)

        logger.info(f"[SmartBID] Total listings: {len(results)}")
        return results

    # Detail page

    def scrape_detail(self, unit_id: str) -> dict:
        """Fetch detail page and return extra fields."""
        url = BASE_DETAIL_URL.format(unit_id)
        try:
            resp = self.session.get(url, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"[SmartBID] Detail fetch failed {unit_id}: {e}")
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        extra = {}

        # Key info table
        for row in soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 3:
                key = cells[0].lower().replace(" ", "_").replace(".", "")
                val = cells[2]
                mapping = {
                    "merk":             "brand",
                    "series":           "series",
                    "no_polisi":        "plate",
                    "transmisi":        "transmission",
                    "tahun":            "year",
                    "kapasitas_mesin_(cc)": "engine_cc",
                    "odometer":         "mileage_km_detail",
                    "no_rangka":        "chassis_no",
                    "no_mesin":         "engine_no",
                    "warna":            "color",
                    "stnk":             "stnk",
                    "pajak_stnk":       "stnk_tax_date",
                    "bpkb":             "bpkb",
                    "faktur":           "faktur",
                    "fk_ktp":           "fk_ktp",
                    "kwt_blangko":      "kwt",
                    "form_a":           "form_a",
                    "keur":             "keur",
                }
                if key in mapping:
                    extra[mapping[key]] = val

        # Auction schedule
        sched_div = soup.find(string=re.compile("Jadwal Lelang"))
        if sched_div:
            parent = sched_div.find_parent()
            if parent:
                sibling = parent.find_next_sibling()
                if sibling:
                    extra["auction_date"] = sibling.get_text(strip=True)

        # Location link  e.g. <a href="/unit-lelang/6907">ADIRA HI</a>
        loc_link = soup.find("a", href=re.compile(r"/unit-lelang/\d+"))
        if loc_link:
            extra["auction_location"] = loc_link.get_text(strip=True)

        return extra

    # Main entry point

    def run(self) -> list[dict]:
        rows = self.scrape_listings()
        if self.config.get("SCRAPE_DETAILS", True):
            delay = self.config.get("REQUEST_DELAY", 1.5)
            for i, row in enumerate(rows):
                if row.get("unit_id"):
                    extra = self.scrape_detail(row["unit_id"])
                    row.update(extra)
                    if i % 20 == 0:
                        logger.info(f"[SmartBID] Detail {i}/{len(rows)}")
                    time.sleep(delay)
        return rows
