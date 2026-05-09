# Restaurant Scraper — Project Context

## What this project is
A web app that scrapes restaurant listings from delivery platforms (Wolt, Bolt, Foodora, Glovo), exports results to Google Sheets, and emails the user a link when done. Runs fully in the cloud.

## Live URLs
- **Frontend:** https://restaurant-scraper-tool.netlify.app
- **Backend API:** https://restaurant-scraper-api-ah9e.onrender.com
- **GitHub repo:** https://github.com/choice-hub/restaurant-scraper

## Architecture
```
frontend/          → Static site (HTML/CSS/JS), hosted on Netlify (free)
backend/           → Flask API, hosted on Render (Python, Starter $7/month)
  app.py           → Main Flask app, job queue (in-memory)
  scrapers/        → One scraper per platform (wolt, bolt, foodora, glovo)
  services/
    sheets.py      → Google Sheets export (adds tabs to shared spreadsheet)
    email_service.py → Gmail SMTP notifications on job complete/error
render.yaml        → Render blueprint (auto-deploy on git push)
deploy.sh          → Full deploy script (backend via git push + frontend via Netlify API)
```

## All credentials are in: `backend/.env`
Secrets are NOT committed to git. The `.env` file is on disk at:
`/Users/alex/Desktop/claude/backend/.env`

Keys stored there:
- `GOOGLE_CREDENTIALS_JSON` — service account JSON for Google Sheets
- `GOOGLE_SPREADSHEET_ID` — shared spreadsheet (1N-n8MNLpxBVn1jDqLgjNEBjVFROElS4ITxFE0uOqjZw)
- `SMTP_USER` / `SMTP_PASSWORD` — Gmail SMTP for email notifications
- `GITHUB_TOKEN` — for pushing to choice-hub/restaurant-scraper
- `NETLIFY_TOKEN` / `NETLIFY_SITE_ID` — for frontend deploys

## Render environment variables (set in Render dashboard)
Same values as .env, but set on the live server:
GOOGLE_CREDENTIALS_JSON, GOOGLE_SPREADSHEET_ID, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

## How deployment works

### Backend (push to GitHub → Render auto-redeploys in ~2-3 min)
```bash
cd /Users/alex/Desktop/claude
source backend/.env  # or load manually
git add -A && git commit -m "your message"
git push "https://choice-hub:${GITHUB_TOKEN}@github.com/choice-hub/restaurant-scraper.git" main
```

### Frontend (Netlify zip upload)
```bash
cd /Users/alex/Desktop/claude
source backend/.env
zip -r /tmp/frontend.zip frontend/ -x "*.DS_Store"
curl -s -X POST "https://api.netlify.com/api/v1/sites/${NETLIFY_SITE_ID}/deploys" \
  -H "Authorization: Bearer ${NETLIFY_TOKEN}" \
  -H "Content-Type: application/zip" \
  --data-binary @/tmp/frontend.zip
```

### Full deploy (both at once)
```bash
bash /Users/alex/Desktop/claude/deploy.sh
```

## Deploy slash command
In Claude Code, just say: **"deploy"** or run `bash deploy.sh`

## Google Sheets setup
- Service account email: `restaurant-scraper@favorable-logic-495519-k1.iam.gserviceaccount.com`
- This account has **Editor** access to the shared spreadsheet
- Each scrape run adds a **new tab** to the spreadsheet (service account cannot create new files — no Drive quota)
- Spreadsheet: https://docs.google.com/spreadsheets/d/1N-n8MNLpxBVn1jDqLgjNEBjVFROElS4ITxFE0uOqjZw

## Test a scrape job
```bash
# Start job
curl -X POST https://restaurant-scraper-api-ah9e.onrender.com/api/scrape \
  -H 'Content-Type: application/json' \
  -d '{"platform":"wolt","location":"Prague, Czech Republic","cuisine":"","email":"alex@choiceqr.com"}'

# Poll status (replace JOB_ID)
curl https://restaurant-scraper-api-ah9e.onrender.com/api/jobs/JOB_ID
```

## Key technical notes
- **Wolt**: uses single listing API call (v1/pages/restaurants) — v3 detail endpoint returns 410
- **Scrape speed**: ~1600 restaurants in <5 seconds (no per-venue requests)
- **Email**: sent to the address entered in the form
- **Job storage**: in-memory only — jobs lost if Render restarts (this is fine for the use case)
- **Bolt/Foodora/Glovo**: stubs exist, not yet fully implemented
