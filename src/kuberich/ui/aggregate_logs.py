"""Aggregate logs retain the established viewer controls and explicit source admission."""

import asyncio
from collections import Counter
from collections.abc import Callable
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static

from kuberich.domain.aggregate_logs import (
    MAX_READERS,
    MAX_SOURCES,
    AggregateHistory,
    LogSource,
)
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.log_view import MAX_COPY_BYTES, window_options
from kuberich.domain.logs import LogLine
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.aggregate_logs import AggregateLogs
from kuberich.services.log_export import save_logs
from kuberich.services.logs import LogStream
from kuberich.services.processes import _finish_owned
from kuberich.services.resources import parse_owned
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.logs import LogHelpScreen, LogScreen
from kuberich.ui.presentation import FrameTable
from kuberich.ui.scopes import ScopeScreen


class LogSourcesScreen(ModalScreen[None]):
    AUTO_FOCUS = "#aggregate-sources"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "select_source", "Select"),
        Binding("enter", "only", "Read only this source"),
        Binding("r", "reopen", "Reopen selected"),
        Binding("a", "automatic", "Automatic admission"),
    ]
    DEFAULT_CSS = """
    LogSourcesScreen { background: $background; layout: vertical; }
    #aggregate-sources { height: 1fr; }
    #source-heading, #source-notice { height: auto; min-height: 1; }
    #source-buttons { height: 1; }
    #source-buttons Button { height: 1; border: none; }
    """

    def __init__(self, owner: AggregateLogs, changed: Callable[[], None]) -> None:
        super().__init__()
        self.owner, self.changed = owner, changed
        self.table: DataTable[object] = FrameTable(
            id="aggregate-sources", cursor_type="row", zebra_stripes=True
        )
        self.table.add_column("ID")
        self.table.add_column("SOURCE / UID")
        self.table.add_column("STATE", width=8)
        self.table.add_column("SELECTED / DETAIL")
        self.notice = Static("", id="source-notice", markup=False)
        self._rows: dict[str, tuple[object, ...]] = {}
        self._problem = ""

    def compose(self) -> ComposeResult:
        yield Static(
            "Log sources · Space toggle admission (8 max) · Enter read only row · r explicit reopen · a automatic\n"
            "Selection changes readers; the viewer's s filter only hides retained lines. Ended sources never auto-replay.",
            id="source-heading",
            markup=False,
        )
        yield self.table
        yield self.notice
        with Horizontal(id="source-buttons"):
            yield Button("Back", id="source-back", compact=True)

    def on_mount(self) -> None:
        self.refresh_sources()
        self.set_interval(0.2, self.refresh_sources)

    def refresh_sources(self) -> None:
        index, x, y = self.table.cursor_row, self.table.scroll_x, self.table.scroll_y
        selected = (
            self.table.coordinate_to_cell_key(self.table.cursor_coordinate).row_key.value
            if self.table.row_count
            else None
        )
        top = (
            self.table.coordinate_to_cell_key(
                Coordinate(min(int(y), self.table.row_count - 1), 0)
            ).row_key.value
            if self.table.row_count
            else None
        )
        wanted: dict[str, tuple[object, ...]] = {}
        for state in sorted(
            (*self.owner.states.values(), *self.owner.retired), key=lambda state: state.number
        ):
            admitted = self.owner.selected is None or state.source.key in self.owner.selected
            wanted[str(state.number)] = (
                str(state.number),
                safe_text(state.source.label(state.number)),
                state.status,
                safe_text(f"{'yes' if admitted else 'no'} · {state.message}"),
            )
        # Keep one expired selected row until the operator moves; Enter cannot retarget another UID.
        if selected is not None and selected not in wanted and selected in self._rows:
            old = self._rows[selected]
            wanted[selected] = (
                old[0],
                old[1],
                "expired",
                "No reader; selection no longer available",
            )
        for key in self._rows.keys() - wanted.keys():
            self.table.remove_row(key)
        columns = tuple(self.table.columns)
        for key, cells in wanted.items():
            if key not in self._rows:
                self.table.add_row(*cells, key=key)
            elif cells != self._rows[key]:
                for column, cell in zip(columns, cells, strict=True):
                    self.table.update_cell(key, column, cell)
        self._rows = wanted
        if self.table.row_count:
            self.table.sort(columns[0], key=lambda cell: int(str(cell)))
            self.table.move_cursor(
                row=self.table.get_row_index(selected)
                if selected in wanted
                else min(index, self.table.row_count - 1),
                scroll=False,
            )

            def restore() -> None:
                if (
                    self.table.is_mounted
                    and self.table.row_count
                    and self.table.coordinate_to_cell_key(
                        self.table.cursor_coordinate
                    ).row_key.value
                    == selected
                ):
                    position = self.table.get_row_index(top) + y % 1 if top in self._rows else y
                    self.table.scroll_to(x, position, animate=False, immediate=True, force=True)

            self.table.call_after_refresh(restore)
        self.notice.update(
            safe_text(
                f"{len(self.owner.states)} available / {MAX_SOURCES} catalogue limit · "
                f"{len(self.owner.retired)} recent removed · {self.owner.excess} beyond catalogue limit"
                + (f" · {self._problem}" if self._problem else "")
            )
        )

    def _key(self) -> tuple[str, str] | None:
        if not self.table.row_count:
            return None
        number = int(str(self.table.get_row_at(self.table.cursor_row)[0]))
        return next(
            (key for key, state in self.owner.states.items() if state.number == number), None
        )

    def _choose(self, keys: frozenset[tuple[str, str]] | None, *, reopen: bool = False) -> None:
        try:
            self.owner.choose(keys, reopen=reopen)
        except AppError as error:
            self._problem = str(error)
            self.notice.update(safe_text(str(error)))
        else:
            self._problem = ""
            self.changed()
            self.refresh_sources()

    def action_select_source(self) -> None:
        key = self._key()
        if key is None:
            return
        selected = set(
            self.owner.selected
            if self.owner.selected is not None
            else (key for key, state in self.owner.states.items() if state.status == "active")
        )
        selected.remove(key) if key in selected else selected.add(key)
        self._choose(frozenset(selected))

    def action_only(self) -> None:
        key = self._key()
        if key is not None:
            self._choose(frozenset({key}))

    @on(DataTable.RowSelected)
    def row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_only()

    def action_reopen(self) -> None:
        key = self._key()
        if key is not None:
            self._choose(frozenset({key}), reopen=True)

    def action_automatic(self) -> None:
        self._choose(None)

    @on(Button.Pressed)
    def back(self) -> None:
        self.dismiss()


