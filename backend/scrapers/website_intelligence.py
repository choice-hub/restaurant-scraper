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
    "ChoiceQR":    ["choiceqr.com"],
    "Dish":        ["dish.co", "getdish"],
    "Restaurantic": ["restaurantic"],
    "Squarespace": ["squarespace"],
    "Wix":         ["wixsite", "wix.com"],
    "WordPress":   ["wp-content", "wp-includes", "wp-json"],
    "Webflow":     ["webflow.io"],
    "Lightspeed":  ["lightspeedapp"],
    "Shopify":     ["shopify", "myshopify"],
}

RESERVATION_SIGNS = {
    "OpenTable":   ["opentable.com"],
    "TheFork":     ["thefork.com", "lafourchette"],
    "Resy":        ["resy.com"],
    "Quandoo":     ["quandoo.com"],
    "SevenRooms":  ["sevenrooms.com"],
    "Tock":        ["exploretock.com"],
    "ResDiary":    ["resdiary.com"],
    "Bookio":      ["bookio.com"],
}

ORDERING_SIGNS = {
    "Wolt":        ["wolt.com"],
    "Uber Eats":   ["ubereats.com"],
    "Deliveroo":   ["deliveroo"],
    "Bolt Food":   ["bolt.eu"],
    "Just Eat":    ["just-eat"],
    "Glovo":       ["glovoapp"],
    "ChoiceQR":    ["choiceqr.com"],
}

LEGAL_SUBPAGES = [
    "/about", "/about-us", "/contact", "/contact-us",
    "/legal", "/impressum", "/gdpr", "/terms", "/privacy",
    "/datenschutz", "/o-nas", "/kontakt",
]


def _compact_html(soup: BeautifulSoup, url: str) -> str:
    """Build a compact text representation of the page for Claude analysis."""
    parts = []

    # All anchor links
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)[:80]
        if href:
            links.append(f"{text}: {href}")
    if links:
        parts.append("LINKS:\n" + "\n".join(links[:200]))

    # Script sources (platform fingerprinting)
    script_srcs = [s.get("src", "") for s in soup.find_all("script") if s.get("src")]
    link_hrefs  = [l.get("href", "") for l in soup.find_all("link") if l.get("href")]
    all_assets  = script_srcs + link_hrefs
    if all_assets:
        parts.append("ASSET URLS:\n" + "\n".join(all_assets[:50]))

    # Footer (most important for platform + legal clues)
    footer = (
        soup.find("footer")
        or soup.find(id=re.compile(r"footer", re.I))
        or soup.find(class_=re.compile(r"footer", re.I))
    )
    if footer:
        parts.append("FOOTER:\n" + footer.get_text(" ", strip=True)[:1200])

    # Iframes (reservation / ordering embeds)
    iframes = [f.get("src", "") for f in soup.find_all("iframe") if f.get("src")]
    if iframes:
        parts.append("IFRAMES:\n" + "\n".join(iframes[:20]))

    # Page text
    page_text = soup.get_text(" ", strip=True)
    parts.append("PAGE TEXT:\n" + page_text[:2500])

    return "\n\n".join(parts)[:9000]


def _analyze_with_claude(name: str, url: str, compact_html: str) -> dict:
    """Use Claude Haiku to extract structured data from the website HTML."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {}

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        return {}

    prompt = f"""Analyze this restaurant website data and return ONLY a valid JSON object with these exact fields:

{{
  "instagram_url": "full URL starting with https://instagram.com/... or null",
  "facebook_url": "full URL starting with https://facebook.com/... or null",
  "emails": ["array of email addresses found, e.g. info@restaurant.com"],
  "website_platform": "one of: ChoiceQR, Dish, Restaurantic, WordPress, Wix, Squarespace, Webflow, Shopify, Lightspeed, custom, unknown",
  "reservation_possible": true or false,
  "reservation_provider": "provider name or null if none/phone-only",
  "ordering_possible": true or false,
  "ordering_provider": "provider name or null"
}}

Detection hints:
- Instagram: look for instagram.com/ in links
- Facebook: look for facebook.com/ in links
- Emails: look for mailto: links and email@domain.com patterns
- Platform: check FOOTER text for "Powered by X", "Created by X"; check ASSET URLS for choiceqr.com, wp-content, wixsite, squarespace, webflow.io, shopify, dish.co, lightspeedapp
- Reservation: check LINKS and IFRAMES for opentable.com, thefork.com, resy.com, quandoo.com, sevenrooms.com, exploretock.com, resdiary.com, bookio.com; also text clues like "Reserve a table", "Book a table"
- Ordering: check LINKS and IFRAMES for wolt.com, ubereats.com, deliveroo, bolt.eu, just-eat, glovoapp, choiceqr.com; text like "Order online", "Order now"
- If reservation/ordering button just says "call us" or shows only a phone number, set possible=false

Restaurant: {name}
URL: {url}

{compact_html}

Return JSON only, no explanation:"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        logger.warning("Claude analysis failed for %s: %s", url, e)
        return {}


def _format_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


