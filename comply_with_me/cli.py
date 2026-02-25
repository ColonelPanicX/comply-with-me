"""cwm — Comply With Me CLI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from comply_with_me.downloaders import SERVICES, SERVICES_BY_KEY, ServiceDef
from comply_with_me.downloaders.base import DownloadResult
from comply_with_me.state import StateFile

app = typer.Typer(
    name="cwm",
    help="Download and sync compliance framework documentation.",
    add_completion=False,
    no_args_is_help=True,
)

_KEYS = [s.key for s in SERVICES]
_KEYS_DISPLAY = " | ".join(_KEYS) + " | all"
_console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_result(result: DownloadResult, dry_run: bool) -> None:
    tag = "[dim](dry run)[/dim] " if dry_run else ""

    if result.downloaded:
        verb = "Would download" if dry_run else "Downloaded"
        _console.print(f"  {tag}[green]{verb}:[/green] {len(result.downloaded)}")
        for f in result.downloaded:
            _console.print(f"    [green]✓[/green] {f}")

    if result.skipped:
        _console.print(f"  {tag}[dim]Up to date:[/dim] {len(result.skipped)}")

    if result.errors:
        _console.print(f"  {tag}[red]Errors:[/red] {len(result.errors)}")
        for filename, reason in result.errors:
            name = filename or "(unknown)"
            _console.print(f"    [red]✗[/red] {name}: {reason}")

    if result.manual_required:
        _console.print("\n  [yellow]Manual download required:[/yellow]")
        for label, url in result.manual_required:
            _console.print(f"    [yellow]→[/yellow] {label}")
            _console.print(f"      {url}")
        _console.print(
            f"  Place downloaded files in "
            f"[bold]source-content/{result.framework}/[/bold] when done."
        )

    if result.notices:
        for notice in result.notices:
            _console.print(f"  [dim cyan]note: {notice}[/dim cyan]")

    if not any([result.downloaded, result.skipped, result.errors, result.manual_required]):
        _console.print("  [dim]Nothing to do.[/dim]")


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_dt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")


def _status_entries(entries: dict, svc: ServiceDef) -> dict:
    """Filter state entries belonging to a specific service."""
    prefix = svc.subdir + "/"
    return {k: v for k, v in entries.items() if k.startswith(prefix)}


def _print_status_summary(entries: dict) -> None:
    """Print a one-row-per-framework summary table."""
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Framework", style="cyan", min_width=28)
    table.add_column("Files", justify="right")
    table.add_column("Size", justify="right", min_width=10)
    table.add_column("Last Synced")

    total_files = 0
    total_size = 0
    synced = 0

    for svc in SERVICES:
        svc_entries = _status_entries(entries, svc)
        if not svc_entries:
            table.add_row(svc.label, "[dim]--[/dim]", "[dim]--[/dim]", "[dim]never[/dim]")
            continue
        count = len(svc_entries)
        size = sum(e["size"] for e in svc_entries.values())
        last = max(e["recorded_at"] for e in svc_entries.values())
        total_files += count
        total_size += size
        synced += 1
        table.add_row(svc.label, str(count), _human_size(size), _fmt_dt(last))

    _console.print(Rule("[bold]cwm status[/bold]"))
    _console.print(table)
    _console.print(Rule())
    _console.print(
        f"[dim]Total: {total_files} files  {_human_size(total_size)}"
        f"  across {synced} framework(s)[/dim]"
    )


def _print_status_detail(entries: dict, svc: ServiceDef) -> None:
    """Print a per-file detail table for one framework."""
    svc_entries = _status_entries(entries, svc)
    _console.print(Rule(f"[bold cyan]{svc.label}[/bold cyan]"))

    if not svc_entries:
        _console.print(
            f"  [dim]No files synced yet. Run [bold]cwm sync {svc.key}[/bold] to get started.[/dim]"
        )
        return

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("File", no_wrap=False)
    table.add_column("Size", justify="right", min_width=10)
    table.add_column("Last Synced")

    total_size = 0
    prefix = svc.subdir + "/"
    for key in sorted(svc_entries):
        entry = svc_entries[key]
        total_size += entry["size"]
        table.add_row(
            key[len(prefix):],
            _human_size(entry["size"]),
            _fmt_dt(entry["recorded_at"]),
        )

    _console.print(table)
    _console.print(Rule())
    _console.print(f"[dim]{len(svc_entries)} files  {_human_size(total_size)}[/dim]")


def _run_service(key: str, output_dir: Path, dry_run: bool, force: bool) -> DownloadResult:
    svc = SERVICES_BY_KEY[key]
    label = svc.label
    if dry_run:
        label += " [dim](dry run)[/dim]"
    _console.print(Rule(f"[bold cyan]{label}[/bold cyan]"))

    state = None if dry_run else StateFile(output_dir)

    with _console.status("Working..."):
        result = svc.runner(output_dir, dry_run, force, state)

    _print_result(result, dry_run)
    return result


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def sync(
    framework: Annotated[
        Optional[str],
        typer.Argument(help=f"Framework to sync: {_KEYS_DISPLAY}"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be downloaded without writing to disk."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-download everything regardless of current sync state."),
    ] = False,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Root directory for downloaded files."),
    ] = Path("source-content"),
) -> None:
    """Download and sync compliance framework documentation."""
    if framework is None:
        _console.print(f"[red]Error:[/red] specify a framework or 'all'. Options: {_KEYS_DISPLAY}")
        raise typer.Exit(1)

    if framework != "all" and framework not in SERVICES_BY_KEY:
        _console.print(
            f"[red]Error:[/red] unknown framework '{framework}'. Options: {_KEYS_DISPLAY}"
        )
        raise typer.Exit(1)

    keys = _KEYS if framework == "all" else [framework]
    results = [_run_service(k, output_dir, dry_run, force) for k in keys]

    # Summary and exit code
    total_dl = sum(len(r.downloaded) for r in results)
    total_skip = sum(len(r.skipped) for r in results)
    total_err = sum(len(r.errors) for r in results)
    total_manual = sum(len(r.manual_required) for r in results)

    _console.print(Rule())
    _console.print(
        f"[bold]Done.[/bold]  "
        f"Downloaded: [green]{total_dl}[/green]  "
        f"Skipped: [dim]{total_skip}[/dim]  "
        f"Errors: [red]{total_err}[/red]  "
        f"Manual required: [yellow]{total_manual}[/yellow]"
    )

    # Exit codes: 0 = clean, 1 = partial (errors or manual), 2 = nothing downloaded at all
    if total_err > 0 or total_manual > 0:
        raise typer.Exit(1 if total_dl > 0 else 2)


@app.command()
def status(
    framework: Annotated[
        Optional[str],
        typer.Argument(help=f"Framework to inspect: {' | '.join(_KEYS)}. Omit for all."),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", help="Root directory to inspect.", show_default=True),
    ] = Path("source-content"),
) -> None:
    """Show per-framework download inventory and last sync date."""
    if framework is not None and framework not in SERVICES_BY_KEY:
        _console.print(
            f"[red]Error:[/red] unknown framework '{framework}'. Options: {_KEYS_DISPLAY}"
        )
        raise typer.Exit(1)

    entries = StateFile(output_dir).entries()

    if not entries:
        _console.print(
            "[dim]No sync history found. Run [bold]cwm sync[/bold] to get started.[/dim]"
        )
        return

    if framework is None:
        _print_status_summary(entries)
    else:
        _print_status_detail(entries, SERVICES_BY_KEY[framework])


if __name__ == "__main__":
    app()
