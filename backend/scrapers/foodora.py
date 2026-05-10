"""
Foodora scraper — sitemap-based, no browser required.

Strategy:
  Foodora sitemaps at /adventure-map/adventure-map-restaurant-N.xml are accessible
  via Googlebot UA. Each URL encodes /restaurant/{code}/{slug}. The city name
  appears as a hyphen-delimited word in the slug (e.g. 'mcdonalds-brno-nam-svobody',
  'matcha-crew-brno', 'popeyes-praha-nr7').

  For country queries  → fetch all market sitemaps, populate city from each slug.
  For city queries     → same, then filter to records whose slug contains the city word.

Markets: cz, at, hu, no, se
"""
import logging
import re
import requests
from xml.etree import ElementTree

log = logging.getLogger(__name__)

MARKETS = {
    'cz': {'domain': 'www.foodora.cz', 'country': 'Czech Republic'},
    'at': {'domain': 'www.foodora.at', 'country': 'Austria'},
    'hu': {'domain': 'www.foodora.hu', 'country': 'Hungary'},
    'no': {'domain': 'www.foodora.no', 'country': 'Norway'},
    'se': {'domain': 'www.foodora.se', 'country': 'Sweden'},
}

# location input (lowercase) → market code
LOCATION_TO_MARKET = {
    # CZ — country
    'czech republic': 'cz', 'czechia': 'cz', 'česká republika': 'cz', 'czech': 'cz', 'cz': 'cz',
    # CZ — cities
    'prague': 'cz', 'Praha': 'cz', 'praha': 'cz', 'brno': 'cz', 'ostrava': 'cz',
    'plzeň': 'cz', 'plzen': 'cz', 'liberec': 'cz', 'olomouc': 'cz',
    'české budějovice': 'cz', 'ceske budejovice': 'cz',
    'hradec králové': 'cz', 'hradec kralove': 'cz',
    'pardubice': 'cz', 'zlín': 'cz', 'zlin': 'cz',
    'havířov': 'cz', 'havirov': 'cz', 'kladno': 'cz', 'most': 'cz',
    'opava': 'cz', 'frýdek-místek': 'cz', 'frydek-mistek': 'cz',
    # AT — country
    'austria': 'at', 'österreich': 'at', 'at': 'at',
    # AT — cities
    'vienna': 'at', 'wien': 'at', 'graz': 'at', 'linz': 'at',
    'salzburg': 'at', 'innsbruck': 'at', 'klagenfurt': 'at',
    # HU — country
    'hungary': 'hu', 'magyarország': 'hu', 'hu': 'hu',
    # HU — cities
    'budapest': 'hu', 'debrecen': 'hu', 'miskolc': 'hu',
    'pécs': 'hu', 'pecs': 'hu', 'győr': 'hu', 'gyor': 'hu',
    # NO — country
    'norway': 'no', 'norge': 'no', 'no': 'no',
    # NO — cities
    'oslo': 'no', 'bergen': 'no', 'trondheim': 'no', 'stavanger': 'no',
    # SE — country
    'sweden': 'se', 'sverige': 'se', 'se': 'se',
    # SE — cities
    'stockholm': 'se', 'gothenburg': 'se', 'göteborg': 'se', 'goteborg': 'se',
    'malmö': 'se', 'malmo': 'se', 'uppsala': 'se',
}

# Whole-country inputs that should NOT trigger city filtering
_COUNTRY_KEYS = {
    'czech republic', 'czechia', 'česká republika', 'czech', 'cz',
    'austria', 'österreich', 'at',
    'hungary', 'magyarország', 'hu',
    'norway', 'norge', 'no',
    'sweden', 'sverige', 'se',
}

