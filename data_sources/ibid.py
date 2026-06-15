# ============================================================
# scrapers/ibid.py
# IBID Astra (ibid.astra.co.id) is a React SPA — uses Playwright.
# ============================================================

import re
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

LOGIN_URL  = "https://www.ibid.astra.co.id/login"
SEARCH_URL = "https://www.ibid.astra.co.id/cari-lelang/mobil-bekas"


def _clean_price(text: str) -> Optional[int]:
    m = re.search(r"Rp[\s.]*([\d.,]+)", text.replace("\xa0", ""))
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def _clean_km(text: str) -> Optional[int]:
    m = re.search(r"([\d.,]+)\s*[kK][mM]", text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace(".", "")
    try:
        return int(raw)
    except ValueError:
        return None


class IBIDScraper:
    def __init__(self, config: dict):
        self.config   = config
        self.email    = config.get("IBID_EMAIL", "")
        self.password = config.get("IBID_PASSWORD", "")

    def _login(self, page) -> bool:
        try:
            page.goto(LOGIN_URL, wait_until="networkidle", timeout=30_000)
            time.sleep(2)

            for sel in ['input[type="email"]', 'input[name="email"]', '#email', 'input[placeholder*="email"]']:
                if page.locator(sel).count() > 0:
                    page.fill(sel, self.email)
                    break

            for sel in ['input[type="password"]', 'input[name="password"]', '#password', 'input[placeholder*="sandi"]']:
                if page.locator(sel).count() > 0:
                    page.fill(sel, self.password)
                    break

            # Click login button
            for sel in ['button[type="submit"]', 'button:has-text("Masuk")', 'button:has-text("Login")', 'input[type="submit"]']:
                btn = page.query_selector(sel)
                if btn:
                    btn.click()
                    break
            else:
                page.keyboard.press("Enter")

            page.wait_for_load_state("networkidle", timeout=20_000)
            return page.url != LOGIN_URL
        except Exception as e:
            logger.error(f"[IBID] Login failed: {e}")
            return False

    def _parse_card(self, card_el) -> Optional[dict]:
        try:
            text = card_el.inner_text()

            # Vehicle name
            name = ""
            for sel in ["h3", "h2", ".title", '[class*="title"]', '[class*="name"]']:
                el = card_el.query_selector(sel)
                if el:
                    name = el.inner_text().strip()
                    break
            if not name:
                name = text.split("\n")[0].strip()

            starting_price = _clean_price(text)
            mileage = _clean_km(text)

            year_m = re.search(r"\b(20\d{2}|19\d{2})\b", text)
            year = int(year_m.group(1)) if year_m else None

            plate_m = re.search(r"\b([A-Z]{1,2}\s+\d{1,4}\s+[A-Z]{1,3})\b", text)
            plate = plate_m.group(1) if plate_m else ""

            transmission = "Matic" if re.search(r"\bmatic\b|\batomatik\b", text, re.I) else (
                "Manual" if re.search(r"\bmanual\b", text, re.I) else ""
            )
            fuel = "Solar" if re.search(r"\b(solar|diesel)\b", text, re.I) else (
                "Bensin" if re.search(r"\bbensin\b|\bbenzin\b", text, re.I) else ""
            )

            # Location
            loc_m = re.search(
                r"(?:Lokasi|Kota|Cabang)\s*:?\s*([A-Za-z\s]+?)(?:\n|$|,)", text, re.I
            )
            location = loc_m.group(1).strip() if loc_m else ""

            # Auction date
            date_m = re.search(
                r"\b(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}|\d{4}[\/\-]\d{2}[\/\-]\d{2})\b", text
            )
            auction_date = date_m.group(1) if date_m else ""

            ext_m = re.search(r"Eksterior\s*:?\s*([A-F])", text, re.I)
            int_m = re.search(r"Interior\s*:?\s*([A-F])", text, re.I)
            eng_m = re.search(r"(?:Mesin|Engine)\s*:?\s*([A-F])", text, re.I)

            link_el = card_el.query_selector("a[href]")
            href = link_el.get_attribute("href") if link_el else ""
            if href and not href.startswith("http"):
                href = "https://www.ibid.astra.co.id" + href

            # IBID grade columns
            return {
                "source": "IBID",
                "unit_id": href.rstrip("/").split("/")[-1] if href else "",
                "listing_url": href,
                "lot": "",
                "vehicle_name": name,
                "plate": plate,
                "year": year,
                "mileage_km": mileage,
                "transmission": transmission,
                "fuel": fuel,
                "exterior_grade": ext_m.group(1) if ext_m else "",
                "interior_grade": int_m.group(1) if int_m else "",
                "engine_grade":   eng_m.group(1) if eng_m else "",
                "starting_price": starting_price,
                "ppn_flag": False,
                "auction_location": location,
                "auction_date": auction_date,
                "date_scraped": datetime.now().strftime("%Y-%m-%d"),
            }
        except Exception as e:
            logger.warning(f"[IBID] Card parse error: {e}")
            return None

    def run(self) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("[IBID] playwright not installed.")
            return []

        results  = []
        max_pages = self.config.get("MAX_PAGES", 20)
        headless  = self.config.get("HEADLESS", True)
        delay     = self.config.get("REQUEST_DELAY", 1.5)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless)
            ctx     = browser.new_context(locale="id-ID")
            page    = ctx.new_page()

            if self.email:
                ok = self._login(page)
                if not ok:
                    logger.warning("[IBID] Login may have failed — proceeding anyway.")
            else:
                logger.warning("[IBID] No credentials set.")

            for pg in range(1, max_pages + 1):
                url = f"{SEARCH_URL}?page={pg}"
                logger.info(f"[IBID] Page {pg}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                    time.sleep(delay)
                except Exception as e:
                    logger.error(f"[IBID] Navigation error: {e}")
                    break

                # Detect cards
                cards = []
                for sel in [
                    ".car-card", ".auction-item", ".vehicle-card",
                    '[class*="card"]', '[class*="item"]', "article",
                ]:
                    cards = page.query_selector_all(sel)
                    if cards:
                        break

                if not cards:
                    logger.info(f"[IBID] No cards on page {pg}. Stopping.")
                    break

                page_results = [r for c in cards if (r := self._parse_card(c))]
                results.extend(page_results)
                logger.info(f"[IBID] Page {pg}: {len(page_results)} listings")

                next_btn = page.query_selector(
                    'a[aria-label="Next"], button:has-text("Selanjutnya"), .pagination-next, [aria-label*="next"]'
                )
                if not next_btn or not next_btn.is_visible():
                    break

            browser.close()

        logger.info(f"[IBID] Total: {len(results)}")
        return results
