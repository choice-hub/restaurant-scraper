import re
import json
import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

PLATFORM_SIGNS = {
    "ChoiceQR":     ["choiceqr.com"],
    "Dish":         ["dish.co", "getdish"],
    "Restaurantic": ["restaurantic"],
    "Squarespace":  ["squarespace"],
    "Wix":          ["wixsite", "wix.com"],
    "WordPress":    ["wp-content", "wp-includes", "wp-json"],
    "Webflow":      ["webflow.io"],
    "Lightspeed":   ["lightspeedapp"],
    "Shopify":      ["shopify", "myshopify"],
    "Strikingly":   ["strikingly.com"],
    "GoDaddy":      ["godaddy", "secureserver.net"],
}

# iframe / script src patterns that confirm an EMBEDDED reservation widget
RESERVATION_PROVIDERS = {
    "OpenTable":  ["opentable.com"],
    "TheFork":    ["thefork.com", "lafourchette.com"],
    "Resy":       ["resy.com"],
    "Quandoo":    ["quandoo.com"],
    "SevenRooms": ["sevenrooms.com"],
    "Tock":       ["exploretock.com"],
    "ResDiary":   ["resdiary.com"],
    "Bookio":     ["bookio.com"],
    "Restaumatic":["restaumatic.com"],
    "TableAgent": ["tableagent.com"],
    "Yelp":       ["yelp.com/reservations"],
    "Tablein":    ["tablein.com"],
}

# href / iframe / script patterns that confirm an EMBEDDED ordering widget on the site
# External links to delivery apps (wolt.com/restaurant/xyz) do NOT count
ORDERING_PROVIDERS = {
    "ChoiceQR":  ["choiceqr.com/order", "choiceqr.com/menu"],
    "Dish":      ["dish.co/order"],
    "Flipdish":  ["flipdish.com", "flipdish.co"],
    "Ordify":    ["ordify.com"],
    "Bopple":    ["bopple.com"],
    "Yumbi":     ["yumbi.com"],
    "Doshii":    ["doshii.io"],
    "HungryHungry": ["hungryhungry.com"],
    "Lightspeed": ["lightspeedapp.com/order"],
    "Square":    ["squareup.com/order", "squareonlinestore.com"],
    "Wix Order": ["wixrestaurants.com"],
}

# Keywords in link text/href suggesting a reservation link to follow
RESERVATION_LINK_KEYWORDS = [
    "rezerv", "reserv", "book", "stol", "tisch", "table",
    "prenota", "réserv", "boek", "réserver", "boeking",
]

# Keywords in link text/href suggesting external delivery (NOT embedded ordering)
DELIVERY_EXTERNAL_KEYWORDS = [
    "wolt.com", "bolt.eu", "ubereats.com", "deliveroo",
    "just-eat", "glovoapp", "foodora", "lieferando",
]


# ── Deterministic detectors ────────────────────────────────────────────────────

def _detect_platform(soup: BeautifulSoup, page_html: str) -> str:
    html_lower = page_html.lower()
    # Check asset URLs (scripts/links) and inline text
    for platform, signs in PLATFORM_SIGNS.items():
        if any(s in html_lower for s in signs):
            return platform
    return "custom"


def _scan_for_provider(sources: list[str], provider_dict: dict) -> str:
    """Return the first provider name whose signature appears in any of the sources."""
    combined = " ".join(s.lower() for s in sources if s)
    for provider, signs in provider_dict.items():
        if any(s in combined for s in signs):
            return provider
    return ""


def _get_all_srcs(soup: BeautifulSoup) -> list[str]:
    """Collect all iframe srcs + script srcs from a parsed page."""
    srcs = []
    for tag in soup.find_all(["iframe", "script", "a"], src=True):
        srcs.append(tag.get("src", ""))
    for a in soup.find_all("a", href=True):
        srcs.append(a["href"])
    return srcs


