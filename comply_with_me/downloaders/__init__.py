"""Downloader registry — maps CLI framework keys to runner functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import cmmc, disa, fedramp, nist
from .base import DownloadResult


@dataclass(frozen=True)
class ServiceDef:
    key: str
    label: str
    runner: Callable[[Path, bool, bool], DownloadResult]


SERVICES: list[ServiceDef] = [
    ServiceDef("fedramp", "FedRAMP", fedramp.run),
    ServiceDef("nist-finals", "NIST Final Publications", nist.run_finals),
    ServiceDef("nist-drafts", "NIST Draft Publications", nist.run_drafts),
    ServiceDef("cmmc", "CMMC", cmmc.run),
    ServiceDef("disa", "DISA STIGs", disa.run),
]

SERVICES_BY_KEY: dict[str, ServiceDef] = {s.key: s for s in SERVICES}
