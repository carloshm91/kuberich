"""Actual local-plugin catalogue, review and job screens loaded on request."""

import asyncio
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static

from kuberich.domain.plugins import Plugin
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessResult
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.plugins import PluginJob, PluginManager, PluginRequest, PluginSource
from kuberich.services.processes import ProcessRunner, TargetGuard, _finish_owned
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.presentation import FrameTable


class PluginCatalogue(ModalScreen[str | None]):
    AUTO_FOCUS = "#plugin-catalogue"
    DEFAULT_CSS = """
    PluginCatalogue { align: center middle; background: $background 80%; }
    #plugin-list { width: 96%; height: 90%; border: solid $primary; background: $surface; }
    #plugin-catalogue { height: 1fr; }
    #plugin-list Static { height: auto; max-height: 3; }
    #plugin-back { height: 1; border: none; }
    """

    def __init__(self, plugins: tuple[Plugin, ...]) -> None:
        super().__init__()
        self.plugins = plugins

    def compose(self) -> ComposeResult:
        with Vertical(id="plugin-list"):
            yield Static("Local plugins · Enter reviews · Escape returns", markup=False)
            yield Static(
                "Unsandboxed local code: review files before trusting them. A selected connection is required to run.",
                markup=False,
            )
            yield FrameTable(id="plugin-catalogue", cursor_type="row", zebra_stripes=True)
            yield Button("Back", id="plugin-back", compact=True)

    def on_mount(self) -> None:
        table = self.query_one(FrameTable)
        table.add_columns("Name", "Mode", "Key", "Classification", "Scopes", "Description")
        for plugin in self.plugins:
            table.add_row(
                *(
                    safe_text(value)
                    for value in (
                        plugin.name,
                        plugin.mode.name.lower(),
                        plugin.shortcut or "—",
                        "trusted read-only"
                        if plugin.trusted_read_only and not plugin.dangerous
                        else "unclassified/write",
                        ", ".join(plugin.scopes),
                        plugin.description,
                    )
                ),
                key=plugin.name,
            )

    @on(DataTable.RowSelected)
    def selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.dismiss(str(event.row_key.value))

    @on(Button.Pressed, "#plugin-back")
    def back(self) -> None:
        self.dismiss(None)


