"""
Bolt Food scraper — Playwright + API response interception.

Strategy:
1. Navigate to food.bolt.eu/en/{city_id}-{slug}/ with headless Chromium
2. Intercept all getScreenContent API responses (they return full provider data)
3. Scroll the page to trigger lazy-loading of more carousels
4. Aggregate unique providers across all intercepted responses
5. Return structured restaurant records

This avoids fragile DOM parsing — data comes straight from Bolt's JSON API.

KNOWN_CITIES: add new cities by calling discover_bolt_city_id(city_name, lat, lng).
"""
import asyncio
import logging
import random
import re
from datetime import datetime

# KNOWN_CITIES: lowercase city name → (city_id, url_slug)
KNOWN_CITIES = {
    "brno":       (456, "brno"),
    "prague":     (271, "prague"),
    "bratislava": (270, "bratislava"),
    "warsaw":     (300, "warsaw"),
    "riga":       (302, "riga"),
    "tallinn":    (303, "tallinn"),
    "vilnius":    (301, "vilnius"),
    "budapest":   (280, "budapest"),
    "helsinki":   (250, "helsinki"),
}

# Prague IP coords — what Bolt's server uses for CZ/SK IPs
IP_LAT, IP_LNG = 50.0805, 14.467

SUGG_SEL = "[data-testid='screens.DestinationLanding.searchSuggestion']"

log = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

async def _rand(lo=1.2, hi=2.8):
    await asyncio.sleep(random.uniform(lo, hi))


def _eta_str(seconds_min: int, seconds_max: int) -> str:
    """Convert seconds range to '15 to 20 minutes' string."""
    if not seconds_min and not seconds_max:
        return ""
    lo = seconds_min // 60
    hi = seconds_max // 60
    return f"{lo} to {hi} minutes" if lo != hi else f"{lo} minutes"


def _provider_to_record(provider: dict, city: str) -> dict:
    """Map a Bolt Food API provider object to our standard record format."""
    contact = provider.get("contact", {})
    delivery = provider.get("delivery", {}) or {}
    fee_info = delivery.get("fee", {}) or {}
    eta_info  = provider.get("eta", {}).get("delivery", {}) or {}
    rating    = provider.get("rating", {}) or {}
    slug      = provider.get("slug", "")
    pid       = provider.get("id", "")

    city_id = KNOWN_CITIES.get(city.lower(), (None,))[0]
    slug_city = KNOWN_CITIES.get(city.lower(), (None, ""))[1]
    if city_id and slug:
        platform_url = f"https://food.bolt.eu/en/{city_id}-{slug_city}/p/{pid}-{slug}/"
    else:
        platform_url = ""

    return {
        "name":           provider.get("name", ""),
        "brand_name":     "",
        "phone":          contact.get("phone", ""),
        "website":        "",
        "address":        contact.get("address", ""),
        "city":           city,
        "country":        "",
        "cuisine":        "",
        "rating":         str(rating.get("value", "")),
        "review_count":   str(rating.get("count", "")),
        "delivery_fee":   fee_info.get("price_str", ""),
        "delivery_time":  _eta_str(eta_info.get("min", 0), eta_info.get("max", 0)),
        "merchant_name":  "",
        "business_id":    "",
        "legal_street":   "",
        "legal_city":     "",
        "legal_post_code": "",
        "legal_country":  "",
        "platform_url":   platform_url,
    }


# ── City discovery ─────────────────────────────────────────────────────────

