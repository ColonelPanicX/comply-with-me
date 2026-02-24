#!/usr/bin/env python3
"""Crawl NIST draft publications and download all available PDFs."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import requests

try:
    from bs4 import BeautifulSoup
except ImportError as exc:
    raise SystemExit(
        "BeautifulSoup is required. Install with `pip install beautifulsoup4`."
    ) from exc

# Crawl configuration defaults.
BASE_LISTING_URL = "https://csrc.nist.gov/publications/draft-pubs"
HEADERS = {"User-Agent": "nist-drafts-auto-dl (https://csrc.nist.gov/)"}
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
RETRY_DELAY = 2
LISTING_RATE_DELAY = 0.8
DETAIL_RATE_DELAY = 0.5
DOWNLOAD_RATE_DELAY = 0.2
DETAIL_WORKERS = 6
DOWNLOAD_WORKERS = 4
SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_ROOT = SCRIPT_DIR / "downloads" / "draft-pubs"
REPORTS_ROOT = SCRIPT_DIR / "reports" / "drafts"
DRAFT_TERMINATORS = {"draft", "ipd", "fpd", "pd", "iprd", "2pd"}


@dataclass
class Publication:
    """Metadata for a single publication."""

    detail_url: str
    download_url: Optional[str]
    title: str
    series: str
    number: str
    status: str
    note: str = ""


def build_listing_urls(max_pages: Optional[int]) -> Iterable[str]:
    """Yield listing URLs until max_pages is hit or pages run dry."""
    page = 0
    while True:
        if max_pages is not None and page >= max_pages:
            return
        yield BASE_LISTING_URL if page == 0 else f"{BASE_LISTING_URL}?page={page}"
        page += 1


def fetch_text(session: requests.Session, url: str, *, delay: float) -> Optional[str]:
    """Fetch text content with retries and simple rate limiting."""
    time.sleep(delay)
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                logging.warning("Not found: %s", url)
                return None
        except requests.RequestException as exc:
            logging.warning(
                "Request error (attempt %s) for %s: %s", attempt + 1, url, exc
            )
        time.sleep(RETRY_DELAY)
    logging.error("Failed to fetch after retries: %s", url)
    return None


def parse_listing(html: str, origin: str) -> List[str]:
    """Extract detail page URLs from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if not href:
            continue
        if not re.search(r"/pubs/.+/(?:draft|ipd|fpd|pd|iprd|2pd)(?:/|$)", href):
            continue
        absolute = urljoin(origin, href)
        links.append(absolute)
    # Preserve order but deduplicate.
    seen = set()
    ordered = []
    for link in links:
        if link not in seen:
            seen.add(link)
            ordered.append(link)
    return ordered


def extract_series_number(detail_url: str) -> tuple[str, str]:
    """Derive series and number from the detail URL path segments."""
    parsed = urlparse(detail_url)
    parts = [p for p in parsed.path.split("/") if p]
    # Expected pattern: /pubs/<series>/<number>/.../<draft-status>
    try:
        series_idx = parts.index("pubs") + 1
        series = parts[series_idx].lower()
        number_parts: List[str] = []
        for part in parts[series_idx + 1 :]:
            if part.lower() in DRAFT_TERMINATORS:
                break
            number_parts.append(part)
        number = "-".join(number_parts) if number_parts else "unknown"
    except (ValueError, IndexError):
        series = "unknown"
        number = "unknown"
    return series, number


def parse_detail(detail_html: str, detail_url: str) -> Publication:
    """Extract title and download link from a detail page."""
    soup = BeautifulSoup(detail_html, "html.parser")
    title = soup.find("h1").get_text(strip=True) if soup.find("h1") else "Unknown title"

    download_link = None
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = anchor.get_text(strip=True).lower()
        if href.lower().endswith(".pdf"):
            download_link = urljoin(detail_url, href)
            break
        if "nvlpubs.nist.gov" in href.lower():
            download_link = urljoin(detail_url, href)
            break
        if "download" in text and href.startswith("http"):
            download_link = urljoin(detail_url, href)
            break

    series, number = extract_series_number(detail_url)
    status = "found" if download_link else "missing"
    note = "" if download_link else "No download link detected"
    return Publication(
        detail_url=detail_url,
        download_url=download_link,
        title=title,
        series=series,
        number=number,
        status=status,
        note=note,
    )


def crawl_listings(session: requests.Session, max_pages: Optional[int]) -> List[str]:
    """Collect all publication detail URLs across listing pages."""
    all_links: List[str] = []
    seen_before_page: set[str] = set()
    for url in build_listing_urls(max_pages):
        logging.info("Fetching listing: %s", url)
        html = fetch_text(session, url, delay=LISTING_RATE_DELAY)
        if not html:
            logging.info("No content at %s; stopping listing crawl.", url)
            break
        links = parse_listing(html, url)
        new_links = [link for link in links if link not in seen_before_page]
        if not new_links:
            logging.info("No new publication links at %s; stopping pagination.", url)
            break
        logging.info("Found %s publications on page.", len(links))
        all_links.extend(new_links)
        seen_before_page.update(new_links)
    # Final dedupe to be safe.
    deduped = []
    seen = set()
    for link in all_links:
        if link not in seen:
            seen.add(link)
            deduped.append(link)
    logging.info("Total unique publication pages: %s", len(deduped))
    return deduped


