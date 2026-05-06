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
    """Fetch all restaurant listings for the given coordinates."""
    restaurants = []
    skip = 0
    batch = 100

    while True:
        url = f'{BASE}/v1/pages/restaurants'
        params = {'lat': lat, 'lon': lon, 'limit': batch, 'skip': skip}
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()

        items = []
        sections = data.get('sections', [])
        for section in sections:
            for item in section.get('items', []):
                # Wolt API nests venue data differently across versions
                venue = item.get('venue', {})
                if not isinstance(venue, dict):
                    venue = {}
                slug = venue.get('slug') or item.get('slug', '')
                name = venue.get('name') or item.get('name', '')
                if slug:
                    items.append({'slug': slug, 'name': name})

        if not items:
            break

        restaurants.extend(items)
        skip += batch
        job['total'] = len(restaurants)
        job['message'] = f'Found {len(restaurants)} restaurants so far...'
        time.sleep(0.3)

        if len(items) < batch:
            break

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
