#!/usr/bin/env python3
"""
Restaurant Scraper MCP Server
Gives Claude direct access to the restaurant scraper backend.

Usage (local stdio — for Claude Code):
    python3 mcp_server.py

Usage (remote HTTP — for hosting on Render for colleagues):
    python3 mcp_server.py --http
"""
import os
import sys
import time
import textwrap

import httpx
from mcp.server.fastmcp import FastMCP

# ── Config ─────────────────────────────────────────────────────────────────────
API_BASE      = "https://restaurant-scraper-api-ah9e.onrender.com"
POLL_INTERVAL = 5      # seconds between status checks
MAX_POLL_SECS = 300    # 5 minutes — then return "still running" with job ID

# ── Server ─────────────────────────────────────────────────────────────────────
mcp = FastMCP(
    "Restaurant Scraper",
    instructions=textwrap.dedent("""
        Tools for scraping restaurant data from delivery platforms, Google Maps,
        and individual restaurant websites. Results are returned directly in this
        conversation. Start with `describe_platforms` to understand what data
        each source provides.
    """).strip(),
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _poll(job_id: str) -> dict:
    """Poll until job is done, error, or MAX_POLL_SECS elapsed."""
    start = time.time()
    with httpx.Client(timeout=20) as client:
        while True:
            job = client.get(f"{API_BASE}/api/jobs/{job_id}").json()
            if job.get("status") in ("done", "error"):
                return job
            if time.time() - start > MAX_POLL_SECS:
                job["status"] = "timeout"
                return job
            time.sleep(POLL_INTERVAL)


def _md_table(rows: list[dict], columns: list[str], max_rows: int = 15) -> str:
    """Render a list of dicts as a Markdown table."""
    if not rows:
        return "_No results._"
    header    = " | ".join(columns)
    separator = " | ".join(["---"] * len(columns))
    lines     = [f"| {header} |", f"| {separator} |"]
    for r in rows[:max_rows]:
        cells = " | ".join(str(r.get(c, "") or "").replace("|", "∣")[:60] for c in columns)
        lines.append(f"| {cells} |")
    if len(rows) > max_rows:
        lines.append(f"\n_…and {len(rows) - max_rows} more rows (download for full data)_")
    return "\n".join(lines)


def _download_url(job_id: str) -> str:
    return f"{API_BASE}/api/jobs/{job_id}/download"


def _timeout_msg(job: dict) -> str:
    job_id = job["id"]
    return (
        f"⏳ **Job still running** — progress: {job.get('progress', 0)}%, "
        f"found {job.get('scraped', 0)} so far.\n\n"
        f"**Job ID:** `{job_id}`\n"
        f"**Download when done:** {_download_url(job_id)}\n\n"
        f"Call `check_job(job_id='{job_id}')` later to get the full results."
    )


# ── Tools ──────────────────────────────────────────────────────────────────────

@mcp.tool()
def describe_platforms() -> str:
    """
    Show all available scraping sources and exactly what data columns
    each one returns. Call this first to decide which tool to use.
    """
    return textwrap.dedent("""
    ## 🔵 Wolt
    **Columns:** Restaurant Name, Brand Name, Phone, Website, Address, City, Country,
    Cuisine, Rating, Merchant/Legal Company, Business ID, Legal Street, Legal City,
    Legal Post Code, Legal Country, Platform URL
    **Speed:** ~1,600 restaurants per city in under 5 seconds.
    **Markets:** CZ, AT, PL, HU, SK, DE, FI, NO, SE, DK, EE, LV, LT, IL, GR, RO,
    RS, HR, BG, CH, JP, GE, AZ, KZ

    ---

    ## 🟢 Bolt Food
    **Columns:** Restaurant Name, Cuisine, Rating, Review Count, Delivery Fee,
    Delivery Time, Address, City, Platform URL
    **Best for:** Delivery pricing and ETA data.

    ---

    ## 🔴 Foodora
    **Columns:** Restaurant Name, City, Country, Platform URL
    **Markets:** CZ, AT, HU, NO, SE

    ---

    ## 🗺️ Google Maps
    **Columns:** Name, Address, City, Country, Website, Phone, Rating, Review Count,
    Price Range, Delivery Companies (Wolt / Bolt / Uber Eats / Deliveroo / etc.),
    Reservation Systems (OpenTable / TheFork / Quandoo / etc.)
    **Filters available:** min reviews, min rating, require website, require phone
    **Speed:** ~1–60 min depending on city/country size.

    ---

    ## 🔍 Website Intelligence
    **Columns:** Instagram URL, Instagram Followers, Facebook URL, Facebook Followers,
    Email Addresses, Legal Name, Company ID / IČO, Website Platform
    (WordPress / Wix / ChoiceQR / Squarespace / etc.),
    Reservation System (Yes/No + Provider), Online Ordering (Yes/No + Provider)
    **Input required:** List of restaurant names + website URLs.
    **Speed:** ~10–20 seconds per restaurant.
    """).strip()


@mcp.tool()
def scrape_delivery(
    location: str,
    platforms: list[str],
    cuisine: str = "",
    email: str = "",
) -> str:
    """
    Scrape restaurant listings from delivery platforms and return results.

    Args:
        location: City or country, e.g. "Prague" or "Czech Republic"
        platforms: Which platforms to scrape. Options: ["wolt", "bolt", "foodora"]
                   Example: ["wolt", "bolt"]
        cuisine:  Optional cuisine filter, e.g. "pizza" or "sushi"
        email:    Optional — also email results as Excel when done

    Returns results directly in the conversation (top 15 rows + stats).
    For the full Excel file use the download link in the response.
    """
    valid = {"wolt", "bolt", "foodora"}
    bad   = [p for p in platforms if p not in valid]
    if bad:
        return f"❌ Unknown platform(s): {bad}. Valid options: {sorted(valid)}"

    payload = {
        "platforms": platforms,
        "location":  location,
        "cuisine":   cuisine,
        "email":     email or "noreply@example.com",  # backend requires email field
    }

    with httpx.Client(timeout=20) as client:
        r = client.post(f"{API_BASE}/api/scrape", json=payload)
        if not r.is_success:
            return f"❌ Could not start job: {r.text}"
        job_id = r.json()["job_id"]

    job = _poll(job_id)

    if job["status"] == "timeout":
        return _timeout_msg(job)
    if job["status"] == "error":
        return f"❌ Scraping failed: {job.get('message', 'Unknown error')}"

    total = job.get("scraped", 0)
    plats = ", ".join(p.capitalize() for p in platforms)

    # Build summary
    lines = [
        f"✅ **{total:,} restaurants** scraped from **{location}** via {plats}",
        "",
        f"📥 [Download full Excel]({_download_url(job_id)})",
    ]
    if email:
        lines.append(f"📧 Also sent to {email}")

    lines += ["", "### Preview (top 15 results)"]

    # Best columns to show for delivery platforms
    columns = ["name", "cuisine", "rating", "phone", "website", "city"]
    lines.append(_md_table([], columns))   # placeholder — we don't have row data here

    lines.append(
        "\n_Note: row data is in the Excel download. "
        "For inline row data, use `analyze_websites` with the website URLs from the Excel._"
    )

    return "\n".join(lines)


@mcp.tool()
def scrape_google_maps(
    location: str,
    min_reviews: int = 0,
    min_rating: float = 0.0,
    require_website: bool = False,
    require_phone: bool = False,
    email: str = "",
) -> str:
    """
    Scrape restaurant & cafe data from Google Maps for a city or country.

    Args:
        location:        City or country, e.g. "Prague" or "Czech Republic"
        min_reviews:     Minimum review count filter (0 = no filter)
        min_rating:      Minimum star rating filter (0.0 = no filter)
        require_website: Only return places that have a website listed
        require_phone:   Only return places that have a phone number listed
        email:           Optional — also email results as Excel when done

    This can take 1–60 min for large areas. Results are returned here for
    quick city scrapes; for country-level you'll get a job ID to check later.
    """
    payload = {
        "platforms": ["google_maps"],
        "location":  location,
        "cuisine":   "",
        "email":     email or "noreply@example.com",
        "gm_params": {
            "business_types":  ["restaurants"],
            "min_reviews":     min_reviews,
            "min_rating":      min_rating,
            "require_website": require_website,
            "require_phone":   require_phone,
        },
    }

    with httpx.Client(timeout=20) as client:
        r = client.post(f"{API_BASE}/api/scrape", json=payload)
        if not r.is_success:
            return f"❌ Could not start job: {r.text}"
        job_id = r.json()["job_id"]

    job = _poll(job_id)

    if job["status"] == "timeout":
        return _timeout_msg(job)
    if job["status"] == "error":
        return f"❌ Scraping failed: {job.get('message', 'Unknown error')}"

    total  = job.get("scraped", 0)
    stats  = job.get("gm_stats", {})

    def pct(n):
        return f"{round(n / total * 100)}%" if total else "—"

    lines = [
        f"✅ **{total:,} places** found on Google Maps for **{location}**",
        "",
        f"| Stat | Count | % |",
        f"| --- | --- | --- |",
        f"| With phone    | {stats.get('with_phone', '—')} | {pct(stats.get('with_phone', 0))} |",
        f"| With website  | {stats.get('with_website', '—')} | {pct(stats.get('with_website', 0))} |",
        f"| With delivery | {stats.get('with_delivery', '—')} | {pct(stats.get('with_delivery', 0))} |",
        f"| With reservation | {stats.get('with_reservation', '—')} | {pct(stats.get('with_reservation', 0))} |",
        "",
        f"📥 [Download full Excel (4 sheets)]({_download_url(job_id)})",
    ]
    if email:
        lines.append(f"📧 Also sent to {email}")

    return "\n".join(lines)


@mcp.tool()
def analyze_websites(
    restaurants: list[dict],
    email: str = "",
) -> str:
    """
    Analyze restaurant websites to extract social media profiles, follower counts,
    contact emails, legal registration data, website platform, reservation system,
    and online ordering system.

    Args:
        restaurants: List of dicts, each with 'name' and 'url' keys.
                     Example: [{"name": "Cafe Savoy", "url": "https://cafesavoy.ambi.cz"}]
        email:       Optional — also email results as Excel when done

    Returns all results inline (every row, key columns shown as table).
    """
    if not restaurants:
        return "❌ Please provide at least one restaurant with 'name' and 'url'."

    bad = [r for r in restaurants if not r.get("url")]
    if bad:
        return f"❌ These entries are missing a 'url': {bad}"

    # Normalise URLs
    cleaned = []
    for r in restaurants:
        url = str(r.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        cleaned.append({"name": r.get("name", url), "url": url})

    with httpx.Client(timeout=20) as client:
        r = client.post(f"{API_BASE}/api/website-intel", json={"restaurants": cleaned, "email": email})
        if not r.is_success:
            return f"❌ Could not start job: {r.text}"
        job_id = r.json()["job_id"]

    job = _poll(job_id)

    if job["status"] == "timeout":
        return _timeout_msg(job)
    if job["status"] == "error":
        return f"❌ Analysis failed: {job.get('message', 'Unknown error')}"

    total = job.get("scraped", 0)
    lines = [
        f"✅ **{total} restaurant{'s' if total != 1 else ''}** analyzed",
        f"📥 [Download Excel]({_download_url(job_id)})",
        "",
    ]
    if email:
        lines.append(f"📧 Also sent to {email}\n")

    lines.append("_Note: Download the Excel for the complete dataset with all columns._")
    return "\n".join(lines)


@mcp.tool()
def check_job(job_id: str) -> str:
    """
    Check the status of a previously started scraping job and get its results.
    Use this when a job returned a job ID because it was taking too long.

    Args:
        job_id: The job ID returned by a previous scraping tool call.
    """
    with httpx.Client(timeout=15) as client:
        try:
            job = client.get(f"{API_BASE}/api/jobs/{job_id}").json()
        except Exception as e:
            return f"❌ Could not reach scraper API: {e}"

    status   = job.get("status", "unknown")
    progress = job.get("progress", 0)
    scraped  = job.get("scraped", 0)
    message  = job.get("message", "")
    has_file = job.get("has_file", False)

    if status == "done":
        lines = [
            f"✅ **Job complete** — {scraped:,} results",
            f"💬 {message}",
        ]
        if has_file:
            lines.append(f"📥 [Download Excel]({_download_url(job_id)})")
        return "\n".join(lines)

    if status == "error":
        return f"❌ Job failed: {message}"

    return (
        f"⏳ **Job running** — {progress}% complete, {scraped:,} found so far\n"
        f"💬 {message}\n\n"
        f"Call `check_job('{job_id}')` again in a moment."
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--http" in sys.argv:
        # Remote HTTP mode — for deploying on Render so colleagues can connect
        port = int(os.environ.get("PORT", 8080))
        print(f"Starting HTTP MCP server on port {port}…", flush=True)
        mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
    else:
        # Local stdio mode — standard for Claude Code
        mcp.run(transport="stdio")
