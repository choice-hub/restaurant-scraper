"""
Wolt scraper using Wolt's internal REST API.
Phase 1: single listing call for all venues (fast).
Phase 2: concurrent per-venue page scrapes for phone, merchant/legal data.
"""
import gc
import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = 'https://restaurant-api.wolt.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://wolt.com',
    'Referer': 'https://wolt.com/',
}
PAGE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

# ISO 3166-1 alpha-2 → Wolt URL country segment
_COUNTRY_CODE_MAP = {
    'cz': 'cze', 'sk': 'svk', 'pl': 'pol', 'hu': 'hun', 'ro': 'rou',
    'hr': 'hrv', 'rs': 'srb', 'bg': 'bgr', 'gr': 'grc', 'il': 'isr',
    'fi': 'fin', 'se': 'swe', 'no': 'nor', 'dk': 'dnk', 'ee': 'est',
    'lv': 'lva', 'lt': 'ltu', 'de': 'deu', 'at': 'aut', 'ch': 'che',
    'jp': 'jpn', 'ge': 'geo', 'az': 'aze', 'kz': 'kaz',
}

# Matches the merchant/legal block Wolt embeds in every restaurant page
_MERCHANT_RE = re.compile(
    r'"name":"(?P<merchant_name>[^"]+)",'
    r'"business_id":"(?P<business_id>[^"]+)",'
    r'"street_address":"(?P<legal_street>[^"]+)",'
    r'"city":"(?P<legal_city>[^"]+)",'
    r'"post_code":"(?P<legal_post_code>[^"]+)",'
    r'"country":"(?P<legal_country>[^"]+)"'
)
_PHONE_RE = re.compile(r'"phone":"([^"]+)"')
_WEBSITE_RE = re.compile(r'"sameAs":"(https?://[^"]+)"')

_geocode_cache: dict = {}

# Fallback coords for common cities to survive Nominatim rate limits
_CITY_FALLBACKS = {
    'brno': (49.1950602, 16.6068371, 'Brno, Czechia', 'brno', 'cze'),
    'prague': (50.0874654, 14.4212535, 'Prague, Czechia', 'prague', 'cze'),
    'praha': (50.0874654, 14.4212535, 'Prague, Czechia', 'prague', 'cze'),
    'bratislava': (48.1516988, 17.1093063, 'Bratislava, Slovakia', 'bratislava', 'svk'),
    'warsaw': (52.2319581, 21.0067249, 'Warsaw, Poland', 'warsaw', 'pol'),
    'budapest': (47.4979937, 19.0403594, 'Budapest, Hungary', 'budapest', 'hun'),
}

# Cache for country city lists so we only hit /v1/cities once per country per process
_country_cities_cache: dict = {}


def fetch_country_cities(country_alpha3: str) -> list[dict]:
    """Return all Wolt-served cities for a country as [{name, slug, lat, lon}].

    Also pre-populates _geocode_cache so subsequent scrape_wolt() calls for these
    cities never hit Nominatim.
    """
    alpha3 = country_alpha3.upper()
    if alpha3 in _country_cities_cache:
        return _country_cities_cache[alpha3]

    r = requests.get(f'{BASE}/v1/cities', headers=HEADERS, timeout=15)
    r.raise_for_status()

    country_slug = _COUNTRY_CODE_MAP.get(
        # alpha3 → alpha2 reverse lookup for _COUNTRY_CODE_MAP
        next((k for k, v in _COUNTRY_CODE_MAP.items() if v == alpha3.lower()), ''),
        alpha3.lower()
    )

    results = []
    for c in r.json().get('results', []):
        if c.get('country_code_alpha3', '').upper() != alpha3:
            continue
        lon, lat = c['location']['coordinates']
        name  = c['name']
        slug  = c.get('slug', name.lower().replace(' ', '-'))
        entry = {'name': name, 'slug': slug, 'lat': lat, 'lon': lon}
        results.append(entry)
        # Pre-populate _CITY_FALLBACKS so geocode_location() finds cities by name
        # without calling Nominatim (geocode_location checks first_word in _CITY_FALLBACKS)
        fallback_key = name.lower()
        if fallback_key not in _CITY_FALLBACKS:
            _CITY_FALLBACKS[fallback_key] = (lat, lon, name, slug, country_slug)

    _country_cities_cache[alpha3] = results
    return results


