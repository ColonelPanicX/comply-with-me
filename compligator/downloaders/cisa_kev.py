"""CISA Known Exploited Vulnerabilities (KEV) downloader.

Downloads the CISA KEV catalog directly from cisa.gov. Both the JSON
feed and the CSV export are fetched. These files are small and updated
continuously — a natural candidate for quick-scan mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import DownloadResult, download_file

SOURCE_URL = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"

# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "known_exploited_vulnerabilities.json",
        "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
    ),
    (
        "known_exploited_vulnerabilities.csv",
        "https://www.cisa.gov/sites/default/files/csv/known_exploited_vulnerabilities.csv",
    ),
]


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cisa-kev"
    result = DownloadResult(framework="cisa-kev")

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
