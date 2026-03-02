"""OMB Cybersecurity Memoranda downloader.

Downloads key OMB cybersecurity and IT management memoranda directly
from whitehouse.gov. All documents are public-domain federal records
with no authentication required.

The curated list covers memos with direct, ongoing relevance to federal
IT security, zero trust, and compliance reporting obligations.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import DownloadResult, download_file

SOURCE_URL = "https://www.whitehouse.gov/omb/information-resources/guidance/memoranda/"

# Date these URLs were last manually verified against the OMB memo index.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# (filename, url)
# Filenames use the memo identifier for predictability.
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "M-21-31.pdf",
        "https://www.whitehouse.gov/wp-content/uploads/2021/08/M-21-31-Improving-the-Federal-Governments-Investigative-and-Remediation-Capabilities-Related-to-Cybersecurity-Incidents.pdf",
    ),
    (
        "M-22-09.pdf",
        "https://www.whitehouse.gov/wp-content/uploads/2022/01/M-22-09.pdf",
    ),
    # M-23-16 omitted — URL not found on whitehouse.gov; add when verified.
    (
        "M-25-04.pdf",
        "https://www.whitehouse.gov/wp-content/uploads/2025/01/M-25-04-Fiscal-Year-2025-Guidance-on-Federal-Information-Security-and-Privacy-Management-Requirements.pdf",
    ),
]


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "omb"
    result = DownloadResult(framework="omb")

    if dry_run:
        for filename, _url in KNOWN_DOCS:
            target = dest / filename
            if not force and target.exists() and target.stat().st_size > 0:
                result.skipped.append(filename)
            else:
                result.downloaded.append(filename)
        return result

    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for filename, url in KNOWN_DOCS:
        target = dest / filename
        ok, msg = download_file(session, url, target, force=force, state=state)
        if msg == "skipped":
            result.skipped.append(filename)
        elif ok:
            result.downloaded.append(filename)
        else:
            result.errors.append((filename, msg))

    return result
