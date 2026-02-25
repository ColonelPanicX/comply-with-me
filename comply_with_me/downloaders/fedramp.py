"""FedRAMP Rev 5 documents and templates downloader."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from comply_with_me.state import StateFile

from .base import (
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    USER_AGENT,
    DownloadResult,
    download_file,
    sanitize_filename,
)

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xlsx", ".xls", ".zip"}

SOURCE_URL = "https://www.fedramp.gov/rev5/documents-templates/"
DOWNLOAD_WORKERS = 4


def _fetch_html() -> str:
    """Fetch the FedRAMP page via requests; fall back to Playwright if blocked."""
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = requests.get(SOURCE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        import time
        time.sleep(RETRY_DELAY)

    # Playwright fallback
    from .base import require_playwright
    require_playwright()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(SOURCE_URL, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def _parse_links(html: str) -> list[tuple[str, str]]:
    """Return list of (filename, url) for all downloadable links."""
    soup = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    links: list[tuple[str, str]] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue
        url = urljoin(SOURCE_URL, href)
        if url in seen:
            continue
        ext = Path(urlparse(url).path).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            continue
        seen.add(url)
        filename = sanitize_filename(Path(urlparse(url).path).name)
        links.append((filename, url))
    return links


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    result = DownloadResult(framework="fedramp")
    dest = output_dir / "fedramp"

    html = _fetch_html()
    links = _parse_links(html)

    if not links:
        result.errors.append(("", "No downloadable links found on FedRAMP page"))
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

    def _download(item: tuple[str, str]) -> tuple[str, bool, str]:
        filename, url = item
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, referer=SOURCE_URL, state=state)
        return filename, ok, msg

    with concurrent.futures.ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as executor:
        for filename, ok, msg in executor.map(_download, links):
            if msg == "skipped":
                result.skipped.append(filename)
            elif ok:
                result.downloaded.append(filename)
            else:
                result.errors.append((filename, msg))

    return result
