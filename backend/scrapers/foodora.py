"""
Foodora scraper — sitemap-based, no browser required.

Strategy:
  Foodora sitemaps at /adventure-map/adventure-map-restaurant-N.xml are accessible
  via Googlebot UA. Each URL encodes /restaurant/{code}/{slug}. We extract the name
  from the slug (capitalize each word) and return records with name + platform_url.

Markets: cz (foodora.cz), at (foodora.at), hu (foodora.hu), no (foodora.no), se (foodora.se)
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

LOCATION_TO_MARKET = {
    # CZ
    'czech republic': 'cz', 'czechia': 'cz', 'česká republika': 'cz', 'czech': 'cz', 'cz': 'cz',
    'prague': 'cz', 'Praha': 'cz', 'praha': 'cz', 'brno': 'cz', 'ostrava': 'cz',
    'plzeň': 'cz', 'plzen': 'cz', 'liberec': 'cz', 'olomouc': 'cz',
    'české budějovice': 'cz', 'ceske budejovice': 'cz',
    'hradec králové': 'cz', 'hradec kralove': 'cz',
    'pardubice': 'cz', 'zlín': 'cz', 'zlin': 'cz',
    'havířov': 'cz', 'havirov': 'cz', 'kladno': 'cz', 'most': 'cz',
    'opava': 'cz', 'frýdek-místek': 'cz', 'frydek-mistek': 'cz',
    # AT
    'austria': 'at', 'österreich': 'at', 'at': 'at',
    'vienna': 'at', 'wien': 'at', 'graz': 'at', 'linz': 'at',
    'salzburg': 'at', 'innsbruck': 'at', 'klagenfurt': 'at',
    # HU
    'hungary': 'hu', 'magyarország': 'hu', 'hu': 'hu',
    'budapest': 'hu', 'debrecen': 'hu', 'miskolc': 'hu',
    'pécs': 'hu', 'pecs': 'hu', 'győr': 'hu', 'gyor': 'hu',
    # NO
    'norway': 'no', 'norge': 'no', 'no': 'no',
    'oslo': 'no', 'bergen': 'no', 'trondheim': 'no', 'stavanger': 'no',
    # SE
    'sweden': 'se', 'sverige': 'se', 'se': 'se',
    'stockholm': 'se', 'gothenburg': 'se', 'göteborg': 'se', 'goteborg': 'se',
    'malmö': 'se', 'malmo': 'se', 'uppsala': 'se',
}

_GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
_RESTAURANT_RE = re.compile(r'/restaurant/([^/]+)/([^/?\s]+)')
_NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}


def _detect_market(location: str) -> str:
    key = location.strip().lower().split(',')[0].strip()
    market = LOCATION_TO_MARKET.get(key)
    if market:
        return market
    # Prefix match (e.g. "Czech Republic, Europe")
    for alias, code in LOCATION_TO_MARKET.items():
        if key.startswith(alias):
            return code
    raise ValueError(
        f"Foodora is not available for '{location}'. "
        f"Supported markets: Czech Republic, Austria, Hungary, Norway, Sweden."
    )


def _slug_to_name(slug: str, code: str) -> str:
    """Convert a URL slug to a readable restaurant name."""
    # Remove trailing market code suffix like '-0123' or '-ab12'
    slug = re.sub(r'-[a-z0-9]{4}$', '', slug)
    return ' '.join(word.capitalize() for word in slug.split('-'))


def _fetch_sitemap_urls(domain: str) -> list[str]:
    """Fetch all restaurant page URLs from Foodora sitemaps."""
    urls = []
    session = requests.Session()
    session.headers['User-Agent'] = _GOOGLEBOT_UA

    for index in range(20):  # up to 20 sitemap shards
        sitemap_url = f"https://{domain}/adventure-map/adventure-map-restaurant-{index}.xml"
        try:
            r = session.get(sitemap_url, timeout=20)
            if r.status_code == 404:
                break  # no more shards
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
    market_code = _detect_market(location)
    market = MARKETS[market_code]
    domain = market['domain']
    country = market['country']

    job['message'] = f"Foodora: fetching restaurant list for {country}..."
    job['progress'] = 5

    urls = _fetch_sitemap_urls(domain)
    log.info(f"Foodora {market_code}: {len(urls)} sitemap URLs")

    job['message'] = f"Foodora: parsing {len(urls)} restaurant URLs..."
    job['progress'] = 60

    records = []
    seen = set()
    for url in urls:
        m = _RESTAURANT_RE.search(url)
        if not m:
            continue
        code, slug = m.group(1), m.group(2)
        if code in seen:
            continue
        seen.add(code)
        name = _slug_to_name(slug, market_code)
        records.append({
            'name':            name,
            'brand_name':      '',
            'phone':           '',
            'website':         '',
            'address':         '',
            'city':            '',
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

    job['scraped'] = len(records)
    job['total'] = len(records)
    job['progress'] = 100
    job['message'] = f"Foodora: done — {len(records)} restaurants for {country}."
    return records
