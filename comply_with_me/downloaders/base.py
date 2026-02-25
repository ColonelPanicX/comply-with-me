"""Shared types and utilities for all downloaders."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from comply_with_me.state import StateFile

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120
REQUEST_RETRIES = 3
RETRY_DELAY = 2.0
RATE_LIMIT_DELAY = 0.25


@dataclass
class DownloadResult:
    framework: str
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    manual_required: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.downloaded) + len(self.skipped) + len(self.errors)


def sanitize_filename(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", name)
    return safe.strip("_") or "file"


def download_file(
    session: requests.Session,
    url: str,
    dest: Path,
    *,
    force: bool = False,
    referer: Optional[str] = None,
    state: Optional["StateFile"] = None,
) -> tuple[bool, str]:
    """Download url to dest. Returns (success, message)."""
    if not force:
        if state is not None:
            if state.needs_adopt(dest):
                state.adopt(dest, url)
            if state.is_fresh(dest, url):
                return True, "skipped"
        elif dest.exists() and dest.stat().st_size > 0:
            return True, "skipped"

    headers: dict[str, str] = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer

    dest.parent.mkdir(parents=True, exist_ok=True)
    time.sleep(RATE_LIMIT_DELAY)

    for attempt in range(REQUEST_RETRIES):
        try:
            with session.get(url, headers=headers, timeout=DOWNLOAD_TIMEOUT, stream=True) as resp:
                if resp.status_code == 200:
                    with dest.open("wb") as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
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
                return False, f"failed after {REQUEST_RETRIES} attempts: {exc}"

    return False, "failed after retries"


def require_playwright() -> None:
    """Raise a clear error if Playwright is not installed."""
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Playwright is required but not installed.\n"
            "Run: pip install playwright && playwright install chromium"
        ) from exc
