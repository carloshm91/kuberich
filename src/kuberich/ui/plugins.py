"""Deliberate local-plugin catalogue, typed review and app-owned job controls."""

import asyncio
import re
from typing import TYPE_CHECKING, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static

from kuberich.adapters.editing import file_worker
from kuberich.adapters.plugin_files import load_plugins
from kuberich.config.plugins import plugins_from
from kuberich.domain.plugins import Plugin, PluginSelection, plugin_bindings
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessResult
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.plugins import PluginJob, PluginManager, PluginRequest, PluginSource
from kuberich.services.processes import ProcessRunner, TargetGuard, _finish_owned
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.presentation import FrameTable

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp


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
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "cancel", "Cancel", priority=True)]
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


class PluginController:
    def __init__(self, app: "KubeRichApp") -> None:
        self.app = app
        self.manager = PluginManager(app.commands.policy)
        self.plugins: tuple[Plugin, ...] = ()
        self._context: str | None = None
        self._loader: asyncio.Task[None] | None = None
        self._opening: asyncio.Task[None] | None = None
        self._closed = False
        self._loaded = False
        self._loaders: set[asyncio.Task[None]] = set()
        self.error: str | None = None

    def refresh(self) -> None:
        app = self.app
        context = app._theme_context()
        if self._closed or (self._loaded and context == self._context) or app.preferences is None:
            return
        self._context = context
        self._loaded = True
        self.plugins = ()
        if self._loader is not None:
            self._loader.cancel()
        if "plugins" not in app.preferences.document.extensions:
            return
        self._loader = asyncio.create_task(self._load(context))
        self._loaders.add(self._loader)
        self._loader.add_done_callback(self._loaders.discard)

    async def _load(self, context: str | None) -> None:
        preferences = self.app.preferences
        assert preferences is not None
        try:
            plugins = await file_worker(
                lambda: load_plugins(
                    plugins_from(preferences.document, preferences.location.path.parent),
                    context,
                    keys=self.app.navigation.keys,
                )
            )
        except (AppError, OSError) as error:
            if self._context == context:
                self.error = (
                    str(error)
                    if isinstance(error, AppError)
                    else "Cannot read configured plugin files."
                )
            return
        if self._context == context and not self._closed:
            self.plugins, self.error = plugins, None

    def resource(self) -> str | None:
        scope = self.app.workspace.store.observation.scope
        return (
            scope.resource.api_version + "/" + scope.resource.name
            if scope is not None and self.app._resource_name != "contexts"
            else None
        )

    def bindings(self) -> tuple[tuple[str, str], ...]:
        if self.app._resource_name == "contexts":
            return ()
        return plugin_bindings(self.plugins, self.resource(), self.app.navigation.keys)

    def open(self, name: str | None = None) -> None:
        if self._closed or (self._opening is not None and not self._opening.done()):
            return
        self.refresh()
        self._opening = asyncio.create_task(self._open(name))

    def capture_source(self) -> PluginSource:
        app = self.app
        view, client = app.workspace.store.observation, app.sessions.client
        if client is None or view.scope is None:
            raise AppError("Select a connected context before running a plugin.")
        local_contexts = app._resource_name == "contexts"
        resource = None if local_contexts else view.scope.resource
        if resource is not None and resource.name != app._resource_name:
            raise AppError("The resource view is loading; wait before reviewing a plugin.")
        generic = app._generic_selection
        if (
            resource is not None
            and generic is not None
            and (generic.group != resource.group or generic.version not in {None, resource.version})
        ):
            raise AppError("The resource version is loading; wait before reviewing a plugin.")
        uid = app._active_table.capture_viewport().selected
        selected = (
            app._capture_target() if uid is not None and app._resource_name != "contexts" else None
        )
        target = None
        columns: tuple[tuple[str, str], ...] = ()
        if selected is not None:
            client, resource, _, target, current = selected
            table = app._active_table
            columns = tuple(
                (re.sub(r"[^A-Z0-9_-]", "_", column.label.plain.upper()), str(value))
                for column, value in zip(
                    table.columns.values(), table.get_row(target.uid), strict=True
                )
                if re.match(r"[A-Za-z]", column.label.plain)
            )
        else:

            def current() -> bool:
                observation = app.workspace.store.observation
                return (
                    app.sessions.client is client
                    and observation.scope == view.scope
                    and observation.revision == view.revision
                )

        context_data = app.sessions.catalog.contexts[client.context.name].data
        selection = PluginSelection(
            client.context.name,
            resource.api_version + "/" + resource.name if resource is not None else None,
            target,
            variables=(
                ("CLUSTER", str(context_data.get("cluster", ""))),
                ("USER", str(context_data.get("user", ""))),
                ("FILTER", app.filter_input.value),
            ),
            columns=columns,
            namespace=None if local_contexts else view.scope.namespace,
        )
        return PluginSource(
            client, resource, selection, app.commands.policy, current, app._process_environment
        )

    async def _open(self, name: str | None) -> None:
        original_client = self.app.sessions.client
        original_scope = self.app.workspace.store.observation.scope
        try:
            source = self.capture_source() if name is not None else None
        except AppError as error:
            self.app._set_status(str(error))
            return
        if self._loader is not None:
            await asyncio.shield(self._loader)
        app = self.app
        if (
            self._closed
            or isinstance(app.screen, ModalScreen)
            or app.sessions.client is not original_client
            or app.workspace.store.observation.scope != original_scope
        ):
            return
        if self.error is not None:
            app._set_status(self.error)
            return
        if name is None:
            app.push_screen(
                PluginCatalogue(
                    tuple(plugin for plugin in self.plugins if plugin.applies(self.resource()))
                ),
                lambda result: self.open(result) if result is not None else None,
            )
            return
        plugin = next((plugin for plugin in self.plugins if plugin.name == name), None)
        try:
            if plugin is None:
                raise AppError("Plugin is not configured for this context. Use :plugins.")
            plugin.require_access(app.commands.policy.read_only)
            assert source is not None
            source.require(plugin)
            app.push_screen(PluginScreen(plugin, source, self.manager))
        except AppError as error:
            app._set_status(str(error))

    async def close(self) -> None:
        self._closed = True
        for task in (self._opening, *tuple(self._loaders)):
            if task is not None:
                if not task.done():
                    task.cancel()
                await _finish_owned(asyncio.gather(task, return_exceptions=True))
        await self.manager.close()
