"""
Google Maps scraper using the Outscraper API.
Supports multiple business types, dedup by place_id,
per-platform delivery/reservation column extraction.
"""
import os
from outscraper import ApiClient

# ── Business type query strings ───────────────────────────────────────────────
BUSINESS_TYPE_QUERIES = {
    'restaurants': 'restaurants',
    'cafes':       'cafes coffee shops',
    'bars':        'bars pubs',
    'bakeries':    'bakeries',
    'fast_food':   'fast food',
}

DEFAULT_BUSINESS_TYPES = ['restaurants', 'cafes']

# Fields to request from Outscraper
OUTSCRAPER_FIELDS = (
    'name,type,full_address,city,country_code,latitude,longitude,'
    'phone,site,rating,reviews,range,working_hours,'
    'permanently_closed,temporarily_closed,'
    'order_links,booking_appointment_link,photos,url,place_id'
)

# Delivery platform domain matchers (checked in order)
_DELIVERY_MATCHERS = [
    ('delivery_uber_eats',  ['ubereats.com']),
    ('delivery_doordash',   ['doordash.com']),
    ('delivery_wolt',       ['wolt.com']),
    ('delivery_bolt_food',  ['food.bolt.eu', 'bolt.eu/food', 'food.bolt']),
    ('delivery_deliveroo',  ['deliveroo.com']),
    ('delivery_just_eat',   ['just-eat.com', 'just-eat.co.uk', 'just-eat.']),
]

_RESERVATION_MATCHERS = [
    ('reservation_opentable',   ['opentable.com']),
    ('reservation_resy',        ['resy.com']),
    ('reservation_sevenrooms',  ['sevenrooms.com']),
    ('reservation_tock',        ['tock.com', 'exploretock.com']),
]


def _to_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return [str(v) for v in val if v]
    return [str(val)]


def _parse_place(r: dict, business_type: str) -> dict:
    order_links   = _to_list(r.get('order_links'))
    booking_links = _to_list(r.get('booking_appointment_link'))

    # Per-platform delivery columns
    result = {}
    matched_delivery_urls = set()
    for col, domains in _DELIVERY_MATCHERS:
        found = ''
        for link in order_links:
            if any(d in link.lower() for d in domains):
                found = link
                matched_delivery_urls.add(link)
                break
        result[col] = found

    # Anything left over goes to delivery_other
    other_delivery = [l for l in order_links if l not in matched_delivery_urls]
    result['delivery_other'] = other_delivery[0] if other_delivery else ''
    result['has_delivery'] = 'TRUE' if any(
        result[c] for c in ['delivery_uber_eats', 'delivery_doordash', 'delivery_wolt',
                             'delivery_bolt_food', 'delivery_deliveroo', 'delivery_just_eat',
                             'delivery_other']
    ) else ''

    # Per-platform reservation columns
    matched_res_urls = set()
    for col, domains in _RESERVATION_MATCHERS:
        found = ''
        for link in booking_links:
            if any(d in link.lower() for d in domains):
                found = link
                matched_res_urls.add(link)
                break
        result[col] = found

    other_res = [l for l in booking_links if l not in matched_res_urls]
    result['reservation_other'] = other_res[0] if other_res else ''
    result['has_reservation'] = 'TRUE' if any(
        result[c] for c in ['reservation_opentable', 'reservation_resy',
                             'reservation_sevenrooms', 'reservation_tock', 'reservation_other']
    ) else ''

    # Working hours: convert dict/list → readable string
    wh = r.get('working_hours', '')
    if isinstance(wh, dict):
        wh = '; '.join(f"{k}: {v}" for k, v in wh.items())
    elif isinstance(wh, list):
        wh = '; '.join(str(h) for h in wh)

    # First photo URL
    photos = _to_list(r.get('photos'))
    photo1 = photos[0] if photos else ''

    result.update({
        'name':                r.get('name', ''),
        'business_type':       business_type,
        'category':            r.get('type', ''),
        'address':             r.get('full_address', '') or r.get('address', ''),
        'city':                r.get('city', ''),
        'country':             r.get('country_code', '') or r.get('country', ''),
        'latitude':            str(r.get('latitude', '')),
        'longitude':           str(r.get('longitude', '')),
        'phone':               r.get('phone', ''),
        'website':             r.get('site', ''),
        'rating':              str(r.get('rating', '')),
        'reviews':             str(r.get('reviews', '')),
        'price_range':         r.get('range', ''),
        'working_hours':       wh,
        'permanently_closed':  'Yes' if r.get('permanently_closed') else '',
        'temporarily_closed':  'Yes' if r.get('temporarily_closed') else '',
        'photo_url_1':         photo1,
        'google_maps_url':     r.get('url', ''),
        'place_id':            r.get('place_id', ''),
        # kept for app.py compatibility
        'platform_url':        r.get('url', ''),
        'brand_name':          '',
    })
    return result