def _find_reservation(homepage_soup: BeautifulSoup, base_url: str, client: httpx.Client) -> tuple[bool, str]:
    """
    Returns (has_reservation, provider_name).
    Follows internal reservation links one level deep to find booking iframes.
    """
    # 1 — Check iframes/scripts on homepage directly
    provider = _scan_for_provider(_get_all_srcs(homepage_soup), RESERVATION_PROVIDERS)
    if provider:
        return True, provider

    # 2 — Find reservation-related links and follow them
    visited = set()
    for a in homepage_soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).lower()
        href_lower = href.lower()

        if not any(kw in text + href_lower for kw in RESERVATION_LINK_KEYWORDS):
            continue

        # External link → check directly
        if href_lower.startswith("http"):
            provider = _scan_for_provider([href], RESERVATION_PROVIDERS)
            if provider:
                return True, provider
            continue

        # Internal link → fetch and scan
        sub_url = urljoin(base_url, href)
        if sub_url in visited:
            continue
        visited.add(sub_url)

        try:
            res = client.get(sub_url, headers=HEADERS, timeout=10, follow_redirects=True)
            if res.status_code != 200:
                continue
            sub_soup = BeautifulSoup(res.text, "html.parser")
            srcs = _get_all_srcs(sub_soup)
            provider = _scan_for_provider(srcs, RESERVATION_PROVIDERS)
            if provider:
                return True, provider
            # Even if no known provider, if there's a booking iframe → custom
            for s in srcs:
                if "iframe" in s or "booking" in s.lower() or "widget" in s.lower():
                    return True, "custom"
        except Exception:
            pass

    # 3 — Did we find a reservation link at all (even without a known provider)?
    for a in homepage_soup.find_all("a", href=True):
        text = a.get_text(strip=True).lower()
        href = a["href"].lower()
        if any(kw in text + href for kw in RESERVATION_LINK_KEYWORDS):
            return True, ""   # has reservation but unknown provider

    return False, ""


def _find_ordering(homepage_soup: BeautifulSoup) -> tuple[bool, str]:
    """
    Returns (has_ordering, provider_name).
    Only returns True for EMBEDDED ordering widgets — not links to external delivery apps.
    """
    # Check iframes and scripts for known embedded ordering providers
    srcs = []
    for tag in homepage_soup.find_all(["iframe", "script"], src=True):
        srcs.append(tag.get("src", ""))
    provider = _scan_for_provider(srcs, ORDERING_PROVIDERS)
    if provider:
        return True, provider

    # Check page HTML for ordering widget signatures
    html = homepage_soup.decode_contents().lower()
    provider = _scan_for_provider([html], ORDERING_PROVIDERS)
    if provider:
        return True, provider

    return False, ""


def _extract_legal_regex(text: str) -> dict:
    """Fast regex pass for common legal registration patterns."""
    result = {"legal_name": "", "company_id": "", "ico": ""}

    # Czech / Slovak IČO (always 8 digits)
    m = re.search(r"IČ[OO]?:?\s*(\d{8})", text, re.IGNORECASE)
    if m:
        result["ico"] = m.group(1)

    # German HRB / HRA
    m = re.search(r"(HRB|HRA)\s*(\d+)", text)
    if m:
        result["company_id"] = m.group(0)

    # Generic "Company No." / "Reg No."
    if not result["company_id"]:
        m = re.search(
            r"(?:Company|Registration|Reg)\.?\s*No\.?:?\s*([\w\d\s/-]{3,20})",
            text, re.IGNORECASE
        )
        if m:
            result["company_id"] = m.group(1).strip()

    # Legal entity name (s.r.o., a.s., GmbH, Ltd., etc.)
    m = re.search(
        r"([^\n,;|·–—]{2,60}?\b(?:s\.r\.o\.|a\.s\.|spol\.\s*s\s*r\.o\.|s\.p\.|"
        r"GmbH|Ltd\.|LLC|Inc\.|S\.A\.|S\.L\.|B\.V\.|N\.V\.))",
        text,
    )
    if m:
        result["legal_name"] = m.group(1).strip()

    return result


# ── Claude (only for social + email) ──────────────────────────────────────────

