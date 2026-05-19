import gc
import os
import uuid
import threading
from datetime import datetime
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv

from scrapers.wolt import scrape_wolt, fetch_country_cities
from scrapers.bolt import scrape_bolt, inject_known_cities
from scrapers.foodora import scrape_foodora
from scrapers.glovo import scrape_glovo
from scrapers.google_maps import scrape_google_maps
from scrapers.website_intelligence import scrape_website_intel
from services.email_service import send_completion_email, send_error_email, build_excel, build_google_maps_excel, build_website_intel_excel

load_dotenv()

app = Flask(__name__)
CORS(app)

jobs = {}

SCRAPERS = {
    'wolt':         scrape_wolt,
    'bolt':         scrape_bolt,
    'foodora':      scrape_foodora,
    'glovo':        scrape_glovo,
    'google_maps':  scrape_google_maps,
}

# Country name/alias → ISO alpha-3 code (covers every country Wolt operates in)
COUNTRY_ALIASES = {
    # Czech Republic
    'czech republic': 'CZE', 'czechia': 'CZE', 'česká republika': 'CZE', 'czech': 'CZE', 'cz': 'CZE',
    # Austria
    'austria': 'AUT', 'österreich': 'AUT', 'at': 'AUT',
    # Poland
    'poland': 'POL', 'polska': 'POL', 'pl': 'POL',
    # Hungary
    'hungary': 'HUN', 'magyarország': 'HUN', 'hu': 'HUN',
    # Slovakia
    'slovakia': 'SVK', 'slovensko': 'SVK', 'sk': 'SVK',
    # Germany
    'germany': 'DEU', 'deutschland': 'DEU', 'de': 'DEU',
    # Finland
    'finland': 'FIN', 'suomi': 'FIN', 'fi': 'FIN',
    # Norway
    'norway': 'NOR', 'norge': 'NOR', 'no': 'NOR',
    # Sweden
    'sweden': 'SWE', 'sverige': 'SWE', 'se': 'SWE',
    # Denmark
    'denmark': 'DNK', 'danmark': 'DNK', 'dk': 'DNK',
    # Estonia
    'estonia': 'EST', 'eesti': 'EST', 'ee': 'EST',
    # Latvia
    'latvia': 'LVA', 'latvija': 'LVA', 'lv': 'LVA',
    # Lithuania
    'lithuania': 'LTU', 'lietuva': 'LTU', 'lt': 'LTU',
    # Israel
    'israel': 'ISR', 'il': 'ISR',
    # Greece
    'greece': 'GRC', 'ελλάδα': 'GRC', 'gr': 'GRC',
    # Romania
    'romania': 'ROU', 'românia': 'ROU', 'ro': 'ROU',
    # Serbia
    'serbia': 'SRB', 'srbija': 'SRB', 'rs': 'SRB',
    # Croatia
    'croatia': 'HRV', 'hrvatska': 'HRV', 'hr': 'HRV',
    # Bulgaria
    'bulgaria': 'BGR', 'българия': 'BGR', 'bg': 'BGR',
    # Switzerland
    'switzerland': 'CHE', 'schweiz': 'CHE', 'ch': 'CHE',
    # Japan
    'japan': 'JPN', 'jp': 'JPN',
    # Georgia
    'georgia': 'GEO', 'საქართველო': 'GEO', 'ge': 'GEO',
    # Azerbaijan
    'azerbaijan': 'AZE', 'az': 'AZE',
    # Kazakhstan
    'kazakhstan': 'KAZ', 'kz': 'KAZ',
}

# alpha-3 → human-readable display name
COUNTRY_DISPLAY = {
    'CZE': 'Czech Republic', 'AUT': 'Austria',    'POL': 'Poland',
    'HUN': 'Hungary',        'SVK': 'Slovakia',   'DEU': 'Germany',
    'FIN': 'Finland',        'NOR': 'Norway',      'SWE': 'Sweden',
    'DNK': 'Denmark',        'EST': 'Estonia',     'LVA': 'Latvia',
    'LTU': 'Lithuania',      'ISR': 'Israel',      'GRC': 'Greece',
    'ROU': 'Romania',        'SRB': 'Serbia',      'HRV': 'Croatia',
    'BGR': 'Bulgaria',       'CHE': 'Switzerland', 'JPN': 'Japan',
    'GEO': 'Georgia',        'AZE': 'Azerbaijan',  'KAZ': 'Kazakhstan',
}


