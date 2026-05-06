"""
Glovo scraper using Glovo's public store API.
"""
import time
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; RestaurantScraper/1.0)',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
    'Glovo-App-Type': 'WEB',
    'Glovo-Language': 'en',
}

GEOCODE_URL = 'https://nominatim.openstreetmap.org/search'


def geocode_location(location: str) -> tuple[float, float]:
    r = requests.get(
        GEOCODE_URL,
        params={'q': location, 'format': 'json', 'limit': 1},
        headers={'User-Agent': 'RestaurantScraper/1.0'},
        timeout=10
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f'Could not geocode: {location}')
    return float(results[0]['lat']), float(results[0]['lon'])


def scrape_glovo(location: str, cuisine: str, job: dict) -> list[dict]:
    job['message'] = f'Geocoding "{location}" for Glovo...'
    lat, lon = geocode_location(location)
    job['message'] = 'Fetching Glovo restaurant list...'

    url = 'https://api.glovoapp.com/v3/stores/addresses'
    params = {
        'latitude': lat,
        'longitude': lon,
        'storeTypeId': 1,  # restaurants
        'limit': 200,
    }

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f'Glovo API error: {e}')

    stores = data.get('stores', [])
    job['total'] = len(stores)
    job['message'] = f'Found {len(stores)} Glovo restaurants. Processing...'

    results = []
    for i, store in enumerate(stores):
        cuisine_tags = ', '.join(
            c.get('name', '') for c in store.get('attributes', [])
            if c.get('type') == 'CUISINE'
        )
        if cuisine and cuisine.lower() not in cuisine_tags.lower():
            job['progress'] = int((i + 1) / len(stores) * 100)
            continue

        address = store.get('address', {})
        results.append({
            'name': store.get('name', ''),
            'city': address.get('city', location),
            'address': address.get('street', ''),
            'phone': store.get('phone', ''),
            'website': store.get('externalWebsite', ''),
            'legal_id': store.get('id', ''),
            'cuisine': cuisine_tags,
            'wolt_url': f"https://glovoapp.com/en/store/{store.get('slug', '')}",
        })

        job['scraped'] = len(results)
        job['progress'] = int((i + 1) / len(stores) * 100)
        job['message'] = f'Processed {i + 1}/{len(stores)} Glovo restaurants...'
        time.sleep(0.05)

    return results
