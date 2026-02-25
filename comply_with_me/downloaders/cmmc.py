"""CMMC resources downloader (requires Playwright — DoD portal blocks plain requests)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

import requests

if TYPE_CHECKING:
    from comply_with_me.state import StateFile

from .base import (
    RATE_LIMIT_DELAY,
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


def _fetch_html() -> str:
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


def _playwright_download(
    links: list[tuple[str, str, str]],
    dest: Path,
    force: bool,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    """Download files using Playwright browser context (handles DoD auth/redirect)."""
    require_playwright()
    from playwright.sync_api import sync_playwright

    result = DownloadResult(framework="cmmc")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(SOURCE_URL, wait_until="networkidle")

        for _section, filename, url in links:
            target = dest / filename
            if not force:
                if state is not None:
                    if state.needs_adopt(target):
                        state.adopt(target, url)
                    if state.is_fresh(target, url):
                        result.skipped.append(filename)
                        continue
                elif target.exists() and target.stat().st_size > 0:
                    result.skipped.append(filename)
                    continue

            locator = page.locator(f"a[href='{url}']")
            if locator.count() == 0:
                # Link not found in live page — try direct HTTP download
                session = requests.Session()
                ok, msg = download_file(
                    session, url, target, force=force, referer=SOURCE_URL, state=state
                )
                if msg == "skipped":
                    result.skipped.append(filename)
                elif ok:
                    result.downloaded.append(filename)
                else:
                    result.manual_required.append((filename, url))
                continue

            try:
                time.sleep(RATE_LIMIT_DELAY)
                target.parent.mkdir(parents=True, exist_ok=True)
                with page.expect_download(timeout=REQUEST_TIMEOUT * 1000) as dl_info:
                    locator.first.click()
                dl_info.value.save_as(str(target))
                if target.stat().st_size == 0:
                    target.unlink(missing_ok=True)
                    raise OSError("Empty file")
                if state is not None:
                    state.record(target, url)
                result.downloaded.append(filename)
            except Exception as exc:  # noqa: BLE001
                result.errors.append((filename, str(exc)))

        browser.close()

    return result


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cmmc"
    result = DownloadResult(framework="cmmc")

    html = _fetch_html()

    if _is_access_denied(html):
        # The DoD portal blocks all automated access (headless browsers, bots).
        # Surface the source URL so the user can download manually.
        result.manual_required.append(
            ("CMMC Resources page", SOURCE_URL)
        )
        return result

    links = _parse_links(html)

    if not links:
        result.manual_required.append(
            ("CMMC Resources page (no links detected)", SOURCE_URL)
        )
        return result

    if dry_run:
        for _section, filename, _url in links:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    dest.mkdir(parents=True, exist_ok=True)
    return _playwright_download(links, dest, force, state)
