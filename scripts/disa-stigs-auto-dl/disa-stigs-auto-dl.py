#!/usr/bin/env python3
"""Download DISA STIG library ZIPs from cyber.mil/stigs/downloads."""

from __future__ import annotations

import argparse
import csv
import logging
import calendar
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

TARGET_URL = "https://www.cyber.mil/stigs/downloads"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
ALLOWED_EXTENSIONS = {".zip"}
REQUEST_TIMEOUT = 60
REQUEST_RETRIES = 3
RETRY_DELAY = 3
RATE_LIMIT_DELAY = 0.3
SCRIPT_DIR = Path(__file__).resolve().parent
DOWNLOAD_ROOT = SCRIPT_DIR / "downloads"
REPORTS_ROOT = SCRIPT_DIR / "reports"
LIBRARY_BASE = "https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/"


@dataclass
class Resource:
    title: str
    class_type: str
    download_url: str
    status: str
    note: str = ""


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def probe_library_url(months_back: int = 24) -> str | None:
    """Probe recent months for the SRG-STIG library ZIP."""
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT}
    year = time.gmtime().tm_year
    month = time.gmtime().tm_mon
    for _ in range(months_back):
        month_name = calendar.month_name[month]
        candidate = f"{LIBRARY_BASE}U_SRG-STIG_Library_{month_name}_{year}.zip"
        try:
            resp = session.head(candidate, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                return candidate
        except requests.RequestException:
            pass
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return None


def write_manifest(resources: List[Resource], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["title", "class_type", "download_url", "status", "note"])
        for res in resources:
            writer.writerow([res.title, res.class_type, res.download_url, res.status, res.note])
    logging.info("Wrote manifest: %s", manifest_path)


def download_all(resources: List[Resource], base_dir: Path) -> list[dict]:
    results: list[dict] = []
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Referer": TARGET_URL}

    def download_one(res: Resource) -> dict:
        if res.download_url == "N/A":
            return {
                "title": res.title,
                "class_type": res.class_type,
                "download_url": res.download_url,
                "message": "Skipped (no downloadable link)",
                "success": False,
                "path": "",
            }
        filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(urlparse(res.download_url).path).name) or "file.zip"
        target_path = base_dir / filename
        if target_path.exists() and target_path.stat().st_size > 0:
            return {
                "title": res.title,
                "class_type": res.class_type,
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
                            "class_type": res.class_type,
                            "download_url": res.download_url,
                            "message": "Downloaded",
                            "success": True,
                            "path": str(target_path),
                        }
                    if resp.status_code == 404:
                        return {
                            "title": res.title,
                            "class_type": res.class_type,
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
            "class_type": res.class_type,
            "download_url": res.download_url,
            "message": "Failed after retries",
            "success": False,
            "path": "",
        }

    base_dir.mkdir(parents=True, exist_ok=True)
    for res in resources:
        results.append(download_one(res))
    return results


def write_results(results: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["title", "class_type", "download_url", "message", "success", "path"],
        )
        writer.writeheader()
        for row in results:
            writer.writerow(row)
    logging.info("Wrote download report: %s", path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download DISA STIG library ZIPs."
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Only build manifest; do not download files.",
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

    library_url = probe_library_url()
    resources: List[Resource] = []
    if library_url:
        resources.append(
            Resource(
                title="U_SRG-STIG_Library",
                class_type="Unclassified",
                download_url=library_url,
                status="ready",
            )
        )
    else:
        resources.append(
            Resource(
                title="U_SRG-STIG_Library",
                class_type="Unclassified",
                download_url="N/A",
                status="skipped",
                note="Library archive not found in recent months",
            )
        )

    manifest_path = REPORTS_ROOT / "disa-stigs-manifest.csv"
    write_manifest(resources, manifest_path)

    if args.skip_download:
        logging.info("Skip download requested; stopping after manifest.")
        return

    logging.info("Starting downloads for %s resources.", len(resources))
    results = download_all(resources, DOWNLOAD_ROOT)
    results_path = REPORTS_ROOT / "disa-stigs-download-results.csv"
    write_results(results, results_path)

    successes = sum(1 for r in results if r["success"])
    logging.info("Downloads complete. Success: %s / %s", successes, len(resources))


if __name__ == "__main__":
    main()
