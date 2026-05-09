"""
Wolt scraper using Wolt's internal REST API.
Extracts all restaurant data from the single listing endpoint (no per-venue calls needed).
"""
import requests

BASE = 'https://restaurant-api.wolt.com'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Origin': 'https://wolt.com',
    'Referer': 'https://wolt.com/',
}


# ISO 3166-1 alpha-2 → Wolt URL country segment
_COUNTRY_CODE_MAP = {
    'cz': 'cze', 'sk': 'svk', 'pl': 'pol', 'hu': 'hun', 'ro': 'rou',
    'hr': 'hrv', 'rs': 'srb', 'bg': 'bgr', 'gr': 'grc', 'il': 'isr',
    'fi': 'fin', 'se': 'swe', 'no': 'nor', 'dk': 'dnk', 'ee': 'est',
    'lv': 'lva', 'lt': 'ltu', 'de': 'deu', 'at': 'aut', 'ch': 'che',
    'jp': 'jpn', 'ge': 'geo', 'az': 'aze', 'kz': 'kaz',
}


def geocode_location(location: str) -> tuple[float, float, str, str, str]:
    """Resolve a city/country string to lat/lon using OpenStreetMap Nominatim.
    Returns (lat, lon, formatted, city_slug, country_slug)."""
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
    country_code2 = res.get('address', {}).get('country_code', '').lower()
    country_slug = _COUNTRY_CODE_MAP.get(country_code2, country_code2)
    city_slug = city.lower().replace(' ', '-')
    formatted = f"{city}, {country}" if country else city
    return float(res['lat']), float(res['lon']), formatted, city_slug, country_slug


def scrape_wolt(location: str, cuisine: str, job: dict) -> list[dict]:
    """Main entry point. Extracts all restaurant data from the listing API in one call."""
    job['message'] = f'Geocoding "{location}"...'
    lat, lon, formatted, city_slug, country_slug = geocode_location(location)
    city_name = formatted.split(',')[0].strip()

    job['message'] = f'Fetching restaurant list near {formatted}...'
    url = f'{BASE}/v1/pages/restaurants'
    r = requests.get(url, params={'lat': lat, 'lon': lon}, headers=HEADERS, timeout=30)
    r.raise_for_status()
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
            if isinstance(tags, list):
                cuisine_str = ', '.join(t for t in tags if isinstance(t, str))
            else:
                cuisine_str = ''

            rating_data = venue.get('rating') or {}
            rating_score = rating_data.get('score', '') if isinstance(rating_data, dict) else ''

            results.append({
                'name': venue.get('name', ''),
                'city': venue.get('city') or city_name,
                'address': venue.get('address', ''),
                'phone': '',
                'website': '',
                'legal_id': venue.get('id', ''),
                'cuisine': cuisine_str,
                'rating': str(rating_score) if rating_score else '',
                'wolt_url': f'https://wolt.com/en/{country_slug}/{city_slug}/restaurant/{slug}',
            })

    job['total'] = len(results)
    job['scraped'] = len(results)
    job['failed'] = 0
    job['progress'] = 100
    job['message'] = f'Found {len(results)} restaurants near {formatted}.'
    return results
