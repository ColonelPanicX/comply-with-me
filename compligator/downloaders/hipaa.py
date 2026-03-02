"""HIPAA Security Rule downloader.

Downloads the HIPAA Security Rule as originally published in the Federal
Register (68 Fed. Reg. 8333, 2003-02-20) from govinfo.gov, the official
U.S. government online bookstore and authoritative public record source.

The HHS.gov guidance pages that previously hosted this content return 403
for automated requests (site redesign — paths are stale). The govinfo.gov
version is the authoritative source for the rule as enacted.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import DownloadResult, download_file

SOURCE_URL = "https://www.govinfo.gov/content/pkg/FR-2003-02-20/pdf/03-3877.pdf"

# Date these URLs were last manually verified.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "hipaa-security-rule-fr-2003-02-20.pdf",
        "https://www.govinfo.gov/content/pkg/FR-2003-02-20/pdf/03-3877.pdf",
    ),
]


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "hipaa"
    result = DownloadResult(framework="hipaa")

    result.notices.append(
        "HIPAA source is the Federal Register original rule (govinfo.gov). "
        "The HHS.gov guidance pages return 403 for automated requests."
    )

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
