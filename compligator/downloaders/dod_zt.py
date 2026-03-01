"""DoD Zero Trust and Cybersecurity Directives downloader.

Downloads the DoD Zero Trust Strategy, Zero Trust Reference Architecture,
and key DoD cybersecurity issuances (DoDI 8500.01, DoDI 8510.01) directly
from dodcio.defense.gov and esd.whs.mil. All documents are cleared for
public release with no authentication required.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import DownloadResult, download_file

SOURCE_URL = "https://dodcio.defense.gov/Library/"

# Date these URLs were last manually verified.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    # DoD Zero Trust Strategy (November 2022)
    (
        "DoD-ZT-Strategy.pdf",
        "https://dodcio.defense.gov/Portals/0/Documents/Library/DoD-ZTStrategy.pdf",
    ),
    # DoD Zero Trust Reference Architecture v2.0 (September 2022)
    (
        "DoD-ZT-RA-v2.0.pdf",
        "https://dodcio.defense.gov/Portals/0/Documents/Library/(U)ZT_RA_v2.0(U)_Sep22.pdf",
    ),
    # DoDI 8500.01 — Cybersecurity (March 2014, Change 1)
    (
        "DoDI-8500.01.pdf",
        "https://www.esd.whs.mil/portals/54/documents/dd/issuances/dodi/850001_2014.pdf",
    ),
    # DoDI 8510.01 — Risk Management Framework (RMF) for DoD Systems
    (
        "DoDI-8510.01.pdf",
        "https://www.esd.whs.mil/Portals/54/Documents/DD/issuances/dodi/851001p.pdf",
    ),
]


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "dod-zt"
    result = DownloadResult(framework="dod-zt")

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
