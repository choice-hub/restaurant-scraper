"""
Foodora scraper using their public API.
"""
import time
import requests

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (compatible; RestaurantScraper/1.0)',
    'Accept': 'application/json',
    'Accept-Language': 'en-US,en;q=0.9',
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


def scrape_foodora(location: str, cuisine: str, job: dict) -> list[dict]:
    job['message'] = f'Geocoding "{location}" for Foodora...'
    lat, lon = geocode_location(location)
    job['message'] = 'Fetching Foodora restaurant list...'

    url = 'https://www.foodora.com/api/v2/restaurants'
    params = {
        'latitude': lat,
        'longitude': lon,
        'limit': 200,
        'offset': 0,
        'include': 'cuisines,address',
    }

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise RuntimeError(f'Foodora API error: {e}')

    restaurants_raw = data.get('data', {}).get('items', [])
    job['total'] = len(restaurants_raw)
    job['message'] = f'Found {len(restaurants_raw)} Foodora restaurants. Processing...'

    results = []
    for i, r_data in enumerate(restaurants_raw):
        cuisine_tags = ', '.join(
            c.get('name', '') for c in r_data.get('cuisines', [])
        )
        if cuisine and cuisine.lower() not in cuisine_tags.lower():
            job['progress'] = int((i + 1) / len(restaurants_raw) * 100)
            continue

        address = r_data.get('address', {})
        results.append({
            'name': r_data.get('name', ''),
            'city': address.get('city', location),
            'address': address.get('street_name', '') + ' ' + address.get('street_number', ''),
            'phone': r_data.get('phone', ''),
            'website': r_data.get('website', ''),
            'legal_id': r_data.get('id', ''),
            'cuisine': cuisine_tags,
            'wolt_url': f"https://www.foodora.com/restaurant/{r_data.get('code', '')}",
        })

        job['scraped'] = len(results)
        job['progress'] = int((i + 1) / len(restaurants_raw) * 100)
        job['message'] = f'Processed {i + 1}/{len(restaurants_raw)} Foodora restaurants...'
        time.sleep(0.05)

    return results