def _analyze_social_email(name: str, url: str, soup: BeautifulSoup) -> dict:
    """Use Claude Haiku to extract Instagram URL, Facebook URL, and email addresses."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}

    # Build a compact link + text snippet for Claude
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)[:60]
        if href:
            links.append(f"{text}: {href}")

    footer = (
        soup.find("footer")
        or soup.find(id=re.compile(r"footer", re.I))
        or soup.find(class_=re.compile(r"footer", re.I))
    )
    footer_text = footer.get_text(" ", strip=True)[:800] if footer else ""
    page_text = soup.get_text(" ", strip=True)

    context = (
        f"LINKS:\n" + "\n".join(links[:150]) +
        f"\n\nFOOTER:\n{footer_text}" +
        f"\n\nPAGE TEXT (excerpt):\n{page_text[:1500]}"
    )[:7000]

    prompt = f"""Find the Instagram profile URL, Facebook page URL, and contact email addresses for this restaurant.
Return ONLY a JSON object:

{{
  "instagram_url": "full URL or null",
  "facebook_url": "full URL or null",
  "emails": ["list of contact email addresses, e.g. info@place.com"]
}}

Rules:
- instagram_url must start with https://instagram.com/ or https://www.instagram.com/
- facebook_url must start with https://facebook.com/ or https://www.facebook.com/
- Only include business contact emails, not personal or staff emails
- Return null / empty array if not found

Restaurant: {name}
URL: {url}

{context}

JSON only:"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        logger.warning("Claude social/email failed for %s: %s", url, e)
        return {}


# ── Follower counts ────────────────────────────────────────────────────────────

def _format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


def _get_instagram_followers(ig_url: str, client: httpx.Client) -> str:
    try:
        username = ig_url.rstrip("/").split("/")[-1].split("?")[0]
        if not username or username.lower() in ("instagram", "p", "reel", "explore", "stories"):
            return "Unknown"

        try:
            import instaloader
            L = instaloader.Instaloader(
                quiet=True, download_pictures=False, download_videos=False,
                download_video_thumbnails=False, download_geotags=False,
                download_comments=False, save_metadata=False,
            )
            profile = instaloader.Profile.from_username(L.context, username)
            return _format_count(profile.followers)
        except Exception:
            pass

        res = client.get(
            f"https://www.instagram.com/{username}/",
            headers=HEADERS, timeout=10, follow_redirects=True,
        )
        for pat in [r'"edge_followed_by":\{"count":(\d+)\}', r'"follower_count":(\d+)']:
            m = re.search(pat, res.text)
            if m:
                return _format_count(int(m.group(1)))

        return "Login Required"
    except Exception as e:
        return f"Error: {str(e)[:60]}"


def _get_facebook_followers(fb_url: str, client: httpx.Client) -> str:
    try:
        res = client.get(fb_url, headers=HEADERS, timeout=10, follow_redirects=True)
        for pat in [r'"follower_count":(\d+)', r'"followers_count":(\d+)',
                    r'([\d,]+)\s+(?:people\s+)?(?:follow|followers)']:
            m = re.search(pat, res.text, re.IGNORECASE)
            if m:
                raw = m.group(1).replace(",", "")
                try:
                    return _format_count(int(raw))
                except ValueError:
                    return raw
        return "Not found"
    except Exception as e:
        return f"Error: {str(e)[:60]}"


# ── Main per-restaurant function ───────────────────────────────────────────────

