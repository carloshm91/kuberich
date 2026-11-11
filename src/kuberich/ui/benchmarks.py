"""Reviewed HTTP load with an owned cancellation boundary and an offline result browser."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Select, Static, TextArea

from kuberich.domain.benchmark_results import BenchmarkResult
from kuberich.domain.benchmark_targets import BenchmarkBackend
from kuberich.domain.benchmarks import METHODS, LoadOptions, RequestOptions
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.benchmark_store import BenchmarkStore, SavedBenchmark
from kuberich.services.benchmarks import BenchmarkReview, BenchmarkService
from kuberich.services.ownership import finish_owned
from kuberich.ui.artifact_browser import ArtifactTable
from kuberich.ui.benchmark_presentation import backend_label, result_text
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.export_review import ArtifactConfirmation
from kuberich.ui.port_forwards import ForwardInput


class BenchmarkScreen(ModalScreen[None]):
    AUTO_FOCUS = "#benchmark-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("f6", "review", "Review", priority=True),
        Binding("f7", "run_review", "Run reviewed", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    BenchmarkScreen { align: center middle; background: $background 80%; }
    #benchmark-form { width: 98%; max-width: 110; height: 96%; border: round $warning;
        padding: 0 1; background: $surface; }
    #benchmark-title, #benchmark-progress { height: 1; }
    #benchmark-scroll { height: 1fr; min-height: 1; }
    #benchmark-scroll Static { height: auto; }
    #benchmark-editor { height: auto; }
    #benchmark-editor Input, #benchmark-editor Select { height: 3; }
    #benchmark-headers, #benchmark-body { height: 4; }
    #benchmark-feedback { height: auto; max-height: 2; }
    #benchmark-buttons { height: 1; }
    #benchmark-buttons Button { height: 1; border: none; min-width: 7; padding: 0 1; }
    BenchmarkScreen.compact #benchmark-editor Input,
    BenchmarkScreen.compact #benchmark-editor Select { height: 1; border: none; padding: 0; }
    """

    def __init__(
        self,
        owner: BenchmarkService,
        *,
        chrome: WorkspaceChrome,
        trail: tuple[str, ...],
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.owner, self.chrome, self.trail, self.stopped = owner, chrome, trail, stopped
        self.review: BenchmarkReview | None = None
        self.backends: tuple[BenchmarkBackend, ...] = ()
        self.started = self.finished = False
        self._revision = 0
        self._worker: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._stopping = False
        self._unsubscribe: Callable[[], None] = lambda: None
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._duration_seconds = owner.settings.load.duration_seconds
        self.feedback = Static("Reading captured Service/Pod backends…", id="benchmark-feedback")
        self.preview = Static("", markup=False, id="benchmark-preview")
        self.progress = Static("No load started.", markup=False, id="benchmark-progress")
        self.run_button = Button(
            "Run F7", id="benchmark-run", compact=True, disabled=True, variant="warning"
        )
        self.review_button = Button("Review F6", id="benchmark-review", compact=True)
        self.edit_button = Button("Edit", id="benchmark-edit", compact=True, disabled=True)
        self.cancel_button = Button("Cancel", id="benchmark-cancel", compact=True)

    @property
    def busy(self) -> bool:
        return self._worker is not None and not self._worker.done()

    @property
    def private_draft_visible(self) -> bool:
        """Protect the application's own screenshot actions while private fields are shown."""
        return self.is_attached and self.query_one("#benchmark-editor", Vertical).display

    def compose(self) -> ComposeResult:
        load = self.owner.settings.load
        with Vertical(id="benchmark-form"):
            yield Static(
                "HTTP benchmark · explicit reviewed load", id="benchmark-title", markup=False
            )
            with VerticalScroll(id="benchmark-scroll"):
                target = self.owner.target
                yield Static(
                    safe_text(
                        f"Context: {target.session.context} · {target.namespace}/{target.name} · UID {target.uid}"
                    )
                )
                with Vertical(id="benchmark-editor"):
                    yield Static(
                        "Captured backend (choose one explicitly when several are available)",
                        markup=False,
                    )
                    yield Select([], prompt="Choose backend", id="benchmark-backend")
                    yield Static("HTTP method", markup=False)
                    yield Select(
                        [(method, method) for method in sorted(METHODS)],
                        value="GET",
                        allow_blank=False,
                        id="benchmark-method",
                    )
                    yield Static("Relative request target (masked; /path?query)", markup=False)
                    yield ForwardInput("/", password=True, id="benchmark-target", max_length=2048)
                    yield Static("Headers (one Name: value per line; private values)", markup=False)
                    yield TextArea(id="benchmark-headers")
                    yield Static(
                        "Optional UTF-8 request body (private; at most 16 KiB)", markup=False
                    )
                    yield TextArea(id="benchmark-body")
                    for label, name, value in (
                        ("Requested rate, requests/s (1-50)", "rate", load.rate),
                        ("Concurrency (1-8)", "concurrency", load.concurrency),
                        ("Duration, seconds (1-30)", "duration", load.duration_seconds),
                        ("Request timeout, seconds (1-5)", "timeout", load.timeout_seconds),
                    ):
                        yield Static(label, markup=False)
                        yield ForwardInput(str(value), id="benchmark-" + name, max_length=3)
                yield self.preview
            yield self.progress
            yield self.feedback
            with Horizontal(id="benchmark-buttons"):
                yield self.review_button
                yield self.edit_button
                yield self.run_button
                yield self.cancel_button

    def on_resize(self) -> None:
        self.set_class(self.size.height < 18, "compact")

    def on_mount(self) -> None:
        self.on_resize()
        self._unsubscribe = self.owner.subscribe(self.refresh_progress)
        self._worker = asyncio.create_task(self._candidates())
        self.set_interval(0.2, self.refresh_progress)

    def status(self, message: str) -> None:
        if self.feedback.is_attached:
            self.feedback.update(safe_text(message))

    async def _candidates(self) -> None:
        try:
            backends = await self.owner.candidates()
            if self._stopping:
                return
            self.backends = backends
            choices = self.query_one("#benchmark-backend", Select)
            choices.set_options(
                [(backend_label(backend), index) for index, backend in enumerate(backends)]
            )
            if len(backends) == 1:
                choices.value = 0
            self.status("Choose a backend, edit request/load, then Review. No load has started.")
        except AppError as error:
            self.status(str(error))
        except Exception:
            self.status("Backend review failed. Check current target, connection and permissions.")

    def options(self) -> tuple[BenchmarkBackend, RequestOptions, LoadOptions]:
        selected = self.query_one("#benchmark-backend", Select).value
        if type(selected) is not int or not 0 <= selected < len(self.backends):
            raise AppError("Choose one captured backend before reviewing the benchmark.")
        method = self.query_one("#benchmark-method", Select).value
        if not isinstance(method, str):
            raise AppError("Choose an HTTP method.")
        headers = []
        for line in self.query_one("#benchmark-headers", TextArea).text.splitlines():
            if not line.strip():
                continue
            name, colon, value = line.partition(":")
            if not colon:
                raise AppError("Each header requires Name: value on its own line.")
            headers.append((name.strip(), value.strip()))
        try:
            values = [
                int(self.query_one("#benchmark-" + name, Input).value)
                for name in ("rate", "concurrency", "duration", "timeout")
            ]
            body = self.query_one("#benchmark-body", TextArea).text.encode("utf-8")
        except (ValueError, UnicodeError):
            raise AppError("Use whole-number load settings and a UTF-8 request body.") from None
        return (
            self.backends[selected],
            RequestOptions(
                method, self.query_one("#benchmark-target", Input).value, tuple(headers), body
            ),
            LoadOptions(*values),
        )

    @on(Input.Changed)
    @on(Select.Changed)
    @on(TextArea.Changed)
    def changed(self) -> None:
        if not self.started:
            self._revision += 1
            self.review = None
            self.owner.revoke_review()
            self.run_button.disabled = True

    @on(Button.Pressed, "#benchmark-review")
    def action_review(self) -> None:
        if not self.started and not self.busy and not self._stopping:
            self._worker = asyncio.create_task(self._review())

    async def _review(self) -> None:
        self.review = None
        self.run_button.disabled = True
        self.status("Rechecking the captured backend and exact request/load; no load…")
        try:
            backend, request, load = self.options()
            revision = self._revision
            review = await self.owner.review(backend, request, load)
            if self._stopping or revision != self._revision:
                self.owner.revoke_review()
                self.status("Options changed during review. Review the current values again.")
                return
            self.review = review
            value = review.preview
            self.preview.update(
                safe_text(
                    f"{backend_label(backend)}\nMethod: {value.method} · route: {value.route}\nQuery: {'present (values hidden)' if value.query_present else 'none'} · headers: {', '.join(value.header_names) or 'none'} · auth: {'present' if value.auth_present else 'none'} · body: {value.body_bytes} bytes\nRequested rate: {load.rate} requests/s · concurrency: {load.concurrency} · duration: {load.duration_seconds}s · request timeout: {load.timeout_seconds}s · nominal request budget: {load.nominal_requests}\nHTTP/1.1, fresh connections, no redirects; one captured backend, not whole-Service balancing. Requested pacing may catch up, not an exact per-second ceiling.\nSaved locally: up to 100 records / 4 MiB / 30 days, 32 KiB each. Save may prune verified owned records. Request path, query, header values and body are omitted.\nReview this exact intent. Run (F7) authorizes it once.",
                    multiline=True,
                )
            )
            self.query_one("#benchmark-editor", Vertical).display = False
            self.review_button.disabled = True
            self.edit_button.disabled = False
            self.run_button.disabled = False
            self.cancel_button.focus()
            self.status("Review ready. Cancel is selected; Run requires a deliberate action.")
        except AppError as error:
            self.status(str(error))
        except Exception:
            self.status("Review unavailable. Check captured identity, policy and permissions.")

    @on(Button.Pressed, "#benchmark-edit")
    def edit(self) -> None:
        if self.started or self._stopping:
            return
        self.owner.revoke_review()
        self.review = None
        self.run_button.disabled = True
        self.review_button.disabled = False
        self.edit_button.disabled = True
        self.query_one("#benchmark-editor", Vertical).display = True
        self.preview.update("")
        self.status("Edit the request/load, then obtain a fresh review.")

    @on(Button.Pressed, "#benchmark-run")
    def action_run_review(self) -> None:
        review = self.review
        if review is None or self.started or self.busy or self._stopping:
            return
        self.started = True
        self.review = None
        self._started_at = time.monotonic()
        self._duration_seconds = review.load.duration_seconds
        self.query_one("#benchmark-target", Input).value = "/"
        self.query_one("#benchmark-headers", TextArea).load_text("")
        self.query_one("#benchmark-body", TextArea).load_text("")
        self.run_button.disabled = self.edit_button.disabled = self.review_button.disabled = True
        self.cancel_button.focus()
        self._worker = asyncio.create_task(self._run(review))

    async def _run(self, review: BenchmarkReview) -> None:
        try:
            result = await self.owner.run(review)
            if self.preview.is_attached:
                self.preview.update(result_text(result))
            self.status(
                "Save failed; the in-memory result remains visible."
                if self.owner.save_failed
                else "Run finished. Saved results are available in :benchmarks."
            )
        except AppError as error:
            self.status(str(error))
        except Exception:
            self.status("Benchmark failed; no raw request or tool output is included here.")
        finally:
            self.finished = True
            self._finished_at = time.monotonic()
            if self.cancel_button.is_attached:
                self.cancel_button.label = "Back"
            self.refresh_progress()

    def refresh_progress(self) -> None:
        if self.progress.is_attached:
            elapsed = (
                0.0
                if self._started_at is None
                else (self._finished_at or time.monotonic()) - self._started_at
            )
            self.progress.update(
                safe_text(
                    f"State: {self.owner.state.value.replace('_', ' ')} · elapsed {elapsed:.1f}s · configured load {self._duration_seconds}s · {self.owner.message}"
                )
            )

    def validate_target(self) -> None:
        if not self._stopping and not self.finished and not self.owner.validate_target():
            self.request_stop()

    def request_stop(self) -> None:
        if self._stop_task is None:
            self._stopping = True
            self.run_button.disabled = self.review_button.disabled = self.edit_button.disabled = (
                True
            )
            self._stop_task = asyncio.create_task(self._stop())

    async def _stop(self) -> None:
        try:
            await self.owner.cancel()
            if self._worker is not None:
                if not self._worker.done():
                    self._worker.cancel()
                await finish_owned(asyncio.gather(self._worker, return_exceptions=True))
            await self.owner.stop_owned()
            if self.owner.result is not None and self.preview.is_attached:
                self.preview.update(result_text(self.owner.result))
                self.finished = True
                self._finished_at = self._finished_at or time.monotonic()
                self.cancel_button.label = "Back"
                self.status(
                    "The captured target or session ended; owned benchmark work was drained."
                )
            self._unsubscribe()
        finally:
            self.stopped()

    async def stop_owned(self) -> None:
        self.request_stop()
        assert self._stop_task is not None
        await finish_owned(self._stop_task)

    @on(Button.Pressed, "#benchmark-cancel")
    async def cancel(self) -> None:
        if self.started and not self.finished:
            await self.owner.cancel()
            if self._worker is not None:
                await finish_owned(asyncio.gather(self._worker, return_exceptions=True))
        else:
            await self.action_back()

    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_active:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()


class BenchmarkResultScreen(ModalScreen[None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "back", "Back", priority=True)]
    DEFAULT_CSS = """
    BenchmarkResultScreen { align: center middle; background: $background 80%; }
    #benchmark-result-form { width: 98%; height: 96%; border: solid $primary; background: $surface; }
    #benchmark-result-scroll { height: 1fr; padding: 0 1; }
    #benchmark-result-scroll Static { height: auto; }
    #benchmark-result-back { height: 1; border: none; }
    """

    def __init__(self, result: BenchmarkResult) -> None:
        super().__init__()
        self.result = result

    def compose(self) -> ComposeResult:
        with Vertical(id="benchmark-result-form"):
            with VerticalScroll(id="benchmark-result-scroll"):
                yield Static(result_text(self.result), markup=False)
            yield Button("Back", id="benchmark-result-back", compact=True)

    @on(Button.Pressed, "#benchmark-result-back")
    def action_back(self) -> None:
        self.dismiss()


class BenchmarkBrowserScreen(ModalScreen[None]):
    AUTO_FOCUS = "#benchmarks-table"
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "back", "Back", priority=True)]
    DEFAULT_CSS = """
    BenchmarkBrowserScreen { align: center middle; background: $background 80%; }
    #benchmarks-form { width: 98%; height: 96%; border: solid $primary; padding: 0 1; background: $surface; }
    #benchmarks-title, #benchmarks-buttons { height: 1; }
    #benchmarks-filter { height: 3; }
    #benchmarks-table { height: 1fr; min-height: 1; }
    #benchmarks-status { height: auto; max-height: 2; }
    #benchmarks-buttons Button { height: 1; border: none; min-width: 8; }
    BenchmarkBrowserScreen.compact #benchmarks-filter { height: 1; border: none; }
    """

    def __init__(
        self,
        store: BenchmarkStore,
        *,
        chrome: WorkspaceChrome,
        trail: tuple[str, ...],
        stopped: Callable[[], None],
    ) -> None:
        super().__init__()
        self.store, self.chrome, self.trail, self.stopped = store, chrome, trail, stopped
        self.entries: tuple[SavedBenchmark, ...] = ()
        self.records: tuple[SavedBenchmark, ...] = ()
        self.table = ArtifactTable(id="benchmarks-table", cursor_type="row")
        self.filter = ForwardInput(
            placeholder="Filter context, namespace, Service, Pod, method, state or run ID",
            id="benchmarks-filter",
            max_length=1024,
        )
        self.status = Static("Reading local saved results…", id="benchmarks-status", markup=False)
        self._browser_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._stop_task: asyncio.Task[None] | None = None
        self._confirmation: ArtifactConfirmation | None = None

    @property
    def busy(self) -> bool:
        """A dismissed child can still have an owned completion callback to drain."""
        return self._browser_task is not None and not self._browser_task.done()

    def compose(self) -> ComposeResult:
        with Vertical(id="benchmarks-form"):
            yield Static(
                "Saved HTTP benchmarks · local files only · 100 records / 4 MiB / 30 days",
                id="benchmarks-title",
                markup=False,
            )
            yield self.filter
            yield self.table
            yield self.status
            with Horizontal(id="benchmarks-buttons"):
                for name in ("Open", "Delete", "Refresh", "Back"):
                    yield Button(name, id="benchmarks-" + name.lower(), compact=True)

    def on_mount(self) -> None:
        self.on_resize()
        self.table.add_columns(
            "Finished UTC", "Context", "Service / Pod", "Method", "State", "Attempts"
        )
        self.action_refresh()

    def on_resize(self) -> None:
        self.set_class(self.size.height < 18, "compact")

    def selected(self) -> SavedBenchmark | None:
        return (
            self.entries[self.table.cursor_row]
            if 0 <= self.table.cursor_row < len(self.entries)
            else None
        )

    def _start(self, operation: Callable[[], Awaitable[None]]) -> None:
        if not self._stopped and not self.busy:
            self._browser_task = asyncio.create_task(self._operate(operation))

    async def _operate(self, operation: Callable[[], Awaitable[None]]) -> None:
        try:
            await operation()
        except AppError as error:
            self.status.update(safe_text(str(error)))
        except Exception:
            self.status.update(
                "Local benchmark operation failed; no raw file content is displayed."
            )

    @on(Button.Pressed, "#benchmarks-refresh")
    def action_refresh(self) -> None:
        self._start(self._refresh)

    async def _refresh(self) -> None:
        entries = await self.store.scan()
        if self._stopped:
            return
        self.records = entries
        self._render_entries()
        self.status.update(
            f"{len(entries)} saved results. Opening this browser never starts tools, connects or prunes files."
        )

    def _render_entries(self) -> None:
        selected = self.selected()
        row, x, y = self.table.cursor_row, self.table.scroll_x, self.table.scroll_y
        query = self.filter.value.casefold()
        self.entries = tuple(
            saved
            for saved in self.records
            if query
            in " ".join(
                (
                    str(saved.result.run_id),
                    saved.result.target.context,
                    saved.result.target.namespace,
                    saved.result.target.service_name or "",
                    saved.result.target.pod_name,
                    saved.result.method,
                    saved.result.completion.replace("_", " "),
                )
            ).casefold()
        )
        self.table.clear()
        for saved in self.entries:
            result = saved.result
            self.table.add_row(
                *[
                    safe_text(value)
                    for value in (
                        result.finished_at.isoformat(),
                        result.target.context,
                        result.target.service_name or result.target.pod_name,
                        result.method,
                        result.completion.replace("_", " "),
                        str(result.metrics.attempts) if result.metrics else "N/A",
                    )
                ],
                key=str(result.run_id),
            )
        if self.entries:
            index = next(
                (
                    index
                    for index, saved in enumerate(self.entries)
                    if selected is not None and saved.ref == selected.ref
                ),
                min(row, len(self.entries) - 1),
            )
            self.table.move_cursor(row=index, scroll=False)
        selection = self.selected()

        def restore() -> None:
            if self.is_attached and self.selected() == selection:
                self.table.scroll_to(x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    @on(Input.Changed, "#benchmarks-filter")
    def changed_filter(self) -> None:
        self._render_entries()

    @on(Input.Submitted, "#benchmarks-filter")
    def finish_filter(self) -> None:
        self.table.focus()

    @on(DataTable.RowSelected, "#benchmarks-table")
    @on(Button.Pressed, "#benchmarks-open")
    def action_open(self) -> None:
        selected = self.selected()
        if selected is None:
            self.status.update("Select a saved benchmark result first.")
            return

        async def open_result() -> None:
            result = await self.store.read(selected.ref)
            if not self._stopped:
                self.app.push_screen(BenchmarkResultScreen(result))

        self._start(open_result)

    @on(Button.Pressed, "#benchmarks-delete")
    def action_delete(self) -> None:
        selected = self.selected()
        if selected is None:
            self.status.update("Select a saved benchmark result first.")
            return

        async def delete() -> None:
            answer = asyncio.get_running_loop().create_future()
            self._confirmation = ArtifactConfirmation(
                message=f"Delete this saved local benchmark?\n{selected.ref.name}\nThis cannot be undone.",
                label="Delete",
            )
            self.app.push_screen(
                self._confirmation,
                lambda confirmed: answer.set_result(bool(confirmed)) if not answer.done() else None,
            )
            if await answer:
                await self.store.delete(selected.ref, confirmed=True)
                await self._refresh()
            self._confirmation = None

        self._start(delete)

    async def _stop(self) -> None:
        self._stopped = True
        if self._confirmation is not None and self.app.screen is self._confirmation:
            self._confirmation.dismiss(False)
        if self._browser_task is not None:
            self._browser_task.cancel()
            await finish_owned(asyncio.gather(self._browser_task, return_exceptions=True))
        self.stopped()

    async def stop_owned(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await finish_owned(self._stop_task)

    @on(Button.Pressed, "#benchmarks-back")
    async def action_back(self) -> None:
        await self.stop_owned()
        if self.is_active:
            self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()