def _detect_country(location: str):
    """Return (alpha3, display_name) if location is a country name, else None."""
    key = location.strip().lower().split(',')[0].strip()
    alpha3 = COUNTRY_ALIASES.get(key)
    if not alpha3:
        for alias, code in COUNTRY_ALIASES.items():
            if key.startswith(alias):
                alpha3 = code
                break
    if alpha3:
        return alpha3, COUNTRY_DISPLAY.get(alpha3, key.title())
    return None


def _scrape_cities(scraper, cities, cuisine, job, platform_label, scraper_kwargs=None):
    """Scrape a list of cities with one scraper, dedup by name+address, return merged list."""
    seen = set()
    all_results = []
    total_cities = len(cities)
    kwargs = scraper_kwargs or {}

    for idx, city in enumerate(cities, 1):
        city_name = city.split(',')[0].strip()
        job['message'] = f'{platform_label}: scraping {city_name} ({idx}/{total_cities})...'
        job['progress'] = int((idx - 1) / total_cities * 90)

        try:
            city_job = {'message': '', 'progress': 0, 'scraped': 0, 'total': 0}
            results = scraper(city, cuisine, city_job, **kwargs)

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
        finally:
            gc.collect()  # help free per-city JSON objects between iterations

    return all_results


def _cleanup_old_jobs():
    """Remove completed/failed jobs older than 30 minutes to free excel_bytes from RAM."""
    cutoff = 30 * 60  # seconds
    now = datetime.utcnow()
    stale = [
        jid for jid, j in list(jobs.items())
        if j.get('status') in ('done', 'error')
        and (now - datetime.fromisoformat(j['created_at'])).total_seconds() > cutoff
    ]
    for jid in stale:
        del jobs[jid]


def run_scrape_job(job_id, platforms, location, cuisine, email, gm_params=None):
    job = jobs[job_id]
    try:
        job['status'] = 'running'

        results_by_platform = {}
        country_info = _detect_country(location)

        # For country-level scrapes, fetch all platform cities once up front
        country_cities = None   # list of "CityName, Country" strings
        if country_info:
            alpha3, country_display = country_info
            job['message'] = f'Fetching city list for {country_display}...'
            raw_cities = fetch_country_cities(alpha3)   # [{name, slug, lat, lon}]
            country_cities = [f"{c['name']}, {country_display}" for c in raw_cities]
            # Pre-populate Bolt's coord cache so it never needs Nominatim
            inject_known_cities(raw_cities)

        for plat in platforms:
            scraper = SCRAPERS.get(plat)
            if not scraper:
                raise ValueError(f'Unknown platform: {plat}')

            job['platforms_detail'][plat]['status'] = 'running'

            # Google Maps: pass extra params from request
            if plat == 'google_maps':
                gm = gm_params or {}
                results = scraper(
                    location, cuisine, job,
                    business_types=gm.get('business_types'),
                    min_reviews=int(gm.get('min_reviews', 0)),
                    min_rating=float(gm.get('min_rating', 0.0)),
                    require_website=bool(gm.get('require_website', False)),
                    require_phone=bool(gm.get('require_phone', False)),
                )
            # Foodora and Glovo handle country-level scraping internally
            elif country_cities and plat not in ('foodora', 'glovo'):
                # Wolt: skip phase-2 detail scraping (phone/merchant) for country batches
                # to avoid OOM — each city's JSON response is 1-3MB, and 50 cities
                # can exhaust Render's 512MB limit if pages are also fetched per venue.
                extra = {'fetch_details': False} if plat == 'wolt' else {}
                results = _scrape_cities(scraper, country_cities, cuisine, job, plat.capitalize(), scraper_kwargs=extra)
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
        from datetime import date as _date
        safe_loc = location.replace(', ', '_').replace(' ', '_').lower()
        is_gm_only = list(results_by_platform.keys()) == ['google_maps']

        if is_gm_only:
            gm_results = results_by_platform.get('google_maps', [])
            gm_stats   = job.get('gm_stats', {})
            today      = _date.today().isoformat()
            excel_filename = f'google-maps-{safe_loc}-{today}.xlsx'
            job['excel_bytes'] = build_google_maps_excel(gm_results, location, gm_stats)
        else:
            platforms_str = '_'.join(p.capitalize() for p in results_by_platform if results_by_platform[p])
            excel_filename = f'{safe_loc}_{platforms_str}.xlsx'
            job['excel_bytes'] = build_excel(results_by_platform, location)

        job['excel_filename'] = excel_filename

        try:
            # For GM-only jobs reuse the already-built 4-sheet excel so the
            # email attachment matches the download (not the basic 1-sheet version)
            if is_gm_only:
                from services.email_service import send_google_maps_completion_email
                send_google_maps_completion_email(
                    email, results_by_platform.get('google_maps', []),
                    location, job.get('gm_stats', {}), job['excel_bytes'], excel_filename,
                )
            else:
                send_completion_email(email, results_by_platform, location)
            job['message'] = f'Done! {total} places found. Email sent.'
        except Exception as mail_err:
            print(f'[Job {job_id}] Email failed: {mail_err}')
            job['message'] = f'Done! {total} places found. (Email failed — check SMTP settings)'

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

    # Google Maps extra params
    gm_params = data.get('gm_params')  # {business_types, min_reviews, min_rating, ...}

    if not location:
        return jsonify({'error': 'Location is required'}), 400
    if not email or '@' not in email:
        return jsonify({'error': 'Valid email is required'}), 400
    if not platforms:
        return jsonify({'error': 'Select at least one platform'}), 400
    for p in platforms:
        if p not in SCRAPERS:
            return jsonify({'error': f'Unknown platform: {p}'}), 400

    _cleanup_old_jobs()

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'id':               job_id,
        'platforms':        platforms,
        'platform':         '+'.join(platforms),
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
        'gm_stats':         {},
        'excel_filename':   None,
        'created_at':       datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=run_scrape_job,
        args=(job_id, platforms, location, cuisine, email, gm_params),
        daemon=True,
    )
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'pending'})


