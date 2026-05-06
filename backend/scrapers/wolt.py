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
    """Resolve a city/country string to lat/lon using Wolt's geocode endpoint."""
    url = f'{BASE}/v1/google/geocode/json'
    r = requests.get(url, params={'address': location}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    results = data.get('results', [])
    if not results:
        raise ValueError(f'Could not geocode location: {location}')
    loc = results[0]['geometry']['location']
    formatted = results[0].get('formatted_address', location)
    return loc['lat'], loc['lng'], formatted


def get_restaurant_slugs(lat: float, lon: float, job: dict) -> list[dict]:
    """Fetch all restaurant listings for the given coordinates (handles pagination)."""
    restaurants = []
    skip = 0
    batch = 100

    while True:
        url = f'{BASE}/v1/pages/restaurants'
        params = {'lat': lat, 'lon': lon, 'limit': batch, 'skip': skip}
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        # Wolt returns sections; find the restaurant list section
        sections = data.get('sections', [])
        items = []
        for section in sections:
            for item in section.get('items', []):
                venue = item.get('venue') or item.get('track_id') or {}
                if isinstance(item.get('venue'), dict):
                    venue = item['venue']
                    items.append({
                        'slug': venue.get('slug', ''),
                        'name': venue.get('name', ''),
                    })

        if not items:
            break

        restaurants.extend(items)
        skip += batch

        if len(items) < batch:
            break

        job['total'] = len(restaurants)
        job['message'] = f'Found {len(restaurants)} restaurants so far...'
        time.sleep(0.3)

    return restaurants


def get_venue_details(slug: str) -> dict:
    """Fetch full details for a single venue by slug."""
    url = f'{BASE}/v3/venues/slug/{slug}'
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json()
    venue = data.get('results', [{}])[0] if data.get('results') else data

    # Extract fields
    address = venue.get('address', {})
    contact = venue.get('contact', {})
    tags = [t.get('name', '') for t in venue.get('tags', []) if t.get('name')]

    return {
        'name': venue.get('name', ''),
        'city': address.get('city', ''),
        'address': address.get('street_address', ''),
        'phone': contact.get('phone_number', ''),
        'website': contact.get('website', ''),
        'legal_id': venue.get('merchant_id', '') or venue.get('legal_id', ''),
        'cuisine': ', '.join(tags),
        'wolt_url': f'https://wolt.com/en/venue/{slug}',
        'slug': slug,
    }


def scrape_wolt(location: str, cuisine: str, job: dict) -> list[dict]:
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
                # Apply cuisine filter if set
                if cuisine and cuisine.lower() not in details.get('cuisine', '').lower():
                    job['scraped'] = len(results)
                    job['progress'] = int((i + 1) / len(slugs) * 100)
                    continue

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
