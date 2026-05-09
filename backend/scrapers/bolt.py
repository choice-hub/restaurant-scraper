"""
Bolt Food scraper using Playwright browser automation.
Navigates directly to known city URLs (food.bolt.eu/en/{city_id}-{slug}/)
and extracts restaurant data from aria-label attributes on card buttons.
"""
import asyncio
import csv
import logging
import random
import re
from datetime import datetime
from pathlib import Path

# KNOWN_CITIES: lowercase city name → (city_id, url_slug)
# Discover new cities with: discover_bolt_city_id(city, lat, lng)
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

# Prague IP coords — what Bolt's server returns for Czech IPs
IP_LAT, IP_LNG = 50.0805, 14.467

CARD_SEL   = "[data-testid='components.ProviderCard.horizontalView']"
RATING_SEL = "[data-testid='components.ProviderCard.providerRatingBadge']"
SUGG_SEL   = "[data-testid='screens.DestinationLanding.searchSuggestion']"

_RE_PRICE  = re.compile(r"Delivery price\s+(.+?)(?:,\s*Delivery time|$)", re.I)
_RE_TIME   = re.compile(r"Delivery time\s+(.+?)(?:,\s*Rating|$)", re.I)
_RE_RATING = re.compile(r"Rating\s+([\d.,]+)", re.I)
_RE_REVIEW = re.compile(r"\(([\d+,]+\+?)\)")

log = logging.getLogger(__name__)


def _parse_aria(label: str) -> dict:
    """Extract name, delivery_fee, delivery_time, rating from aria-label string."""
    m_name   = re.match(r"^(.+?)(?:,\s*Delivery price|$)", label, re.I)
    m_price  = _RE_PRICE.search(label)
    m_time   = _RE_TIME.search(label)
    m_rating = _RE_RATING.search(label)
    return {
        "name":          m_name.group(1).strip() if m_name else label.strip(),
        "delivery_fee":  m_price.group(1).strip() if m_price else "",
        "delivery_time": m_time.group(1).strip()  if m_time  else "",
        "rating":        m_rating.group(1).strip() if m_rating else "",
    }


async def _rand(lo=1.5, hi=3.5):
    await asyncio.sleep(random.uniform(lo, hi))


async def _discover_city(city: str, city_lat: float, city_lng: float) -> tuple:
    """Navigate food.bolt.eu with mocked coords to find a city's URL slug/ID."""
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    import urllib.request as ur

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

        async def mock_suggest(route):
            url = route.request.url
            if "suggestDeliveryLocations" in url:
                url = (url
                    .replace(f"lat={IP_LAT}", f"lat={city_lat}")
                    .replace(f"lng={IP_LNG}", f"lng={city_lng}")
                    .replace("lat=50.0805", f"lat={city_lat}")
                    .replace("lng=14.467", f"lng={city_lng}")
                )
                try:
                    req = ur.Request(url, headers={
                        k: v for k, v in dict(route.request.headers).items()
                        if k.lower() not in ('host', 'content-length')
                    })
                    with ur.urlopen(req, timeout=10) as resp:
                        await route.fulfill(status=200, body=resp.read(), content_type="application/json")
                        return
                except Exception:
                    pass
            await route.continue_()

        await page.route("**/*", mock_suggest)
        await page.goto("https://food.bolt.eu", timeout=30_000, wait_until="domcontentloaded")
        await _rand(2, 3)

        for text in ["Allow all", "Accept all"]:
            try:
                btn = page.locator(f"button:has-text('{text}')").first
                if await btn.is_visible(timeout=3_000):
                    await btn.click(); await _rand(0.8, 1.5); break
            except Exception:
                pass

        try:
            container = page.locator("[data-testid='screens.DestinationLanding.searchInput.container']").first
            await container.click(timeout=5_000)
        except Exception:
            pass

        await _rand(0.5, 1.0)
        inp = page.locator("input[placeholder*='address' i]").first
        await inp.type(city, delay=random.randint(60, 100))
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
                t = (await item.inner_text(timeout=1_000)).strip()
                if city.lower() in t.lower():
                    target = item; break
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