def geocode_location(location: str) -> tuple[float, float, str, str, str]:
    """Resolve a city/country string to lat/lon using OpenStreetMap Nominatim.
    Returns (lat, lon, formatted, city_slug, country_slug)."""
    import time

    key = location.lower().strip()
    if key in _geocode_cache:
        return _geocode_cache[key]

    # Use built-in fallback if available (avoids Nominatim entirely)
    first_word = key.split(',')[0].strip()
    if first_word in _CITY_FALLBACKS:
        result = _CITY_FALLBACKS[first_word]
        _geocode_cache[key] = result
        return result

    url = 'https://nominatim.openstreetmap.org/search'
    for attempt in range(5):
        r = requests.get(
            url,
            params={'q': location, 'format': 'json', 'limit': 1, 'addressdetails': 1},
            headers={'User-Agent': 'RestaurantScraper/1.0', 'Accept-Language': 'en'},
            timeout=10
        )
        if r.status_code == 429:
            time.sleep(3 ** attempt)
            continue
        r.raise_for_status()
        break
    results = r.json()
    if not results:
        raise ValueError(f'Could not find location: {location}. Try a more specific city name.')
    res = results[0]
    addr = res.get('address', {})
    city = addr.get('city') or addr.get('town') or addr.get('village') or location
    country = addr.get('country', '')
    country_code2 = res.get('address', {}).get('country_code', '').lower()
    country_slug = _COUNTRY_CODE_MAP.get(country_code2, country_code2)
    city_slug = city.lower().replace(' ', '-')
    formatted = f"{city}, {country}" if country else city
    result = (float(res['lat']), float(res['lon']), formatted, city_slug, country_slug)
    _geocode_cache[key] = result
    return result


def _fetch_venue_detail(wolt_url: str) -> dict:
    """Scrape a single Wolt restaurant page for phone and merchant/legal data."""
    try:
        r = requests.get(wolt_url, headers=PAGE_HEADERS, timeout=15)
        if r.status_code != 200:
            return {}
        text = r.text
        detail = {}
        m = _PHONE_RE.search(text)
        if m:
            detail['phone'] = m.group(1)
        m = _WEBSITE_RE.search(text)
        if m:
            detail['website'] = m.group(1)
        m = _MERCHANT_RE.search(text)
        if m:
            detail.update(m.groupdict())
        return detail
    except Exception:
        return {}


def scrape_wolt(location: str, cuisine: str, job: dict, fetch_details: bool = True) -> list[dict]:
    """Main entry point.
    Phase 1: listing API (always runs).
    Phase 2: per-venue page scrapes for phone/merchant data (skipped when fetch_details=False).
    fetch_details=False is used for country-level batches to avoid OOM on large cities.
    """
    job['message'] = f'Geocoding "{location}"...'
    lat, lon, formatted, city_slug, country_slug = geocode_location(location)
    city_name = formatted.split(',')[0].strip()

    job['message'] = f'Fetching restaurant list near {formatted}...'
    url = f'{BASE}/v1/pages/restaurants'
    for attempt in range(5):
        r = requests.get(url, params={'lat': lat, 'lon': lon}, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            wait = int(r.headers.get('Retry-After', 4 ** attempt))
            job['message'] = f'Rate limited by Wolt — retrying in {wait}s (attempt {attempt+1}/5)...'
            time.sleep(wait)
            continue
        r.raise_for_status()
        break
    else:
        raise Exception('Wolt API rate limit: too many requests. Try again in a few minutes.')
    data = r.json()

    results = []
    seen_slugs = set()

    for section in data.get('sections', []):
        for item in section.get('items', []):
            venue = item.get('venue', {})
            if not isinstance(venue, dict):
                continue

            slug = venue.get('slug', '')
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            tags = venue.get('tags', [])
            cuisine_str = ', '.join(t for t in tags if isinstance(t, str)) if isinstance(tags, list) else ''

            rating_data = venue.get('rating') or {}
            rating_score = rating_data.get('score', '') if isinstance(rating_data, dict) else ''

            wolt_url = f'https://wolt.com/en/{country_slug}/{city_slug}/restaurant/{slug}'

            results.append({
                'name': venue.get('name', ''),
                'brand_name': venue.get('franchise', ''),
                'city': venue.get('city') or city_name,
                'country': venue.get('country', country_slug.upper()),
                'address': venue.get('address', ''),
                'phone': '',
                'website': '',
                'cuisine': cuisine_str,
                'rating': str(rating_score) if rating_score else '',
                'merchant_name': '',
                'business_id': '',
                'legal_street': '',
                'legal_city': '',
                'legal_post_code': '',
                'legal_country': '',
                'platform_url': wolt_url,
            })

    # Free the large JSON response before phase 2 (or before returning)
    del data, r
    gc.collect()

    total = len(results)
    job['total'] = total

    if not fetch_details:
        job['scraped'] = total
        job['progress'] = 100
        job['message'] = f'Done! Found {total} restaurants near {formatted}.'
        return results

    job['message'] = f'Found {total} restaurants. Fetching details (phone, merchant data)...'
    job['progress'] = 10

    # Phase 2: concurrent per-venue detail scrapes
    index_map = {r['platform_url']: i for i, r in enumerate(results)}
    completed = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_venue_detail, r['platform_url']): r['platform_url'] for r in results}
        for future in as_completed(futures):
            wolt_url = futures[future]
            detail = future.result()
            if detail:
                results[index_map[wolt_url]].update(detail)
            completed += 1
            if completed % 20 == 0:
                pct = 10 + int(completed / total * 85)
                job['progress'] = pct
                job['message'] = f'Fetching details... {completed}/{total}'

    job['scraped'] = total
    job['failed'] = 0
    job['progress'] = 100
    job['message'] = f'Done! Fetched details for {total} restaurants near {formatted}.'
    return results
