import os
import uuid
import threading
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from scrapers.wolt import scrape_wolt
from scrapers.bolt import scrape_bolt
from scrapers.foodora import scrape_foodora
from scrapers.glovo import scrape_glovo
from services.sheets import export_to_sheets
from services.email_service import send_completion_email

load_dotenv()

app = Flask(__name__)
CORS(app)

# In-memory job store (persists as long as the server is running)
jobs = {}

SCRAPERS = {
    'wolt': scrape_wolt,
    'bolt': scrape_bolt,
    'foodora': scrape_foodora,
    'glovo': scrape_glovo,
}


def run_scrape_job(job_id, platform, location, cuisine, email):
    job = jobs[job_id]
    try:
        job['status'] = 'running'
        job['message'] = f'Searching for restaurants in {location}...'

        scraper = SCRAPERS.get(platform)
        if not scraper:
            raise ValueError(f'Unknown platform: {platform}')

        restaurants = scraper(location, cuisine, job)

        job['message'] = 'Exporting to Google Sheets...'
        sheet_url = export_to_sheets(restaurants, platform, location)

        job['message'] = 'Sending email notification...'
        send_completion_email(email, sheet_url, platform, location, len(restaurants))

        job['status'] = 'done'
        job['sheet_url'] = sheet_url
        job['message'] = f'Done! Exported {len(restaurants)} restaurants.'
        job['scraped'] = len(restaurants)

    except Exception as e:
        job['status'] = 'error'
        job['message'] = str(e)
        print(f'[Job {job_id}] Error: {e}')


@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    data = request.get_json()
    platform = data.get('platform', 'wolt')
    location = data.get('location', '').strip()
    cuisine = data.get('cuisine', '').strip()
    email = data.get('email', '').strip()

    if not location:
        return jsonify({'error': 'Location is required'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email is required'}), 400
    if platform not in SCRAPERS:
        return jsonify({'error': f'Unknown platform: {platform}'}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'id': job_id,
        'platform': platform,
        'location': location,
        'cuisine': cuisine,
        'email': email,
        'status': 'pending',
        'message': 'Job queued',
        'total': 0,
        'scraped': 0,
        'failed': 0,
        'progress': 0,
        'sheet_url': None,
        'created_at': datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=run_scrape_job,
        args=(job_id, platform, location, cuisine, email),
        daemon=True
    )
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'pending'})


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
