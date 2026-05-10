import os
import uuid
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv

from scrapers.wolt import scrape_wolt
from scrapers.bolt import scrape_bolt
from scrapers.foodora import scrape_foodora
from scrapers.glovo import scrape_glovo
from services.email_service import send_completion_email, send_error_email, build_excel

load_dotenv()

app = Flask(__name__)
CORS(app)

jobs = {}

SCRAPERS = {
    'wolt':    scrape_wolt,
    'bolt':    scrape_bolt,
    'foodora': scrape_foodora,
    'glovo':   scrape_glovo,
}

# Country → list of cities to scrape (in order of size)
COUNTRY_CITIES = {
    'czech republic': [
        'Prague, Czech Republic',
        'Brno, Czech Republic',
        'Ostrava, Czech Republic',
        'Plzeň, Czech Republic',
        'Liberec, Czech Republic',
        'Olomouc, Czech Republic',
        'České Budějovice, Czech Republic',
        'Hradec Králové, Czech Republic',
        'Pardubice, Czech Republic',
        'Zlín, Czech Republic',
        'Havířov, Czech Republic',
        'Kladno, Czech Republic',
        'Most, Czech Republic',
        'Opava, Czech Republic',
        'Frýdek-Místek, Czech Republic',
    ],
    'czechia': None,  # alias, resolved below
}
COUNTRY_CITIES['czechia'] = COUNTRY_CITIES['czech republic']

# Aliases that map input text → canonical country key
COUNTRY_ALIASES = {
    'czech republic': 'czech republic',
    'czechia': 'czech republic',
    'česká republika': 'czech republic',
    'czech': 'czech republic',
    'cz': 'czech republic',
}


def _detect_country(location: str):
    """Return list of cities if location is a country we support, else None."""
    key = location.strip().lower()
    country = COUNTRY_ALIASES.get(key)
    if country:
        return COUNTRY_CITIES[country]
    for alias, canonical in COUNTRY_ALIASES.items():
        if key.startswith(alias):
            return COUNTRY_CITIES[canonical]
    return None


def _scrape_cities(scraper, cities, cuisine, job, platform_label):
    """Scrape a list of cities with one scraper, dedup by name+address, return merged list."""
    seen = set()
    all_results = []
    total_cities = len(cities)

    for idx, city in enumerate(cities, 1):
        city_name = city.split(',')[0].strip()
        job['message'] = f'{platform_label}: scraping {city_name} ({idx}/{total_cities})...'
        job['progress'] = int((idx - 1) / total_cities * 90)

        try:
            city_job = {'message': '', 'progress': 0, 'scraped': 0, 'total': 0}
            results = scraper(city, cuisine, city_job)

            added = 0
            for r in results:
                key = (r.get('name', '').lower().strip(), r.get('address', '').lower().strip())
                if key not in seen and key != ('', ''):
                    seen.add(key)
                    all_results.append(r)
                    added += 1

            job['scraped'] = len(all_results)
            print(f'[{platform_label}] {city_name}: {len(results)} found, {added} new (total {len(all_results)})')
        except Exception as e:
            print(f'[{platform_label}] {city_name} failed: {e}')

    return all_results


def run_scrape_job(job_id, platforms, location, cuisine, email):
    job = jobs[job_id]
    try:
        job['status'] = 'running'

        results_by_platform = {}
        cities = _detect_country(location)

        for plat in platforms:
            scraper = SCRAPERS.get(plat)
            if not scraper:
                raise ValueError(f'Unknown platform: {plat}')

            job['platforms_detail'][plat]['status'] = 'running'

            if cities and plat != 'foodora':
                results = _scrape_cities(scraper, cities, cuisine, job, plat.capitalize())
            else:
                job['message'] = f'Searching {plat.capitalize()} restaurants in {location}...'
                results = scraper(location, cuisine, job)

            results_by_platform[plat] = results
            job['platforms_detail'][plat]['status'] = 'done'
            job['platforms_detail'][plat]['scraped'] = len(results)

        total = sum(len(v) for v in results_by_platform.values())
        job['status'] = 'done'
        job['scraped'] = total
        job['progress'] = 100
        job['message'] = f'Done! Found {total} restaurants. Preparing file...'

        # Build Excel and store for direct download
        safe_loc = location.replace(', ', '_').replace(' ', '_')
        platforms_str = '_'.join(p.capitalize() for p in results_by_platform if results_by_platform[p])
        excel_filename = f'{safe_loc}_{platforms_str}.xlsx'
        job['excel_bytes'] = build_excel(results_by_platform, location)
        job['excel_filename'] = excel_filename

        try:
            send_completion_email(email, results_by_platform, location)
            job['message'] = f'Done! {total} restaurants. Email sent.'
        except Exception as mail_err:
            print(f'[Job {job_id}] Email failed: {mail_err}')
            job['message'] = f'Done! {total} restaurants. (Email failed — check SMTP settings)'

    except Exception as e:
        error_msg = str(e)
        job['status'] = 'error'
        job['message'] = error_msg
        print(f'[Job {job_id}] Error: {error_msg}')
        try:
            send_error_email(email, '+'.join(platforms), location, error_msg)
        except Exception as mail_err:
            print(f'[Job {job_id}] Error email failed: {mail_err}')


@app.route('/api/scrape', methods=['POST'])
def start_scrape():
    data = request.get_json()
    location = data.get('location', '').strip()
    cuisine  = data.get('cuisine', '').strip()
    email    = data.get('email', '').strip()

    # Accept either platforms[] array (new) or platform string (legacy)
    platforms_raw = data.get('platforms')
    if platforms_raw and isinstance(platforms_raw, list):
        platforms = [p.strip() for p in platforms_raw if p.strip()]
    else:
        platform = data.get('platform', 'wolt')
        platforms = ['wolt', 'bolt'] if platform == 'both' else [platform]

    if not location:
        return jsonify({'error': 'Location is required'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email is required'}), 400
    if not platforms:
        return jsonify({'error': 'Select at least one platform'}), 400
    for p in platforms:
        if p not in SCRAPERS:
            return jsonify({'error': f'Unknown platform: {p}'}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'id':               job_id,
        'platforms':        platforms,
        'platform':         '+'.join(platforms),  # legacy display field
        'location':         location,
        'cuisine':          cuisine,
        'email':            email,
        'status':           'pending',
        'message':          'Job queued',
        'total':            0,
        'scraped':          0,
        'failed':           0,
        'progress':         0,
        'platforms_detail': {p: {'status': 'pending', 'scraped': 0} for p in platforms},
        'excel_filename':   None,
        'created_at':       datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=run_scrape_job,
        args=(job_id, platforms, location, cuisine, email),
        daemon=True,
    )
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'pending'})


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    # Exclude raw bytes from JSON — expose only whether file is ready
    safe = {k: v for k, v in job.items() if k != 'excel_bytes'}
    safe['has_file'] = bool(job.get('excel_bytes'))
    return jsonify(safe)


@app.route('/api/jobs/<job_id>/download', methods=['GET'])
def download_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    excel_bytes = job.get('excel_bytes')
    if not excel_bytes:
        return jsonify({'error': 'File not ready yet'}), 404
    filename = job.get('excel_filename', 'restaurants.xlsx')
    return Response(
        excel_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
    )


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
