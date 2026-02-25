"""DISA STIGs library downloader — probes for the current monthly ZIP."""

from __future__ import annotations

import calendar
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse

import requests

if TYPE_CHECKING:
    from comply_with_me.state import StateFile

from .base import (
    REQUEST_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    USER_AGENT,
    DownloadResult,
    sanitize_filename,
)

LIBRARY_BASE = "https://dl.dod.cyber.mil/wp-content/uploads/stigs/zip/"
REFERER = "https://www.cyber.mil/stigs/downloads"
PROBE_MONTHS_BACK = 24


def _probe_url() -> str | None:
    """Probe recent month/year combinations to find the current library ZIP."""
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT}
    now = time.gmtime()
    year, month = now.tm_year, now.tm_mon

    for _ in range(PROBE_MONTHS_BACK):
        month_name = calendar.month_name[month]
        candidate = f"{LIBRARY_BASE}U_SRG-STIG_Library_{month_name}_{year}.zip"
        try:
            resp = session.head(
                candidate, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True
            )
            if resp.status_code == 200:
                return candidate
        except requests.RequestException:
            pass
        month -= 1
        if month == 0:
            month = 12
            year -= 1

    return None


def _download_zip(
    url: str,
    dest: Path,
    force: bool,
    state: Optional["StateFile"] = None,
) -> tuple[bool, str]:
    """Stream-download the STIG library ZIP to dest."""
    if not force:
        if state is not None:
            if state.needs_adopt(dest):
                state.adopt(dest, url)
            if state.is_fresh(dest, url):
                return True, "skipped"
        elif dest.exists() and dest.stat().st_size > 0:
            return True, "skipped"

    dest.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT, "Referer": REFERER}

    for attempt in range(REQUEST_RETRIES):
        try:
            with session.get(url, headers=headers, timeout=300, stream=True) as resp:
                if resp.status_code == 200:
                    with dest.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                fh.write(chunk)
                    if dest.stat().st_size == 0:
                        dest.unlink(missing_ok=True)
                        raise OSError("Empty file after download")
                    if state is not None:
                        state.record(dest, url)
                    return True, "downloaded"
                if resp.status_code == 404:
                    return False, "not found (404)"
        except requests.RequestException as exc:
            if attempt < REQUEST_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return False, f"failed: {exc}"

    return False, "failed after retries"


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    result = DownloadResult(framework="disa")
    dest = output_dir / "disa-stigs"

    url = _probe_url()
    if not url:
        result.errors.append((
            "U_SRG-STIG_Library.zip",
            f"Archive not found within {PROBE_MONTHS_BACK} months — "
            "check LIBRARY_BASE URL or probe window in disa.py",
        ))
        return result

    filename = sanitize_filename(re.sub(r"[^a-zA-Z0-9._-]", "_", urlparse(url).path.split("/")[-1]))
    target = dest / filename

    if dry_run:
        if not force and target.exists() and target.stat().st_size > 0:
            result.skipped.append(filename)
        else:
            result.downloaded.append(filename)
        return result

    ok, msg = _download_zip(url, target, force, state)
    if msg == "skipped":
        result.skipped.append(filename)
    elif ok:
        result.downloaded.append(filename)
    else:
        result.errors.append((filename, msg))

    return result
