# 🍽️ Restaurant Scraper

A web app + AI agent toolkit for scraping restaurant data from delivery platforms, Google Maps, and individual restaurant websites. Runs fully in the cloud — no local setup needed to use it.

---

## Live URLs (already running — just open)

| Service | URL |
|---------|-----|
| **Web app** | https://restaurant-scraper-tool.netlify.app |
| **Backend API** | https://restaurant-scraper-api-ah9e.onrender.com |
| **MCP connector** | `https://restaurant-scraper-mcp.onrender.com/mcp` |
| **GitHub repo** | https://github.com/choice-hub/restaurant-scraper |

---

## What it does

### 1. Delivery platform scraper
Scrape restaurant listings from **Wolt**, **Bolt Food**, and **Foodora**.
- **Wolt**: ~1,600 restaurants per city in under 5 seconds
- Output: Restaurant name, phone, website, address, cuisine, rating, legal company, business ID, platform URL
- Markets: CZ, AT, PL, HU, SK, DE, FI, NO, SE, DK, EE, LV, LT, IL, GR, RO, RS, HR, BG, CH, JP, GE, AZ, KZ

### 2. Google Maps scraper
Scrape all restaurants/cafes in a city or country from Google Maps.
- Output: Name, address, phone, website, rating, review count, delivery companies (Wolt/Bolt/Uber Eats/etc.), reservation systems (OpenTable/TheFork/etc.)
- Filters: min reviews, min rating, require website, require phone

### 3. Website Intelligence
Upload a CSV/Excel with restaurant names + website URLs — the tool analyzes each site and appends 14 new columns to your original file:
- Instagram URL + follower count
- Facebook URL + follower count
- Email addresses found on the site
- Legal name, Company ID / IČO
- Website platform (WordPress, Wix, ChoiceQR, Squarespace, etc.)
- Reservation system: Yes/No + provider name
- Online ordering: Yes/No + provider name (embedded widget only)

### 4. MCP connector (Claude AI agent mode)
Connect Claude directly to the scraper — no web UI needed. Ask Claude in natural language and get results inline in the chat.

**Connect via claude.ai:** Settings → Connectors → Add custom connector
```
https://restaurant-scraper-mcp.onrender.com/mcp
```

**Connect via Claude Code** (add to `~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "restaurant-scraper": {
      "command": "python3",
      "args": ["/path/to/mcp_server.py"]
    }
  }
}
```

---

## Project structure

```
├── frontend/                        ← Static site hosted on Netlify
│   ├── index.html                   ← 4 tabs: Delivery, Google Maps, Website Intel, Jobs
│   ├── app.js                       ← All UI logic, file parsing, job polling
│   └── style.css
│
├── backend/                         ← Flask API hosted on Render
│   ├── app.py                       ← Routes: /api/scrape, /api/website-intel, /api/jobs/...
│   ├── scrapers/
│   │   ├── wolt.py                  ← ✅ Working (v1 API, ~1600 results in <5s)
│   │   ├── bolt.py                  ← Partial
│   │   ├── foodora.py               ← Partial
│   │   ├── google_maps.py           ← ✅ Working (via Outscraper API)
│   │   └── website_intelligence.py  ← ✅ Working (httpx + BS4 + Claude Haiku)
│   ├── services/
│   │   ├── email_service.py         ← Excel export (openpyxl) + Gmail notifications
│   │   └── sheets.py                ← Google Sheets export
│   └── requirements.txt
│
├── mcp_server.py                    ← MCP server (stdio for Claude Code, HTTP for claude.ai)
├── mcp_requirements.txt             ← Deps for the MCP Render service
├── render.yaml                      ← Two Render services: API + MCP
└── deploy.sh                        ← One-command deploy (backend + frontend)
```

---

## Credentials

All secrets are in `backend/.env` (not committed to git — ask Alex for the file).

| Key | What it's for |
|-----|--------------|
| `ANTHROPIC_API_KEY` | Claude Haiku for website intelligence analysis |
| `OUTSCRAPER_API_KEY` | Google Maps scraping |
| `GOOGLE_CREDENTIALS_JSON` | Service account JSON for Sheets export |
| `GOOGLE_SPREADSHEET_ID` | Shared results spreadsheet |
| `SMTP_USER` / `SMTP_PASSWORD` | Gmail for email notifications |
| `GITHUB_TOKEN` | Push to this repo |
| `NETLIFY_TOKEN` / `NETLIFY_SITE_ID` | Frontend deploys |

The same keys (except GITHUB/NETLIFY) are also set as env vars in the Render dashboard for the live services.

---

## Deploying changes

```bash
# Deploy everything (backend + frontend)
bash deploy.sh

# Backend only — push to GitHub, Render auto-redeploys in ~2 min
source backend/.env
git add -A && git commit -m "your message"
git push "https://choice-hub:${GITHUB_TOKEN}@github.com/choice-hub/restaurant-scraper.git" main

# Frontend only
source backend/.env
rm -f /tmp/frontend.zip && zip -r /tmp/frontend.zip frontend/ -x "*.DS_Store"
curl -s -X POST "https://api.netlify.com/api/v1/sites/${NETLIFY_SITE_ID}/deploys" \
  -H "Authorization: Bearer ${NETLIFY_TOKEN}" -H "Content-Type: application/zip" \
  --data-binary @/tmp/frontend.zip
```

---

## Running locally (for development)

```bash
cd backend
pip install -r requirements.txt
# get .env from Alex
python app.py   # runs on localhost:5000
```

Open `frontend/index.html` in your browser (the app.js already points to the live Render API, change `API_BASE` to `http://localhost:5000` for local testing).
