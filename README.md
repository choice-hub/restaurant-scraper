# 🍽️ Restaurant Scraper

Scrapes restaurant listings from Wolt, Bolt Food, Foodora, and Glovo — exports to Google Sheets and sends an email when done. Runs in the cloud (no laptop required).

---

## Project structure

```
claude/
├── frontend/          ← Static website (HTML/CSS/JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── backend/           ← Python Flask API + scrapers
│   ├── app.py
│   ├── scrapers/
│   │   ├── wolt.py
│   │   ├── bolt.py
│   │   ├── foodora.py
│   │   └── glovo.py
│   ├── services/
│   │   ├── sheets.py
│   │   └── email_service.py
│   ├── requirements.txt
│   └── .env.example
└── render.yaml        ← Deployment config for Render.com
```

---

## Setup (one-time)

### 1. Google Sheets API

1. Go to https://console.cloud.google.com
2. Create a new project (e.g. "RestaurantScraper")
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts → Create Service Account**
5. Name it anything, click through to finish
6. Click the service account → **Keys → Add Key → JSON**
7. Download the `.json` file — you'll need its contents

### 2. Gmail App Password (for email)

1. Go to https://myaccount.google.com/apppasswords
2. Create an App Password (select "Mail" + your device)
3. Copy the 16-character password

### 3. Deploy to Render.com (free — runs 24/7)

1. Go to https://render.com and create a free account
2. Click **New → Blueprint** and connect your GitHub repo
   - (Upload the `claude` folder to a new GitHub repo first)
3. Render reads `render.yaml` automatically and creates both services
4. In the **restaurant-scraper-api** service → **Environment**:
   - `GOOGLE_CREDENTIALS_JSON` → paste the full contents of your downloaded `.json` file
   - `SMTP_USER` → your Gmail address
   - `SMTP_PASSWORD` → your App Password
5. Copy the API URL (e.g. `https://restaurant-scraper-api.onrender.com`)

### 4. Update frontend API URL

Open `frontend/app.js` and replace:
```js
'https://YOUR-RENDER-APP.onrender.com'
```
with your actual Render API URL.

### 5. Deploy frontend to Netlify (free)

1. Go to https://netlify.com → **Add new site → Deploy manually**
2. Drag the `frontend/` folder into the upload box
3. Done — you get a live public URL!

---

## Running locally (for testing)

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python app.py
```

Then open `frontend/index.html` in your browser.

---

## Data exported to Google Sheet

| Column | Description |
|--------|-------------|
| Name | Restaurant name |
| City | City |
| Address | Street address |
| Phone | Phone number |
| Website | Restaurant website |
| Legal ID | Merchant/legal identifier |
| Cuisine / Kitchen | Cuisine tags |
| Platform URL | Link to restaurant on the platform |
