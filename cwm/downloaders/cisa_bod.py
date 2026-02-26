"""CISA Binding Operational Directives (BOD) downloader.

CISA BODs are published as HTML pages, not PDFs — the full directive text is
embedded in each detail page at cisa.gov/news-events/directives/bod-*.

Fetch strategy:
1. Scrape the index page (SOURCE_URL) for all BOD detail-page links
2. Download each detail page as a .html file into source-content/cisa-bod/
   using the URL slug as the filename (e.g. bod-25-01-...html)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from cwm.state import StateFile

from .base import (
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    USER_AGENT,
    DownloadResult,
    download_file,
    sanitize_filename,
)

SOURCE_URL = "https://www.cisa.gov/directives"
BASE_URL = "https://www.cisa.gov"

# URL path prefix that all BOD detail pages share
BOD_PATH_PREFIX = "/news-events/directives/bod-"


def _fetch_html(url: str) -> Optional[str]:
    """Fetch a page via plain requests. Returns response text or None on failure."""
    headers = {"User-Agent": USER_AGENT}
    import time

    for attempt in range(REQUEST_RETRIES):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        if attempt < REQUEST_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return None


def _parse_bod_links(html: str) -> list[tuple[str, str]]:
    """Return list of (filename, full_url) for all BOD detail pages on the index.

    Filters for links whose path starts with BOD_PATH_PREFIX to capture both
    main directive pages and implementation-guidance pages.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[tuple[str, str]] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue
        full_url = urljoin(BASE_URL, href)
        path = urlparse(full_url).path
        if not path.startswith(BOD_PATH_PREFIX):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        # Derive filename from the URL slug, preserving the full slug for traceability
        slug = Path(path).name
        filename = sanitize_filename(slug) + ".html"
        links.append((filename, full_url))

    return links


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cisa-bod"
    result = DownloadResult(framework="cisa-bod")

    html = _fetch_html(SOURCE_URL)
    if html is None:
        result.errors.append(("", f"Failed to fetch CISA directives index: {SOURCE_URL}"))
        return result

    links = _parse_bod_links(html)
    if not links:
        result.errors.append(("", "No BOD pages found on CISA directives index"))
        return result

    if dry_run:
        for filename, _url in links:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for filename, url in links:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, referer=SOURCE_URL, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            result.errors.append((filename, msg))

    return result