def _get_instagram_followers(ig_url: str, client: httpx.Client) -> str:
    """Attempt to get Instagram follower count from a public profile."""
    try:
        # Extract username from URL
        username = ig_url.rstrip("/").rstrip("?").split("/")[-1].split("?")[0]
        if not username or username.lower() in ("instagram", "p", "reel", "explore", "stories"):
            return "Unknown"

        # Try instaloader (best approach, pure Python)
        try:
            import instaloader
            L = instaloader.Instaloader(quiet=True, download_pictures=False,
                                        download_videos=False, download_video_thumbnails=False,
                                        download_geotags=False, download_comments=False,
                                        save_metadata=False)
            profile = instaloader.Profile.from_username(L.context, username)
            return _format_count(profile.followers)
        except Exception:
            pass

        # Fallback: fetch profile page, look for count in embedded JSON
        res = client.get(
            f"https://www.instagram.com/{username}/",
            headers=HEADERS,
            timeout=10,
            follow_redirects=True,
        )
        for pattern in [
            r'"edge_followed_by":\{"count":(\d+)\}',
            r'"follower_count":(\d+)',
        ]:
            m = re.search(pattern, res.text)
            if m:
                return _format_count(int(m.group(1)))

        return "Login Required"
    except Exception as e:
        return f"Error: {str(e)[:60]}"


def _get_facebook_followers(fb_url: str, client: httpx.Client) -> str:
    """Attempt to get Facebook page follower count."""
    try:
        res = client.get(fb_url, headers=HEADERS, timeout=10, follow_redirects=True)
        for pattern in [
            r'"follower_count":(\d+)',
            r'"followers_count":(\d+)',
            r'([\d,]+)\s+(?:people\s+)?(?:follow|followers)',
        ]:
            m = re.search(pattern, res.text, re.IGNORECASE)
            if m:
                raw = m.group(1).replace(",", "")
                try:
                    return _format_count(int(raw))
                except ValueError:
                    return raw
        return "Not found"
    except Exception as e:
        return f"Error: {str(e)[:60]}"


def _get_legal_data(base_url: str, client: httpx.Client) -> dict:
    """Fetch sub-pages and use Claude to extract company registration info."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"legal_name": "", "company_id": "", "ico": ""}

    combined_text = ""
    tried = 0
    legal_keywords = {"ičo", "ico", "company", "registered", "reg no", "ltd",
                      "s.r.o", "gmbh", "legal", "org.nr", "impressum", "kvk"}

    for path in LEGAL_SUBPAGES:
        if tried >= 3:
            break
        try:
            url = urljoin(base_url, path)
            res = client.get(url, headers=HEADERS, timeout=8, follow_redirects=True)
            if res.status_code != 200:
                continue
            soup = BeautifulSoup(res.text, "html.parser")
            text = soup.get_text(" ", strip=True)
            text_lower = text.lower()
            if any(kw in text_lower for kw in legal_keywords):
                combined_text += f"\n\n--- {path} ---\n{text[:2500]}"
                tried += 1
        except Exception:
            continue

    if not combined_text:
        return {"legal_name": "", "company_id": "", "ico": ""}

    try:
        import anthropic
        claude = anthropic.Anthropic(api_key=api_key)
        prompt = f"""Extract legal/company registration info from this restaurant website text.
Return ONLY a JSON object with these fields:
{{
  "legal_name": "official registered company name or empty string",
  "company_id": "company registration number or empty string",
  "ico": "IČO number (Czech/Slovak) or empty string"
}}

Text:
{combined_text[:5000]}

JSON only:"""
        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```[a-z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        return json.loads(text)
    except Exception as e:
        logger.warning("Legal extraction failed for %s: %s", base_url, e)
        return {"legal_name": "", "company_id": "", "ico": ""}


def analyze_restaurant(name: str, url: str, orig_data: dict = None) -> dict:
    """Analyze a single restaurant website and return a flat result dict."""
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
            compact = _compact_html(soup, url)

            # 2 — Claude analysis (homepage)
            try:
                cd = _analyze_with_claude(name, url, compact)
                if cd:
                    result["instagram_url"]     = cd.get("instagram_url") or ""
                    result["facebook_url"]       = cd.get("facebook_url") or ""
                    emails = cd.get("emails", [])
                    result["emails"]             = ", ".join(emails) if isinstance(emails, list) else str(emails or "")
                    result["website_platform"]   = cd.get("website_platform") or ""
                    result["reservation_possible"] = "Yes" if cd.get("reservation_possible") else "No"
                    result["reservation_provider"] = cd.get("reservation_provider") or ""
                    result["ordering_possible"]   = "Yes" if cd.get("ordering_possible") else "No"
                    result["ordering_provider"]   = cd.get("ordering_provider") or ""
            except Exception as e:
                result["notes"] = f"AI analysis error: {str(e)[:80]}"

            # 3 — Instagram follower count
            if result["instagram_url"]:
                result["instagram_followers"] = _get_instagram_followers(result["instagram_url"], client)

            # 4 — Facebook follower count
            if result["facebook_url"]:
                result["facebook_followers"] = _get_facebook_followers(result["facebook_url"], client)

            # 5 — Legal data from sub-pages
            try:
                legal = _get_legal_data(url, client)
                result["legal_name"]  = legal.get("legal_name", "")
                result["company_id"]  = legal.get("company_id", "")
                result["ico"]         = legal.get("ico", "")
            except Exception:
                pass

    except Exception as e:
        result["notes"] = f"Unexpected error: {str(e)[:150]}"

    return result


def scrape_website_intel(restaurants: list, job: dict) -> list:
    """Process a list of restaurants concurrently.

    restaurants: [{"name": "...", "url": "..."}, ...]
    job: shared dict with progress/message/scraped keys
    """
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

    # Filter out any None gaps (shouldn't happen, but be safe)
    return [r for r in results if r is not None]
