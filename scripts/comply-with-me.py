#!/usr/bin/env python3
"""Interactive menu to run downloaders with a diff-and-confirm flow."""

from __future__ import annotations

import csv
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO_VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
FALLBACK_PY = Path(sys.executable)


@dataclass
class Service:
    name: str
    script: Path
    manifest: Path
    download_dir: Path


SERVICES: List[Service] = [
    Service(
        name="CMMC",
        script=Path("scripts/cmmc-auto-dl/cmmc-auto-dl.py"),
        manifest=Path("scripts/cmmc-auto-dl/reports/cmmc-manifest.csv"),
        download_dir=Path("scripts/cmmc-auto-dl/downloads/draft-pubs"),
    ),
    Service(
        name="FedRAMP",
        script=Path("scripts/fedramp-auto-dl/fedramp-auto-dl.py"),
        manifest=Path("scripts/fedramp-auto-dl/reports/fedramp-manifest.csv"),
        download_dir=Path("source-content/fedramp"),
    ),
    Service(
        name="DISA STIGs",
        script=Path("scripts/disa-stigs-auto-dl/disa-stigs-auto-dl.py"),
        manifest=Path("scripts/disa-stigs-auto-dl/reports/disa-stigs-manifest.csv"),
        download_dir=Path("scripts/disa-stigs-auto-dl/downloads"),
    ),
]

NIST_SERVICES: List[Service] = [
    Service(
        name="NIST Finals",
        script=Path("scripts/nist-auto-dl/nist-finals-auto-dl.py"),
        manifest=Path("scripts/nist-auto-dl/reports/manifest.csv"),
        download_dir=Path("scripts/nist-auto-dl/downloads/final-pubs"),
    ),
    Service(
        name="NIST Drafts",
        script=Path("scripts/nist-auto-dl/nist-drafts-auto-dl.py"),
        manifest=Path("scripts/nist-auto-dl/reports/drafts/draft-manifest.csv"),
        download_dir=Path("scripts/nist-auto-dl/downloads/draft-pubs"),
    ),
]


def run_command(args: List[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def read_manifest(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def filename_from_url(url: str) -> str:
    from urllib.parse import urlparse
    import re

    parsed = urlparse(url)
    name = Path(parsed.path).name or "file"
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name) or "file"


def diff_manifest(current: List[dict], cached: List[dict], download_dir: Path) -> List[dict]:
    local_urls = set()
    if download_dir.exists():
        for row in current:
            if row.get("status", "").lower() == "ready" and row.get("download_url"):
                fname = filename_from_url(row["download_url"])
                target = download_dir / fname
                if target.is_dir():
                    for child in target.iterdir():
                        if child.is_file() and child.stat().st_size > 0:
                            local_urls.add(row["download_url"])
                            break
                elif target.exists() and target.stat().st_size > 0:
                    local_urls.add(row["download_url"])
    return [
        row
        for row in current
        if row.get("status", "").lower() == "ready"
        and row.get("download_url")
        and row["download_url"] not in local_urls
    ]


def copy_manifest(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())


def process_service(service: Service) -> None:
    console = Console()
    console.print(f"\n[bold cyan]=== {service.name} ===[/bold cyan]")
    script_path = REPO_ROOT / service.script
    manifest_path = REPO_ROOT / service.manifest
    # skip-download to refresh manifest
    python_bin = (
        REPO_VENV_PY
        if REPO_VENV_PY.exists()
        else FALLBACK_PY
    )
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
        task = progress.add_task("Refreshing manifest...", total=None)
        ret, out, err = run_command([str(python_bin), str(script_path), "--skip-download"])
        progress.update(task, completed=True)
    if ret != 0:
        console.print(f"[red][ERROR][/red] skip-download failed:\n{err or out}")
        return
    current = read_manifest(manifest_path)
    cached_path = manifest_path.with_name("last-manifest.csv")
    cached = read_manifest(cached_path)
    download_dir = REPO_ROOT / service.download_dir
    new_items = diff_manifest(current, cached, download_dir)
    ready_count = len([r for r in current if r.get("status", "").lower() == "ready"])
    console.print(f"Ready items: [bold]{ready_count}[/bold], New since last run: [bold]{len(new_items)}[/bold]")
    if new_items:
        rows = [f"- {item.get('title','(no title)')} -> {item.get('download_url','')}" for item in new_items[:10]]
        if len(new_items) > 10:
            rows.append(f"... and {len(new_items)-10} more")
        console.print(Panel("\n".join(rows), title="New items", box=box.SIMPLE, expand=False))
        choice = input("Proceed to download? [y/N]: ").strip().lower() if sys.stdin.isatty() else "n"
        if choice != "y":
            console.print("Skipped download.")
            return
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console, transient=True) as progress:
            task = progress.add_task("Downloading...", total=None)
            ret, out, err = run_command([str(python_bin), str(script_path)])
            progress.update(task, completed=True)
        if ret != 0:
            console.print(f"[red][ERROR][/red] download failed:\n{err or out}")
            return
        if out.strip():
            console.print(out.strip())
        copy_manifest(manifest_path, cached_path)
    else:
        console.print("No new items detected. Nothing to download.")
        copy_manifest(manifest_path, cached_path)


def run_group(services: List[Service]) -> None:
    for svc in services:
        process_service(svc)


def nist_submenu() -> None:
    console = Console()
    while True:
        console.print("\n[bold cyan]NIST Options[/bold cyan]")
        console.print("  1) Final Publications")
        console.print("  2) Draft Publications")
        console.print("  3) All (Final + Draft)")
        console.print("  x) Back")
        choice_raw = input("Enter choice: ").strip() if sys.stdin.isatty() else "x"
        choice = choice_raw.lower()
        if choice == "x":
            return
        if choice == "1":
            process_service(NIST_SERVICES[0])
        elif choice == "2":
            process_service(NIST_SERVICES[1])
        elif choice == "3":
            run_group(NIST_SERVICES)
        else:
            console.print("Invalid selection.")


def menu() -> None:
    console = Console()
    while True:
        console.print("\nSelect an option:")
        console.print("  1) NIST")
        console.print("  2) CMMC")
        console.print("  3) FedRAMP")
        console.print("  4) DISA STIGs")
        console.print("  9) Download all")
        console.print("  x) Exit")
        choice_raw = input("Enter choice: ").strip() if sys.stdin.isatty() else "x"
        choice = choice_raw.lower()
        if choice == "x":
            return
        if choice == "9":
            run_group(NIST_SERVICES)
            for svc in SERVICES:
                process_service(svc)
            continue
        if choice == "1":
            nist_submenu()
            continue
        if choice == "2":
            process_service(SERVICES[0])
            continue
        if choice == "3":
            process_service(SERVICES[1])
            continue
        if choice == "4":
            process_service(SERVICES[2])
            continue
        console.print("Invalid input.")


if __name__ == "__main__":
    menu()
