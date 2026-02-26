"""Hash-based sync state file for cwm."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

STATE_FILENAME = ".cwm-state.json"
_SCHEMA_VERSION = 1


class StateFile:
    """Persistent record of downloaded files indexed by SHA-256 hash.

    Thread-safe: used by downloaders that run workers via ThreadPoolExecutor.
    The state file is written atomically (tmp → rename) to prevent corruption.
    """

    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self._path = output_dir / STATE_FILENAME
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def needs_adopt(self, path: Path) -> bool:
        """Return True if *path* exists on disk but has no state record."""
        if not path.exists() or path.stat().st_size == 0:
            return False
        key = self._key(path)
        with self._lock:
            return key not in self._entries

    def is_fresh(self, path: Path, url: str) -> bool:
        """Return True if *path* is tracked and its on-disk hash matches.

        Does NOT modify state — call adopt() first for untracked files.
        Returns False if path is absent, empty, untracked, or hash-mismatched.
        """
        if not path.exists() or path.stat().st_size == 0:
            return False
        key = self._key(path)
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return False
        return _sha256(path) == entry["sha256"]

    def entries(self) -> dict[str, dict]:
        """Return a snapshot of all entries (for ``cwm status``)."""
        with self._lock:
            return dict(self._entries)

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def adopt(self, path: Path, url: str) -> None:
        """Hash an existing file and add it to state without re-downloading.

        Idempotent — safe to call even if already recorded (overwrites).
        Used on first run to fingerprint files downloaded before state tracking.
        """
        entry = _build_entry(path, url)
        key = self._key(path)
        with self._lock:
            self._entries[key] = entry
            self._save()

    def record(self, path: Path, url: str) -> None:
        """Hash a freshly downloaded file and persist its metadata."""
        entry = _build_entry(path, url)
        key = self._key(path)
        with self._lock:
            self._entries[key] = entry
            self._save()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _key(self, path: Path) -> str:
        try:
            return path.relative_to(self._output_dir).as_posix()
        except ValueError:
            return str(path)

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if raw.get("schema_version") == _SCHEMA_VERSION:
                self._entries = raw.get("entries", {})
        except (json.JSONDecodeError, OSError, KeyError):
            self._entries = {}

    def _save(self) -> None:
        """Write state to disk atomically. Caller must hold self._lock."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"schema_version": _SCHEMA_VERSION, "entries": self._entries},
            indent=2,
            ensure_ascii=False,
        )
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_entry(path: Path, url: str) -> dict:
    return {
        "sha256": _sha256(path),
        "url": url,
        "size": path.stat().st_size,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
