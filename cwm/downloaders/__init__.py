"""Downloader registry — maps CLI framework keys to runner functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from . import cisa_bod, cmmc, disa, fedramp, nist
from .base import DownloadResult

if TYPE_CHECKING:
    from cwm.state import StateFile


@dataclass(frozen=True)
class ServiceDef:
    key: str
    label: str
    runner: Callable[[Path, bool, bool, Optional["StateFile"]], DownloadResult]
    subdir: str  # path prefix under output_dir used by this downloader


SERVICES: list[ServiceDef] = [
    ServiceDef("fedramp", "FedRAMP", fedramp.run, "fedramp"),
    ServiceDef("nist-finals", "NIST Final Publications", nist.run_finals, "nist/final-pubs"),
    ServiceDef("nist-drafts", "NIST Draft Publications", nist.run_drafts, "nist/draft-pubs"),
    ServiceDef("cmmc", "CMMC", cmmc.run, "cmmc"),
    ServiceDef("disa", "DISA STIGs", disa.run, "disa-stigs"),
    ServiceDef("cisa-bod", "CISA Binding Operational Directives", cisa_bod.run, "cisa-bod"),
]

SERVICES_BY_KEY: dict[str, ServiceDef] = {s.key: s for s in SERVICES}
