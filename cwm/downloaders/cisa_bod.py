"""CISA Binding Operational Directives (BOD) downloader.

CISA BODs are published as HTML pages, not PDFs — the full directive text is
embedded in each detail page at cisa.gov/news-events/directives/bod-*.

Fetch strategy (index page, in order):
1. Plain requests.get() — fast, works if CISA's WAF allows it
2. Playwright headless browser — fallback if plain request is blocked
3. Curated KNOWN_URLS list — last resort if the index itself cannot be scraped;
   individual BOD pages are still publicly accessible even when the index is blocked
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
    require_playwright,
    sanitize_filename,
)

SOURCE_URL = "https://www.cisa.gov/directives"
BASE_URL = "https://www.cisa.gov"

# URL path prefix that all BOD detail pages share
BOD_PATH_PREFIX = "/news-events/directives/bod-"

# ---------------------------------------------------------------------------
# Curated fallback URL list
# ---------------------------------------------------------------------------

# Date these URLs were last manually verified against SOURCE_URL.
KNOWN_URLS_VERIFIED = "2026-02-26"

# Direct BOD detail page URLs. Used when the index page cannot be scraped.
KNOWN_URLS: list[str] = [
    "https://www.cisa.gov/news-events/directives/bod-26-02-mitigating-risk-end-support-edge-devices",
    "https://www.cisa.gov/news-events/directives/bod-25-01-implementing-secure-practices-cloud-services",
    "https://www.cisa.gov/news-events/directives/bod-25-01-implementation-guidance-implementing-secure-practices-cloud-services",
    "https://www.cisa.gov/news-events/directives/binding-operational-directive-23-02",
    "https://www.cisa.gov/news-events/directives/bod-23-02-implementation-guidance-mitigating-risk-internet-exposed-management-interfaces",
    "https://www.cisa.gov/news-events/directives/bod-23-01-improving-asset-visibility-and-vulnerability-detection-federal-networks",
    "https://www.cisa.gov/news-events/directives/bod-23-01-implementation-guidance-improving-asset-visibility-and-vulnerability-detection-federal",
    "https://www.cisa.gov/news-events/directives/bod-22-01-reducing-significant-risk-known-exploited-vulnerabilities",
    "https://www.cisa.gov/news-events/directives/bod-20-01-develop-and-publish-vulnerability-disclosure-policy",
    "https://www.cisa.gov/news-events/directives/bod-19-02-vulnerability-remediation-requirements-internet-accessible-systems",
    "https://www.cisa.gov/news-events/directives/bod-18-02-securing-high-value-assets",
    "https://www.cisa.gov/news-events/directives/bod-18-01-enhance-email-and-web-security",
    "https://www.cisa.gov/news-events/directives/bod-17-01-removal-kaspersky-branded-products",
    "https://www.cisa.gov/news-events/directives/bod-16-03-2016-agency-cybersecurity-reporting-requirements",
    "https://www.cisa.gov/news-events/directives/bod-16-02-threat-network-infrastructure-devices",
    "https://www.cisa.gov/news-events/directives/binding-operational-directive-16-01",
    "https://www.cisa.gov/news-events/directives/binding-operational-directive-15-01",
]

# ---------------------------------------------------------------------------
# Index page fetching
# ---------------------------------------------------------------------------


def _fetch_html_plain() -> Optional[str]:
    """Fetch the index page via plain requests. Returns HTML or None."""
    import time

    headers = {"User-Agent": USER_AGENT}
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = requests.get(SOURCE_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
        except requests.RequestException:
            pass
        if attempt < REQUEST_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return None


def _fetch_html_playwright() -> Optional[str]:
    """Fetch the index page via Playwright headless browser. Returns HTML or None."""
    try:
        require_playwright()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(SOURCE_URL, wait_until="networkidle")
            html = page.content()
            browser.close()
        return html
    except Exception:  # noqa: BLE001
        return None


def _parse_bod_links(html: str) -> list[tuple[str, str]]:
    """Return list of (filename, full_url) for all BOD detail pages on the index."""
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
        slug = Path(path).name
        filename = sanitize_filename(slug) + ".html"
        links.append((filename, full_url))

    return links


def _links_from_known_urls() -> list[tuple[str, str]]:
    """Convert KNOWN_URLS to (filename, url) format."""
    links = []
    for url in KNOWN_URLS:
        slug = Path(urlparse(url).path).name
        filename = sanitize_filename(slug) + ".html"
        links.append((filename, url))
    return links


def _write_known_urls_file(dest: Path) -> None:
    """Write a plain-text list of KNOWN_URLS to dest/_known-urls.txt."""
    lines = [
        f"# CISA BOD known fallback URLs — last verified {KNOWN_URLS_VERIFIED}",
        "# Used when the CISA WAF blocks automated scraping of the directives index.",
        f"# Source page: {SOURCE_URL}",
        "",
    ]
    for url in KNOWN_URLS:
        lines.append(url)
    (dest / "_known-urls.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _try_scrape() -> Optional[list[tuple[str, str]]]:
    """Try plain requests then Playwright to scrape the index. Returns links or None."""
    html = _fetch_html_plain()
    if html:
        links = _parse_bod_links(html)
        if links:
            return links

    html = _fetch_html_playwright()
    if html:
        links = _parse_bod_links(html)
        if links:
            return links

    return None


# ---------------------------------------------------------------------------
# Page downloading (requests → Playwright fallback)
# ---------------------------------------------------------------------------


def _playwright_download_pages(
    links: list[tuple[str, str]],
    dest: Path,
    force: bool,
    state: Optional["StateFile"],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Fetch BOD HTML pages via Playwright. Returns (downloaded, skipped, errors)."""
    downloaded: list[str] = []
    skipped: list[str] = []
    errors: list[tuple[str, str]] = []

    try:
        require_playwright()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            pg = browser.new_page(user_agent=USER_AGENT)
            for filename, url in links:
                target = dest / filename
                if not force and target.exists() and target.stat().st_size > 0:
                    skipped.append(filename)
                    continue
                try:
                    pg.goto(url, wait_until="networkidle", timeout=30000)
                    html = pg.content()
                    target.write_text(html, encoding="utf-8")
                    if state is not None:
                        state.record(target, url)
                    downloaded.append(filename)
                except Exception as exc:  # noqa: BLE001
                    errors.append((filename, f"playwright: {exc}"))
            browser.close()
    except Exception:  # noqa: BLE001
        hint = "WAF blocked; install Playwright browser to enable auto-download"
        for filename, _url in links:
            errors.append((filename, hint))

    return downloaded, skipped, errors


