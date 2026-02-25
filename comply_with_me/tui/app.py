"""cwm TUI — CwmApp and DashboardScreen."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, RichLog
from textual.worker import get_current_worker

from comply_with_me.downloaders import SERVICES, SERVICES_BY_KEY, ServiceDef
from comply_with_me.state import StateFile
from comply_with_me.tui.detail import DetailScreen
from comply_with_me.tui.messages import SyncComplete, SyncError, SyncProgress


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_dt(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")


def _svc_entries(entries: dict, svc: ServiceDef) -> dict:
    prefix = svc.subdir + "/"
    return {k: v for k, v in entries.items() if k.startswith(prefix)}


class DashboardScreen(Screen):
    """Main dashboard: framework table + sync log panel."""

    BINDINGS = [
        Binding("s", "sync_selected", "Sync"),
        Binding("a", "sync_all", "Sync All"),
        Binding("enter", "open_detail", "Detail"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit_app", "Quit"),
    ]

    def __init__(self, output_dir: Path) -> None:
        super().__init__()
        self._output_dir = output_dir
        self._sync_active = False
        self._pending_keys: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="fw-table", zebra_stripes=True, cursor_type="row")
        yield RichLog(id="sync-log", highlight=True, markup=True, max_lines=500)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#fw-table", DataTable)
        table.add_column("Framework", key="framework")
        table.add_column("Files", key="files")
        table.add_column("Size", key="size")
        table.add_column("Last Synced", key="last_sync")

        self.query_one("#sync-log", RichLog).border_title = "Sync Log"
        self._populate_table()
        self.query_one("#sync-log", RichLog).write(
            "[dim]Ready.  [bold]S[/bold] sync selected  "
            "[bold]A[/bold] sync all  "
            "[bold]Enter[/bold] detail  "
            "[bold]R[/bold] refresh  "
            "[bold]Q[/bold] quit[/dim]"
        )

    # ------------------------------------------------------------------
    # Table helpers
    # ------------------------------------------------------------------

    def _read_entries(self) -> dict:
        try:
            return StateFile(self._output_dir).entries()
        except Exception:  # noqa: BLE001
            return {}

    def _populate_table(self) -> None:
        table = self.query_one("#fw-table", DataTable)
        table.clear()
        entries = self._read_entries()

        for svc in SERVICES:
            svc_e = _svc_entries(entries, svc)
            if not svc_e:
                table.add_row(svc.label, "--", "--", "never", key=svc.key)
            else:
                count = len(svc_e)
                size = _human_size(sum(e["size"] for e in svc_e.values()))
                last = _fmt_dt(max(e["recorded_at"] for e in svc_e.values()))
                table.add_row(svc.label, str(count), size, last, key=svc.key)

    def _refresh_row(self, key: str) -> None:
        """Re-read state and update a single framework's table row in-place."""
        entries = self._read_entries()
        svc = SERVICES_BY_KEY[key]
        svc_e = _svc_entries(entries, svc)
        table = self.query_one("#fw-table", DataTable)

        if not svc_e:
            table.update_cell(key, "files", "--")
            table.update_cell(key, "size", "--")
            table.update_cell(key, "last_sync", "never")
        else:
            count = len(svc_e)
            size = _human_size(sum(e["size"] for e in svc_e.values()))
            last = _fmt_dt(max(e["recorded_at"] for e in svc_e.values()))
            table.update_cell(key, "files", str(count))
            table.update_cell(key, "size", size)
            table.update_cell(key, "last_sync", last)

    def _selected_key(self) -> str | None:
        table = self.query_one("#fw-table", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(
                Coordinate(table.cursor_row, 0)
            )
            return row_key.value  # RowKey.value is the str we passed to add_row(key=...)
        except Exception:  # noqa: BLE001
            idx = table.cursor_row
            return SERVICES[idx].key if 0 <= idx < len(SERVICES) else None

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        if self._sync_active:
            self.query_one("#sync-log", RichLog).write(
                "[yellow]Sync in progress — refresh when complete.[/yellow]"
            )
            return
        self._populate_table()
        self.query_one("#sync-log", RichLog).write("[dim]Refreshed.[/dim]")

    def action_open_detail(self) -> None:
        key = self._selected_key()
        if not key:
            return
        svc = SERVICES_BY_KEY[key]
        entries = self._read_entries()
        self.app.push_screen(DetailScreen(svc, entries))

    def action_sync_selected(self) -> None:
        key = self._selected_key()
        if key:
            self._start_sync([key])

    def action_sync_all(self) -> None:
        self._start_sync([svc.key for svc in SERVICES])

    def action_quit_app(self) -> None:
        self.app.exit()

    # ------------------------------------------------------------------
    # Sync orchestration
    # ------------------------------------------------------------------

    def _start_sync(self, keys: list[str]) -> None:
        if self._sync_active:
            self.query_one("#sync-log", RichLog).write(
                "[yellow]Already syncing — please wait.[/yellow]"
            )
            return
        self._sync_active = True
        self._pending_keys = set(keys)
        self._sync_worker(keys, self._output_dir)

    @work(thread=True)
    def _sync_worker(self, keys: list[str], output_dir: Path) -> None:
        w = get_current_worker()
        for key in keys:
            if w.is_cancelled:
                break
            self.post_message(SyncProgress(key=key))
            try:
                svc = SERVICES_BY_KEY[key]
                state = StateFile(output_dir)
                result = svc.runner(output_dir, dry_run=False, force=False, state=state)
            except Exception as exc:  # noqa: BLE001
                if not w.is_cancelled:
                    self.post_message(SyncError(key=key, error=str(exc)))
                continue
            if not w.is_cancelled:
                self.post_message(SyncComplete(key=key, result=result))

    # ------------------------------------------------------------------
    # Message handlers (dispatched on the main thread by Textual)
    # ------------------------------------------------------------------

    def on_sync_progress(self, msg: SyncProgress) -> None:
        svc = SERVICES_BY_KEY[msg.key]
        self.query_one("#fw-table", DataTable).update_cell(
            msg.key, "last_sync", "[yellow]syncing...[/yellow]"
        )
        self.query_one("#sync-log", RichLog).write(
            f"[cyan]{svc.label}[/cyan] — starting sync"
        )

    def on_sync_complete(self, msg: SyncComplete) -> None:
        r = msg.result
        svc = SERVICES_BY_KEY[msg.key]
        self._refresh_row(msg.key)

        log = self.query_one("#sync-log", RichLog)
        log.write(
            f"[green]{svc.label}[/green] — "
            f"downloaded: [green]{len(r.downloaded)}[/green]  "
            f"skipped: [dim]{len(r.skipped)}[/dim]  "
            f"errors: [red]{len(r.errors)}[/red]"
        )
        for label, url in r.manual_required:
            log.write(f"  [yellow]manual:[/yellow] {label}  {url}")
        for notice in r.notices:
            log.write(f"  [dim cyan]note: {notice}[/dim cyan]")

        self._pending_keys.discard(msg.key)
        if not self._pending_keys:
            self._sync_active = False
            log.write("[dim]All done.[/dim]")

    def on_sync_error(self, msg: SyncError) -> None:
        svc = SERVICES_BY_KEY[msg.key]
        self.query_one("#fw-table", DataTable).update_cell(
            msg.key, "last_sync", "[red]error[/red]"
        )
        self.query_one("#sync-log", RichLog).write(
            f"[red]{svc.label}[/red] — error: {msg.error}"
        )
        self._pending_keys.discard(msg.key)
        if not self._pending_keys:
            self._sync_active = False


class CwmApp(App):
    """cwm — Comply With Me interactive TUI."""

    TITLE = "cwm — Comply With Me"

    CSS = """
    DashboardScreen {
        layout: vertical;
    }

    #fw-table {
        height: 2fr;
        border: solid $primary;
        margin: 0 1;
    }

    #sync-log {
        height: 1fr;
        border: solid $panel;
        margin: 0 1;
    }

    DetailScreen {
        layout: vertical;
    }

    #detail-table {
        height: 1fr;
        border: solid $primary;
        margin: 0 1;
    }
    """

    def __init__(self, output_dir: Path = Path("source-content")) -> None:
        super().__init__()
        self._output_dir = output_dir

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(output_dir=self._output_dir))
