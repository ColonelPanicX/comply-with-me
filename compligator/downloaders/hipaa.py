"""HIPAA Security Rule downloader.

Downloads the HIPAA Security Rule and the HHS HIPAA Security Series
guidance papers directly from hhs.gov. All documents are public-domain
federal records — no authentication required.

Fetch strategy:
1. Scrape the HHS Security guidance index for PDF links
2. Fall back to the curated KNOWN_DOCS list if the page is unreachable
"""

from __future__ import annotations

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

SOURCE_URL = "https://www.hhs.gov/hipaa/for-professionals/security/guidance/index.html"
BASE_URL = "https://www.hhs.gov"

# Date the KNOWN_DOCS list was last manually verified.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# Curated fallback — the Security Rule PDF plus the seven-part Security Series.
# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "hipaa-security-rule.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/securityrulepdf.pdf",
    ),
    (
        "hipaa-security-series-1-security-101.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security1.pdf",
    ),
    (
        "hipaa-security-series-2-policies-and-procedures.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security2.pdf",
    ),
    (
        "hipaa-security-series-3-administrative-safeguards.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security3.pdf",
    ),
    (
        "hipaa-security-series-4-technical-safeguards.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security4.pdf",
    ),
    (
        "hipaa-security-series-5-organizational-requirements.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security5.pdf",
    ),
    (
        "hipaa-security-series-6-risk-analysis-and-management.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security6.pdf",
    ),
    (
        "hipaa-security-series-7-implementation-for-small-providers.pdf",
        "https://www.hhs.gov/sites/default/files/ocr/privacy/hipaa/administrative/securityrule/security7.pdf",
    ),
]


# ---------------------------------------------------------------------------
# Index scraping
# ---------------------------------------------------------------------------


def _scrape_guidance_page() -> Optional[list[tuple[str, str]]]:
    """Scrape the HHS guidance index for PDF links.

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
        full_url = urljoin(BASE_URL, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        filename = sanitize_filename(Path(urlparse(full_url).path).name)
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
    dest = output_dir / "hipaa"
    result = DownloadResult(framework="hipaa")

    docs = _scrape_guidance_page()
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
                f"HHS guidance page unreachable — used curated fallback list "
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
            f"HHS guidance page unreachable — used curated fallback list "
            f"(last verified {KNOWN_DOCS_VERIFIED})."
        )

    return result
