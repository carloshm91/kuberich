"""Captured-container logs with owned read/render/export tasks and deliberate follow."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from datetime import datetime
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.await_complete import AwaitComplete
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import DescendantFocus, Resize
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from kuberich.domain.aggregate_logs import AggregateHistory
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.log_view import WINDOWS, LogHistory, parse_start_time, window_options
from kuberich.domain.logs import LogLine
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.log_export import save_logs
from kuberich.services.logs import LogStream
from kuberich.ui.chrome import (
    LOG_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.commands import NavigationInput
from kuberich.ui.log_body import LogBody
from kuberich.ui.scopes import ScopeScreen


class TextRequestScreen(ModalScreen[str | None]):
    AUTO_FOCUS = "#log-value"
    DEFAULT_CSS = """
    TextRequestScreen { align: center middle; background: $background 80%; }
    #log-request { width: 90%; height: auto; border: round $primary; padding: 1; }
    #log-request Static, #log-value, #log-request Horizontal { height: auto; min-height: 1; }
    #log-request Button { height: 1; border: none; }
    """

    def __init__(self, title: str, validate: Callable[[str], object] | None = None) -> None:
        super().__init__()
        self.heading, self.validate = title, validate

    def compose(self) -> ComposeResult:
        with Vertical(id="log-request"):
            yield Static(self.heading, markup=False)
            yield NavigationInput(lambda: None, placeholder="Enter a value", id="log-value")
            yield Static("", id="log-request-error", markup=False)
            with Horizontal():
                yield Button("Accept", id="log-accept", compact=True)
                yield Button("Cancel", id="log-cancel", compact=True)

    @on(Input.Submitted)
    @on(Button.Pressed, "#log-accept")
    def accept(self) -> None:
        value = self.query_one("#log-value", Input).value
        try:
            if not value.strip():
                raise AppError("Enter a value.")
            if self.validate is not None:
                self.validate(value)
        except AppError as error:
            self.query_one("#log-request-error", Static).update(safe_text(str(error)))
        else:
            self.dismiss(value)

    @on(Button.Pressed, "#log-cancel")
    def cancel(self) -> None:
        self.dismiss(None)


class LogHelpScreen(ModalScreen[None]):
    AUTO_FOCUS = "#help-scroll"

    def __init__(self, status: str, *, aggregated: bool = False) -> None:
        super().__init__()
        self.status = status
        self.aggregated = aggregated

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Log controls", id="help-title", markup=False)
            with VerticalScroll(id="help-scroll"):
                yield Static(
                    self.status
                    + "\n\n"
                    + (
                        "c source admission · s display filter · J plain/JSON"
                        if self.aggregated
                        else "c container"
                    )
                    + " · v current/previous · o read window\n"
                    "p pauses/resumes reception; reading older lines does not pause it\n"
                    "f follows the bottom; G jumps to the bottom and follows\n"
                    "g first retained line · j/k down/up · h/l horizontal\n"
                    "Ctrl+F/B page · Ctrl+D/U half-page · arrows/PageUp/PageDown\n"
                    "/ literal search · Enter then n/N next/previous matching line\n"
                    "t timestamps · w wrap · L lock horizontal offset during follow\n"
                    "C clear retained history · m mark first visible line\n"
                    "z fullscreen · Ctrl+Y copy retained text · Ctrl+S save to a new file\n"
                    "? these controls · Esc leaves an input then returns to the prior view\n\n"
                    "Oldest lines are evicted at 10,000 lines or 4 MiB. g/G only navigate\n"
                    "retained output. Reopening or changing a window requests history\n"
                    "again and may repeat it. No automatic stream replay.\n"
                    "Copy/save use retained, redacted, timestamped text. Copy is limited\n"
                    "to 1 MiB; save does not overwrite files. Copy requires terminal\n"
                    "clipboard support.",
                    markup=False,
                )
            yield Button("Back", id="log-help-back", compact=True)

    @on(Button.Pressed)
    def close_help(self) -> None:
        self.dismiss()


class _HeadComplete(Exception):
    pass


class LogScreen(ModalScreen[None]):
    AUTO_FOCUS = "#log-body"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("c", "container", "Container"),
        Binding("v", "previous", "Previous"),
        Binding("o", "window", "Window"),
        Binding("p", "pause", "Pause"),
        Binding("f", "follow", "Follow"),
        Binding("t", "timestamps", "Timestamps"),
        Binding("w", "wrap", "Wrap"),
        Binding("L", "column_lock", "Column lock", show=False),
        Binding("C", "clear", "Clear", show=False),
        Binding("m", "mark", "Mark", show=False),
        Binding("z", "fullscreen", "Fullscreen", show=False),
        Binding("slash", "search", "Search", key_display="/", priority=True),
        Binding("n", "match(False)", "Next match", show=False),
        Binding("N", "match(True)", "Previous match", show=False),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("ctrl+y", "copy", "Copy", priority=True),
        Binding("ctrl+s", "save", "Save", priority=True),
    ]
    DEFAULT_CSS = """
    LogScreen { layout: vertical; background: $background; }
    #log-dialog.fullscreen { border: none; }
    #log-title, #log-status, #log-hints, #log-search, #log-targets, #log-controls { height: 1; }
    #log-title { color: $accent; text-overflow: ellipsis; padding: 0 1; }
    #log-targets Button, #log-controls Button { height: 1; min-width: 5; width: 1fr; border: none; }
    #log-status, #log-hints { color: $text-muted; text-overflow: ellipsis; }
    #log-status { margin: 0 1; }
    #log-search-bar { height: 3; border: solid $primary; }
    LogScreen.short #log-search-bar { height: 1; border-top: none; border-bottom: none; }
    """

    def __init__(
        self,
        stream: LogStream,
        containers: tuple[str, ...],
        *,
        selected: str | None = None,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = ("pods",),
    ) -> None:
        super().__init__()
        if selected is not None and selected not in containers:
            raise AppError("Selected log container is unavailable in this pod.")
        self.stream, self.containers = stream, containers
        self.chrome, self.trail = chrome, trail
        self.breadcrumbs = Breadcrumbs(
            (*trail, "logs"),
            trail[-1].title(),
            visible=chrome is None or not chrome.presentation.crumbsless,
        )
        self.container = selected if selected is not None else containers[0]
        self._selected = selected
        self.history: LogHistory | AggregateHistory = LogHistory()
        self.body = LogBody()
        self.search = NavigationInput(
            lambda: self.set_focus(self.body), placeholder="Literal search · /", id="log-search"
        )
        self.status = Static("Choose a container.", markup=False, id="log-status")
        self.heading = Static("", id="log-title", markup=False)
        self.pause_button = Button("Pause", id="log-pause", compact=True)
        self.previous_button = Button("Previous", id="log-previous", compact=True)
        self.previous, self.paused, self.wrap, self.timestamps = False, False, False, True
        self.window = "Tail 1000"
        self.since: datetime | None = None
        self.message = "Choose a container."
        self.match_index = -1
        self.closed, self.stale = False, False
        self._generation, self._display_generation = 0, 0
        self._change, self._dirty, self._resume = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self._display_ready = asyncio.Event()
        self._resume.set()
        self._read_task: asyncio.Task[None] | None = None
        self._controller: asyncio.Task[None] | None = None
        self._renderer: asyncio.Task[None] | None = None
        self._save_task: asyncio.Task[None] | None = None
        self._layout_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        if self.chrome is not None:
            yield WorkspaceHeader(self.chrome, LOG_SHORTCUTS)
        with WorkspaceBars(id="log-bars"):
            with Horizontal(id="log-search-bar", classes="input-bar"):
                yield Static("/", classes="input-label", markup=False)
                yield self.search
            yield Static(
                "g/G first/last · / search · p pause · ? controls", markup=False, id="log-hints"
            )
        with WorkspaceFrame(id="log-dialog"):
            yield self.heading
            with Horizontal(id="log-targets"):
                yield Button("Container", id="log-container", compact=True)
                yield self.previous_button
                yield Button("Window", id="log-window", compact=True)
                yield Button("Back", id="log-back", compact=True)
            with Horizontal(id="log-controls"):
                yield self.pause_button
                yield Button("Follow", id="log-follow", compact=True)
                yield Button("Wrap", id="log-wrap", compact=True)
                yield Button("Time", id="log-timestamps", compact=True)
                yield Button("Help", id="log-help", compact=True)
            yield self.body
        yield self.breadcrumbs
        yield self.status

    def on_descendant_focus(self, event: DescendantFocus) -> None:
        self.breadcrumbs.show_trail(
            destination="Leave search" if isinstance(self.focused, Input) else None
        )

    def on_mount(self) -> None:
        self._controller = asyncio.create_task(self._control())
        self._renderer = asyncio.create_task(self._render_logs())
        self._status()
        if self._selected is not None or len(self.containers) == 1:
            self._restart()
        else:
            self.action_container()

    def require_current(self) -> None:
        self.stream.require_current()
        if self.closed or self.stale:
            raise AppError("The log target is stale; select the pod again.")

    def validate_target(self) -> None:
        try:
            self.require_current()
        except AppError as error:
            if not self.stale:
                self.stale = True
                self._generation += 1
                self._display_generation += 1
                self.history.clear()
                self.body.clear()
                self.message = str(error)
                self._change.set()
                for button in self.query(Button):
                    button.disabled = button.id not in {"log-back", "log-help"}
                self._status()

    def _restart(self) -> None:
        try:
            self.require_current()
        except AppError as error:
            self.message = str(error)
            self._status()
            return
        self._generation += 1
        self._display_generation += 1
        self.message = "Opening selected container logs…"
        self._change.set()
        self._status()

    async def _control(self) -> None:
        try:
            while True:
                await self._change.wait()
                self._change.clear()
                await self._stop_read()
                self._change.clear()
                if self.stale:
                    continue
                self.history.clear()
                self.body.clear()
                self.body.follow = True
                self._dirty.set()
                self._read_task = asyncio.create_task(self._read(self._generation))
        except Exception as error:
            self.app._handle_exception(error)
        finally:
            await self._stop_read()

    async def _stop_read(self) -> None:
        if self._read_task is not None:
            if not self._read_task.done() and not self._read_task.cancelling():
                self._read_task.cancel()
            await asyncio.gather(self._read_task, return_exceptions=True)

    async def _read(self, generation: int) -> None:
        stream = LogStream(
            self.stream.client,
            replace(self.stream.target, container=self.container),
            self.stream.policy,
            lambda: (
                not self.closed
                and not self.stale
                and generation == self._generation
                and self.stream.current()
            ),
        )
        received = 0
        head = self.window == "Head 1000"

        def opened() -> None:
            self.message = "Waiting for log output"
            self._dirty.set()

        async def retain(line: LogLine) -> None:
            nonlocal received
            await self._resume.wait()
            stream.require_current()
            self.history.append(line)
            received += 1
            self.message = "Receiving logs"
            self._dirty.set()
            if head and received == 1000:
                raise _HeadComplete
            if received % 64 == 0:
                await asyncio.sleep(0)

        try:
            await stream.run(
                window_options(self.window, previous=self.previous, since=self.since),
                retain,
                opened=opened,
            )
        except _HeadComplete:
            self.message = "Head snapshot complete"
        except (AppError, ConnectionProblem) as error:
            if generation == self._generation and not self.stale:
                self.message = str(error)
        except Exception as error:
            self.app._handle_exception(error)
        else:
            self.message = "Stream complete" if received else "Stream complete · no output"
        finally:
            self._dirty.set()

    async def _layout(self) -> bool:
        async with self._layout_lock:
            generation = self._display_generation

            def valid() -> bool:
                return not self.closed and not self.stale and generation == self._display_generation

            await self.body.load(
                tuple(self.history.entries),
                wrap=self.wrap,
                timestamps=self.timestamps,
                query=self.search.value,
                marks=frozenset(self.history.marks),
                valid=valid,
            )
            return valid()

    async def _render_logs(self) -> None:
        try:
            while True:
                await self._dirty.wait()
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._display_ready.wait(), timeout=0.05)
                self._dirty.clear()
                self._display_ready.clear()
                await self._layout()
                self._status()
        except Exception as error:
            self.app._handle_exception(error)

    def _status(self) -> None:
        if self.closed or not self.heading.is_mounted:
            return
        mode = "previous" if self.previous else "current"
        target = self.stream.target
        self.query_one("#log-dialog").border_title = safe_text(
            f"logs({target.namespace}/{target.name}:{self.container}) · {mode}"
        )
        self.heading.update(
            safe_text(
                f"Logs · {self.container} · {mode} · {target.namespace}/{target.name} · {target.session.context}"
            )
        )
        state = "Paused" if self.paused else "Receiving enabled"
        follow = "Following" if self.body.follow else "Reading history"
        self.status.update(
            safe_text(
                f"{self.message} · {state} · {follow} · {len(self.history.entries)} retained · "
                f"{self.history.buffer.dropped_lines} dropped · {self.window} · "
                f"{len(self.body.matches)} matching lines · {'wrap' if self.wrap else 'no wrap'} · "
                f"{'timestamps' if self.timestamps else 'no timestamps'} · "
                f"column lock {'on' if self.body.column_lock else 'off'}"
            )
        )
        self.pause_button.label = "Resume" if self.paused else "Pause"
        self.previous_button.label = "Current" if self.previous else "Previous"

    def _display_changed(self) -> None:
        self._display_generation += 1
        self._dirty.set()
        self._display_ready.set()
        self._status()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not isinstance(self.focused, Input) and (not self.stale or action == "help")

    def action_container(self) -> None:
        def selected(value: str | None) -> None:
            if value is not None:
                self.container = value
                self._restart()
                self.set_focus(self.body)

        self.app.push_screen(
            ScopeScreen("Choose log container (regular / init)", self.containers), selected
        )

    def action_previous(self) -> None:
        self.previous = not self.previous
        self._restart()

    def action_window(self) -> None:
        def selected(value: str | None) -> None:
            if value == "Since time…":
                self.app.push_screen(
                    TextRequestScreen("Start time: RFC3339 with Z/offset", parse_start_time),
                    since_selected,
                )
            elif value is not None:
                self.window, self.since = value, None
                self._restart()
                self.set_focus(self.body)

        def since_selected(value: str | None) -> None:
            if value is not None:
                self.window, self.since = "Since time", parse_start_time(value)
                self._restart()
                self.set_focus(self.body)

        self.app.push_screen(
            ScopeScreen("Choose log read window", (*WINDOWS, "Since time…")), selected
        )

    def action_pause(self) -> None:
        self.paused = not self.paused
        self._resume.clear() if self.paused else self._resume.set()
        self._status()

    def action_follow(self) -> None:
        self.body.action_latest()
        self.set_focus(self.body)
        self._status()

    def action_wrap(self) -> None:
        self.wrap = not self.wrap
        self._display_changed()

    def action_timestamps(self) -> None:
        self.timestamps = not self.timestamps
        self._display_changed()

    def action_column_lock(self) -> None:
        self.body.column_lock = not self.body.column_lock
        self._status()

    def action_clear(self) -> None:
        count = self.history.clear()
        self.body.clear()
        self.message = f"Cleared {count} retained lines"
        self._display_changed()

    def action_mark(self) -> None:
        visible = self.body.first_visible
        if visible is not None:
            try:
                self.history.mark(visible[0])
            except AppError as error:
                self.message = str(error)
            self._display_changed()

    def action_fullscreen(self) -> None:
        frame = self.query_one("#log-dialog")
        frame.toggle_class("fullscreen")
        fullscreen = frame.has_class("fullscreen")
        for header in self.query(WorkspaceHeader):
            header.display = not fullscreen
        self.breadcrumbs.display = not fullscreen and (
            self.chrome is None or not self.chrome.presentation.crumbsless
        )

    def action_search(self) -> None:
        self.set_focus(self.search)

    @on(Input.Changed, "#log-search")
    def search_changed(self) -> None:
        self.match_index = -1
        self._display_changed()

    @on(Input.Submitted, "#log-search")
    async def search_submitted(self) -> None:
        self._dirty.set()
        # Search layout is batched too; finish the selected query before jumping.
        if await self._layout():
            self.action_match(False)

    def action_match(self, reverse: bool) -> None:
        if self.body.matches:
            self.match_index = (self.match_index + (-1 if reverse else 1)) % len(self.body.matches)
            self.body.jump(self.body.matches[self.match_index])
            self.message = f"Matching line {self.match_index + 1}/{len(self.body.matches)}"
        else:
            self.message = "No matching retained lines"
        self._status()

    @on(LogBody.NavigationChanged)
    def navigated(self) -> None:
        self._status()

    def action_help(self) -> None:
        target = self.stream.target
        self.app.push_screen(
            LogHelpScreen(
                f"{target.session.context} · {target.namespace}/{target.name} · {self.container}\n"
                + str(self.status.content)
            )
        )

    def action_copy(self) -> None:
        try:
            self.require_current()
            text = self.history.export(clipboard=True)
        except AppError as error:
            self.message = str(error)
        else:
            self.app.copy_to_clipboard(text)
            self.message = "Retained redacted logs copied"
        self._status()

    def action_save(self) -> None:
        def selected(value: str | None) -> None:
            if value is not None and (self._save_task is None or self._save_task.done()):
                self._save_task = asyncio.create_task(self._save(value))

        self.app.push_screen(
            TextRequestScreen("Save retained redacted logs to a NEW file"), selected
        )

    async def _save(self, path: str) -> None:
        try:
            self.require_current()
            text = self.history.export()
            self.message = "Saving captured redacted logs…"
            self._status()
            await save_logs(path, text)
            if not self.stale:
                self.message = "Captured redacted logs saved"
        except AppError as error:
            self.message = str(error)
        except Exception as error:
            self.app._handle_exception(error)
        finally:
            if not self.closed:
                self._status()

    def back(self) -> None:
        if isinstance(self.focused, Input):
            self.set_focus(self.body)
        else:
            self.dismiss()

    def on_resize(self, event: Resize) -> None:
        self._display_generation += 1
        self._dirty.set()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "log-back":
            self.dismiss()
        else:
            action = (event.button.id or "").removeprefix("log-")
            getattr(self, "action_" + action)()

    def _cancel_tasks(self) -> None:
        self.closed = True
        for task in (self._controller, self._renderer, self._save_task):
            if task is not None and not task.done() and not task.cancelling():
                task.cancel()

    def dismiss(self, result: None = None) -> AwaitComplete:
        self._cancel_tasks()
        return super().dismiss(result)

    async def on_unmount(self) -> None:
        self._cancel_tasks()
        await asyncio.gather(
            *(
                task
                for task in (self._controller, self._renderer, self._save_task)
                if task is not None
            ),
            return_exceptions=True,
        )
