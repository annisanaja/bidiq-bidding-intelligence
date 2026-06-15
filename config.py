# ============================================================
# config.py  —  Edit these values before first run
# ============================================================

CONFIG = {
    # ── Google Sheets ──────────────────────────────────────────────────────────
    # Paste your Sheet ID here after step 3 in SETUP_GUIDE.md
    # (It's the long string in the URL: …/d/<SHEET_ID>/edit)
    "SPREADSHEET_ID": "",

    # Download from Google Cloud Console → APIs & Services → Credentials
    "CREDENTIALS_FILE": "credentials.json",

    # Auto-generated on first run — do not edit
    "TOKEN_FILE": "token.pickle",

    # ── Your Home City ─────────────────────────────────────────────────────────
    # Must match a key in transport_fees.py  (case-insensitive)
    # e.g. "JAKARTA", "SURABAYA", "BANDUNG", "MEDAN", "MAKASSAR"
    "USER_CITY": "JAKARTA",

    # ── Fee Structure ──────────────────────────────────────────────────────────
    "AUCTION_FEE_PCT":  0.011,       # 1.1% — applied when "PPN 1.1%" is flagged
    "ADMIN_FEE_FLAT":   150_000,     # Rp 150 k flat (some ADIRA lots)

    # ── Site Credentials ──────────────────────────────────────────────────────
    "JBA_EMAIL":    "",
    "JBA_PASSWORD": "",

    "IBID_EMAIL":    "",
    "IBID_PASSWORD": "",

    "SMARTBID_EMAIL":    "",         # Not required for public listings
    "SMARTBID_PASSWORD": "",

    # ── Scraping Behaviour ─────────────────────────────────────────────────────
    "MAX_PAGES":        20,          # Max listing pages per site (~50 results each)
    "REQUEST_DELAY":    1.5,         # Seconds between HTTP requests
    "HEADLESS":         True,        # Set False to watch the browser while debugging
    "SCRAPE_DETAILS":   True,        # Fetch individual detail pages (slower but richer)

    # ── Carmudi ────────────────────────────────────────────────────────────────
    "CARMUDI_MAX_RESULTS": 5,        # Retail listings fetched per make/model/year combo
}
