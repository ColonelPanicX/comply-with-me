"""NIST publications downloader — final and draft series."""

from __future__ import annotations

import concurrent.futures
import re
import time
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
    DownloadResult,
    sanitize_filename,
)

# Per-series rate limiting constants (not in base since NIST-specific)
LISTING_RATE_DELAY = 0.8
DETAIL_RATE_DELAY = 0.5
DOWNLOAD_RATE_DELAY = 0.2
DETAIL_WORKERS = 6
DOWNLOAD_WORKERS = 4

FINAL_LISTING_URL = "https://csrc.nist.gov/publications/final-pubs"
DRAFT_LISTING_URL = "https://csrc.nist.gov/publications/draft-pubs"

HEADERS = {"User-Agent": "cwm-nist-dl (https://csrc.nist.gov/)"}

DRAFT_TERMINATORS = {"draft", "ipd", "fpd", "pd", "iprd", "2pd"}


# ---------------------------------------------------------------------------
# Listing crawl
# ---------------------------------------------------------------------------

def _listing_urls(base: str) -> list[str]:
    """Yield paginated listing URLs until exhausted."""
    urls = []
    page = 0
    while True:
        urls.append(base if page == 0 else f"{base}?page={page}")
        page += 1
        if page > 500:  # safety cap
            break
    return urls


def _fetch(session: requests.Session, url: str, delay: float) -> Optional[str]:
    time.sleep(delay)
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                return None
        except requests.RequestException:
            pass
        if attempt < REQUEST_RETRIES - 1:
            time.sleep(RETRY_DELAY)
    return None


def _parse_listing(html: str, origin: str, series_type: str) -> list[str]:
    """Extract detail page URLs from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    pattern = (
        r"/pubs/.+/final"
        if series_type == "finals"
        else r"/pubs/.+/(?:draft|ipd|fpd|pd|iprd|2pd)(?:/|$)"
    )
    links: list[str] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href or not re.search(pattern, href):
            continue
        url = urljoin(origin, href)
        if url not in seen:
            seen.add(url)
            links.append(url)
    return links


def _crawl_listings(session: requests.Session, base_url: str, series_type: str) -> list[str]:
    all_links: list[str] = []
    seen: set[str] = set()
    for url in _listing_urls(base_url):
        html = _fetch(session, url, LISTING_RATE_DELAY)
        if not html:
            break
        new = [link for link in _parse_listing(html, url, series_type) if link not in seen]
        if not new:
            break
        all_links.extend(new)
        seen.update(new)
    return all_links


# ---------------------------------------------------------------------------
# Detail page parsing
# ---------------------------------------------------------------------------

def _extract_series_number(url: str, series_type: str) -> tuple[str, str]:
    parts = [p for p in urlparse(url).path.split("/") if p]
    try:
        idx = parts.index("pubs") + 1
        series = parts[idx].lower()
        terminators = {"final"} if series_type == "finals" else DRAFT_TERMINATORS
        number_parts = []
        for part in parts[idx + 1:]:
            if part.lower() in terminators:
                break
            number_parts.append(part)
        number = "-".join(number_parts) or "unknown"
    except (ValueError, IndexError):
        series, number = "unknown", "unknown"
    return series, number


def _parse_detail(html: str, detail_url: str) -> Optional[str]:
    """Return the PDF download URL from a detail page, or None."""
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = anchor.get_text(strip=True).lower()
        if href.lower().endswith(".pdf"):
            return urljoin(detail_url, href)
        if "nvlpubs.nist.gov" in href.lower():
            return urljoin(detail_url, href)
        if "download" in text and href.startswith("http"):
            return urljoin(detail_url, href)
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_pub(
    session: requests.Session,
    detail_url: str,
    download_url: str,
    base_dir: Path,
    series: str,
    series_type: str,
    force: bool,
    state: Optional["StateFile"] = None,
) -> tuple[str, bool, str]:
    """Download one publication. Returns (filename, success, message)."""
    ser, _num = _extract_series_number(detail_url, series_type)
    filename = sanitize_filename(Path(urlparse(download_url).path).name or f"{ser}.pdf")
    target = base_dir / series / filename

    if not force:
        if state is not None:
            if state.needs_adopt(target):
                state.adopt(target, download_url)
            if state.is_fresh(target, download_url):
                return filename, True, "skipped"
        elif target.exists() and target.stat().st_size > 0:
            return filename, True, "skipped"

    target.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(DOWNLOAD_RATE_DELAY)

    for attempt in range(REQUEST_RETRIES):
        try:
            with session.get(
                download_url, headers=HEADERS, timeout=120, stream=True
            ) as resp:
                if resp.status_code == 200:
                    with target.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                fh.write(chunk)
                    if target.stat().st_size == 0:
                        target.unlink(missing_ok=True)
                        raise OSError("Empty file")
                    if state is not None:
                        state.record(target, download_url)
                    return filename, True, "downloaded"
                if resp.status_code == 404:
                    return filename, False, "not found (404)"
        except requests.RequestException as exc:
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return filename, False, f"failed: {exc}"

    return filename, False, "failed after retries"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def _run(
    output_dir: Path,
    series_type: str,
    dry_run: bool,
    force: bool,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    result = DownloadResult(framework=f"nist-{series_type}")
    base_url = FINAL_LISTING_URL if series_type == "finals" else DRAFT_LISTING_URL
    subdir = "final-pubs" if series_type == "finals" else "draft-pubs"
    base_dir = output_dir / "nist" / subdir

    session = requests.Session()

    detail_urls = _crawl_listings(session, base_url, series_type)
    if not detail_urls:
        result.errors.append(("", "No publication pages found — CSRC listing may have changed"))
        return result

    # Fetch detail pages concurrently to extract download URLs
    pub_map: dict[str, Optional[str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=DETAIL_WORKERS) as ex:
        futures = {ex.submit(_fetch, session, url, DETAIL_RATE_DELAY): url for url in detail_urls}
        for future in concurrent.futures.as_completed(futures):
            url = futures[future]
            html = future.result()
            pub_map[url] = _parse_detail(html, url) if html else None

    downloadable = [(durl, purl) for durl, purl in pub_map.items() if purl]

    if dry_run:
        for detail_url, download_url in downloadable:
            ser, _num = _extract_series_number(detail_url, series_type)
            filename = sanitize_filename(Path(urlparse(download_url).path).name or f"{ser}.pdf")
            target = base_dir / ser / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    base_dir.mkdir(parents=True, exist_ok=True)

    def _dl(item: tuple[str, str]) -> tuple[str, bool, str]:
        detail_url, download_url = item
        ser, _num = _extract_series_number(detail_url, series_type)
        return _download_pub(
            session, detail_url, download_url, base_dir, ser, series_type, force, state
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as ex:
        for filename, ok, msg in ex.map(_dl, downloadable):
            if msg == "skipped":
                result.skipped.append(filename)
            elif ok:
                result.downloaded.append(filename)
            else:
                result.errors.append((filename, msg))

    return result


def run_finals(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    """Download NIST final publications."""
    return _run(output_dir, "finals", dry_run, force, state)


def run_drafts(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    """Download NIST draft publications."""
    return _run(output_dir, "drafts", dry_run, force, state)
