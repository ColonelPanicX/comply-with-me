"""OWASP Application Security Verification Standard (ASVS) downloader.

Downloads release assets (PDF, CSV, DOCX) for the latest stable ASVS
release from the OWASP/ASVS GitHub repository.

The GitHub Releases API is used to discover the current version and its
assets. Set the GITHUB_TOKEN environment variable to raise the
unauthenticated rate limit from 60 to 5,000 requests/hour if needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    DownloadResult,
    download_file,
)

SOURCE_URL = "https://github.com/OWASP/ASVS"
RELEASES_API_URL = "https://api.github.com/repos/OWASP/ASVS/releases/latest"

# File extensions to download from the release assets.
DOWNLOAD_EXTENSIONS = {".pdf", ".csv", ".docx"}

# Date the KNOWN_DOCS list was last manually verified against the latest release.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# Curated fallback — used if the GitHub API is unavailable.
# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "OWASP_Application_Security_Verification_Standard_5.0.0_en.pdf",
        "https://github.com/OWASP/ASVS/releases/download/v5.0.0/OWASP_Application_Security_Verification_Standard_5.0.0_en.pdf",
    ),
]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_latest_assets() -> list[tuple[str, str]]:
    """Return (filename, download_url) for all matching release assets.

    Raises RuntimeError on API errors.
    """
    try:
        resp = requests.get(RELEASES_API_URL, headers=_api_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"GitHub API request failed: {exc}") from exc

    if resp.status_code == 403:
        raise RuntimeError(
            "GitHub API rate-limited. "
            "Set GITHUB_TOKEN env var to increase the unauthenticated limit."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API returned {resp.status_code} for OWASP/ASVS releases")

    data = resp.json()
    return [
        (asset["name"], asset["browser_download_url"])
        for asset in data.get("assets", [])
        if Path(asset["name"]).suffix.lower() in DOWNLOAD_EXTENSIONS
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "owasp-asvs"
    result = DownloadResult(framework="owasp-asvs")

    # Discover assets via GitHub API, fall back to KNOWN_DOCS on failure.
    docs: list[tuple[str, str]]
    used_known = False
    try:
        docs = _fetch_latest_assets()
        if not docs:
            raise RuntimeError("No matching release assets found")
    except RuntimeError as exc:
        result.notices.append(
            f"GitHub API unavailable ({exc}) — using curated fallback list "
            f"(last verified {KNOWN_DOCS_VERIFIED})."
        )
        docs = KNOWN_DOCS
        used_known = True

    if dry_run:
        for filename, _url in docs:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for filename, url in docs:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            if used_known:
                result.errors.append((filename, msg))
            else:
                # API asset URL failed — surface as error with the URL for reference.
                result.errors.append((filename, f"{msg} ({url})"))

    return result