class PluginScreen(ModalScreen[None]):
    AUTO_FOCUS = "#plugin-cancel"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    PluginScreen { align: center middle; background: $background 80%; }
    #plugin-form { width: 96%; max-width: 110; height: 94%; border: round $primary;
        padding: 0 1; background: $surface; }
    #plugin-fields { height: 1fr; }
    #plugin-fields Static { height: auto; }
    #plugin-buttons { height: 1; }
    #plugin-buttons Button { height: 1; border: none; min-width: 10; }
    #plugin-feedback { height: auto; max-height: 3; }
    """

    def __init__(self, plugin: Plugin, source: PluginSource, manager: PluginManager) -> None:
        super().__init__()
        self.plugin, self.source, self.manager = plugin, source, manager
        self.review: PluginRequest | None = None
        self.job: PluginJob | None = None
        self.operation: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="plugin-form"):
            yield Static(
                safe_text(
                    f"Plugin: {self.plugin.name} · {self.plugin.mode.name.lower()} · {self.source.selection.context}"
                )
            )
            with VerticalScroll(id="plugin-fields"):
                yield Static(safe_text(self.plugin.description))
                selection = self.source.selection
                target = selection.target
                yield Static(
                    safe_text(
                        f"Scope: {selection.resource or 'context'} · namespace: "
                        f"{target.namespace or 'cluster' if target is not None else selection.namespace or 'all/cluster'}\n"
                        + (
                            f"Target: {target.resource}/{target.name}\nUID: {target.uid}"
                            if target is not None
                            else "Target: context/scope only; no selected object"
                        ),
                        multiline=True,
                    ),
                    id="plugin-captured-target",
                )
                yield Static(
                    "Runs unsandboxed with your local user privileges. Confirmation is not a sandbox. Foreground output goes directly to your terminal.",
                    markup=False,
                )
                for index, item in enumerate(self.plugin.inputs):
                    name = f"plugin-input-{index}"
                    yield Static(safe_text(item.label))
                    if item.kind == "bool":
                        yield Checkbox(
                            safe_text(item.label),
                            value=item.default is True or item.default == "true",
                            id=name,
                        )
                    elif item.kind == "dropdown":
                        yield Select(
                            ((safe_text(value), value) for value in item.options),
                            value=item.default if isinstance(item.default, str) else Select.NULL,
                            id=name,
                        )
                    else:
                        yield ForwardInput(
                            "" if item.default is None else str(item.default),
                            max_length=8192,
                            id=name,
                        )
                yield Static("", markup=False, id="plugin-preview")
                yield Static("", markup=False, id="plugin-output")
            yield Static(
                "Review inputs, then explicitly run. Cancel is the default.",
                markup=False,
                id="plugin-feedback",
            )
            with Horizontal(id="plugin-buttons"):
                yield Button("Review", id="plugin-review", compact=True)
                yield Button("Run", id="plugin-run", compact=True, variant="warning", disabled=True)
                yield Button("Cancel", id="plugin-cancel", compact=True)

    def _status(self, message: str) -> None:
        self.query_one("#plugin-feedback", Static).update(safe_text(message))

    def _inputs(self) -> dict[str, object]:
        values: dict[str, object] = {}
        for index, item in enumerate(self.plugin.inputs):
            widget = self.query_one(f"#plugin-input-{index}")
            if isinstance(widget, (Input, Checkbox)):
                values[item.name] = widget.value
            elif isinstance(widget, Select):
                values[item.name] = None if widget.value is Select.NULL else widget.value
        return values

    @on(Input.Changed)
    @on(Checkbox.Changed)
    @on(Select.Changed)
    def changed(self) -> None:
        self.source.discard(self.review)
        self.review = None
        self.query_one("#plugin-run", Button).disabled = True

    @on(Button.Pressed, "#plugin-review")
    def prepare(self) -> None:
        if self.operation is None or self.operation.done():
            self.source.discard(self.review)
            self.review = None
            self.query_one("#plugin-run", Button).disabled = True
            self.operation = asyncio.create_task(self._prepare(self._inputs()))

    async def _prepare(self, values: dict[str, object]) -> None:
        try:
            review = await self.source.prepare(self.plugin, values)
        except (AppError, OSError) as error:
            self._status(
                str(error) if isinstance(error, AppError) else "Cannot prepare local plugin state."
            )
            return
        if values != self._inputs():
            self.source.discard(review)
            self._status("Inputs changed. Review them again.")
            return
        self.review = review
        self.query_one("#plugin-preview", Static).update(
            safe_text(
                f"Executable: {self.plugin.command}\nDirectory: {self.plugin.directory}\n"
                f"Mode: {self.plugin.mode.name.lower()} · timeout {self.plugin.timeout:g}s · output {self.plugin.output_limit} bytes\n"
                "The command uses the captured connection. Arguments and input values are concealed in this review.",
                multiline=True,
            )
        )
        self.query_one("#plugin-run", Button).disabled = False
        self.set_focus(self.query_one("#plugin-cancel"))
        self._status("Review complete. Run grants this local command your user privileges.")

    @on(Button.Pressed, "#plugin-run")
    def run_plugin(self) -> None:
        if (
            self.review is None
            or self.job is not None
            or (self.operation is not None and not self.operation.done())
        ):
            return

        async def handoff(
            runner: ProcessRunner, command: ProcessCommand, guard: TargetGuard, timeout: float
        ) -> ProcessResult:
            return await terminal_handoff(self.app, runner, command, guard=guard, timeout=timeout)

        try:
            self.job = self.manager.start(self.source, self.review, confirmed=True, handoff=handoff)
        except AppError as error:
            self._status(str(error))
            return
        self.review = None
        self.query_one("#plugin-review", Button).disabled = True
        self.query_one("#plugin-run", Button).disabled = True
        for widget in self.query("Input, Checkbox, Select"):
            widget.disabled = True
        if self.plugin.mode is ProcessMode.BACKGROUND:
            self._status(
                f"Background job {self.job.number} started. :pluginjobs shows output and Stop."
            )
            self.query_one("#plugin-cancel", Button).label = "Back"
        else:
            self._status("Running. Cancel stops and drains the owned process group.")
            self.operation = asyncio.create_task(self._wait(self.job))

    async def _wait(self, job: PluginJob) -> None:
        await job.wait()
        self._status(f"{job.status} · exit {job.returncode}")
        self.query_one("#plugin-output", Static).update(safe_text(job.output, multiline=True))
        self.query_one("#plugin-cancel", Button).label = "Back"

    @on(Button.Pressed, "#plugin-cancel")
    async def action_cancel(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        if self.operation is not None and not self.operation.done():
            self.operation.cancel()
            await _finish_owned(asyncio.gather(self.operation, return_exceptions=True))
        self.source.discard(self.review)
        if self.job is not None and self.job.mode is not ProcessMode.BACKGROUND:
            await self.manager.stop(self.job)
        if self.job is None or self.job.mode is not ProcessMode.BACKGROUND:
            self.source.close()

    async def on_unmount(self) -> None:
        await self.stop_owned()


class PluginJobs(ModalScreen[None]):
    AUTO_FOCUS = "#plugin-jobs"
    DEFAULT_CSS = """
    PluginJobs { align: center middle; background: $background 80%; }
    #plugin-jobs-frame { width: 96%; height: 94%; border: solid $primary; background: $surface; }
    #plugin-jobs { height: 1fr; }
    #plugin-job-output { height: 1fr; }
    #plugin-job-output Static { height: auto; }
    #plugin-job-buttons { height: 1; }
    #plugin-job-buttons Button { height: 1; border: none; }
    """

    def __init__(self, manager: PluginManager) -> None:
        super().__init__()
        self.manager = manager
        self._snapshot: tuple[tuple[int, str], ...] = ()
        self._stopping: asyncio.Task[None] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="plugin-jobs-frame"):
            yield Static("Owned plugin jobs · Enter shows bounded output", markup=False)
            yield FrameTable(id="plugin-jobs", cursor_type="row")
            with VerticalScroll(id="plugin-job-output"):
                yield Static("", markup=False, id="plugin-job-text")
            with Horizontal(id="plugin-job-buttons"):
                yield Button("Stop selected", id="plugin-job-stop", compact=True)
                yield Button("Back", id="plugin-job-back", compact=True)

    def on_mount(self) -> None:
        self.query_one(FrameTable).add_columns("Job", "Plugin", "Mode", "Status", "Exit")
        self.refresh_jobs()
        self.set_interval(0.2, self.refresh_jobs)

    def refresh_jobs(self) -> None:
        snapshot = tuple((job.number, job.status) for job in self.manager.jobs)
        if snapshot == self._snapshot:
            return
        self._snapshot = snapshot
        table = self.query_one(FrameTable)
        row = table.cursor_row
        table.clear()
        for job in self.manager.jobs:
            table.add_row(
                *(
                    safe_text(str(value))
                    for value in (
                        job.number,
                        job.name,
                        job.mode.name.lower(),
                        job.status,
                        job.returncode,
                    )
                ),
                key=str(job.number),
            )
        table.move_cursor(row=min(row, max(0, table.row_count - 1)))

    def selected_job(self) -> PluginJob | None:
        table = self.query_one(FrameTable)
        if table.row_count:
            number = int(str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value))
            return next((job for job in self.manager.jobs if job.number == number), None)
        return None

    @on(DataTable.RowSelected)
    def show_output(self, event: DataTable.RowSelected) -> None:
        event.stop()
        job = self.selected_job()
        if job is not None:
            self.query_one("#plugin-job-text", Static).update(
                safe_text(f"{job.status} · exit {job.returncode}\n{job.output}", multiline=True)
            )

    @on(Button.Pressed, "#plugin-job-stop")
    def stop_job(self) -> None:
        job = self.selected_job()
        if job is not None and (self._stopping is None or self._stopping.done()):
            self._stopping = asyncio.create_task(self.manager.stop(job))

    @on(Button.Pressed, "#plugin-job-back")
    def back(self) -> None:
        self.dismiss()

    async def on_unmount(self) -> None:
        if self._stopping is not None:
            await _finish_owned(asyncio.gather(self._stopping, return_exceptions=True))