def _download_pages(
    links: list[tuple[str, str]],
    dest: Path,
    force: bool,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    """Download BOD HTML pages: plain requests first, Playwright fallback for failures."""
    result = DownloadResult(framework="cisa-bod")
    session = requests.Session()
    needs_playwright: list[tuple[str, str]] = []

    for filename, url in links:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, referer=SOURCE_URL, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            needs_playwright.append((filename, url))

    if needs_playwright:
        pw_dl, pw_sk, pw_err = _playwright_download_pages(needs_playwright, dest, force, state)
        result.downloaded.extend(pw_dl)
        result.skipped.extend(pw_sk)
        result.errors.extend(pw_err)

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
    dest = output_dir / "cisa-bod"

    links = _try_scrape()
    used_known_urls = links is None
    if links is None:
        links = _links_from_known_urls()

    if not links:
        result = DownloadResult(framework="cisa-bod")
        result.errors.append(("", f"Failed to fetch CISA directives index: {SOURCE_URL}"))
        return result

    if dry_run:
        result = DownloadResult(framework="cisa-bod")
        for filename, _url in links:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        if used_known_urls:
            result.notices.append(
                f"Automated index scrape unavailable — CISA WAF blocked access. "
                f"Used last-known-good URL list (last verified {KNOWN_URLS_VERIFIED}). "
                f"See source-content/cisa-bod/_known-urls.txt for the full URL list."
            )
        return result

    dest.mkdir(parents=True, exist_ok=True)
    _write_known_urls_file(dest)
    result = _download_pages(links, dest, force, state)
    if used_known_urls:
        result.notices.append(
            f"Automated index scrape unavailable — CISA WAF blocked access. "
            f"Used last-known-good URL list (last verified {KNOWN_URLS_VERIFIED}). "
            f"See source-content/cisa-bod/_known-urls.txt for the full URL list."
        )

    return result
