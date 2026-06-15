# 🚗 BidIQ: Smart Bidding Intelligence
### Automated Indonesian Car Auction Intelligence System

![Python](https://img.shields.io/badge/Python-3.10-blue?style=flat&logo=python)
![Playwright](https://img.shields.io/badge/Playwright-Scraping-2EAD33?style=flat&logo=playwright)
![Google Sheets](https://img.shields.io/badge/Google%20Sheets-Live%20Data-34A853?style=flat&logo=google-sheets)
![Status](https://img.shields.io/badge/Status-Live-brightgreen?style=flat)
![Dashboard](https://img.shields.io/badge/Dashboard-bidiq.tiiny.site-7F77DD?style=flat)

> **Live dashboard → [bidiq.tiiny.site](https://bidiq.tiiny.site)**

---

## 📌 Overview
<img width="1600" height="670" alt="image" src="https://github.com/user-attachments/assets/71e2ca8c-595a-4fbb-8f19-976b261de04f" />

BidIQ is an end-to-end auction intelligence system built to solve a real personal problem: **how do you know whether to bid on a car at auction without spending hours manually researching each lot?**

The system scrapes three major Indonesian car auction platforms every morning, computes profitability for each lot against average retail prices for similar vehicles, applies a scoring and decision model (BID / MAYBE / SKIP), and writes everything to Google Sheets which feeds a live interactive dashboard.

The entire pipeline runs with a single command:

```bash
python main.py
```

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DATA SOURCES                         │
│  JBA (Playwright) · IBID (Playwright) · SmartBID (HTML) │
└──────────────────────────┬──────────────────────────────┘
                           │ raw lot data
                           ▼
┌─────────────────────────────────────────────────────────┐
│          PROFITABILITY ENGINE (profitability.py)        │                                                       
│  total_cost = start_price + auction_fee + transport_fee │
│  profit     = retail_price - total_cost                 │
│  margin_%   = profit / retail_price × 100               │
│  roi_%      = profit / total_cost × 100                 │
└──────────────────────────┬──────────────────────────────┘
                           │ enriched rows
                           ▼
┌─────────────────────────────────────────────────────────┐
│            GOOGLE SHEETS (sheets.py / OAuth)            │
│  Tab 1: Raw Data  (every lot, all fields)               │
│  Tab 2: Daily Summary  (aggregated KPIs per source)     │
│  Tab 3: Filtered  (decision-ready view for dashboard)   │
└──────────────────────────┬──────────────────────────────┘
                           │ published CSV
                           ▼
┌─────────────────────────────────────────────────────────┐
│         BIDIQ DASHBOARD  (bidiq_dashboard.html)         │
│  Live filters · Sortable table · Decision badges        │
│  IDR formatting · ROI charts · Export CSV               │
└─────────────────────────────────────────────────────────┘
```

---

## ✨ Features

### Scraping
- Scrapes **JBA**, **IBID Astra**, and **SmartBID**, three of Indonesia's largest car auction platforms
- Uses **Playwright** for JavaScript-heavy sites (JBA, IBID) and **requests + BeautifulSoup** for static pages
- Fetches detail pages for each lot (chassis number, engine number, BPKB/STNK/Faktur status, grade scores)
- Respects rate limits and runs headless by default

### Profitability Engine
- Calculates **auction fee** (1.1% PPN where applicable)
- Looks up **transport fee** from a city-pair matrix covering 25+ Indonesian city routes
- Computes **estimated profit**, **margin %**, and **ROI %** per lot
- Falls back gracefully when retail price is unavailable

### Decision Logic
- Applies a composite **Score** and **Decision** (BID / MAYBE / SKIP) to each lot
- Decisions factor in ROI %, margin %, vehicle grade, and document completeness

### Dashboard
- Single-file HTML dashboard that loads live from Google Sheets CSV
- **8 filters**: brand, series, year, location, transmission, fuel, min ROI, decision
- **Sortable table** with 21 columns including chassis/engine numbers and listing URLs
- **Real-time metrics**: total BID/MAYBE/SKIP counts, avg ROI, avg margin, total investment
- **IDR currency formatting** with Indonesian locale (Rp 185 jt, Rp 1,2 M)
- Export filtered view as CSV

---

## 📂 Project Structure

```
BidIQ/
│
├── config.py               # Initial setup
├── main.py                 # CLI entry point & orchestrator
│
├── scrapers/
│   ├── __init__.py         # Initial config
│   ├── jba.py              # JBA Playwright scraper
│   ├── ibid.py             # IBID Astra Playwright scraper
│   └── smartbid.py         # SmartBID HTML scraper
│
├── bidiq_dashboard.html    # Standalone live dashboard
│
├── credentials.json        # ← NOT committed (add to .gitignore)
├── token.pickle            # ← NOT committed (auto-generated)
└── scraper.log             # Auto-generated run log
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure
Edit `config.py`:
```python
CONFIG = {
    "SPREADSHEET_ID": "your-google-sheet-id",
    "USER_CITY":       "JAKARTA",         # Your city for transport fee calc
    "JBA_EMAIL":       "your@email.com",
    "JBA_PASSWORD":    "yourpassword",
    "IBID_EMAIL":      "your@email.com",
    "IBID_PASSWORD":   "yourpassword",
}
```

### 3. Authenticate with Google (first time only)
```bash
python main.py --auth
```

### 4. Run
```bash
# Full run: all 3 sites
python main.py

# Single site (faster for testing)
python main.py --site smartbid

# Include chassis/engine/doc detail pages
python main.py --with-details
```

---

## 📊 Data Schema

Each lot is written to Google Sheets with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `date_scraped` | date | When the lot was scraped |
| `source` | str | JBA / IBID / SMARTBID |
| `vehicle_name` | str | Full vehicle name |
| `brand` | str | Toyota, Honda, etc. |
| `series` | str | Avanza, Jazz, Xpander, etc. |
| `year` | int | Manufacture year |
| `mileage_km` | int | Odometer reading |
| `starting_price` | int | Auction opening bid (IDR) |
| `ppn_flag` | bool | Whether 1.1% auction fee applies |
| `auction_fee_idr` | int | Calculated auction fee |
| `transport_fee_idr` | int | Estimated transport to user city |
| `total_cost_idr` | int | All-in cost to acquire |
| `retail_price_idr` | int | Mean retail price across bidding platforms for similar vehicle |
| `estimated_profit` | int | retail, total_cost |
| `profit_margin_pct` | float | profit / retail × 100 |
| `roi_pct` | float | profit / total_cost × 100 |
| `Score` | float | Composite score |
| `Decision` | str | BID / MAYBE / SKIP |
| `exterior_grade` | str | A–F condition grade |
| `bpkb` | str | BPKB document status |
| `faktur` | str | Faktur document status |
| `chassis_no` | str | VIN / chassis number |
| `engine_no` | str | Engine serial number |
| `listing_url` | str | Direct link to auction lot |

---

## 🛠️ Tech Stack

| Tool | Purpose |
|------|---------|
| Python 3.10 | Core language |
| Playwright | Browser automation for JS-heavy auction sites |
| requests + BeautifulSoup4 | Lightweight HTML scraping |
| gspread + google-auth | Google Sheets OAuth2 integration |
| HTML / CSS / JavaScript | Interactive dashboard (zero frameworks) |
| Google Sheets | Data storage and live CSV endpoint |

---

## 💡 Design Decisions

**Why a single HTML file for the dashboard?**
The dashboard is a self-contained HTML file with zero build steps, it can be opened locally, hosted on any static server, or shared as an email attachment. The live data connection to Google Sheets means it always reflects the latest scrape without redeployment.

**Why Google Sheets instead of a database?**
Sheets provides a free, shareable, human-editable data store that doubles as a CSV API endpoint. For this use case, one user, daily batch runs, hundreds of rows per day, it's more practical than standing up a database.

**Why Playwright for JBA/IBID?**
Both platforms render their lot listings client-side with JavaScript. Static HTTP requests only return skeleton HTML. Playwright handles the full browser lifecycle including login sessions.

**Why a transport fee matrix instead of an API?**
Transporter quotes in Indonesia vary significantly by route and are best maintained as known quotes rather than estimated programmatically. The matrix is easily editable and covers the most common auction city pairs.

---

## ⚠️ Important

- `credentials.json` and `token.pickle` are **not included** in this repo
- This tool is for personal use, respect each platform's terms of service and scrape responsibly
- Add `credentials.json`, `token.pickle`, and `*.pickle` to your `.gitignore`

---

## 🗺️ Roadmap

- [ ] Scheduled daily runs via cron / Windows Task Scheduler
- [ ] Email/WhatsApp alert for high-ROI lots (> 20%)
- [ ] Historical price trend tracking per model
- [ ] Mobile-responsive dashboard improvements
- [ ] Grade-weighted scoring model

---

## 👩‍💻 Author

**Naja Annisa Arifin**
Business & Data Analyst | Civil Engineering → Analytics
📍 Jakarta, Indonesia → Birmingham, UK (MSc Business Analytics, 2026)
🔗 [Portfolio](https://najaannisa.netlify.app) · [GitHub](https://github.com/annisanaja) · [Live Demo](https://bidiq.tiiny.site)

---

## 📄 License
Personal and educational use.