def fetch_details(session: requests.Session, detail_urls: List[str], workers: int) -> List[Publication]:
    """Fetch and parse all detail pages concurrently."""
    publications: List[Publication] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(fetch_text, session, url, delay=DETAIL_RATE_DELAY): url
            for url in detail_urls
        }
        for future in as_completed(future_map):
            url = future_map[future]
            html = future.result()
            if not html:
                series, number = extract_series_number(url)
                publications.append(
                    Publication(
                        detail_url=url,
                        download_url=None,
                        title="Unknown title",
                        series=series,
                        number=number,
                        status="missing",
                        note="Detail page unavailable",
                    )
                )
                continue
            publications.append(parse_detail(html, url))
    return publications


def write_manifest(publications: List[Publication], manifest_path: Path) -> None:
    """Write manifest CSV for all discovered publications."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["title", "series", "number", "detail_url", "download_url", "status", "note"]
        )
        for pub in publications:
            writer.writerow(
                [
                    pub.title,
                    pub.series,
                    pub.number,
                    pub.detail_url,
                    pub.download_url or "N/A",
                    pub.status,
                    pub.note,
                ]
            )
    logging.info("Wrote manifest: %s", manifest_path)


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe filename component."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return safe.strip("_") or "file"


def download_one(session: requests.Session, pub: Publication, base_dir: Path) -> tuple[Publication, str, bool]:
    """Download a single publication PDF."""
    if not pub.download_url:
        return pub, "Skipped (no download URL)", False

    filename = sanitize_filename(
        Path(urlparse(pub.download_url).path).name or f"{pub.series}-{pub.number}.pdf"
    )
    target_dir = base_dir / pub.series
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if target_path.exists() and target_path.stat().st_size > 0:
        return pub, "Already exists", True

    time.sleep(DOWNLOAD_RATE_DELAY)
    for attempt in range(REQUEST_RETRIES):
        try:
            with session.get(
                pub.download_url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
                stream=True,
            ) as resp:
                if resp.status_code == 200:
                    with target_path.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                fh.write(chunk)
                    if target_path.stat().st_size == 0:
                        target_path.unlink(missing_ok=True)
                        raise IOError("Empty file after download")
                    return pub, "Downloaded", True
                if resp.status_code == 404:
                    return pub, "Not found (404)", False
        except requests.RequestException as exc:
            logging.warning(
                "Download error (attempt %s) %s: %s",
                attempt + 1,
                pub.download_url,
                exc,
            )
        time.sleep(RETRY_DELAY)

    return pub, "Failed after retries", False


def download_all(publications: List[Publication], base_dir: Path, workers: int) -> List[dict]:
    """Download all publications concurrently; return result rows."""
    results: List[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        session = requests.Session()
        futures = {
            executor.submit(download_one, session, pub, base_dir): pub
            for pub in publications
            if pub.download_url
        }
        for future in as_completed(futures):
            pub, message, success = future.result()
            results.append(
                {
                    "title": pub.title,
                    "series": pub.series,
                    "number": pub.number,
                    "detail_url": pub.detail_url,
                    "download_url": pub.download_url or "",
                    "message": message,
                    "success": success,
                    "path": str(
                        base_dir
                        / pub.series
                        / sanitize_filename(
                            Path(urlparse(pub.download_url or "").path).name
                        )
                    )
                    if success
                    else "",
                }
            )
    return results


def write_download_report(results: List[dict], path: Path) -> None:
    """Write CSV report for download attempts."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "title",
                "series",
                "number",
                "detail_url",
                "download_url",
                "message",
                "success",
                "path",
            ],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    logging.info("Wrote download report: %s", path)


def configure_logging(verbose: bool) -> None:
    """Setup console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl NIST draft publications and download available PDFs."
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Limit listing pages to crawl (default: crawl until empty).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only build manifest; do not download files.",
    )
    parser.add_argument(
        "--detail-workers",
        type=int,
        default=DETAIL_WORKERS,
        help="Concurrent workers for fetching detail pages.",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=DOWNLOAD_WORKERS,
        help="Concurrent workers for downloading PDFs.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_logging(args.verbose)

    output_dir: Path = OUTPUT_ROOT
    reports_dir = REPORTS_ROOT
    downloads_dir = output_dir

    logging.info("Output directory: %s", output_dir)

    session = requests.Session()

    detail_urls = crawl_listings(session, args.max_pages)
    if not detail_urls:
        logging.error("No publication detail URLs found; exiting.")
        sys.exit(1)

    publications = fetch_details(session, detail_urls, args.detail_workers)
    manifest_path = reports_dir / "draft-manifest.csv"
    write_manifest(publications, manifest_path)

    if args.skip_download:
        logging.info("Skip download requested; stopping after manifest.")
        return

    available = [p for p in publications if p.download_url]
    logging.info("Starting downloads for %s publications.", len(available))
    results = download_all(available, downloads_dir, args.download_workers)
    report_path = reports_dir / "draft-download-results.csv"
    write_download_report(results, report_path)

    successes = sum(1 for r in results if r["success"])
    logging.info("Downloads complete. Success: %s / %s", successes, len(results))


if __name__ == "__main__":
    main()