# Slug word(s) as they appear in Foodora URLs → city display name
# Longer keys (2-word) must be checked before single-word to avoid partial matches
CITY_SLUGS = {
    # CZ
    'ceske-budejovice': 'České Budějovice',
    'hradec-kralove':   'Hradec Králové',
    'frydek-mistek':    'Frýdek-Místek',
    'jindrichuv-hradec':'Jindřichův Hradec',
    'usti-nad-labem':   'Ústí nad Labem',
    'prague':   'Prague',
    'praha':    'Prague',
    'brno':     'Brno',
    'ostrava':  'Ostrava',
    'plzen':    'Plzeň',
    'liberec':  'Liberec',
    'olomouc':  'Olomouc',
    'pardubice':'Pardubice',
    'zlin':     'Zlín',
    'havirov':  'Havířov',
    'kladno':   'Kladno',
    'opava':    'Opava',
    'most':     'Most',
    'usti':     'Ústí nad Labem',
    # AT
    'wien':        'Vienna',
    'vienna':      'Vienna',
    'graz':        'Graz',
    'linz':        'Linz',
    'salzburg':    'Salzburg',
    'innsbruck':   'Innsbruck',
    'klagenfurt':  'Klagenfurt',
    # HU
    'budapest':  'Budapest',
    'debrecen':  'Debrecen',
    'miskolc':   'Miskolc',
    'pecs':      'Pécs',
    'gyor':      'Győr',
    # NO
    'oslo':        'Oslo',
    'bergen':      'Bergen',
    'trondheim':   'Trondheim',
    'stavanger':   'Stavanger',
    # SE
    'stockholm':   'Stockholm',
    'goteborg':    'Gothenburg',
    'gothenburg':  'Gothenburg',
    'malmo':       'Malmö',
    'uppsala':     'Uppsala',
}

# User city input (lowercase, comma-stripped) → slug key in CITY_SLUGS
_INPUT_TO_CITY_SLUG = {
    'brno': 'brno',
    'prague': 'prague', 'Praha': 'prague', 'praha': 'prague',
    'ostrava': 'ostrava',
    'plzeň': 'plzen', 'plzen': 'plzen',
    'liberec': 'liberec',
    'olomouc': 'olomouc',
    'české budějovice': 'ceske-budejovice', 'ceske budejovice': 'ceske-budejovice',
    'hradec králové': 'hradec-kralove', 'hradec kralove': 'hradec-kralove',
    'pardubice': 'pardubice',
    'zlín': 'zlin', 'zlin': 'zlin',
    'havířov': 'havirov', 'havirov': 'havirov',
    'kladno': 'kladno',
    'opava': 'opava',
    'most': 'most',
    'frýdek-místek': 'frydek-mistek', 'frydek-mistek': 'frydek-mistek',
    'vienna': 'wien', 'wien': 'wien',
    'graz': 'graz', 'linz': 'linz', 'salzburg': 'salzburg',
    'innsbruck': 'innsbruck', 'klagenfurt': 'klagenfurt',
    'budapest': 'budapest', 'debrecen': 'debrecen', 'miskolc': 'miskolc',
    'pécs': 'pecs', 'pecs': 'pecs', 'győr': 'gyor', 'gyor': 'gyor',
    'oslo': 'oslo', 'bergen': 'bergen', 'trondheim': 'trondheim', 'stavanger': 'stavanger',
    'stockholm': 'stockholm',
    'gothenburg': 'goteborg', 'göteborg': 'goteborg', 'goteborg': 'goteborg',
    'malmö': 'malmo', 'malmo': 'malmo', 'uppsala': 'uppsala',
}

_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
_RESTAURANT_RE = re.compile(r'/restaurant/([^/]+)/([^/?\s]+)')
_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
# Ordered longest-first so 2-word cities match before their substrings
_CITY_SLUG_KEYS = sorted(CITY_SLUGS.keys(), key=len, reverse=True)


def _detect_market_and_city(location: str) -> tuple:
    """
    Returns (market_code, city_slug_or_None).
    city_slug is None for whole-country queries.
    """
    key = location.strip().lower().split(',')[0].strip()
    if key in _COUNTRY_KEYS:
        return LOCATION_TO_MARKET[key], None
    market = LOCATION_TO_MARKET.get(key)
    if market:
        return market, _INPUT_TO_CITY_SLUG.get(key)
    # Prefix match
    for alias in LOCATION_TO_MARKET:
        if key.startswith(alias):
            if alias in _COUNTRY_KEYS:
                return LOCATION_TO_MARKET[alias], None
            return LOCATION_TO_MARKET[alias], _INPUT_TO_CITY_SLUG.get(alias)
    raise ValueError(
        f"Foodora is not available for '{location}'. "
        f"Supported: Czech Republic, Austria, Hungary, Norway, Sweden "
        f"(or any city within those markets)."
    )


def _clean_slug(raw: str) -> str:
    """Strip _odr_cz and similar suffixes, normalize."""
    return raw.split('_')[0].lower()


def _strip_hash(parts: list) -> list:
    """Remove trailing 3-6 char token if it contains digits (e.g. z780, nr7, fur4)."""
    if parts and re.fullmatch(r'[a-z0-9]{3,6}', parts[-1]) and re.search(r'[0-9]', parts[-1]):
        return parts[:-1]
    return parts


