"""Downloader registry — maps CLI framework keys to runner functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from . import (
    cisa_bod,
    cisa_kev,
    cisa_zt,
    cjis,
    cmmc,
    disa,
    dod_zt,
    fedramp,
    fedramp_github,
    hipaa,
    nist,
    nist_oscal,
    omb,
    owasp_asvs,
)
from .base import DownloadResult

if TYPE_CHECKING:
    from compligator.state import StateFile


@dataclass(frozen=True)
class ServiceDef:
    key: str
    label: str
    runner: Callable[[Path, bool, bool, Optional["StateFile"]], DownloadResult]
    subdir: str  # path prefix under output_dir used by this downloader


SERVICES: list[ServiceDef] = [
    ServiceDef("fedramp", "FedRAMP", fedramp.run, "fedramp"),
    ServiceDef(
        "fedramp-github", "FedRAMP Automation (GitHub)", fedramp_github.run, "fedramp-github"
    ),
    ServiceDef("nist-finals", "NIST Final Publications", nist.run_finals, "nist/final-pubs"),
    ServiceDef("nist-drafts", "NIST Draft Publications", nist.run_drafts, "nist/draft-pubs"),
    ServiceDef("nist-oscal", "NIST OSCAL Content", nist_oscal.run, "nist-oscal"),
    ServiceDef("cmmc", "CMMC", cmmc.run, "cmmc"),
    ServiceDef("disa", "DISA STIGs", disa.run, "disa-stigs"),
    ServiceDef("cisa-bod", "CISA Binding Operational Directives", cisa_bod.run, "cisa-bod"),
    ServiceDef("cisa-zt", "CISA Zero Trust Maturity Model", cisa_zt.run, "cisa-zt"),
    ServiceDef(
        "cisa-kev",
        "CISA Known Exploited Vulnerabilities",
        cisa_kev.run,
        "cisa-kev",
    ),
    ServiceDef("hipaa", "HIPAA Security Rule", hipaa.run, "hipaa"),
    ServiceDef("cjis", "CJIS Security Policy", cjis.run, "cjis"),
    ServiceDef("owasp-asvs", "OWASP ASVS", owasp_asvs.run, "owasp-asvs"),
    ServiceDef("omb", "OMB Cybersecurity Memoranda", omb.run, "omb"),
    ServiceDef("dod-zt", "DoD Zero Trust & Directives", dod_zt.run, "dod-zt"),
]

SERVICES_BY_KEY: dict[str, ServiceDef] = {s.key: s for s in SERVICES}
