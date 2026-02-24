"""cwm — Comply With Me CLI."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

app = typer.Typer(
    name="cwm",
    help="Download and sync compliance framework documentation.",
    add_completion=False,
    no_args_is_help=True,
)

FRAMEWORKS = ["fedramp", "nist-finals", "nist-drafts", "cmmc", "disa", "all"]
FRAMEWORKS_DISPLAY = " | ".join(FRAMEWORKS)
FRAMEWORKS_NO_ALL = " | ".join(f for f in FRAMEWORKS if f != "all")


@app.command()
def sync(
    framework: Annotated[
        Optional[str],
        typer.Argument(help=f"Framework to sync: {FRAMEWORKS_DISPLAY}"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview what would be downloaded without writing to disk."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-download everything regardless of current sync state."),
    ] = False,
) -> None:
    """Download and sync compliance framework documentation."""
    if framework is None:
        typer.echo(
            f"Error: specify a framework or 'all'. Options: {FRAMEWORKS_DISPLAY}",
            err=True,
        )
        raise typer.Exit(1)

    if framework not in FRAMEWORKS:
        typer.echo(
            f"Error: unknown framework '{framework}'. Options: {FRAMEWORKS_DISPLAY}",
            err=True,
        )
        raise typer.Exit(1)

    # Stub — downloader wiring implemented in issue #8
    typer.echo(f"[stub] sync {framework}  dry_run={dry_run}  force={force} — not yet implemented")


@app.command()
def status(
    framework: Annotated[
        Optional[str],
        typer.Argument(help=f"Framework to inspect: {FRAMEWORKS_NO_ALL}. Omit for all."),
    ] = None,
) -> None:
    """Show per-framework download inventory and last sync date."""
    # Stub — implemented in issue #10
    target = framework or "all"
    typer.echo(f"[stub] status {target} — not yet implemented")


if __name__ == "__main__":
    app()
