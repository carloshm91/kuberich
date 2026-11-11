"""Cached Helm chart browsing and explicit application-owned repository controls."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import ScreenSuspend
from textual.widgets import Button, Checkbox, DataTable, Input, Select, Static

from kuberich.domain.helm import HelmReleaseKey
from kuberich.domain.helm_catalog import (
    CatalogSnapshot,
    ChartVersion,
    HelmRepository,
    RepositoryCredentials,
)
from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.ui.editing import DisclosureCheckbox
from kuberich.ui.helm_lifecycle import HelmLifecycleScreen
from kuberich.ui.nested import CommandWorkspace

if TYPE_CHECKING:
    from kuberich.domain.helm import HelmRequest
    from kuberich.services.helm import HelmService
    from kuberich.services.processes import ProcessRunner


class _CatalogOwner(CommandWorkspace):
    sensitive: ClassVar[bool] = True
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous", show=False, priority=True),
    ]

    def __init__(self, service: HelmService, request: HelmRequest) -> None:
        super().__init__()
        self.service, self.request = service, request
        self.invalidated = False
        self._operation_task: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._generation = 0

    @property
    def operation_count(self) -> int:
        return int(self._operation_task is not None and not self._operation_task.done())

    def _controls(self) -> None:
        pass

    def _clear_private(self) -> None:
        pass

    def _message(self, message: str) -> None:
        if self.is_attached:
            for widget in self.query(".helm-catalog-status"):
                if isinstance(widget, Static):
                    widget.update(safe_text(message))

    def _show_problem(self, message: str) -> None:
        self._message(message)

    def _current(self, generation: int) -> bool:
        return (
            not self.invalidated
            and generation == self._generation
            and self.service.current(self.request)
        )

    def _start(self, operation: Coroutine[Any, Any, None]) -> None:
        if self.invalidated or (
            self._operation_task is not None and not self._operation_task.done()
        ):
            operation.close()
            return
        self._operation_task = asyncio.create_task(operation)
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    def _retired(self, task: asyncio.Task[None]) -> None:
        if self._operation_task is not task:
            if not task.cancelled():
                task.exception()
            return
        if (
            not task.cancelled()
            and (error := task.exception()) is not None
            and not self.invalidated
        ):
            self._show_problem(
                str(error)
                if isinstance(error, AppError)
                else "Helm catalog operation failed; private details were withheld."
            )
        if self._operation_task is task:
            self._operation_task = None
        self._controls()

    def _retire(self) -> None:
        self._generation += 1
        self.service.cancel_review()
        self._clear_private()

    async def _stop_operations(self) -> None:
        self._retire()
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        self._controls()

    def validate_target(self) -> None:
        if not self.invalidated and not self.service.current(self.request):
            self.invalidated = True
            self._retire()
            if self._operation_task is not None:
                self._operation_task.cancel()
            self._message("Helm scope changed; reopen the catalog for the current connection.")
        self._controls()

    async def on_screen_suspend(self, event: ScreenSuspend) -> None:
        await self._stop_operations()

    async def stop_owned(self) -> None:
        self.invalidated = True
        if self._stopping is None:
            self._stopping = asyncio.create_task(self._stop_operations())
        await finish_owned(self._stopping)

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def on_unmount(self) -> None:
        await self.stop_owned()


class HelmCatalogScreen(_CatalogOwner):
    """Only selecting an exact version fetches bytes; search reads the cached snapshot."""

    AUTO_FOCUS = "#helm-catalog-releases"
    DEFAULT_CSS = """
    HelmCatalogScreen { align: center middle; background: $background 80%; }
    #helm-catalog-form { width: 98%; height: 96%; border: solid $primary; background: $surface; padding: 0 1; }
    #helm-catalog-heading, #helm-catalog-search, #helm-catalog-name, #helm-catalog-repository, .helm-catalog-status { height: 1; }
    #helm-catalog-search, #helm-catalog-name, #helm-catalog-repository { border: none; padding: 0; }
    #helm-catalog-releases { height: 1fr; min-height: 1; border: none; }
    #helm-catalog-buttons { height: 2; layout: grid; grid-size: 3; grid-rows: 1 1; }
    #helm-catalog-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    HelmCatalogScreen .nested-command-bar { height: 1; border-top: none; border-bottom: none; }
    """

    def __init__(
        self,
        *,
        service: HelmService,
        request: HelmRequest,
        runner: ProcessRunner,
        address: HelmReleaseKey | None = None,
        operation: HelmLifecycleKind = HelmLifecycleKind.INSTALL,
    ) -> None:
        if operation not in {HelmLifecycleKind.INSTALL, HelmLifecycleKind.UPGRADE}:
            raise AppError("Chart selection supports install or upgrade.")
        if operation is HelmLifecycleKind.UPGRADE and address is None:
            raise AppError("Select an existing release before choosing an upgrade chart.")
        super().__init__(service, request)
        self.runner, self.address, self.operation = runner, address, operation
        self.snapshot = CatalogSnapshot()
        self.problem: str | None = None
        self.table: DataTable[Text] = DataTable(id="helm-catalog-releases", cursor_type="row")
        self._chart_rows: dict[str, ChartVersion] = {}
        self._render_tasks: set[asyncio.Task[None]] = set()
        self._render_generation = 0
        self._selection_anchor: ChartVersion | None = None
        self._child: _CatalogOwner | HelmLifecycleScreen | None = None

    @property
    def operation_count(self) -> int:
        return super().operation_count + sum(not task.done() for task in self._render_tasks)

    def compose(self) -> ComposeResult:
        with Vertical(id="helm-catalog-form"):
            yield Static(
                safe_text(
                    f"Helm charts · {self.request.scope.session.context} · {self.request.scope.namespace or 'all namespaces'}"
                ),
                id="helm-catalog-heading",
            )
            yield Input(placeholder="Search cached charts and versions", id="helm-catalog-search")
            yield Select(
                [("All repositories", "")],
                value="",
                allow_blank=False,
                id="helm-catalog-repository",
            )
            if self.operation is HelmLifecycleKind.INSTALL:
                yield Input(placeholder="New release name", id="helm-catalog-name")
            else:
                assert self.address is not None
                yield Static(
                    safe_text(f"Upgrade {self.address.namespace}/{self.address.name}"),
                    id="helm-catalog-name",
                )
            yield self.table
            yield Static(
                "Loading cached catalog; no repository refresh or tool probe.",
                markup=False,
                classes="helm-catalog-status",
            )
            with Horizontal(id="helm-catalog-buttons"):
                for label, name in (
                    ("Add repository", "add"),
                    ("Update repository", "update"),
                    ("Remove repository", "remove"),
                    ("Select version", "select"),
                    ("Reload cache", "refresh"),
                    ("Back", "back"),
                ):
                    yield Button(label, id="helm-catalog-" + name, compact=True)
            yield from self.command_bar()

    def on_mount(self) -> None:
        self.table.add_columns("REPOSITORY", "CHART", "VERSION", "PACKAGE SHA256")
        self.refresh_catalog()

    def _controls(self) -> None:
        if not self.table.is_attached:
            return
        busy = bool(self.operation_count)
        blocked = self.invalidated or self.service.policy.read_only or self.problem is not None
        repository = self.query_one("#helm-catalog-repository", Select).value
        selected = self.selected_chart()
        for name in ("add", "update", "remove", "select"):
            self.query_one("#helm-catalog-" + name, Button).disabled = (
                busy
                or blocked
                or (name in {"update", "remove"} and not repository)
                or (name == "select" and selected is None)
            )
        self.query_one("#helm-catalog-refresh", Button).disabled = busy or self.invalidated

    def selected_chart(self) -> ChartVersion | None:
        if self.table.row_count and self.table.cursor_row < self.table.row_count:
            key = self.table.ordered_rows[self.table.cursor_row].key.value
            return self._chart_rows.get(str(key))
        return None

    def _publish(self, snapshot: CatalogSnapshot) -> None:
        self.problem = None
        self.snapshot = snapshot
        field = self.query_one("#helm-catalog-repository", Select)
        selected = field.value
        field.set_options(
            [("All repositories", ""), *((item.name, item.name) for item in snapshot.repositories)]
        )
        field.value = (
            selected if selected in {"", *(item.name for item in snapshot.repositories)} else ""
        )
        self._schedule_render()

    def _schedule_render(self) -> None:
        if self.invalidated or not self.table.is_attached:
            return
        self._render_generation += 1
        if not any(not task.done() for task in self._render_tasks):
            self._selection_anchor = self.selected_chart()
        for task in tuple(self._render_tasks):
            task.cancel()
        task = asyncio.create_task(self._draw_catalog(self._render_generation))
        self._render_tasks.add(task)
        task.add_done_callback(self._rendered)
        self._controls()

    async def _draw_catalog(self, generation: int) -> None:
        selected = self._selection_anchor
        row = self.table.cursor_row
        x, y = self.table.scroll_x, self.table.scroll_y
        repository = self.query_one("#helm-catalog-repository", Select).value
        charts = self.service.catalog.search(self.query_one("#helm-catalog-search", Input).value)
        charts = tuple(item for item in charts if not repository or item.repository == repository)
        self.table.clear()
        self._chart_rows = {}
        selected_key = None
        for index, item in enumerate(charts):
            key = hashlib.sha256(repr(item).encode()).hexdigest()
            self._chart_rows[key] = item
            self.table.add_row(
                *(
                    safe_text(value)
                    for value in (item.repository, item.name, item.version, item.sha256)
                ),
                key=key,
            )
            if item == selected:
                selected_key = key
            if index % 64 == 63:
                await asyncio.sleep(0)
                if generation != self._render_generation or self.invalidated:
                    return
        if selected_key is not None:
            self.table.move_cursor(row=self.table.get_row_index(selected_key), scroll=False)
        elif charts:
            self.table.move_cursor(row=min(row, len(charts) - 1), scroll=False)
        self.table.scroll_to(x=x, y=y, animate=False, immediate=True)
        self._selection_anchor = self.selected_chart()
        self._message(
            self.problem
            or f"{len(charts)} cached versions · select an exact version to download and review {self.operation.value}."
        )

    def _show_problem(self, message: str) -> None:
        self.problem = message
        self._message(message)

    def _rendered(self, task: asyncio.Task[None]) -> None:
        self._render_tasks.discard(task)
        if (
            not task.cancelled()
            and (error := task.exception()) is not None
            and not self.invalidated
        ):
            self._show_problem(
                str(error) if isinstance(error, AppError) else "Cached Helm chart rendering failed."
            )
        self._controls()

    @on(Input.Changed, "#helm-catalog-search")
    @on(Select.Changed, "#helm-catalog-repository")
    def filter_changed(self) -> None:
        self._schedule_render()

    @on(DataTable.RowHighlighted, "#helm-catalog-releases")
    def row_highlighted(self) -> None:
        self._controls()

    @on(Button.Pressed, "#helm-catalog-refresh")
    def refresh_catalog(self) -> None:
        self.problem = None
        self._retire()
        self._start(self._load(self._generation))

    async def _load(self, generation: int) -> None:
        snapshot = await self.service.catalog.load()
        if self._current(generation):
            self._publish(snapshot)

    @on(Button.Pressed, "#helm-catalog-add")
    def add_repository(self) -> None:
        self._repository_action("add")

    @on(Button.Pressed, "#helm-catalog-update")
    def update_repository(self) -> None:
        self._repository_action("update")

    @on(Button.Pressed, "#helm-catalog-remove")
    def remove_repository(self) -> None:
        self._repository_action("remove")

    def _repository_action(self, action: str) -> None:
        if (
            self.invalidated
            or self.operation_count
            or self.service.policy.read_only
            or self.problem is not None
        ):
            return
        name = self.query_one("#helm-catalog-repository", Select).value
        repository = next((item for item in self.snapshot.repositories if item.name == name), None)
        if action != "add" and repository is None:
            self._message("Choose a repository before reviewing its update or removal.")
            return
        child = HelmRepositoryScreen(
            service=self.service,
            request=self.request,
            action=action,
            repository=repository,
            expected_generation=self.snapshot.generation,
        )
        self._child = child
        self.app.push_screen(child, self._repository_returned)

    def _repository_returned(self, result: None) -> None:
        self._child = None
        if not self.invalidated and self.service.current(self.request):
            self._publish(self.service.catalog.snapshot)

    @on(DataTable.RowSelected, "#helm-catalog-releases")
    @on(Button.Pressed, "#helm-catalog-select")
    def select_version(self) -> None:
        if (
            self.invalidated
            or self.operation_count
            or self.service.policy.read_only
            or self.problem is not None
        ):
            return
        chart = self.selected_chart()
        if chart is None:
            return
        try:
            address = self.address
            if self.operation is HelmLifecycleKind.INSTALL:
                if self.request.scope.namespace is None:
                    raise AppError(
                        "Choose a concrete namespace, then reopen Helm charts before installing."
                    )
                address = HelmReleaseKey(
                    self.request.scope.namespace, self.query_one("#helm-catalog-name", Input).value
                )
            assert address is not None
        except AppError as error:
            self._message(str(error))
            return
        self._retire()
        self._start(self._select(chart, address, self._generation))

    async def _select(self, chart: ChartVersion, address: HelmReleaseKey, generation: int) -> None:
        snapshot = await self.service.catalog.select(chart)
        if self._current(generation) and self.app.screen is self:
            child = HelmLifecycleScreen(
                service=self.service,
                request=self.request,
                address=address,
                operation=self.operation,
                chart=snapshot,
                runner=self.runner,
            )
            self._child = child
            self.app.push_screen(child, self._lifecycle_returned)

    def _lifecycle_returned(self, result: None) -> None:
        self._child = None
        self._controls()

    async def _stop_operations(self) -> None:
        self._render_generation += 1
        for task in tuple(self._render_tasks):
            task.cancel()
        await finish_owned(asyncio.gather(*tuple(self._render_tasks), return_exceptions=True))
        await super()._stop_operations()

    async def stop_owned(self) -> None:
        if self._child is not None:
            await self._child.stop_owned()
        await super().stop_owned()

    @on(Button.Pressed, "#helm-catalog-back")
    async def back(self) -> None:
        await self.action_back()


class HelmRepositoryScreen(_CatalogOwner):
    """Private registration fields and exact-generation repository effect reviews."""

    AUTO_FOCUS = "#helm-repository-cancel"
    DEFAULT_CSS = """
    HelmRepositoryScreen { align: center middle; background: $background 80%; }
    #helm-repository-form { width: 98%; height: 96%; border: solid $warning; background: $surface; padding: 0 1; }
    #helm-repository-fields { height: 1fr; min-height: 1; }
    #helm-repository-fields Static, #helm-repository-fields Checkbox { height: auto; }
    #helm-repository-fields Input, #helm-repository-fields Select { height: 3; }
    #helm-repository-heading, #helm-repository-status { height: 1; }
    #helm-repository-buttons { height: 1; }
    #helm-repository-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    HelmRepositoryScreen .nested-command-bar { height: 1; border-top: none; border-bottom: none; }
    """

    def __init__(
        self,
        *,
        service: HelmService,
        request: HelmRequest,
        action: str = "add",
        repository: HelmRepository | None = None,
        expected_generation: int = 0,
    ) -> None:
        if action not in {"add", "update", "remove"} or (action != "add" and repository is None):
            raise AppError("Choose an explicit repository registration or current-entry review.")
        super().__init__(service, request)
        self.action, self.repository, self.expected_generation = (
            action,
            repository,
            expected_generation,
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="helm-repository-form"):
            yield Static(
                "Helm repository · " + self.action, markup=False, id="helm-repository-heading"
            )
            with VerticalScroll(id="helm-repository-fields"):
                if self.action == "add":
                    yield Input(
                        placeholder="Application-owned repository name", id="helm-repository-name"
                    )
                    yield Select(
                        [("HTTPS chart repository", "http"), ("OCI registered chart path", "oci")],
                        value="http",
                        allow_blank=False,
                        id="helm-repository-kind",
                    )
                    yield Input(
                        placeholder="https://host/charts or oci://host/charts/name",
                        id="helm-repository-url",
                    )
                    yield DisclosureCheckbox(
                        "Allow plaintext only for this loopback development endpoint",
                        id="helm-repository-loopback",
                    )
                    yield Input(
                        placeholder="Optional absolute CA certificate path", id="helm-repository-ca"
                    )
                    yield Select(
                        [
                            ("Anonymous", "none"),
                            ("Private Basic credentials", "basic"),
                            ("Explicit bearer token", "bearer"),
                        ],
                        value="none",
                        allow_blank=False,
                        id="helm-repository-auth",
                    )
                    yield Input(
                        placeholder="Private username", password=True, id="helm-repository-username"
                    )
                    yield Input(
                        placeholder="Private password", password=True, id="helm-repository-password"
                    )
                    yield Input(
                        placeholder="Private bearer token",
                        password=True,
                        id="helm-repository-token",
                    )
                    yield Input(
                        placeholder="Additional approved token origins (comma-separated)",
                        id="helm-repository-token-origins",
                    )
                    yield Input(
                        placeholder="Additional approved download origins (comma-separated)",
                        id="helm-repository-download-origins",
                    )
                    yield Static(
                        "Only this application's catalog is changed. OCI registration requires a chart repository path; registry-wide discovery is not assumed.",
                        markup=False,
                    )
                else:
                    assert self.repository is not None
                    yield Static(
                        safe_text(
                            f"Repository: {self.repository.name}\nURL: {self.repository.url}\nKind: {self.repository.kind.value}\nIndex identity: {self.repository.revision}\nCatalog generation: {self.expected_generation}",
                            multiline=True,
                        )
                    )
                    yield Static(
                        "Update fetches and replaces this exact application-owned cache entry."
                        if self.action == "update"
                        else "Remove retires this application's repository entry, cached versions and private credentials. Remote repository contents are unchanged.",
                        markup=False,
                    )
            yield Static(
                "Review the selected repository before confirming.",
                markup=False,
                classes="helm-catalog-status",
                id="helm-repository-status",
            )
            with Horizontal(id="helm-repository-buttons"):
                yield Button(
                    "Confirm " + self.action,
                    id="helm-repository-confirm",
                    variant="warning",
                    compact=True,
                )
                yield Button("Cancel", id="helm-repository-cancel", compact=True)
            yield from self.command_bar()

    def on_mount(self) -> None:
        self._controls()

    def _controls(self) -> None:
        if not self.query("#helm-repository-confirm"):
            return
        busy = bool(self.operation_count)
        blocked = self.invalidated or self.service.policy.read_only
        self.query_one("#helm-repository-confirm", Button).disabled = busy or blocked
        self.query_one("#helm-repository-fields").disabled = busy or blocked
        if self.action == "add":
            auth = self.query_one("#helm-repository-auth", Select).value
            for name in ("username", "password", "token"):
                self.query_one("#helm-repository-" + name, Input).disabled = (
                    busy or blocked or (auth != "bearer" if name == "token" else auth != "basic")
                )

    def _clear_private(self) -> None:
        if self.action == "add":
            for name in ("username", "password", "token"):
                for field in self.query("#helm-repository-" + name):
                    if isinstance(field, Input):
                        field.value = ""

    @on(Select.Changed, "#helm-repository-auth")
    def auth_changed(self) -> None:
        self._clear_private()
        self._controls()

    @on(Button.Pressed, "#helm-repository-confirm")
    def confirm(self) -> None:
        if self.invalidated or self.operation_count or self.service.policy.read_only:
            return
        self._start(self._apply(self._generation))

    async def _apply(self, generation: int) -> None:
        if self.action == "add":
            auth = self.query_one("#helm-repository-auth", Select).value
            username = self.query_one("#helm-repository-username", Input).value
            password = self.query_one("#helm-repository-password", Input).value
            token = self.query_one("#helm-repository-token", Input).value
            credentials = (
                RepositoryCredentials(username=username, password=password)
                if auth == "basic"
                else RepositoryCredentials(token=token)
                if auth == "bearer"
                else RepositoryCredentials()
            )
            name = self.query_one("#helm-repository-name", Input).value
            url = self.query_one("#helm-repository-url", Input).value
            oci = self.query_one("#helm-repository-kind", Select).value == "oci"
            loopback = self.query_one("#helm-repository-loopback", Checkbox).value
            ca = self.query_one("#helm-repository-ca", Input).value
            origins = tuple(
                item.strip()
                for item in self.query_one("#helm-repository-token-origins", Input).value.split(",")
                if item.strip()
            )
            download_origins = tuple(
                item.strip()
                for item in self.query_one("#helm-repository-download-origins", Input).value.split(
                    ","
                )
                if item.strip()
            )
            self._clear_private()
            await self.service.catalog.add(
                name,
                url,
                oci=oci,
                credentials=credentials,
                allow_loopback_http=loopback,
                ca_file=Path(ca) if ca else None,
                token_origins=origins,
                download_origins=download_origins,
            )
        else:
            assert self.repository is not None
            if self.action == "update":
                await self.service.catalog.update(
                    self.repository.name, expected_generation=self.expected_generation
                )
            else:
                await self.service.catalog.remove(
                    self.repository.name, expected_generation=self.expected_generation
                )
        if self._current(generation) and self.app.screen is self:
            self.dismiss()

    async def on_screen_suspend(self, event: ScreenSuspend) -> None:
        if self.action != "add":
            self.invalidated = True
        await super().on_screen_suspend(event)
        self._message("Repository review expired while covered; credentials were cleared.")

    @on(Button.Pressed, "#helm-repository-cancel")
    async def cancel(self) -> None:
        await self.action_back()
