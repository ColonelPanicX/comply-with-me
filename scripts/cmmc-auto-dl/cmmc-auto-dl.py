#!/usr/bin/env python3
"""Crawl the CMMC Resources page and download linked documents."""

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
from typing import List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# Configuration
BASE_URL = "https://dodcio.defense.gov/cmmc/Resources-Documentation/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx"}
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
RETRY_DELAY = 2
DOWNLOAD_WORKERS = 4
RATE_LIMIT_DELAY = 0.25
SCRIPT_DIR = Path(__file__).resolve().parent
DOWNLOAD_ROOT = SCRIPT_DIR / "downloads"
REPORTS_ROOT = SCRIPT_DIR / "reports"
SECTION_MODULES = {
    "internal": "dnn_ctr136430_ModuleContent",
    "external": "dnn_ctr136428_ModuleContent",
}


@dataclass
class Resource:
    """Metadata for a single CMMC resource link."""

    section: str
    title: str
    href: str
    download_url: str
    status: str
    note: str = ""


def configure_logging(verbose: bool) -> None:
    """Configure console logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def fetch_page_html() -> str:
    """Load the CMMC resources page with a headless browser and return HTML."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(BASE_URL, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe filename component."""
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return safe.strip("_") or "file"


def parse_resources(html: str) -> List[Resource]:
    """Extract resources grouped by section, marking non-downloadables."""
    soup = BeautifulSoup(html, "html.parser")
    resources: List[Resource] = []
    for section, module_id in SECTION_MODULES.items():
        container = soup.find(id=module_id)
        if not container:
            logging.warning("Missing container for section %s (%s)", section, module_id)
            continue
        seen: Set[str] = set()
        for anchor in container.find_all("a", href=True):
            raw_href = anchor["href"].strip()
            if not raw_href:
                continue
            abs_href = urljoin(BASE_URL, raw_href)
            if abs_href in seen:
                continue
            seen.add(abs_href)

            title = anchor.get_text(strip=True) or Path(urlparse(abs_href).path).name
            ext = Path(urlparse(abs_href).path).suffix.lower()
            downloadable = ext in ALLOWED_EXTENSIONS
            download_url = abs_href if downloadable else "N/A"
            status = "ready" if downloadable else "skipped"
            note = "" if downloadable else f"Unsupported extension: {ext or 'none'}"

            resources.append(
                Resource(
                    section=section,
                    title=title,
                    href=abs_href,
                    download_url=download_url,
                    status=status,
                    note=note,
                )
            )
    return resources


