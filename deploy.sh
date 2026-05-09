#!/bin/bash
# Full deployment: backend (GitHub → Render) + frontend (Netlify)
# Credentials loaded from backend/.env

set -e
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

# Load credentials from .env
if [ -f "backend/.env" ]; then
  set -a
  # Parse .env safely (skip lines with JSON braces that confuse bash)
  while IFS='=' read -r key rest; do
    [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
    [[ "$key" == *"{"* ]] && continue  # skip JSON lines
    export "$key=$rest"
  done < <(grep -E '^(GITHUB_TOKEN|NETLIFY_TOKEN|NETLIFY_SITE_ID)=' backend/.env)
  set +a
fi

if [ -z "$GITHUB_TOKEN" ] || [ -z "$NETLIFY_TOKEN" ]; then
  echo "ERROR: Missing GITHUB_TOKEN or NETLIFY_TOKEN in backend/.env"
  exit 1
fi

BACKEND_URL="https://restaurant-scraper-api-ah9e.onrender.com"

echo "=== Restaurant Scraper — Full Deploy ==="
echo ""

# ── 1. Backend: commit + push to GitHub ───────────────────────────────────────
echo "▶ [1/3] Pushing backend to GitHub..."
git add -A
if git diff --cached --quiet; then
  echo "  No new changes to commit."
else
  git commit -m "Deploy: $(date '+%Y-%m-%d %H:%M')"
fi
git push "https://choice-hub:${GITHUB_TOKEN}@github.com/choice-hub/restaurant-scraper.git" main
echo "  ✓ Pushed to GitHub. Render auto-redeploy started (~2-3 min)."
echo ""

# ── 2. Frontend: deploy to Netlify ────────────────────────────────────────────
echo "▶ [2/3] Deploying frontend to Netlify..."
zip -r /tmp/restaurant-frontend.zip frontend/ -x "*.DS_Store" > /dev/null
RESULT=$(curl -s -X POST "https://api.netlify.com/api/v1/sites/${NETLIFY_SITE_ID}/deploys" \
  -H "Authorization: Bearer ${NETLIFY_TOKEN}" \
  -H "Content-Type: application/zip" \
  --data-binary @/tmp/restaurant-frontend.zip)
STATE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state','unknown'))" 2>/dev/null)
echo "  ✓ Frontend deployed (state: $STATE)"
echo "  URL: https://restaurant-scraper-tool.netlify.app"
echo ""

# ── 3. Health check ───────────────────────────────────────────────────────────
echo "▶ [3/3] Checking backend health..."
for i in $(seq 1 24); do
  if curl -sf "${BACKEND_URL}/health" > /dev/null 2>&1; then
    echo "  ✓ Backend live: ${BACKEND_URL}"
    break
  fi
  [ "$i" -eq 24 ] && echo "  ⚠ Backend still starting — check Render dashboard."
  sleep 5
done

echo ""
echo "=== Done! ==="
echo "  Frontend : https://restaurant-scraper-tool.netlify.app"
echo "  Backend  : ${BACKEND_URL}"
echo "  Repo     : https://github.com/choice-hub/restaurant-scraper"
