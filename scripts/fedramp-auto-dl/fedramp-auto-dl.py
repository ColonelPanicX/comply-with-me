#!/usr/bin/env python3
"""Download FedRAMP Rev 5 documents/templates from the public page."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://www.fedramp.gov/rev5/documents-templates/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xlsx", ".xls", ".zip"}
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
RETRY_DELAY = 2
DOWNLOAD_WORKERS = 4
RATE_LIMIT_DELAY = 0.2
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[3]
SOURCE_ROOT = REPO_ROOT / "source-content" / "fedramp"
REPORTS_ROOT = SCRIPT_DIR / "reports"


@dataclass
class Resource:
    title: str
    href: str
    download_url: str
    status: str
    note: str = ""


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def fetch_html_requests() -> Optional[str]:
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(REQUEST_RETRIES):
        try:
            resp = requests.get(TARGET_URL, headers=headers, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp.text
            logging.warning("HTTP %s from requests fetch", resp.status_code)
        except requests.RequestException as exc:
            logging.warning("requests fetch error (attempt %s): %s", attempt + 1, exc)
        time.sleep(RETRY_DELAY)
    return None


def fetch_html_playwright() -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # Defer import so --skip-download works without playwright installed
        raise RuntimeError("playwright not installed; install via `pip install playwright` and `playwright install chromium`") from exc
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        page = browser.new_page(user_agent=USER_AGENT)
        page.goto(TARGET_URL, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def fetch_page_html() -> str:
    html = fetch_html_requests()
    if html:
        return html
    logging.info("Falling back to Playwright for HTML fetch.")
    try:
        return fetch_html_playwright()
    except RuntimeError as exc:
        logging.error("Failed to fetch page: %s", exc)
        sys.exit(1)


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return safe.strip("_") or "file"


def parse_resources(html: str) -> List[Resource]:
    soup = BeautifulSoup(html, "html.parser")
    resources: List[Resource] = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href:
            continue
        abs_href = urljoin(TARGET_URL, href)
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
                title=title,
                href=abs_href,
                download_url=download_url,
                status=status,
                note=note,
            )
        )
    return resources


def target_path_for_resource(res: Resource, base_dir: Path) -> Path:
    filename = sanitize_filename(Path(urlparse(res.download_url).path).name)
    return base_dir / filename


def write_manifest(resources: List[Resource], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title", "href", "download_url", "status", "note"])
        for res in resources:
            writer.writerow([res.title, res.href, res.download_url, res.status, res.note])
    logging.info("Wrote manifest: %s", manifest_path)


def download_all(resources: List[Resource], base_dir: Path, workers: int) -> list[dict]:
    import concurrent.futures

    results: list[dict] = []
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Referer": TARGET_URL}

    def download_one(res: Resource) -> dict:
        if res.download_url == "N/A":
            return {
                "title": res.title,
                "href": res.href,
                "download_url": res.download_url,
                "message": "Skipped (no downloadable link)",
                "success": False,
                "path": "",
            }
        target_path = target_path_for_resource(res, base_dir)
        if target_path.exists() and target_path.stat().st_size > 0:
            return {
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
                    headers=headers,
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
                            "title": res.title,
                            "href": res.href,
                            "download_url": res.download_url,
                            "message": "Downloaded",
                            "success": True,
                            "path": str(target_path),
                        }
                    if resp.status_code == 404:
                        return {
                            "title": res.title,
                            "href": res.href,
                            "download_url": res.download_url,
                            "message": "Not found (404)",
                            "success": False,
                            "path": "",
                        }
            except requests.RequestException as exc:
                logging.warning("Download error (attempt %s) %s: %s", attempt + 1, res.download_url, exc)
            time.sleep(RETRY_DELAY)
        return {
            "title": res.title,
            "href": res.href,
            "download_url": res.download_url,
            "message": "Failed after retries",
            "success": False,
            "path": "",
        }

    base_dir.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(download_one, res): res for res in resources}
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
    return results


def write_results(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["title", "href", "download_url", "message", "success", "path"],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    logging.info("Wrote download report: %s", path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download FedRAMP Rev 5 documents/templates."
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

    logging.info("Output directory: %s", SOURCE_ROOT)

    html = fetch_page_html()
    resources = parse_resources(html)
    if not resources:
        logging.error("No resources found; exiting.")
        sys.exit(1)

    manifest_path = REPORTS_ROOT / "fedramp-manifest.csv"
    write_manifest(resources, manifest_path)

    if args.skip_download:
        logging.info("Skip download requested; stopping after manifest.")
        return

    downloadable = [res for res in resources if res.download_url != "N/A"]
    new_resources: List[Resource] = []
    for res in downloadable:
        target_path = target_path_for_resource(res, SOURCE_ROOT)
        if not target_path.exists() or target_path.stat().st_size == 0:
            new_resources.append(res)

    if not new_resources:
        logging.info("No new downloadable files compared to %s; nothing to download.", SOURCE_ROOT)
        return

    logging.info("Found %s new files not present in %s.", len(new_resources), SOURCE_ROOT)
    for res in new_resources:
        logging.info("New: %s -> %s", res.title, target_path_for_resource(res, SOURCE_ROOT).name)

    proceed = input("Download new files directly into source-content/fedramp? [y/N]: ").strip().lower()
    if proceed not in {"y", "yes"}:
        logging.info("Aborted by user; no downloads performed.")
        return

    SOURCE_ROOT.mkdir(parents=True, exist_ok=True)
    logging.info("Starting downloads for %s new resources.", len(new_resources))
    results = download_all(new_resources, SOURCE_ROOT, args.download_workers)
    results_path = REPORTS_ROOT / "fedramp-download-results.csv"
    write_results(results, results_path)

    successes = sum(1 for r in results if r["success"])
    logging.info("Downloads complete. Success: %s / %s", successes, len(resources))


if __name__ == "__main__":
    main()