def scrape_google_maps(
    location: str,
    cuisine: str,
    job: dict,
    business_types: list = None,
    min_reviews: int = 0,
    min_rating: float = 0.0,
    require_website: bool = False,
    require_phone: bool = False,
) -> list[dict]:
    """
    Query Outscraper for each business type, dedup by place_id, apply filters.
    Returns list of records with per-platform delivery/reservation columns.
    """
    api_key = os.environ.get('OUTSCRAPER_API_KEY')
    if not api_key:
        raise ValueError(
            'OUTSCRAPER_API_KEY is not set — add it to Render environment variables.'
        )

    types_to_scrape = business_types or DEFAULT_BUSINESS_TYPES
    client = ApiClient(api_key=api_key)

    all_records: dict[str, dict] = {}   # place_id → record
    total_types = len(types_to_scrape)

    for idx, btype in enumerate(types_to_scrape, 1):
        query_term = BUSINESS_TYPE_QUERIES.get(btype, btype)
        query = f'{query_term} in {location}'

        job['message'] = f'Google Maps: searching {query_term} ({idx}/{total_types})...'
        job['progress'] = int((idx - 1) / total_types * 85)
        print(f'[Google Maps] Query: {query}')

        try:
            raw = client.google_maps_search(
                [query],
                language='en',
                limit=500,
                drop_duplicates=True,
                fields=OUTSCRAPER_FIELDS,
            )
            # API returns flat list of dicts (not list-of-lists)
            places = raw if isinstance(raw, list) and raw and isinstance(raw[0], dict) else (raw[0] if raw else [])
            print(f'[Google Maps] {btype}: {len(places)} raw results')

            for place in places:
                pid = place.get('place_id', '')
                if not pid:
                    continue
                if pid not in all_records:
                    all_records[pid] = _parse_place(place, query_term)
                else:
                    # Merge business type label
                    existing = all_records[pid]['business_type']
                    if query_term not in existing:
                        all_records[pid]['business_type'] = f'{existing}, {query_term}'

        except Exception as e:
            print(f'[Google Maps] {btype} query failed: {e}')

    results = list(all_records.values())

    # Apply filters
    if min_reviews > 0:
        results = [r for r in results if int(r.get('reviews') or 0) >= min_reviews]
    if min_rating > 0:
        results = [r for r in results if float(r.get('rating') or 0) >= min_rating]
    if require_website:
        results = [r for r in results if r.get('website')]
    if require_phone:
        results = [r for r in results if r.get('phone')]

    # Compute stats for the job
    job['gm_stats'] = {
        'total':            len(results),
        'with_phone':       sum(1 for r in results if r.get('phone')),
        'with_website':     sum(1 for r in results if r.get('website')),
        'with_delivery':    sum(1 for r in results if r.get('has_delivery') == 'TRUE'),
        'with_reservation': sum(1 for r in results if r.get('has_reservation') == 'TRUE'),
    }

    job['scraped']  = len(results)
    job['progress'] = 100
    job['message']  = f'Google Maps: found {len(results)} places in {location}.'
    print(f'[Google Maps] Done — {len(results)} results after dedup + filters')
    return results
