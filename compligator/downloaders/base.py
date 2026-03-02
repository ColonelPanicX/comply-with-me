"""Shared types and utilities for all downloaders."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

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
    notices: list[str] = field(default_factory=list)

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


def playwright_download_file(
    url: str,
    dest: Path,
    *,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> tuple[bool, str]:
    """Download a URL that the server serves as a browser attachment (not inline).

    Some government sites (CISA, FBI) respond to plain HTTP requests with 403 but
    serve the file correctly when a real browser navigates to it — the response
    includes Content-Disposition: attachment, which triggers a browser download
    rather than inline rendering. Playwright's accept_downloads mode catches that
    event and saves the file.

    Returns (success, message) with the same semantics as download_file().
    """
    if not force:
        if state is not None:
            if state.needs_adopt(dest):
                state.adopt(dest, url)
            if state.is_fresh(dest, url):
                return True, "skipped"
        elif dest.exists() and dest.stat().st_size > 0:
            return True, "skipped"

    require_playwright()
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(user_agent=USER_AGENT, accept_downloads=True)
            page = ctx.new_page()
            with page.expect_download(timeout=60_000) as dl_info:
                try:
                    page.goto(url, timeout=10_000)
                except Exception:
                    pass  # Navigation "fails" because the server triggers a download — expected
            dl = dl_info.value
            dest.parent.mkdir(parents=True, exist_ok=True)
            dl.save_as(str(dest))
            browser.close()

        if not dest.exists() or dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            return False, "downloaded file was empty"

        if state is not None:
            state.record(dest, url)
        return True, "downloaded"

    except Exception as exc:  # noqa: BLE001
        return False, f"playwright download failed: {exc}"
