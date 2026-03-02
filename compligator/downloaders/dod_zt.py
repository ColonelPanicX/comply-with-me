"""DoD Zero Trust and Cybersecurity Directives downloader.

Downloads the DoD Zero Trust Strategy from a publicly accessible DTIC mirror.
The remaining documents (ZT Reference Architecture, DoDI 8500.01, DoDI 8510.01)
are listed as manual_required — dodcio.defense.gov and esd.whs.mil return 403
for all automated requests including headless browsers; no working public mirror
has been identified.

Manual download sources:
  - ZT RA v2.0:   https://dodcio.defense.gov/Library/
  - DoDI 8500.01: https://www.esd.whs.mil/Directives/issuances/dodi/
  - DoDI 8510.01: https://www.esd.whs.mil/Directives/issuances/dodi/
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

# (filename, url) — documents that can be fetched automatically.
# DoD ZT Strategy is mirrored on DTIC (Defense Technical Information Center),
# which serves files publicly without WAF restrictions.
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "DoD-ZT-Strategy.pdf",
        "https://apps.dtic.mil/sti/trecms/pdf/AD1205814.pdf",
    ),
]

# Documents that require manual download — (filename, source_url).
MANUAL_DOCS: list[tuple[str, str]] = [
    (
        "DoD-ZT-RA-v2.0.pdf",
        "https://dodcio.defense.gov/Library/",
    ),
    (
        "DoDI-8500.01.pdf",
        "https://www.esd.whs.mil/Directives/issuances/dodi/",
    ),
    (
        "DoDI-8510.01.pdf",
        "https://www.esd.whs.mil/Directives/issuances/dodi/",
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

    # Always surface the manual-required items regardless of dry_run.
    for filename, source in MANUAL_DOCS:
        result.manual_required.append((filename, source))

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
