"""Textual TUI for bloatr."""

from __future__ import annotations

import time
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Label, ProgressBar, Static

from bloatr.cleaner import delete_with_progress
from bloatr.models import Item
from bloatr.scanner import list_children, scan_locations
from bloatr.sizes import format_size


# ========================================================================= #
# Confirmation modal
# ========================================================================= #


class ConfirmScreen(ModalScreen[bool]):
    """Modal 'are you sure?' prompt shown before any deletion runs."""

    DEFAULT_CSS = """
    ConfirmScreen {
        align: center middle;
    }
    #confirm-dialog {
        padding: 2 4;
        background: $surface;
        border: tall $warning;
        width: 70;
        height: auto;
    }
    #confirm-question {
        text-align: center;
        margin-bottom: 1;
        text-style: bold;
    }
    #confirm-hint {
        text-align: center;
        color: $text-muted;
    }
    """

    BINDINGS: ClassVar = [
        Binding("y", "confirm", "Yes"),
        Binding("n,escape", "cancel", "No"),
    ]

    def __init__(self, total_size: int, count: int, dry_run: bool) -> None:
        super().__init__()
        self._total_size = total_size
        self._count = count
        self._dry_run = dry_run

    def compose(self) -> ComposeResult:
        prefix = "DRY RUN — would delete" if self._dry_run else "Delete"
        with Vertical(id="confirm-dialog"):
            yield Static(
                f"{prefix} {self._count} item(s)  ({format_size(self._total_size)})?",
                id="confirm-question",
            )
            yield Static(
                "Press  Y  to confirm,  N  or  ESC  to cancel",
                id="confirm-hint",
            )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ========================================================================= #
# Progress modal — live deletion progress
# ========================================================================= #


class ProgressResult:
    """Result object dismissed from :class:`ProgressScreen`."""

    def __init__(
        self,
        freed: int,
        errors: list[tuple[Item, str]],
        done_paths: set[Path],
    ) -> None:
        self.freed = freed
        self.errors = errors
        self.done_paths = done_paths


class ProgressScreen(ModalScreen[ProgressResult]):
    """Modal that streams live deletion progress and runs the worker."""

    DEFAULT_CSS = """
    ProgressScreen {
        align: center middle;
    }
    #progress-dialog {
        padding: 2 4;
        background: $surface;
        border: tall $primary;
        width: 90;
        height: auto;
    }
    #progress-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #progress-current {
        color: $text-muted;
        margin-bottom: 1;
        width: 100%;
    }
    #progress-bar {
        margin-bottom: 1;
    }
    #progress-stats {
        text-align: center;
        color: $text;
    }
    """

    BINDINGS: ClassVar = []  # no keys — user waits for worker

    def __init__(self, items: list[Item], dry_run: bool) -> None:
        super().__init__()
        self._items = items
        self._dry_run = dry_run
        self._total_bytes = max(sum(max(i.size, 0) for i in items), 1)
        self._freed = 0
        self._errors: list[tuple[Item, str]] = []
        self._done_paths: set[Path] = set()

    def compose(self) -> ComposeResult:
        title = "DRY RUN — simulating deletion" if self._dry_run else "Deleting"
        with Vertical(id="progress-dialog"):
            yield Static(title, id="progress-title")
            yield Static(
                f"[1/{len(self._items)}] preparing…",
                id="progress-current",
            )
            yield ProgressBar(
                total=self._total_bytes,
                show_eta=False,
                show_percentage=True,
                id="progress-bar",
            )
            yield Static(
                f"0 B / {format_size(self._total_bytes)}",
                id="progress-stats",
            )

    def on_mount(self) -> None:
        self._run_worker()

    # ------------------------------------------------------------------ #
    # Worker — runs in a background thread
    # ------------------------------------------------------------------ #

    @work(thread=True, exclusive=True)
    def _run_worker(self) -> None:
        # Throttle UI updates: batch byte deltas and push at ~12 fps.
        state = {"pending_bytes": 0, "last_push": 0.0}
        UPDATE_INTERVAL = 0.08  # seconds

        def flush_progress() -> None:
            if state["pending_bytes"] > 0:
                delta = state["pending_bytes"]
                state["pending_bytes"] = 0
                state["last_push"] = time.monotonic()
                self.app.call_from_thread(self._add_progress, delta)

        for idx, item in enumerate(self._items):
            # Flush previous item's leftover bytes first.
            flush_progress()

            # Update "current item" line in the UI.
            self.app.call_from_thread(self._set_current, idx, item)

            def on_progress(delta: int, _path: str) -> None:
                state["pending_bytes"] += delta
                now = time.monotonic()
                if now - state["last_push"] >= UPDATE_INTERVAL:
                    pending = state["pending_bytes"]
                    state["pending_bytes"] = 0
                    state["last_push"] = now
                    self.app.call_from_thread(self._add_progress, pending)

            try:
                _, error = delete_with_progress(
                    item,
                    on_progress=on_progress,
                    dry_run=self._dry_run,
                )
                if error:
                    self._errors.append((item, error))
                else:
                    self._done_paths.add(item.path)
            except Exception as exc:
                self._errors.append((item, str(exc)))

        # Final flush.
        flush_progress()
        self.app.call_from_thread(self._finish)

    # ------------------------------------------------------------------ #
    # UI update methods — always called from the main thread
    # ------------------------------------------------------------------ #

    def _set_current(self, idx: int, item: Item) -> None:
        current = self.query_one("#progress-current", Static)
        current.update(f"[{idx + 1}/{len(self._items)}]  {item.display}")

    def _add_progress(self, delta: int) -> None:
        self._freed += delta
        capped = min(self._freed, self._total_bytes)
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.update(progress=capped)
        stats = self.query_one("#progress-stats", Static)
        stats.update(
            f"{format_size(self._freed)} / {format_size(self._total_bytes)}"
        )

    def _finish(self) -> None:
        self.dismiss(
            ProgressResult(
                freed=self._freed,
                errors=self._errors,
                done_paths=self._done_paths,
            )
        )