class AggregateLogScreen(LogScreen):
    BINDINGS: ClassVar[list[BindingType]] = [
        *LogScreen.BINDINGS,
        Binding("s", "source_filter", "Source filter"),
        Binding("J", "json", "Plain/JSON"),
    ]

    def __init__(
        self,
        owner: AggregateLogs,
        *,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = ("pods",),
        stopped: Callable[[], None] = lambda: None,
    ) -> None:
        stream = LogStream(owner.client, owner.target, owner.policy, owner.current)
        super().__init__(
            stream, ("all sources",), selected="all sources", chrome=chrome, trail=trail
        )
        self.owner = owner
        self.aggregate = AggregateHistory()
        self.history = self.aggregate
        self._copy_task: asyncio.Task[None] | None = None
        self._stopped = stopped

    def on_mount(self) -> None:
        # Textual dispatches base-class mount handlers after this one.
        self.query_one("#log-container", Button).label = "Sources"
        self.query_one("#log-hints", Static).update(
            "c sources · s display filter · J plain/JSON · / search · ? controls"
        )

    def require_current(self) -> None:
        super().require_current()
        self.owner.require_current()

    async def _read(self, generation: int) -> None:
        # A new options/window invocation is an explicit replay; existing EOFs never reopen themselves.
        self.owner.closed = False
        self.owner.states.clear()
        self.owner.retired.clear()
        self.owner.selected = None
        self.aggregate.filter = None

        async def retain(source: LogSource, number: int, line: LogLine) -> None:
            await self._resume.wait()
            self.require_current()
            self.owner.require_source(source, number)
            if generation != self._generation:
                raise AppError("The aggregate read window has changed.")
            self.aggregate.retain(source, number, line)
            self._dirty.set()

        def notice(message: str) -> None:
            if generation == self._generation and not self.closed:
                self.message = message
                self._dirty.set()

        try:
            await self.owner.run(
                window_options(self.window, previous=self.previous, since=self.since),
                retain,
                notice,
                head_lines=1000 if self.window == "Head 1000" else None,
            )
        except (AppError, ConnectionProblem) as error:
            notice(str(error))
        except Exception as error:
            self.app._handle_exception(error)
        finally:
            self._dirty.set()

    async def _layout(self) -> bool:
        async with self._layout_lock:
            generation = self._display_generation

            def valid() -> bool:
                return not self.closed and not self.stale and generation == self._display_generation

            # Freeze references before owned formatting; source filtering never touches transports.
            records, mode, source_filter, timestamps = (
                tuple(self.aggregate.records.values()),
                self.aggregate.json_mode,
                self.aggregate.filter,
                self.timestamps,
            )
            entries = await parse_owned(
                lambda: tuple(
                    (record.number, record.text(json_mode=mode, timestamps=timestamps))
                    for record in records
                    if source_filter is None or record.source.key == source_filter
                )
            )
            if valid():
                await self.body.load(
                    entries,
                    wrap=self.wrap,
                    timestamps=True,
                    query=self.search.value,
                    marks=frozenset(self.aggregate.marks),
                    valid=valid,
                )
            return valid()

    def _display_changed(self) -> None:
        self.body.invalidate()
        super()._display_changed()

    def _status(self) -> None:
        if not self.status.is_mounted:
            return
        target = self.owner.target
        counts = Counter(state.status for state in self.owner.states.values())
        stopped = self.closed or self.stale or self.owner.closed
        if not stopped:
            self.pause_button.label = "Resume" if self.paused else "Pause"
            self.previous_button.label = "Current" if self.previous else "Previous"
            self.query_one("#log-dialog").border_title = safe_text(
                f"aggregate({target.namespace}/{target.name})"
            )
        active = 0 if stopped else counts["active"]
        receiving = (
            "Reception stopped" if stopped else "Paused" if self.paused else "Receiving enabled"
        )
        draining = stopped and any(
            task is not None and not task.done()
            for task in (
                self._controller,
                self._renderer,
                self._read_task,
                self._save_task,
                self._copy_task,
            )
        )
        if not stopped:
            self.heading.update(
                safe_text(
                    f"Aggregated logs · {target.namespace}/{target.name} · {target.resource} · {target.session.context}"
                )
            )
        self.status.update(
            safe_text(
                f"{self.message} · {receiving}{' · cleanup draining' if draining else ''} · "
                f"{active}/{MAX_READERS} readers · {len(self.owner.states)} sources · {self.owner.excess} excess · "
                f"{counts['failed']} failed / {counts['ended']} ended / {counts['waiting']} waiting · c sources · "
                f"{counts['starting']} starting · "
                f"{counts['no prior']} no previous · "
                f"{len(self.aggregate.records)} retained · {self.aggregate.buffer.dropped_lines} dropped · "
                f"{self.window} · {'JSON' if self.aggregate.json_mode else 'plain'} · "
                f"{'timestamps' if self.timestamps else 'no timestamps'} · "
                f"{'filtered' if self.aggregate.filter is not None else 'all sources'} · "
                f"{'Following' if self.body.follow else 'Reading history'}"
            )
        )

    def action_container(self) -> None:
        self.app.push_screen(LogSourcesScreen(self.owner, self._display_changed))

    def action_source_filter(self) -> None:
        candidates = {
            record.source.key: (record.source, record.source_number)
            for record in self.aggregate.records.values()
        }
        candidates.update(
            {key: (state.source, state.number) for key, state in self.owner.states.items()}
        )
        labels = {source.label(number): key for key, (source, number) in candidates.items()}

        def chosen(value: str | None) -> None:
            if value is not None:
                self.aggregate.filter = labels.get(value)
                self._display_changed()

        self.app.push_screen(
            ScopeScreen("Display retained source (no reader changes)", ("All sources", *labels)),
            chosen,
        )

    def action_json(self) -> None:
        self.aggregate.json_mode = not self.aggregate.json_mode
        self._display_changed()

    def action_help(self) -> None:
        self.app.push_screen(
            LogHelpScreen(
                "Aggregated logs: c source admission · s retained-output filter · J plain/JSON\n"
                "8 readers, 256 current sources, 64 recent removed statuses. Space/Enter in sources selects readers; r explicitly reopens.\n"
                "Each source: 500 lines / 256 KiB; aggregate: 5,000 lines / 4 MiB. Payloads bound to 4,096 escaped characters.\n"
                "Arrival order only; server timestamps may differ or regress. Same-name Pod recreation has a new UID/source ID.\n"
                "Filtered copy/save preserve source identity in the current plain/JSON mode, including timestamps.\n"
                "Malformed/excessive JSON is withheld; decoded credential keys and controls are sanitized. EOF never automatically replays.\n\n"
                + str(self.status.content),
                aggregated=True,
            )
        )

    async def _export_text(self, *, clipboard: bool = False) -> str:
        self.require_current()
        records, mode, source_filter = (
            tuple(self.aggregate.records.values()),
            self.aggregate.json_mode,
            self.aggregate.filter,
        )
        text = await parse_owned(
            lambda: "\n".join(
                record.text(json_mode=mode)
                for record in records
                if source_filter is None or record.source.key == source_filter
            )
        )
        self.require_current()
        if clipboard and len(text.encode()) > MAX_COPY_BYTES:
            raise AppError("Copy exceeds 1 MiB; filter sources or save to a file.")
        return text

    def action_copy(self) -> None:
        if self._copy_task is None or self._copy_task.done():
            self._copy_task = asyncio.create_task(self._copy())

    async def _copy(self) -> None:
        try:
            text = await self._export_text(clipboard=True)
            self.app.copy_to_clipboard(text)
            self.message = "Retained redacted logs copied"
        except AppError as error:
            self.message = str(error)
        finally:
            self._status()

    async def _save(self, path: str) -> None:
        try:
            text = await self._export_text()
            self.message = "Saving retained logs…"
            self._status()
            await save_logs(path, text)
            if not self.stale:
                self.message = "Retained redacted logs saved"
        except AppError as error:
            self.message = str(error)
        finally:
            self._status()

    def _cancel_tasks(self) -> None:
        super()._cancel_tasks()
        if (
            self._copy_task is not None
            and not self._copy_task.done()
            and not self._copy_task.cancelling()
        ):
            self._copy_task.cancel()
        self._status()

    async def stop_owned(self) -> None:
        self._cancel_tasks()
        await self.owner.close()
        await _finish_owned(
            asyncio.gather(
                *(
                    task
                    for task in (
                        self._controller,
                        self._renderer,
                        self._read_task,
                        self._save_task,
                        self._copy_task,
                    )
                    if task is not None
                ),
                return_exceptions=True,
            )
        )
        self._status()
        self._stopped()

    async def on_unmount(self) -> None:
        await self.stop_owned()
