"""Custom Textual messages for thread-safe worker → UI communication."""

from __future__ import annotations

from dataclasses import dataclass

from textual.message import Message

from comply_with_me.downloaders.base import DownloadResult


@dataclass
class SyncProgress(Message):
    """Posted by the sync worker when a framework sync begins."""

    key: str


@dataclass
class SyncComplete(Message):
    """Posted by the sync worker when a framework sync finishes successfully."""

    key: str
    result: DownloadResult


@dataclass
class SyncError(Message):
    """Posted by the sync worker when a framework sync raises an unhandled exception."""

    key: str
    error: str
