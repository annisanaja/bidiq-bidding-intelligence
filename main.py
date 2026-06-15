# main.py  --  Daily auction data pull

import argparse
import logging
import sys
from datetime import datetime

from config import CONFIG
from scrapers import SmartBidScraper, JBAScraper, IBIDScraper
from sheets import write_auction_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")


def run(config: dict, site_filter: str = "") -> None:
    logger.info("=" * 60)
    logger.info(f"Auction data pull started at {datetime.now()}")
    logger.info("=" * 60)

    all_rows: list[dict] = []

    scrapers = {
        "smartbid": SmartBidScraper,
        "jba":      JBAScraper,
        "ibid":     IBIDScraper,
    }

    for key, ScraperClass in scrapers.items():
        if site_filter and site_filter.lower() != key:
            continue
        logger.info(f"Starting {key.upper()} scraper...")
        try:
            rows = ScraperClass(config).run()
            logger.info(f"{key.upper()} returned {len(rows)} rows.")
            all_rows.extend(rows)
        except Exception as e:
            logger.error(f"{key.upper()} scraper failed: {e}", exc_info=True)

    if not all_rows:
        logger.warning("No rows collected. Exiting.")
        return

    logger.info(f"Total rows collected: {len(all_rows)}")

    print("\n" + "=" * 60)
    print(f"  AUCTION DATA PULL  ({datetime.now().date()})")
    print("=" * 60)
    for row in all_rows[:20]:
        print(
            f"  {row.get('source', '?'):8s} "
            f"{row.get('vehicle_name', '?'):35s} "
            f"Rp{row.get('starting_price', 0) or 0:>12,}  "
            f"{row.get('auction_location', '?')}"
        )
    if len(all_rows) > 20:
        print(f"  ... and {len(all_rows) - 20} more rows")
    print("=" * 60 + "\n")

    write_auction_data(all_rows, config)
    logger.info("Done.")


def auth_only(config: dict) -> None:
    logger.info("Running Google OAuth flow...")
    from sheets import _get_credentials
    _get_credentials(config)
    logger.info("Authentication successful. token.pickle saved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auction scraper")
    parser.add_argument("--auth",       action="store_true", help="Authenticate with Google only")
    parser.add_argument("--site",       default="",          help="Scrape one site: jba | ibid | smartbid")
    parser.add_argument("--with-details", action="store_true", help="Fetch detail pages (slower, adds chassis/engine/doc fields)")
    args = parser.parse_args()

    if args.with_details:
        CONFIG["SCRAPE_DETAILS"] = True

    if args.auth:
        auth_only(CONFIG)
    else:
        run(CONFIG, site_filter=args.site)