def write_manifest(resources: List[Resource], path: Path) -> None:
    """Write the manifest CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["section", "title", "href", "download_url", "status", "note"]
        )
        for res in resources:
            writer.writerow(
                [res.section, res.title, res.href, res.download_url, res.status, res.note]
            )
    logging.info("Wrote manifest: %s", path)


def download_one(session: requests.Session, res: Resource, base_dir: Path) -> dict:
    """Download a single resource if it has a valid download URL."""
    if res.download_url == "N/A":
        return {
            "section": res.section,
            "title": res.title,
            "href": res.href,
            "download_url": res.download_url,
            "message": "Skipped (no downloadable link)",
            "success": False,
            "path": "",
        }

    filename = sanitize_filename(Path(urlparse(res.download_url).path).name)
    target_dir = base_dir / res.section
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    if target_path.exists() and target_path.stat().st_size > 0:
        return {
            "section": res.section,
            "title": res.title,
            "href": res.href,
            "download_url": res.download_url,
            "message": "Already exists",
            "success": True,
            "path": str(target_path),
        }

    time.sleep(RATE_LIMIT_DELAY)
    for attempt in range(REQUEST_RETRIES):
        try:
            with session.get(
                res.download_url,
                headers={"User-Agent": USER_AGENT},
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
                    return {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": "Downloaded",
                        "success": True,
                        "path": str(target_path),
                    }
                if resp.status_code == 404:
                    return {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": "Not found (404)",
                        "success": False,
                        "path": "",
                    }
        except requests.RequestException as exc:
            logging.warning(
                "Download error (attempt %s) %s: %s",
                attempt + 1,
                res.download_url,
                exc,
            )
        time.sleep(RETRY_DELAY)

    return {
        "section": res.section,
        "title": res.title,
        "href": res.href,
        "download_url": res.download_url,
        "message": "Failed after retries",
        "success": False,
        "path": "",
    }


def download_all(resources: List[Resource], base_dir: Path, workers: int) -> List[dict]:
    """Download all resources with concurrency."""
    results: List[dict] = []
    session = requests.Session()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_one, session, res, base_dir): res
            for res in resources
            if res.download_url != "N/A"
        }
        for future in as_completed(futures):
            results.append(future.result())
    # Add skipped entries for completeness.
    for res in resources:
        if res.download_url == "N/A":
            results.append(
                {
                    "section": res.section,
                    "title": res.title,
                    "href": res.href,
                    "download_url": res.download_url,
                    "message": "Skipped (no downloadable link)",
                    "success": False,
                    "path": "",
                }
            )
    return results


def playwright_download_all(resources: List[Resource], base_dir: Path) -> List[dict]:
    """Download resources using Playwright page context with download capture."""
    results: List[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.goto(BASE_URL, wait_until="networkidle")

        for res in resources:
            if res.download_url == "N/A":
                results.append(
                    {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": "Skipped (no downloadable link)",
                        "success": False,
                        "path": "",
                    }
                )
                continue

            filename = sanitize_filename(
                Path(urlparse(res.download_url).path).name
            )
            target_dir = base_dir / res.section
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / filename

            if target_path.exists() and target_path.stat().st_size > 0:
                results.append(
                    {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": "Already exists",
                        "success": True,
                        "path": str(target_path),
                    }
                )
                continue

            try:
                time.sleep(RATE_LIMIT_DELAY)
                locator = page.locator(f"a[href='{res.download_url}']")
                if locator.count() == 0:
                    results.append(
                        {
                            "section": res.section,
                            "title": res.title,
                            "href": res.href,
                            "download_url": res.download_url,
                            "message": "Link not found on page",
                            "success": False,
                            "path": "",
                        }
                    )
                    continue

                with page.expect_download(timeout=REQUEST_TIMEOUT * 1000) as download_info:
                    locator.first.click()
                download = download_info.value
                download.save_as(str(target_path))
                if target_path.stat().st_size == 0:
                    target_path.unlink(missing_ok=True)
                    raise IOError("Empty file after download")
                results.append(
                    {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": "Downloaded",
                        "success": True,
                        "path": str(target_path),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "section": res.section,
                        "title": res.title,
                        "href": res.href,
                        "download_url": res.download_url,
                        "message": f"Error: {exc}",
                        "success": False,
                        "path": "",
                    }
                )
        browser.close()
    return results


def write_results(results: List[dict], path: Path) -> None:
    """Write download results CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "section",
                "title",
                "href",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl CMMC Resources and download linked documents."
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only build manifest; do not download files.",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=DOWNLOAD_WORKERS,
        help="Concurrent workers for downloads.",
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

    logging.info("Output directory: %s", DOWNLOAD_ROOT)

    html = fetch_page_html()
    resources = parse_resources(html)
    if not resources:
        logging.error("No resources discovered; exiting.")
        sys.exit(1)

    manifest_path = REPORTS_ROOT / "cmmc-manifest.csv"
    write_manifest(resources, manifest_path)

    if args.skip_download:
        logging.info("Skip download requested; stopping after manifest.")
        return

    logging.info("Starting downloads for %s resources (via Playwright context).", len(resources))
    results = playwright_download_all(resources, DOWNLOAD_ROOT)
    results_path = REPORTS_ROOT / "cmmc-download-results.csv"
    write_results(results, results_path)

    successes = sum(1 for r in results if r["success"])
    logging.info("Downloads complete. Success: %s / %s", successes, len(resources))


if __name__ == "__main__":
    main()
