"""
Bolt Food scraper — direct API calls, no browser required.

Strategy:
1. Geocode the city to get lat/lng
2. Call the Bolt Food getScreenContent API (screen_id=360003) with lat/lng
3. Parse the providers dict from the response
4. Return structured restaurant records

The API at deliveryuser.live.boltsvc.net is publicly accessible with minimal
device headers. No Playwright, no headless browser, no Cloudflare cookies needed.

KNOWN_CITIES: lat/lng coords for fast lookups without geocoding.
Add new cities by adding their coordinates.
"""
import logging
import uuid

import requests

log = logging.getLogger(__name__)

# KNOWN_CITIES: lowercase city name → (lat, lng)
KNOWN_CITIES = {
    # Czech Republic
    "brno":                  (49.1951,  16.6068),
    "prague":                (50.0755,  14.4378),
    "praha":                 (50.0755,  14.4378),
    "ostrava":               (49.8209,  18.2625),
    "plzeň":                 (49.7384,  13.3736),
    "plzen":                 (49.7384,  13.3736),
    "liberec":               (50.7671,  15.0562),
    "olomouc":               (49.5938,  17.2509),
    "české budějovice":      (48.9745,  14.4746),
    "ceske budejovice":      (48.9745,  14.4746),
    "hradec králové":        (50.2092,  15.8328),
    "hradec kralove":        (50.2092,  15.8328),
    "pardubice":             (50.0343,  15.7812),
    "zlín":                  (49.2244,  17.6647),
    "zlin":                  (49.2244,  17.6647),
    "havířov":               (49.7801,  18.4334),
    "havirov":               (49.7801,  18.4334),
    "kladno":                (50.1473,  14.1029),
    "most":                  (50.5018,  13.6367),
    "opava":                 (49.9381,  17.9036),
    "frýdek-místek":         (49.6875,  18.3653),
    "frydek-mistek":         (49.6875,  18.3653),
    # Slovakia
    "bratislava":            (48.1486,  17.1077),
    # Poland
    "warsaw":                (52.2298,  21.0118),
    # Baltics
    "riga":                  (56.9460,  24.1059),
    "tallinn":               (59.4370,  24.7536),
    "vilnius":               (54.6872,  25.2797),
    # Hungary
    "budapest":              (47.4979,  19.0402),
    # Nordics
    "helsinki":              (60.1699,  24.9384),
    "stockholm":             (59.3293,  18.0686),
    "oslo":                  (59.9139,  10.7522),
    "copenhagen":            (55.6761,  12.5683),
    # DACH
    "berlin":                (52.5200,  13.4050),
    "vienna":                (48.2082,  16.3738),
    "wien":                  (48.2082,  16.3738),
    # Western Europe
    "amsterdam":             (52.3676,   4.9041),
    "paris":                 (48.8566,   2.3522),
    "london":                (51.5074,  -0.1278),
    "madrid":                (40.4168,  -3.7038),
    "rome":                  (41.9028,  12.4964),
    "lisbon":                (38.7169,  -9.1395),
    # SEE
    "bucharest":             (44.4268,  26.1025),
    "sofia":                 (42.6977,  23.3219),
    "athens":                (37.9838,  23.7275),
    "zagreb":                (45.8150,  15.9819),
    "belgrade":              (44.7866,  20.4489),
    # Eastern Europe
    "kiev":                  (50.4501,  30.5234),
    "kyiv":                  (50.4501,  30.5234),
    "minsk":                 (53.9045,  27.5615),
    "tbilisi":               (41.6938,  44.8015),
    "yerevan":               (40.1792,  44.4991),
    "baku":                  (40.4093,  49.8671),
}

BOLT_SCREEN_ID = 360003
BOLT_API_URL = "https://deliveryuser.live.boltsvc.net/deliveryClient/public/getScreenContent"

_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
})


def _eta_str(seconds_min: int, seconds_max: int) -> str:
    if not seconds_min and not seconds_max:
        return ""
    lo = seconds_min // 60
    hi = seconds_max // 60
    return f"{lo} to {hi} minutes" if lo != hi else f"{lo} minutes"


def _provider_to_record(provider: dict, city: str) -> dict:
    contact  = provider.get("contact", {}) or {}
    delivery = provider.get("delivery", {}) or {}
    fee_info = delivery.get("fee", {}) or {}
    eta_info = (provider.get("eta", {}) or {}).get("delivery", {}) or {}
    rating   = provider.get("rating", {}) or {}
    pid      = provider.get("id", "")
    slug     = provider.get("slug", "")

    platform_url = f"https://food.bolt.eu/en/p/{pid}-{slug}/" if pid and slug else ""

    return {
        "name":            provider.get("name", ""),
        "brand_name":      "",
        "phone":           contact.get("phone", ""),
        "website":         "",
        "address":         contact.get("address", ""),
        "city":            city,
        "country":         "",
        "cuisine":         "",
        "rating":          str(rating.get("value", "")),
        "review_count":    str(rating.get("count", "")),
        "delivery_fee":    fee_info.get("price_str", ""),
        "delivery_time":   _eta_str(eta_info.get("min", 0), eta_info.get("max", 0)),
        "merchant_name":   "",
        "business_id":     "",
        "legal_street":    "",
        "legal_city":      "",
        "legal_post_code": "",
        "legal_country":   "",
        "platform_url":    platform_url,
    }


def _fetch_providers(lat: float, lng: float) -> dict:
    """Fetch all providers from Bolt Food API for given coordinates."""
    params = {
        "screen_id":       BOLT_SCREEN_ID,
        "delivery_lat":    lat,
        "delivery_lng":    lng,
        "deviceId":        str(uuid.uuid4()),
        "deviceType":      "web",
        "device_name":     "Chrome",
        "device_os_version": "124",
        "language":        "en",
        "version":         "1.0",
    }
    resp = _SESSION.get(BOLT_API_URL, params=params, timeout=20)
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise ValueError(f"Bolt API error: {body.get('message')} (code {body.get('code')})")
    return body.get("data", {}).get("providers", {}).get("data", {})


def scrape_bolt(location: str, cuisine: str, job: dict) -> list:
    """Synchronous entry point called by app.py."""
    city_key = location.strip().lower().split(",")[0].strip()
    city_display = location.split(",")[0].strip()

    job["message"] = f"Bolt: locating {city_display}..."
    job["progress"] = 5

    if city_key in KNOWN_CITIES:
        lat, lng = KNOWN_CITIES[city_key]
        log.info(f"Bolt: known city '{city_key}' → ({lat}, {lng})")
    else:
        from scrapers.wolt import geocode_location
        lat, lng, *_ = geocode_location(location)
        log.info(f"Bolt: geocoded '{location}' → ({lat}, {lng})")

    job["message"] = f"Bolt: fetching restaurants for {city_display}..."
    job["progress"] = 20

    providers = _fetch_providers(lat, lng)
    log.info(f"Bolt: fetched {len(providers)} providers for {city_display}")

    records = [_provider_to_record(p, city_display) for p in providers.values()]

    job["scraped"]  = len(records)
    job["total"]    = len(records)
    job["progress"] = 100
    job["message"]  = f"Bolt: done — {len(records)} restaurants from {city_display}."
    return records