def analyze_restaurant(name: str, url: str, orig_data: dict = None) -> dict:
    result = {
        "_orig": orig_data or {},
        "name": name,
        "url": url,
        "instagram_url": "",
        "instagram_followers": "",
        "facebook_url": "",
        "facebook_followers": "",
        "emails": "",
        "legal_name": "",
        "company_id": "",
        "ico": "",
        "website_platform": "",
        "reservation_possible": "",
        "reservation_provider": "",
        "ordering_possible": "",
        "ordering_provider": "",
        "notes": "",
    }

    if not url or not url.startswith(("http://", "https://")):
        result["notes"] = "Invalid or missing URL"
        return result

    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:

            # 1 — Fetch homepage
            try:
                res = client.get(url, headers=HEADERS)
                res.raise_for_status()
            except Exception as e:
                result["notes"] = f"Failed to fetch: {str(e)[:100]}"
                return result

            soup = BeautifulSoup(res.text, "html.parser")
            page_html = res.text
            page_text = soup.get_text(" ", strip=True)

            # 2 — Platform detection (deterministic)
            result["website_platform"] = _detect_platform(soup, page_html)

            # 3 — Reservation (follow links, scan iframes)
            has_res, res_provider = _find_reservation(soup, url, client)
            result["reservation_possible"]  = "Yes" if has_res else "No"
            result["reservation_provider"]  = res_provider

            # 4 — Ordering (embedded widget only — external delivery links don't count)
            has_ord, ord_provider = _find_ordering(soup)
            result["ordering_possible"]  = "Yes" if has_ord else "No"
            result["ordering_provider"]  = ord_provider

            # 5 — Legal: regex first, then Claude on sub-pages if nothing found
            legal = _extract_legal_regex(page_text)
            if not any(legal.values()):
                # Try footer specifically
                footer = soup.find("footer") or soup.find(class_=re.compile(r"footer", re.I))
                if footer:
                    legal = _extract_legal_regex(footer.get_text(" ", strip=True))
            if not any(legal.values()):
                legal = _extract_legal_from_subpages(url, client)
            result["legal_name"]  = legal.get("legal_name", "")
            result["company_id"]  = legal.get("company_id", "")
            result["ico"]         = legal.get("ico", "")

            # 6 — Social + email via Claude
            try:
                cd = _analyze_social_email(name, url, soup)
                if cd:
                    result["instagram_url"] = cd.get("instagram_url") or ""
                    result["facebook_url"]  = cd.get("facebook_url") or ""
                    emails = cd.get("emails", [])
                    result["emails"] = ", ".join(emails) if isinstance(emails, list) else str(emails or "")
            except Exception as e:
                result["notes"] = f"AI error: {str(e)[:80]}"

            # 7 — Follower counts
            if result["instagram_url"]:
                result["instagram_followers"] = _get_instagram_followers(result["instagram_url"], client)
            if result["facebook_url"]:
                result["facebook_followers"] = _get_facebook_followers(result["facebook_url"], client)

    except Exception as e:
        result["notes"] = f"Unexpected error: {str(e)[:150]}"

    return result


def _extract_legal_from_subpages(base_url: str, client: httpx.Client) -> dict:
    """Fetch legal sub-pages and run regex on their text."""
    SUBPAGES = ["/about", "/about-us", "/contact", "/contact-us",
                "/legal", "/impressum", "/gdpr", "/terms", "/privacy",
                "/datenschutz", "/o-nas", "/kontakt"]
    KEYWORDS = {"ičo", "ico", "company", "registered", "reg no", "ltd",
                "s.r.o", "gmbh", "impressum", "org.nr", "kvk"}

    for path in SUBPAGES[:5]:
        try:
            res = client.get(urljoin(base_url, path), headers=HEADERS, timeout=8, follow_redirects=True)
            if res.status_code != 200:
                continue
            text = BeautifulSoup(res.text, "html.parser").get_text(" ", strip=True)
            if any(kw in text.lower() for kw in KEYWORDS):
                legal = _extract_legal_regex(text)
                if any(legal.values()):
                    return legal
        except Exception:
            continue

    return {"legal_name": "", "company_id": "", "ico": ""}


# ── Batch orchestrator ─────────────────────────────────────────────────────────

def scrape_website_intel(restaurants: list, job: dict) -> list:
    total = len(restaurants)
    job["total"] = total
    job["message"] = f"Starting analysis of {total} restaurants..."

    results = [None] * total
    completed = 0

    def process_one(idx_item):
        idx, item = idx_item
        return idx, analyze_restaurant(item.get("name", ""), item.get("url", ""), item.get("_orig"))

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(process_one, (i, r)): i for i, r in enumerate(restaurants)}
        for future in as_completed(futures):
            try:
                idx, result = future.result()
                results[idx] = result
            except Exception as e:
                i = futures[future]
                r = restaurants[i]
                results[i] = {
                    "name": r.get("name", ""),
                    "url": r.get("url", ""),
                    "notes": f"Processing error: {str(e)[:100]}",
                }
            completed += 1
            job["scraped"] = completed
            job["progress"] = int(completed / total * 95)
            job["message"] = f"Analyzed {completed}/{total} restaurants..."

    return [r for r in results if r is not None]
