import os
from outscraper import ApiClient

# Map booking URL domains → provider names
RESERVATION_PROVIDERS = {
    'opentable.com':          'OpenTable',
    'resy.com':               'Resy',
    'thefork.com':            'TheFork',
    'lafourchette.com':       'TheFork',
    'fork.com':               'TheFork',
    'sevenrooms.com':         'SevenRooms',
    'tock.com':               'Tock',
    'yelp.com/reservations':  'Yelp Reservations',
    'quandoo.':               'Quandoo',
    'bookatable.':            'Bookatable',
    'formitable.':            'Formitable',
    'covermanager.':          'CoverManager',
    'restablo.':              'Restablo',
    'resengo.':               'Resengo',
    'eat.app':                'Eat App',
    'tableo.':                'Tableo',
}


def _detect_reservation_provider(links) -> str:
    """Given a list (or string) of booking URLs, return the provider name."""
    if not links:
        return ''
    # Outscraper may return a list or a single string
    if isinstance(links, str):
        links = [links]
    for link in links:
        url = str(link).lower()
        for domain, name in RESERVATION_PROVIDERS.items():
            if domain in url:
                return name
    return 'Yes (unknown provider)'


def scrape_google_maps(location: str, cuisine: str, job: dict) -> list[dict]:
    api_key = os.environ.get('OUTSCRAPER_API_KEY')
    if not api_key:
        raise ValueError('OUTSCRAPER_API_KEY not configured — add it to .env and Render env vars')

    client = ApiClient(api_key=api_key)

    # Build search query
    if cuisine:
        query = f'{cuisine} restaurants in {location}'
    else:
        query = f'restaurants in {location}'

    job['message'] = f'Google Maps: searching "{query}"...'
    print(f'[Google Maps] Query: {query}')

    results_raw = client.google_maps_search(
        [query],
        language='en',
        limit=500,           # Outscraper paginates automatically up to this count
        drop_duplicates=True,
    )

    # google_maps_search returns a list of lists (one per query)
    restaurants = results_raw[0] if results_raw else []
    print(f'[Google Maps] Raw results: {len(restaurants)}')

    out = []
    for r in restaurants:
        # Reservation: Outscraper field is 'booking_appointment_links' (list or None)
        booking_links = r.get('booking_appointment_links') or []
        reservation = _detect_reservation_provider(booking_links)

        out.append({
            'name':               r.get('name', ''),
            'website':            r.get('site', ''),
            'reviews':            r.get('reviews', ''),
            'rating':             r.get('rating', ''),
            'city':               r.get('city', '') or location,
            'address':            r.get('full_address', '') or r.get('address', ''),
            'reservation_system': reservation,
            'google_maps_url':    r.get('url', ''),
            # Fields used by app.py dedup logic
            'brand_name':         '',
            'platform_url':       r.get('url', ''),
        })

    job['scraped'] = len(out)
    job['message'] = f'Google Maps: {len(out)} restaurants found'
    print(f'[Google Maps] Done — {len(out)} restaurants')
    return out
