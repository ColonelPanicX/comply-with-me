"""Downloader registry — maps CLI framework keys to runner functions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from . import cmmc, disa, fedramp, nist
from .base import DownloadResult

if TYPE_CHECKING:
    from comply_with_me.state import StateFile


@dataclass(frozen=True)
class ServiceDef:
    key: str
    label: str
    runner: Callable[[Path, bool, bool, Optional["StateFile"]], DownloadResult]


SERVICES: list[ServiceDef] = [
    ServiceDef("fedramp", "FedRAMP", fedramp.run),
    ServiceDef("nist-finals", "NIST Final Publications", nist.run_finals),
    ServiceDef("nist-drafts", "NIST Draft Publications", nist.run_drafts),
    ServiceDef("cmmc", "CMMC", cmmc.run),
    ServiceDef("disa", "DISA STIGs", disa.run),
]

SERVICES_BY_KEY: dict[str, ServiceDef] = {s.key: s for s in SERVICES}