async def _discover_city_async(city: str, city_lat: float, city_lng: float) -> tuple | None:
    """
    Open food.bolt.eu with mocked geolocation coordinates, type city name,
    click first matching suggestion, and extract (city_id, slug) from URL.
    """
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    import urllib.request as ur

    log.info(f"Bolt: discovering city URL for '{city}' ...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # Mock suggestDeliveryLocations to return city coords instead of Prague IP
        async def mock_route(route):
            url = route.request.url
            if "suggestDeliveryLocations" in url:
                url = url.replace(f"lat={IP_LAT}", f"lat={city_lat}") \
                         .replace(f"lng={IP_LNG}", f"lng={city_lng}") \
                         .replace("lat=50.0805",   f"lat={city_lat}") \
                         .replace("lng=14.467",    f"lng={city_lng}")
                try:
                    req = ur.Request(url, headers={
                        k: v for k, v in dict(route.request.headers).items()
                        if k.lower() not in ('host', 'content-length')
                    })
                    with ur.urlopen(req, timeout=10) as resp:
                        await route.fulfill(status=200, body=resp.read(), content_type="application/json")
                        return
                except Exception as e:
                    log.warning(f"Route mock error: {e}")
            await route.continue_()

        await page.route("**/*", mock_route)
        await page.goto("https://food.bolt.eu", timeout=30_000, wait_until="domcontentloaded")
        await _rand(2, 3)

        for text in ["Allow all", "Accept all"]:
            try:
                if await page.locator(f"button:has-text('{text}')").first.is_visible(timeout=3_000):
                    await page.locator(f"button:has-text('{text}')").first.click()
                    await _rand(0.8, 1.5)
                    break
            except Exception:
                pass

        try:
            await page.locator("[data-testid='screens.DestinationLanding.searchInput.container']").first.click(timeout=5_000)
        except Exception:
            pass

        await _rand(0.5, 1.0)
        await page.locator("input[placeholder*='address' i]").first.type(city, delay=random.randint(60, 100))
        await _rand(3, 5)

        try:
            await page.wait_for_selector(SUGG_SEL, timeout=12_000)
        except PWTimeout:
            log.error(f"No suggestions for '{city}'")
            await browser.close()
            return None

        items = await page.locator(SUGG_SEL).all()
        target = None
        for item in items:
            try:
                if city.lower() in (await item.inner_text(timeout=1_000)).lower():
                    target = item
                    break
            except Exception:
                pass
        if not target and items:
            target = items[0]

        if not target:
            await browser.close()
            return None

        await target.click()
        await _rand(2, 4)
        url = page.url
        await browser.close()

    m = re.search(r"/en/(\d+)-([^/?#]+)", url)
    if m:
        return int(m.group(1)), m.group(2)
    return None


# ── Main scraper ───────────────────────────────────────────────────────────

async def _scrape_async(city_url: str, city: str, job: dict, max_restaurants: int) -> list:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    providers_seen: dict[int, dict] = {}  # id → provider record

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = await ctx.new_page()

        # Intercept getScreenContent responses to harvest provider data
        async def on_response(resp):
            if "getScreenContent" in resp.url:
                try:
                    body = await resp.json()
                    data = body.get("data", {})
                    raw = data.get("providers", {}).get("data", {})
                    providers = raw if isinstance(raw, dict) else {}
                    for pid_str, prov in providers.items():
                        pid = prov.get("id", pid_str)
                        if pid not in providers_seen:
                            providers_seen[pid] = prov
                except Exception:
                    pass

        page.on("response", on_response)

        await page.goto(city_url, timeout=30_000, wait_until="domcontentloaded")
        await _rand(2, 3)

        for text in ["Allow all", "Accept all", "Reject all"]:
            try:
                if await page.locator(f"button:has-text('{text}')").first.is_visible(timeout=3_000):
                    await page.locator(f"button:has-text('{text}')").first.click()
                    await _rand(0.8, 1.5)
                    break
            except Exception:
                pass

        # Wait for first content
        try:
            await page.wait_for_selector(
                "[data-testid='components.ProviderCard.horizontalView']",
                timeout=20_000,
            )
        except PWTimeout:
            log.warning("ProviderCard not found — waiting for any content")
            await _rand(3, 5)

        # Scroll to trigger lazy loading of more carousels
        stalls = 0
        prev_count = len(providers_seen)
        scroll_attempts = 0

        while len(providers_seen) < max_restaurants and scroll_attempts < 20:
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.85)")
            await _rand(1.5, 3.0)
            scroll_attempts += 1

            current_count = len(providers_seen)
            if current_count == prev_count:
                stalls += 1
                if stalls >= 6:
                    break
            else:
                stalls = 0
                prev_count = current_count

            job["scraped"] = current_count
            job["progress"] = min(10 + int(current_count / max(max_restaurants, 1) * 85), 95)
            job["message"] = f"Bolt: collected {current_count} restaurants so far..."
            log.info(f"Bolt scroll {scroll_attempts}: {current_count} providers ({stalls} stalls)")

        await browser.close()

    log.info(f"Bolt: total providers collected: {len(providers_seen)}")
    records = [_provider_to_record(p, city) for p in providers_seen.values()]
    return records[:max_restaurants]


# ── Public entry point ─────────────────────────────────────────────────────

def scrape_bolt(location: str, cuisine: str, job: dict) -> list:
    """
    Synchronous entry point called by app.py.
    Runs async Playwright code in a new event loop.
    """
    city_key = location.strip().lower().split(",")[0].strip()

    if city_key in KNOWN_CITIES:
        city_id, slug = KNOWN_CITIES[city_key]
        log.info(f"Bolt: known city '{city_key}' → city_id={city_id}")
    else:
        job["message"] = f"Bolt: finding city URL for '{location}'..."
        from scrapers.wolt import geocode_location
        lat, lon, *_ = geocode_location(location)
        result = asyncio.run(_discover_city_async(location, lat, lon))
        if not result:
            raise ValueError(
                f"Bolt Food does not seem to serve '{location}'. "
                "Try a larger nearby city or add it to KNOWN_CITIES."
            )
        city_id, slug = result
        log.info(f"Bolt: discovered '{location}' → city_id={city_id}, slug={slug}")

    city_url = f"https://food.bolt.eu/en/{city_id}-{slug}/"
    city_display = location.split(",")[0].strip()

    job["message"] = f"Bolt: loading restaurant data for {city_display}..."
    job["progress"] = 5

    restaurants = asyncio.run(_scrape_async(city_url, city_display, job, max_restaurants=2000))

    job["scraped"] = len(restaurants)
    job["total"]   = len(restaurants)
    job["progress"] = 100
    job["message"]  = f"Bolt: done — {len(restaurants)} restaurants from {city_display}."
    return restaurants
