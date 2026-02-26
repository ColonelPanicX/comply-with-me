"""Comply With Me — compliance document downloader."""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Dependency check — must run before any third-party imports
# ---------------------------------------------------------------------------

def _check_dependencies() -> None:
    """Verify required packages are installed and print install instructions if not."""
    required = [
        ("requests",       "requests"),
        ("beautifulsoup4", "bs4"),
        ("pymupdf",        "fitz"),
    ]
    missing_pkgs = []
    for pkg_name, import_name in required:
        try:
            __import__(import_name)
        except ImportError:
            missing_pkgs.append(pkg_name)

    if missing_pkgs:
        print("Comply With Me is missing required packages:\n")
        for pkg in missing_pkgs:
            print(f"  - {pkg}")
        print()
        print("Run the tool via comply_with_me.py to install automatically:")
        print("  python3 comply_with_me.py")
        print()
        sys.exit(1)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _print_menu(services, entries: dict) -> None:
    print()
    print("Comply With Me")
    print("-" * 52)

    for i, svc in enumerate(services, 1):
        prefix = svc.subdir + "/"
        svc_entries = {k: v for k, v in entries.items() if k.startswith(prefix)}

        if svc_entries:
            count = len(svc_entries)
            size  = _human_size(sum(e["size"] for e in svc_entries.values()))
            last  = max(e["recorded_at"] for e in svc_entries.values())[:10]
            info  = f"{count} files  {size}  last synced {last}"
        else:
            info  = "never synced"

        print(f"  {i}. {svc.label:<32} {info}")

    sync_all_n = len(services) + 1
    normalize_n = len(services) + 2
    print()
    print(f"  {sync_all_n}. Sync All")
    print(f"  {normalize_n}. Normalize Downloaded Documents")
    print("  0. Quit")
    print()


def _run_sync(svc, output_dir: Path, state) -> None:
    print(f"Syncing {svc.label}...", end="", flush=True)
    try:
        result = svc.runner(output_dir, dry_run=False, force=False, state=state)
        print(" done.")
        if result.downloaded:
            print(f"  Downloaded : {len(result.downloaded)}")
        if result.skipped:
            print(f"  Up to date : {len(result.skipped)}")
        if result.errors:
            print(f"  Errors     : {len(result.errors)}")
            for name, err in result.errors:
                print(f"    {name}: {err}")
        if result.manual_required:
            print("  Manual download required:")
            for label, url in result.manual_required:
                print(f"    {label}")
                print(f"    {url}")
        if result.notices:
            print()
            for notice in result.notices:
                print(f"  [!] {notice}")
    except Exception as exc:  # noqa: BLE001
        print(f" failed.\n  Error: {exc}")


def _run_normalize(source_dir: Path, output_dir: Path) -> None:
    from comply_with_me.normalizer import normalize_all

    output_dir.mkdir(parents=True, exist_ok=True)

    seen_frameworks: set[str] = set()

    def _progress(framework_key: str, filename: str) -> None:
        if framework_key not in seen_frameworks:
            seen_frameworks.add(framework_key)
            print(f"  Normalizing {framework_key}...", flush=True)

    print("Normalizing downloaded documents...")
    print("  (This may take a while for large collections.)")
    print()

    try:
        result = normalize_all(source_dir, output_dir, force=False, progress_callback=_progress)
    except Exception as exc:  # noqa: BLE001
        print(f"  Normalization failed: {exc}")
        return

    print()
    if result.processed:
        print(f"  Normalized   : {len(result.processed)}")
    if result.skipped:
        print(f"  Already done : {len(result.skipped)}")
    if result.unsupported:
        print(f"  Skipped (unsupported format) : {len(result.unsupported)}")
    if result.errors:
        print(f"  Errors       : {len(result.errors)}")
        for name, err in result.errors:
            print(f"    {name}: {err}")
    if not result.processed and not result.skipped and not result.errors:
        print("  Nothing to normalize — sync a framework first.")

    print()
    print(f"  Output: {output_dir}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    _check_dependencies()

    # Lazy imports — only reached if dependencies are present
    from comply_with_me.downloaders import SERVICES
    from comply_with_me.state import StateFile

    source_dir = Path("source-content")
    normalized_dir = Path("normalized-content")
    source_dir.mkdir(parents=True, exist_ok=True)
    state = StateFile(source_dir)

    while True:
        _print_menu(SERVICES, state.entries())

        try:
            choice = input("Select: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye.")
            break

        if choice == "0":
            print("Goodbye.")
            break

        if not choice.isdigit():
            print("Invalid selection.")
            continue

        n = int(choice)
        sync_all_n = len(SERVICES) + 1
        normalize_n = len(SERVICES) + 2

        if 1 <= n <= len(SERVICES):
            _run_sync(SERVICES[n - 1], source_dir, state)
        elif n == sync_all_n:
            for svc in SERVICES:
                _run_sync(svc, source_dir, state)
        elif n == normalize_n:
            _run_normalize(source_dir, normalized_dir)
        else:
            print("Invalid selection.")