# ========================================================================= #
# Main application
# ========================================================================= #


class BloatrApp(App):
    """Main bloatr Textual application."""

    TITLE = "bloatr"
    SUB_TITLE = "Kill your Mac's bloat"

    CSS = """
    DataTable {
        height: 1fr;
    }
    #status {
        height: 1;
        background: $panel;
        padding: 0 1;
        color: $text-muted;
        dock: bottom;
    }
    """

    BINDINGS: ClassVar = [
        Binding("j,down", "cursor_down", "Down", show=False),
        Binding("k,up", "cursor_up", "Up", show=False),
        Binding("space", "toggle_select", "Select"),
        Binding("enter", "drill_in", "Explore"),
        Binding("escape,backspace", "go_back", "Back"),
        Binding("d", "delete_selected", "Delete"),
        Binding("r", "rescan", "Rescan"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        items: list[Item],
        dry_run: bool = False,
        scan_root: Path | None = None,
    ) -> None:
        super().__init__()
        self._items = items
        self._dry_run = dry_run
        self._scan_root = scan_root
        self._stack: list[tuple[str, list[Item]]] = []  # (breadcrumb, items)
        self._selected: set[Path] = set()
        self._current_path: str = str(scan_root) if scan_root else "~"

    # ------------------------------------------------------------------ #
    # Composition & mount
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Label("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column(" ", width=3, key="checkbox")
        table.add_column("SIZE", width=12, key="size")
        table.add_column("LOCATION", key="location")
        self._load_items(self._items)

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

    def _load_items(self, items: list[Item]) -> None:
        """Refresh the DataTable with *items* as the current view."""
        self._items = items
        table = self.query_one(DataTable)
        table.clear()

        if not items:
            table.add_row("", "", "(no items)", key="__empty__")
            self._set_status("No items in this view. Press ESC to go back or Q to quit.")
            return

        for item in items:
            checkbox = "✓" if item.path in self._selected else "○"
            if item.error:
                size_str = "-- missing --"
            else:
                size_str = format_size(item.size)
            explore = " ▶" if item.is_dir and not item.error else "  "
            table.add_row(checkbox, size_str, f"{item.display}{explore}", key=str(item.path))

        self._update_status()

    def _update_status(self) -> None:
        count = len(self._selected)
        total = sum(i.size for i in self._items if i.path in self._selected)
        mode = "  [DRY RUN]" if self._dry_run else ""
        if count:
            self._set_status(
                f"{count} selected — {format_size(total)} to free  |  press D to delete{mode}"
            )
        else:
            self._set_status(
                f"SPACE select  •  ENTER explore  •  ESC back  •  D delete  •  R rescan  •  Q quit{mode}"
            )

    def _set_status(self, msg: str) -> None:
        self.query_one("#status", Label).update(msg)

    def _current_item(self) -> Item | None:
        table = self.query_one(DataTable)
        try:
            coord = table.cursor_coordinate
            row_key = table.coordinate_to_cell_key(coord).row_key
            path_str = row_key.value
            if path_str is None or path_str == "__empty__":
                return None
            return next((i for i in self._items if str(i.path) == path_str), None)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()

    def action_toggle_select(self) -> None:
        item = self._current_item()
        if item is None or item.error:
            return

        if item.path in self._selected:
            self._selected.discard(item.path)
        else:
            self._selected.add(item.path)

        # Update ONLY the checkbox cell — cursor position is preserved.
        checkbox = "✓" if item.path in self._selected else "○"
        table = self.query_one(DataTable)
        table.update_cell(str(item.path), "checkbox", checkbox)
        self._update_status()

    # DataTable intercepts Enter internally and emits RowSelected before
    # App-level key bindings fire — so we handle drill-in via the event,
    # not the key binding.  action_drill_in is kept as a documented fallback.
    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._drill_into_key(event.row_key.value)

    def action_drill_in(self) -> None:
        item = self._current_item()
        if item:
            self._drill_into_key(str(item.path))

    def _drill_into_key(self, path_str: str | None) -> None:
        if path_str is None or path_str == "__empty__":
            return
        item = next((i for i in self._items if str(i.path) == path_str), None)
        if item is None or not item.is_dir or item.error:
            return
        self._stack.append((self._current_path, self._items))
        self._current_path = item.display
        self._set_status(f"Scanning {item.display}…")
        self._fetch_children(item)

    @work(thread=True)
    def _fetch_children(self, item: Item) -> None:
        children = list_children(item)
        self.call_from_thread(self._load_items, children)

    def action_go_back(self) -> None:
        if not self._stack:
            return
        prev_path, prev_items = self._stack.pop()
        self._current_path = prev_path
        self._load_items(prev_items)

    def action_rescan(self) -> None:
        """Rescan from scratch — either the custom root or built-in locations."""
        self._stack.clear()
        self._current_path = str(self._scan_root) if self._scan_root else "~"
        self._selected.clear()
        self._set_status("Rescanning…")
        self._do_rescan()

    @work(thread=True)
    def _do_rescan(self) -> None:
        if self._scan_root:
            root_item = Item.from_path(self._scan_root)
            items = list_children(root_item)
        else:
            from bloatr.locations import get_locations
            items = scan_locations(get_locations())
        self.call_from_thread(self._load_items, items)

    def action_delete_selected(self) -> None:
        selected_items = [i for i in self._items if i.path in self._selected]
        if not selected_items:
            self._set_status("Nothing selected. Press SPACE on items first.")
            return

        total = sum(i.size for i in selected_items)

        def handle_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                self._set_status("Cancelled.")
                return

            def handle_progress(result: ProgressResult | None) -> None:
                if result is None:
                    return
                # Drop deleted items from current view
                self._selected -= result.done_paths
                self._items = [i for i in self._items if i.path not in result.done_paths]
                self._load_items(self._items)

                # Summarise
                if self._dry_run:
                    self._set_status(
                        f"DRY RUN complete — would have freed {format_size(result.freed)}"
                    )
                elif result.errors:
                    first = result.errors[0]
                    errmsg = f"{first[0].display}: {first[1]}"
                    self._set_status(
                        f"Freed {format_size(result.freed)} — {len(result.errors)} error(s). First: {errmsg}"
                    )
                else:
                    self._set_status(
                        f"✓ Success! Freed {format_size(result.freed)} across {len(result.done_paths)} item(s)."
                    )

            self.push_screen(
                ProgressScreen(selected_items, self._dry_run),
                handle_progress,
            )

        self.push_screen(
            ConfirmScreen(total, len(selected_items), self._dry_run),
            handle_confirm,
        )


# ========================================================================= #
# Entry point
# ========================================================================= #


def run_tui(
    items: list[Item],
    dry_run: bool = False,
    scan_root: Path | None = None,
) -> None:
    """Launch the bloatr TUI.

    Args:
        items: Pre-scanned list of Items to display on first paint.
        dry_run: When True, deletions are simulated only.
        scan_root: When set, rescans this directory instead of built-in locations.
    """
    app = BloatrApp(items=items, dry_run=dry_run, scan_root=scan_root)
    app.run()
