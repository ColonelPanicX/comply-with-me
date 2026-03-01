"""CJIS Security Policy downloader.

Downloads the current FBI CJIS Security Policy PDF from le.fbi.gov.
The document is publicly accessible — no law enforcement credentials
are required.

Fetch strategy:
1. Scrape the CJIS resource center page for the current policy PDF link
2. Fall back to the curated KNOWN_DOCS list if the page is unreachable
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional
from urllib.parse import urljoin, urlparse

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import (
    REQUEST_TIMEOUT,
    USER_AGENT,
    DownloadResult,
    download_file,
    sanitize_filename,
)

SOURCE_URL = "https://le.fbi.gov/cjis/cjis-security-policy-resource-center"
BASE_URL = "https://le.fbi.gov"

# Pattern that matches CJIS Security Policy PDF filenames on le.fbi.gov.
_POLICY_PDF_RE = re.compile(r"cjis_security_policy", re.IGNORECASE)

# Date the KNOWN_DOCS list was last manually verified.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "CJIS-Security-Policy-v6.0.pdf",
        "https://le.fbi.gov/file-repository/cjis_security_policy_v6-0_20241227.pdf",
    ),
]


# ---------------------------------------------------------------------------
# Resource center scraping
# ---------------------------------------------------------------------------


def _scrape_resource_center() -> Optional[list[tuple[str, str]]]:
    """Scrape the CJIS resource center for policy PDF links.

    Returns a list of (filename, url) pairs, or None on failure.
    """
    try:
        resp = requests.get(
            SOURCE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
    except requests.RequestException:
        return None

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    seen: set[str] = set()
    links: list[tuple[str, str]] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href.lower().endswith(".pdf"):
            continue
        if not _POLICY_PDF_RE.search(href):
            continue
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        raw_name = Path(urlparse(full_url).path).name
        filename = sanitize_filename(raw_name)
        links.append((filename, full_url))

    return links if links else None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cjis"
    result = DownloadResult(framework="cjis")

    docs = _scrape_resource_center()
    used_known = docs is None
    if docs is None:
        docs = KNOWN_DOCS

    if dry_run:
        for filename, _url in docs:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        if used_known:
            result.notices.append(
                f"CJIS resource center unreachable — used curated fallback list "
                f"(last verified {KNOWN_DOCS_VERIFIED})."
            )
        return result

    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for filename, url in docs:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, referer=SOURCE_URL, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            result.errors.append((filename, msg))

    if used_known:
        result.notices.append(
            f"CJIS resource center unreachable — used curated fallback list "
            f"(last verified {KNOWN_DOCS_VERIFIED})."
        )

    return result