def _extract_city_and_name(slug: str) -> tuple[str, str]:
    """
    Scan slug parts for a known city slug (longest match wins).
    Returns (city_display, name_without_city_and_hash).
    """
    parts = slug.split('-')

    for city_key in _CITY_SLUG_KEYS:
        city_parts = city_key.split('-')
        n = len(city_parts)
        for i in range(len(parts) - n + 1):
            if parts[i:i+n] == city_parts:
                city_display = CITY_SLUGS[city_key]
                remaining = parts[:i] + parts[i+n:]
                remaining = _strip_hash(remaining)
                name = ' '.join(w.capitalize() for w in remaining if w)
                return city_display, name

    # No city found — just clean the name
    remaining = _strip_hash(list(parts))
    name = ' '.join(w.capitalize() for w in remaining if w)
    return '', name


def _fetch_sitemap_urls(domain: str) -> list[str]:
    """Fetch all restaurant page URLs from Foodora sitemaps."""
    urls = []
    session = requests.Session()
    session.headers['User-Agent'] = _GOOGLEBOT_UA

    for index in range(20):
        sitemap_url = f"https://{domain}/adventure-map/adventure-map-restaurant-{index}.xml"
        try:
            r = session.get(sitemap_url, timeout=20)
            if r.status_code == 404:
                break
            r.raise_for_status()
            root = ElementTree.fromstring(r.content)
            locs = [el.text for el in root.findall('sm:url/sm:loc', _NS) if el.text]
            if not locs:
                break
            urls.extend(locs)
            log.info(f"Foodora sitemap {index}: {len(locs)} URLs (total {len(urls)})")
        except ElementTree.ParseError as e:
            log.warning(f"Foodora sitemap {index} parse error: {e}")
            break
        except Exception as e:
            log.warning(f"Foodora sitemap {index} fetch error: {e}")
            break

    return urls


def scrape_foodora(location: str, cuisine: str, job: dict) -> list[dict]:
    """Synchronous entry point called by app.py."""
    market_code, city_filter = _detect_market_and_city(location)
    market  = MARKETS[market_code]
    domain  = market['domain']
    country = market['country']

    city_label = CITY_SLUGS.get(city_filter, location.split(',')[0].strip()) if city_filter else country

    job['message'] = f"Foodora: fetching sitemaps for {country}..."
    job['progress'] = 5

    urls = _fetch_sitemap_urls(domain)
    log.info(f"Foodora {market_code}: {len(urls)} sitemap URLs")

    job['message'] = f"Foodora: parsing {len(urls)} URLs" + (f", filtering by {city_label}..." if city_filter else "...")
    job['progress'] = 60

    records = []
    seen = set()
    for url in urls:
        m = _RESTAURANT_RE.search(url)
        if not m:
            continue
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)

        raw_slug = m.group(2)
        slug = _clean_slug(raw_slug)
        city_display, name = _extract_city_and_name(slug)

        # Apply city filter
        if city_filter and city_filter not in slug.split('-'):
            # Also try multi-word city (e.g. ceske-budejovice)
            if '-' in city_filter:
                city_parts = city_filter.split('-')
                slug_parts = slug.split('-')
                found = any(slug_parts[i:i+len(city_parts)] == city_parts
                            for i in range(len(slug_parts) - len(city_parts) + 1))
                if not found:
                    continue
            else:
                continue

        records.append({
            'name':            name or slug.replace('-', ' ').title(),
            'brand_name':      '',
            'phone':           '',
            'website':         '',
            'address':         '',
            'city':            city_display,
            'country':         country,
            'cuisine':         '',
            'rating':          '',
            'review_count':    '',
            'delivery_fee':    '',
            'delivery_time':   '',
            'merchant_name':   '',
            'business_id':     '',
            'legal_street':    '',
            'legal_city':      '',
            'legal_post_code': '',
            'legal_country':   '',
            'platform_url':    url,
        })

    # If city filter returned nothing, fall back to full market
    if city_filter and not records:
        log.warning(f"Foodora: no results for city filter '{city_filter}', returning full market")
        return scrape_foodora(country, cuisine, job)

    job['scraped'] = len(records)
    job['total']   = len(records)
    job['progress'] = 100
    job['message']  = f"Foodora: done — {len(records)} restaurants" + (f" in {city_label}." if city_filter else f" for {country}.")
    return records