@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    # Exclude raw bytes from JSON response — expose only whether file is ready
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


def run_website_intel_job(job_id: str, restaurants: list, email: str):
    job = jobs[job_id]
    try:
        job['status'] = 'running'
        results = scrape_website_intel(restaurants, job)

        total = len(results)
        job['status'] = 'done'
        job['scraped'] = total
        job['progress'] = 100
        job['message'] = f'Done! Analyzed {total} restaurants. Preparing file...'

        from datetime import date as _date
        today = _date.today().isoformat()
        excel_filename = f'website-intel-{today}.xlsx'
        job['excel_bytes'] = build_website_intel_excel(results)
        job['excel_filename'] = excel_filename

        try:
            if email and '@' in email:
                from services.email_service import _send
                _send(
                    email,
                    f'✅ Website Intelligence done — {total} restaurants analyzed',
                    f"""<html><body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
                      <h2 style="color:#7c3aed;">🔍 Website Intelligence complete!</h2>
                      <p>Analysis of <strong>{total}</strong> restaurants is done. Excel file attached.</p>
                      <p style="color:#6b7280;font-size:0.85rem;">Generated by Restaurant Scraper · Website Intelligence</p>
                    </body></html>""",
                    attachment=job['excel_bytes'],
                    filename=excel_filename,
                )
            job['message'] = f'Done! {total} restaurants analyzed. Email sent.'
        except Exception as mail_err:
            print(f'[Job {job_id}] Email failed: {mail_err}')
            job['message'] = f'Done! {total} restaurants analyzed.'

    except Exception as e:
        error_msg = str(e)
        job['status'] = 'error'
        job['message'] = error_msg
        print(f'[Job {job_id}] Website intel error: {error_msg}')


@app.route('/api/website-intel', methods=['POST'])
def start_website_intel():
    data = request.get_json()
    restaurants = data.get('restaurants', [])
    email = data.get('email', '').strip()

    if not restaurants or not isinstance(restaurants, list):
        return jsonify({'error': 'restaurants list is required'}), 400
    if len(restaurants) > 500:
        return jsonify({'error': 'Maximum 500 restaurants per job'}), 400

    # Validate each entry has name + url
    cleaned = []
    for r in restaurants:
        name = str(r.get('name', '')).strip()
        url  = str(r.get('url', '')).strip()
        if url:
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            cleaned.append({'name': name or url, 'url': url})

    if not cleaned:
        return jsonify({'error': 'No valid restaurant URLs found'}), 400

    _cleanup_old_jobs()

    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        'id':             job_id,
        'type':           'website_intel',
        'status':         'pending',
        'message':        'Job queued',
        'total':          len(cleaned),
        'scraped':        0,
        'progress':       0,
        'excel_filename': None,
        'created_at':     datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=run_website_intel_job,
        args=(job_id, cleaned, email),
        daemon=True,
    )
    thread.start()

    return jsonify({'job_id': job_id, 'status': 'pending'})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
