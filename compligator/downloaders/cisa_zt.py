"""CISA Zero Trust Maturity Model downloader.

Downloads the CISA Zero Trust Maturity Model (ZTMM) and related ZT
implementation guidance directly from cisa.gov. All documents are
publicly accessible with no authentication required.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

import requests

if TYPE_CHECKING:
    from compligator.state import StateFile

from .base import DownloadResult, download_file

SOURCE_URL = "https://www.cisa.gov/zero-trust-maturity-model"

# Date these URLs were last manually verified.
KNOWN_DOCS_VERIFIED = "2026-03-01"

# (filename, url)
KNOWN_DOCS: list[tuple[str, str]] = [
    (
        "CISA-ZTMM-v2.0.pdf",
        "https://www.cisa.gov/sites/default/files/2023-04/zero_trust_maturity_model_v2_508.pdf",
    ),
]


def run(
    output_dir: Path,
    dry_run: bool = False,
    force: bool = False,
    state: Optional["StateFile"] = None,
) -> DownloadResult:
    dest = output_dir / "cisa-zt"
    result = DownloadResult(framework="cisa-zt")

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
