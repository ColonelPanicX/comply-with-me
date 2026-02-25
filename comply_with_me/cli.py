"""cwm — Comply With Me CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.rule import Rule

from comply_with_me.downloaders import SERVICES, SERVICES_BY_KEY
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

    if not any([result.downloaded, result.skipped, result.errors, result.manual_required]):
        _console.print("  [dim]Nothing to do.[/dim]")


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
    # Stub — implemented in issue #10
    target = framework or "all"
    _console.print(f"[dim][stub] status {target} — not yet implemented (issue #10)[/dim]")


if __name__ == "__main__":
    app()
