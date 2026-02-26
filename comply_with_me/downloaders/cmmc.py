"""CMMC resources downloader.

Fetch strategy (in order):
1. Plain requests.get() on the resources page — works if DoD WAF allows the request
2. Playwright headless browser — fallback if plain request is access-denied
3. Curated KNOWN_URLS list — used when the page itself cannot be scraped; the
   individual PDF URLs are direct and publicly accessible even when the HTML
   page is blocked
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests

if TYPE_CHECKING:
    from comply_with_me.state import StateFile

from .base import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    DownloadResult,
    download_file,
    require_playwright,
    sanitize_filename,
)

SOURCE_URL = "https://dodcio.defense.gov/cmmc/Resources-Documentation/"
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}

# DNN CMS module IDs for the two content sections on the CMMC resources page.
# These may need updating if the DoD site is redesigned.
SECTION_MODULES = {
    "internal": "dnn_ctr136430_ModuleContent",
    "external": "dnn_ctr136428_ModuleContent",
}

_ACCESS_DENIED_TITLE = "access denied"

# ---------------------------------------------------------------------------
# Curated fallback URL list
# ---------------------------------------------------------------------------

# Date these URLs were last manually verified against SOURCE_URL.
# Update KNOWN_URLS_VERIFIED whenever you re-confirm the list is current.
KNOWN_URLS_VERIFIED = "2026-02-25"

# Direct download URLs extracted from SOURCE_URL.
# Used as a fallback when the resources page cannot be scraped automatically.
# Format: (section, url)  — section matches SECTION_MODULES keys above.
KNOWN_URLS: list[tuple[str, str]] = [
    ("internal", "https://dowcio.war.gov/Portals/0/Documents/CMMC/CMMC-FAQsv4.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/CMMC-101-Nov2025.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/ModelOverviewv2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/ScopingGuideL1v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL1v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/ScopingGuideL2v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL2v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/ScopingGuideL3v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/AssessmentGuideL3v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/HashingGuide_v2.14.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/CMMC-AlignmentNIST-Standards.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/CMMC-SPRS.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/CMMC-eMASS.pdf?ver=l-hPeQGKDLRXdQrpxM2AQg%3d%3d"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/FedRAMP-AuthorizationEquivalency.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/CMMC-LevelsDeterminationBrief_v2.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/TechImplementationCMMC-Rqrmnts.pdf"),
    ("internal", "https://dodcio.defense.gov/Portals/0/Documents/CMMC/OrgDefinedParmsNISTSP800-171.pdf"),
    ("external", "https://cyberab.org/Portals/0/CMMC%20Assessment%20Process%20v2.0.pdf"),
    ("external", "https://www.esd.whs.mil/Portals/54/Documents/DD/issuances/dodi/500090p.PDF"),
    ("external", "https://dodcio.defense.gov/Portals/0/Documents/Library/FulcrumAdvStrat.pdf"),
]

# ---------------------------------------------------------------------------
# Page fetching
# ---------------------------------------------------------------------------


def _fetch_html_plain() -> Optional[str]:
    """Fetch the resources page with plain requests.

    Returns the response text on HTTP 200, or None on error / non-200.
    """
    try:
        resp = requests.get(
            SOURCE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.text
        return None
    except requests.RequestException:
        return None


def _fetch_html_playwright() -> str:
    """Fetch the resources page using a Playwright headless browser."""
    require_playwright()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(SOURCE_URL, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def _is_access_denied(html: str) -> bool:
    """Return True if the DoD portal returned an Access Denied page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    return title is not None and _ACCESS_DENIED_TITLE in title.get_text().lower()


def _parse_links(html: str) -> list[tuple[str, str, str]]:
    """Return list of (section, filename, url) for all downloadable links."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    links: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for section, module_id in SECTION_MODULES.items():
        container = soup.find(id=module_id)
        if not container:
            continue
        for anchor in container.find_all("a", href=True):
            raw_href = anchor["href"].strip()
            if not raw_href:
                continue
            url = urljoin(SOURCE_URL, raw_href)
            if url in seen:
                continue
            ext = Path(urlparse(url).path).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            seen.add(url)
            filename = sanitize_filename(Path(urlparse(url).path).name)
            links.append((section, filename, url))

    return links


def _try_scrape() -> Optional[list[tuple[str, str, str]]]:
    """Attempt to scrape the resources page. Returns parsed links or None if blocked."""
    # Attempt 1: plain requests
    html = _fetch_html_plain()
    if html is not None and not _is_access_denied(html):
        links = _parse_links(html)
        if links:
            return links

    # Attempt 2: Playwright
    try:
        html = _fetch_html_playwright()
        if not _is_access_denied(html):
            links = _parse_links(html)
            if links:
                return links
    except Exception:  # noqa: BLE001
        pass

    return None


def _links_from_known_urls() -> list[tuple[str, str, str]]:
    """Convert KNOWN_URLS to the standard (section, filename, url) format."""
    links = []
    for section, url in KNOWN_URLS:
        filename = sanitize_filename(unquote(Path(urlparse(url).path).name))
        links.append((section, filename, url))
    return links


# ---------------------------------------------------------------------------
# Downloading
# ---------------------------------------------------------------------------


def _requests_download(
    links: list[tuple[str, str, str]],
    dest: Path,
    force: bool,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    """Download files via plain HTTP requests."""
    result = DownloadResult(framework="cmmc")
    session = requests.Session()

    for _section, filename, url in links:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, referer=SOURCE_URL, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            result.manual_required.append((filename, url))

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cmmc"
    result = DownloadResult(framework="cmmc")

    links = _try_scrape()
    used_known_urls = links is None
    if links is None:
        links = _links_from_known_urls()

    if not links:
        result.manual_required.append(("CMMC Resources page (no links detected)", SOURCE_URL))
        return result

    if dry_run:
        for _section, filename, _url in links:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        if used_known_urls:
            result.notices.append(
                f"Automated download unavailable — DoD portal blocked access. "
                f"Used last-known-good URL list (last verified {KNOWN_URLS_VERIFIED}). "
                f"See comply_with_me/downloaders/cmmc.py (KNOWN_URLS) for the full URL list."
            )
        return result

    dest.mkdir(parents=True, exist_ok=True)
    result = _requests_download(links, dest, force, state)
    if used_known_urls:
        result.notices.append(
            f"Automated download unavailable — DoD portal blocked access. "
            f"Used last-known-good URL list (last verified {KNOWN_URLS_VERIFIED}). "
            f"See comply_with_me/downloaders/cmmc.py (KNOWN_URLS) for the full URL list."
        )
    return result
