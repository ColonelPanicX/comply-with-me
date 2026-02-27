"""NIST OSCAL content downloader.

Downloads structured OSCAL artifacts from the usnistgov/oscal-content GitHub
repository. Covers SP 800-53 Rev 5, SP 800-171 Rev 3, SP 800-218 Ver 1, and
CSF v2.0 — all in OSCAL JSON format (non-minified).

The GitHub API is used to discover file listings; actual downloads come from
raw.githubusercontent.com and are not subject to API rate limits. Set the
GITHUB_TOKEN environment variable to increase the API rate limit from 60 to
5,000 requests/hour if needed (unlikely given the small number of API calls).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from cwm.state import StateFile

from .base import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    DownloadResult,
    download_file,
)

SOURCE_URL = "https://github.com/usnistgov/oscal-content"
REPO_API_BASE = "https://api.github.com/repos/usnistgov/oscal-content/contents/nist.gov"

# (GitHub API path relative to REPO_API_BASE, local subdir under dest)
CONTENT_SETS: list[tuple[str, str]] = [
    ("SP800-53/rev5/json",  "SP800-53/rev5"),
    ("SP800-171/rev3/json", "SP800-171/rev3"),
    ("SP800-218/ver1/json", "SP800-218/ver1"),
    ("CSF/v2.0/json",       "CSF/v2.0"),
]


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _api_headers() -> dict[str, str]:
    """Build request headers, including a GitHub token if set in the environment."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _list_json_files(api_path: str) -> list[tuple[str, str]]:
    """Return (filename, download_url) for non-minified JSON files in an OSCAL content dir.

    Raises RuntimeError on API errors (rate limit, network failure).
    """
    url = f"{REPO_API_BASE}/{api_path}"
    try:
        resp = requests.get(url, headers=_api_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise RuntimeError(f"GitHub API request failed for {api_path}: {exc}") from exc

    if resp.status_code == 403:
        raise RuntimeError(
            f"GitHub API rate-limited ({api_path}). "
            "Set GITHUB_TOKEN env var to increase the unauthenticated limit."
        )
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub API returned {resp.status_code} for {api_path}")

    return [
        (item["name"], item["download_url"])
        for item in resp.json()
        if item["type"] == "file"
        and item["name"].endswith(".json")
        and not item["name"].endswith("-min.json")
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
    dest = output_dir / "nist-oscal"
    result = DownloadResult(framework="nist-oscal")

    # Discover all files via GitHub API
    all_links: list[tuple[str, str, str]] = []  # (filename, url, subdir)
    for api_path, subdir in CONTENT_SETS:
        try:
            for filename, url in _list_json_files(api_path):
                all_links.append((filename, url, subdir))
        except RuntimeError as exc:
            result.errors.append(("", str(exc)))

    if not all_links:
        return result

    if dry_run:
        for filename, _url, subdir in all_links:
            target = dest / subdir / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for filename, url, subdir in all_links:
        target = dest / subdir / filename
        ok, msg = download_file(session, url, target, force=force, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            result.errors.append((filename, msg))

    return result
