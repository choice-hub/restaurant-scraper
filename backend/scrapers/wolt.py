"""
Wolt scraper using Wolt's internal REST API.
Fetches restaurant listings and detail pages.
"""
import time
import requests

BASE = 'https://restaurant-api.wolt.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; RestaurantScraper/1.0)',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://wolt.com',
    'Referer': 'https://wolt.com/',
}


def geocode_location(location: str) -> tuple[float, float, str]:
    """Resolve a city/country string to lat/lon using OpenStreetMap Nominatim."""
    url = 'https://nominatim.openstreetmap.org/search'
    r = requests.get(
        url,
        params={'q': location, 'format': 'json', 'limit': 1, 'addressdetails': 1},
        headers={'User-Agent': 'RestaurantScraper/1.0', 'Accept-Language': 'en'},
        timeout=10
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f'Could not find location: {location}. Try a more specific city name.')
    res = results[0]
    addr = res.get('address', {})
    city = addr.get('city') or addr.get('town') or addr.get('village') or location
    country = addr.get('country', '')
    formatted = f"{city}, {country}" if country else city
    return float(res['lat']), float(res['lon']), formatted


def get_restaurant_slugs(lat: float, lon: float, job: dict) -> list[dict]:
    """Fetch all restaurant listings in one call — Wolt returns everything at once."""
    url = f'{BASE}/v1/pages/restaurants'
    r = requests.get(url, params={'lat': lat, 'lon': lon}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    restaurants = []
    seen_slugs = set()

    for section in data.get('sections', []):
        for item in section.get('items', []):
            venue = item.get('venue', {})
            if not isinstance(venue, dict):
                venue = {}
            slug = venue.get('slug') or item.get('slug', '')
            name = venue.get('name') or item.get('name', '')
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                restaurants.append({'slug': slug, 'name': name})

    job['total'] = len(restaurants)
    job['message'] = f'Found {len(restaurants)} restaurants. Fetching details...'
    return restaurants


def get_venue_details(slug: str, retries: int = 3) -> dict:
    """Fetch full details for a single venue by slug, with retry on rate limit."""
    url = f'{BASE}/v3/venues/slug/{slug}'
    for attempt in range(retries):
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return {}
        if r.status_code == 429:
            wait = 5 * (attempt + 1)
            print(f'[Wolt] Rate limited on {slug}, waiting {wait}s...')
            time.sleep(wait)
            continue
        r.raise_for_status()
        break
    else:
        return {}

    data = r.json()
    results = data.get('results', [])
    venue = results[0] if results else data

    address = venue.get('address', {})
    contact = venue.get('contact', {})
    tags = [t.get('name', '') for t in venue.get('tags', []) if t.get('name')]

    return {
        'name': venue.get('name', ''),
        'city': address.get('city', ''),
        'address': address.get('street_address', '') or address.get('street', ''),
        'phone': contact.get('phone_number', '') or contact.get('phone', ''),
        'website': contact.get('website', ''),
        'legal_id': str(venue.get('merchant_id', '') or venue.get('legal_id', '')),
        'cuisine': ', '.join(tags),
        'wolt_url': f'https://wolt.com/en/venue/{slug}',
    }


def scrape_wolt(location: str, cuisine: str, job: dict) -> list[dict]:  # cuisine kept for API compat
    """Main entry point. Returns list of restaurant dicts."""
    job['message'] = f'Geocoding "{location}"...'
    lat, lon, formatted = geocode_location(location)
    job['message'] = f'Fetching restaurant list near {formatted}...'

    slugs = get_restaurant_slugs(lat, lon, job)
    job['total'] = len(slugs)
    job['message'] = f'Found {len(slugs)} restaurants. Fetching details...'

    results = []
    failed = 0

    for i, item in enumerate(slugs):
        slug = item.get('slug')
        if not slug:
            failed += 1
            job['failed'] = failed
            continue

        try:
            details = get_venue_details(slug)
            if details:
                results.append(details)

        except Exception as e:
            failed += 1
            job['failed'] = failed
            print(f'[Wolt] Error fetching {slug}: {e}')

        job['scraped'] = len(results)
        job['failed'] = failed
        job['progress'] = int((i + 1) / len(slugs) * 100)
        job['message'] = f'Scraped {i + 1}/{len(slugs)} restaurants...'
        time.sleep(0.15)  # polite rate limiting

    return results