async def _scrape_async(city_url: str, city: str, job: dict, max_restaurants: int = 5000) -> list:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    results = []
    seen = set()
    timestamp = datetime.now().isoformat()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
        )
        page = await ctx.new_page()

        await page.goto(city_url, timeout=30_000, wait_until="domcontentloaded")
        await _rand(2, 3)

        for text in ["Allow all", "Accept all", "Reject all"]:
            try:
                btn = page.locator(f"button:has-text('{text}')").first
                if await btn.is_visible(timeout=3_000):
                    await btn.click(); await _rand(0.8, 1.5); break
            except Exception:
                pass

        try:
            await page.wait_for_selector(CARD_SEL, timeout=25_000)
        except PWTimeout:
            log.error(f"No cards at {city_url}")
            await browser.close()
            return results

        stalls = 0
        prev_count = 0

        while len(results) < max_restaurants:
            cards = page.locator(CARD_SEL)
            total = await cards.count()

            if total == prev_count:
                stalls += 1
                if stalls >= 8:
                    break
                await page.evaluate("window.scrollBy(0, window.innerHeight * 0.7)")
                await _rand(1.5, 3.0)
                continue

            stalls = 0

            for i in range(prev_count, total):
                if len(results) >= max_restaurants:
                    break
                try:
                    card = cards.nth(i)
                    btn = card.locator("button[href]").first
                    aria = await btn.get_attribute("aria-label", timeout=2_000) or ""
                    href = await btn.get_attribute("href", timeout=2_000) or ""

                    if not aria:
                        continue

                    parsed = _parse_aria(aria)
                    platform_url = f"https://food.bolt.eu{href}" if href.startswith("/") else href

                    key = platform_url or parsed["name"]
                    if not key or key in seen:
                        continue
                    seen.add(key)

                    review_count = ""
                    try:
                        badge = (await card.locator(RATING_SEL).first.inner_text(timeout=1_500)).strip()
                        m = _RE_REVIEW.search(badge)
                        if m:
                            review_count = m.group(1)
                    except Exception:
                        pass

                    results.append({
                        "name":          parsed["name"],
                        "brand_name":    "",
                        "phone":         "",
                        "website":       "",
                        "address":       "",
                        "city":          city,
                        "country":       "",
                        "cuisine":       "",
                        "rating":        parsed["rating"],
                        "review_count":  review_count,
                        "delivery_fee":  parsed["delivery_fee"],
                        "delivery_time": parsed["delivery_time"],
                        "merchant_name": "",
                        "business_id":   "",
                        "legal_street":  "",
                        "legal_city":    "",
                        "legal_post_code": "",
                        "legal_country": "",
                        "platform_url":  platform_url,
                    })

                    n = len(results)
                    job["scraped"] = n
                    job["progress"] = min(10 + int(n / max(max_restaurants, 1) * 85), 95)
                    job["message"] = f"Bolt: scraped {n} restaurants from {city}..."

                except Exception as e:
                    log.debug(f"Bolt card {i} error: {e}")

            prev_count = total
            await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
            await _rand(1.5, 3.0)

        await browser.close()

    return results


def scrape_bolt(location: str, cuisine: str, job: dict) -> list:
    """Synchronous entry point. Runs Playwright in a new event loop."""
    city_key = location.strip().lower().split(",")[0].strip()

    if city_key in KNOWN_CITIES:
        city_id, slug = KNOWN_CITIES[city_key]
        log.info(f"Bolt: known city {city_key} → city_id={city_id}")
    else:
        job["message"] = f"Bolt: discovering city URL for '{location}'..."
        from scrapers.wolt import geocode_location
        lat, lon, *_ = geocode_location(location)
        result = asyncio.run(_discover_city(location, lat, lon))
        if not result:
            raise ValueError(f"Bolt Food does not seem to serve '{location}'. Try a larger nearby city.")
        city_id, slug = result
        log.info(f"Bolt: discovered {location} → city_id={city_id}, slug={slug}")

    city_url = f"https://food.bolt.eu/en/{city_id}-{slug}/"
    city_display = location.split(",")[0].strip()

    job["message"] = f"Bolt: loading restaurant list for {city_display}..."
    job["progress"] = 5

    restaurants = asyncio.run(_scrape_async(city_url, city_display, job))

    job["scraped"] = len(restaurants)
    job["total"] = len(restaurants)
    job["progress"] = 100
    job["message"] = f"Bolt: done — {len(restaurants)} restaurants from {city_display}."
    return restaurants
