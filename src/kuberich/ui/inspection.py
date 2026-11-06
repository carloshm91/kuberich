"""Literal read-only resource viewer; owns reads and restores the underlying table."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Literal

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.curated_navigation import CuratedLink
from kuberich.domain.inspection import MAX_MATCHES, text_matches
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.curated_navigation import (
    CuratedNavigator,
    CuratedOrigin,
    ResolvedCuratedDestination,
)
from kuberich.services.inspection import InspectionResult, InspectionService, read_error
from kuberich.services.ownership import finish_owned
from kuberich.ui.chrome import (
    TEXT_SHORTCUTS,
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.commands import NavigationInput
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.read_only_text import ReadOnlyText

if TYPE_CHECKING:
    from kuberich.services.exports import ExportChoices

Page = Literal["yaml", "details", "events", "links"]


class InspectionScreen(CommandWorkspace):
    AUTO_FOCUS = "#inspection-text"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "page('yaml')", "YAML"),
        Binding("d", "page('details')", "Details"),
        Binding("e", "page('events')", "Events"),
        Binding("L", "page('links')", "Links", key_display="Shift+L"),
        Binding("m", "managed", "Managed fields"),
        Binding("slash", "search", "Search", key_display="/", priority=True),
        Binding("n", "match(False)", "Next match"),
        Binding("N", "match(True)", "Previous match", show=False),
        Binding("ctrl+y", "copy", "Copy", priority=True),
    ]
    DEFAULT_CSS = """
    InspectionScreen { layout: vertical; background: $background; }
    #inspection-dialog { height: 1fr; min-height: 2; }
    InspectionScreen.short #inspection-title, InspectionScreen.short #inspection-status { display: none; }
    InspectionScreen.short #inspection-dialog.fullscreen #inspection-status { display: block; }
    #inspection-title, #inspection-status, #inspection-search { height: 1; }
    #inspection-title { color: $accent; padding: 0 1; text-overflow: ellipsis; }
    #inspection-buttons { height: 1; }
    #inspection-buttons Button { height: 1; min-width: 5; width: 1fr; border: none; }
    #inspection-text { height: 1fr; min-height: 1; border: none; }
    #inspection-links { height: 1fr; min-height: 1; border: none; display: none; }
    #inspection-status { padding: 0 1; text-overflow: ellipsis; color: $text-muted; }
    """

    def __init__(
        self,
        service: InspectionService,
        page: Page = "details",
        *,
        chrome: WorkspaceChrome | None = None,
        navigator: CuratedNavigator | None = None,
        revision: int = 0,
        observed_resource_version: str | None = None,
        current_curated: Callable[[CuratedOrigin], bool] | None = None,
        navigate_curated: Callable[[CuratedOrigin, ResolvedCuratedDestination], None] | None = None,
        stopped: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__()
        self.service = service
        self.chrome = chrome
        self.navigator, self.revision, self._navigate_curated = (
            navigator,
            revision,
            navigate_curated,
        )
        self.observed_resource_version, self._current_curated = (
            observed_resource_version,
            current_curated,
        )
        self._notify_stopped = stopped
        self._stop_task: asyncio.Task[None] | None = None
        self._link_task: (
            asyncio.Task[tuple[CuratedOrigin, ResolvedCuratedDestination] | None] | None
        ) = None
        self._link_tasks: set[
            asyncio.Task[tuple[CuratedOrigin, ResolvedCuratedDestination] | None]
        ] = set()
        self.invalidated = False
        self.page = page
        self.managed = False
        self.result: InspectionResult | None = None
        self._load_task: asyncio.Task[None] | None = None
        self.viewer = ReadOnlyText(
            read_only=True,
            soft_wrap=False,
            highlight_cursor_line=False,
            show_line_numbers=True,
            id="inspection-text",
        )
        self.search = NavigationInput(
            lambda: self.set_focus(self.viewer),
            placeholder="Literal search · Enter then n / N",
            id="inspection-search",
        )
        self.status = Static("Loading selected resource…", markup=False, id="inspection-status")
        self.matches: tuple[tuple[int, int, int], ...] = ()
        self.match_index = -1
        self.links = OptionList(id="inspection-links")

    @property
    def operation_count(self) -> int:
        return (
            int(self._load_task is not None and not self._load_task.done())
            + sum(not task.done() for task in self._link_tasks)
            + (self.navigator.operation_count if self.navigator else 0)
        )

    def _links_text(self) -> str:
        curated = self.result.curated if self.result is not None else None
        if curated is None or not curated.links:
            return "No declared curated links are available.\n"
        return "\n\n".join(self._link_text(index) for index in range(len(curated.links))) + "\n"

    def _link_text(self, index: int) -> str:
        assert self.result is not None and self.result.curated is not None
        link = self.result.curated.links[index]
        availability = link.unavailable_reason or (
            "Available" if link.destination is not None else "Unavailable"
        )
        return sanitize_text(
            f"{index + 1}. {link.label}\n{link.provenance}\n{availability}", allow_newlines=True
        )

    def capture_export(self, at: datetime) -> ExportChoices:
        from kuberich.domain.exports import DocumentSource, ExportPresentation
        from kuberich.ui.export_captures import captured_lease, header_namespace, target_scope

        result, page, managed = self.result, self.page, self.managed
        if result is None or self.invalidated or not self.is_mounted or not self.service.current():
            return ()
        field = "managed_yaml" if page == "yaml" and managed else page
        text = self._links_text() if page == "links" else getattr(result.documents, field)
        if page == "events" and result.events_error is not None:
            text = result.events_error
        source_page = "managed-yaml" if page == "yaml" and managed else page
        if page == "links":
            document_source = DocumentSource(page="evidence", text=text)
        elif page == "yaml":
            document_source = DocumentSource(page="managed-yaml" if managed else "yaml", text=text)
        else:
            document_source = DocumentSource(page=page, text=text)
        lease = captured_lease(
            target_scope(
                at,
                self.service.target,
                resource=self.service.resource,
                resource_version=result.resource_version,
                source_at=result.observed_at,
                header=header_namespace(self.chrome),
            ),
            document_source,
            lambda: (
                self.is_mounted
                and not self.invalidated
                and self.service.current()
                and self.result is result
                and self.page == page
                and self.managed == managed
            ),
            target=self.service.target,
            presentation=ExportPresentation(
                view="inspection/" + source_page, query=self.search.value
            ),
            notices=(result.events_error,) if result.events_error else (),
        )
        return (
            (("resource-yaml", lease), ("screen", lease))
            if page == "yaml"
            else (("screen", lease),)
        )

    def compose(self) -> ComposeResult:
        target = self.service.target
        if hasattr(self.app, "chrome"):
            yield WorkspaceHeader(self.app.chrome, TEXT_SHORTCUTS, binding_profile="text")
        with WorkspaceBars():
            yield self.search
            yield from self.command_bar()
        with WorkspaceFrame(id="inspection-dialog"):
            yield Static(
                safe_text(
                    f"{target.session.context} · {target.namespace or 'Cluster'} / {target.name}"
                ),
                id="inspection-title",
                markup=False,
            )
            with Horizontal(id="inspection-buttons"):
                yield Button("YAML", id="show-yaml", compact=True)
                yield Button("Details", id="show-details", compact=True)
                yield Button("Events", id="show-events", compact=True)
                yield Button("Links", id="show-links", compact=True)
                yield Button("Copy", id="copy-view", compact=True)
                yield Button("Back", id="inspection-back", compact=True)
            yield self.viewer
            yield self.links
            yield self.status
        yield Breadcrumbs((self.service.target.resource, self.page), "Resource table")

    def on_mount(self) -> None:
        self.on_resize()
        self._load_task = asyncio.create_task(self._load())

    def _set_status(self, message: str | Text) -> None:
        self.status.update(message)
        if self.is_mounted:
            self.on_resize()

    def on_resize(self) -> None:
        self.query_one("#inspection-dialog", WorkspaceFrame).border_subtitle = (
            safe_text(str(self.status.content)) if self.app.size.height < 16 else ""
        )

    async def _load(self) -> None:
        try:
            result = await self.service.load()
        except (AppError, ConnectionProblem) as error:
            self.viewer.load_text("")
            self._set_status(safe_text(read_error(error)))
        except Exception as error:
            self.app._handle_exception(error)
        else:
            if not self.invalidated:
                self.result = result
                self.show_page()

    async def _stop(self) -> None:
        self.invalidated = True
        self.result = None
        self.viewer.load_text("")
        self.links.clear_options()
        tasks = (*self._link_tasks, *((self._load_task,) if self._load_task is not None else ()))
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        if self.navigator is not None:
            await self.navigator.stop()
        await finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._notify_stopped()

    async def stop_owned(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await finish_owned(self._stop_task)

    async def on_unmount(self) -> None:
        await self.stop_owned()

    def validate_target(self) -> None:
        try:
            if self.invalidated:
                raise AppError("The inspection target is stale; select the resource again.")
            self.service.require_current()
        except AppError as error:
            self.invalidated = True
            self.result = None
            self.viewer.load_text("")
            self._set_status(safe_text(str(error)))
            if self._load_task is not None and not self._load_task.cancelling():
                self._load_task.cancel()
            if self._stop_task is None:
                self._stop_task = asyncio.create_task(self._stop())

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"page", "managed", "match", "search"}:
            return not isinstance(self.focused, Input) and (
                action not in {"match", "search"} or self.page != "links"
            )
        return True

    def show_page(self) -> None:
        self.query_one("#inspection-dialog", WorkspaceFrame).border_title = safe_text(
            f"{self.page}({self.service.target.namespace or 'Cluster'}/{self.service.target.name})"
        )
        if self.result is None:
            return
        documents = self.result.documents
        self.viewer.display = self.page != "links"
        self.links.display = self.page == "links"
        if self.page == "links":
            self.links.clear_options()
            curated = self.result.curated
            self.links.add_options(
                [
                    safe_text(self._link_text(index), multiline=True)
                    for index in range(len(curated.links))
                ]
                if curated is not None
                else []
            )
            if curated is not None and curated.links:
                self.links.highlighted = 0
            else:
                self.links.add_option(
                    Option(safe_text(self._links_text(), multiline=True), disabled=True)
                )
            self.viewer.load_text(self._links_text())
            self._set_status(
                "Links · Shift+L links · Enter opens selected declared link · Esc back"
            )
            return
        text = (
            (documents.managed_yaml if self.managed else documents.yaml)
            if self.page == "yaml"
            else getattr(documents, self.page)
        )
        if self.page == "events" and self.result.events_error is not None:
            text = self.result.events_error
        self.viewer.load_text(text)
        self._search_changed()
        self._set_status(
            safe_text(
                f"{self.page.title()} · redacted · Shift+L links · m managedFields · / search · Ctrl+Y copy · Esc back"
            )
        )

    def action_page(self, page: Page) -> None:
        self.page = page
        self.show_page()
        self.set_focus(self.links if page == "links" else self.viewer)

    @on(OptionList.OptionSelected, "#inspection-links")
    def select_link(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if self.app.screen is not self:
            return
        if self.navigator is None or self._navigate_curated is None:
            self._set_status("Curated navigation is unavailable in this workspace.")
            return
        if self.result is None or self.result.curated is None or self.invalidated:
            return
        self.validate_target()
        if self.invalidated:
            return
        target = self.service.target
        origin = CuratedOrigin(
            target.session,
            self.revision,
            self.service.resource,
            target.name,
            target.uid,
            target.namespace,
            self.result.resource_version,
            self.observed_resource_version,
        )
        link = self.result.curated.links[event.option_index]
        task = asyncio.create_task(self._resolve_link(origin, link))
        self._link_task = task
        self._link_tasks.add(task)
        task.add_done_callback(self._link_done)

    async def _resolve_link(
        self, origin: CuratedOrigin, link: CuratedLink
    ) -> tuple[CuratedOrigin, ResolvedCuratedDestination] | None:
        assert self.navigator is not None
        try:
            destination = await self.navigator.resolve(origin, link)
        except AppError as error:
            if not self.invalidated:
                self._set_status(safe_text(str(error)))
            return None
        return origin, destination

    def _link_done(
        self, task: asyncio.Task[tuple[CuratedOrigin, ResolvedCuratedDestination] | None]
    ) -> None:
        self._link_tasks.discard(task)
        if task.cancelled():
            return
        failure = task.exception()
        if isinstance(failure, Exception):
            self.app._handle_exception(failure)
            return
        resolved = task.result()
        if (
            resolved is not None
            and task is self._link_task
            and not self.invalidated
            and self.is_mounted
        ):
            self.call_later(self._handoff, *resolved, task)

    def _handoff(
        self,
        origin: CuratedOrigin,
        destination: ResolvedCuratedDestination,
        task: asyncio.Task[tuple[CuratedOrigin, ResolvedCuratedDestination] | None],
    ) -> None:
        if (
            task is not self._link_task
            or self.app.screen is not self
            or self.invalidated
            or not self.is_mounted
            or self.result is None
            or self.result.resource_version != origin.resource_version
        ):
            return
        self.validate_target()
        if self._current_curated is not None and not self._current_curated(origin):
            self._set_status("The source changed; reopen its details before navigating.")
            return
        if not self.invalidated and self._navigate_curated is not None:
            self.dismiss()
            self._navigate_curated(origin, destination)

    def action_managed(self) -> None:
        self.managed = not self.managed
        self.page = "yaml"
        self.show_page()
        self._set_status(
            f"YAML · managedFields {'shown' if self.managed else 'hidden'} · sensitive field sets hidden"
        )

    def action_search(self) -> None:
        self.set_focus(self.search)

    @on(Input.Changed, "#inspection-search")
    def _search_changed(self) -> None:
        self.matches = text_matches(self.viewer.text, self.search.value)
        self.match_index = -1
        self._set_status(
            f"{len(self.matches)}{'+' if len(self.matches) == MAX_MATCHES else ''} matches · Enter then n / N · Esc leaves search"
        )

    @on(Input.Submitted, "#inspection-search")
    def search_submitted(self) -> None:
        self.action_match(False)

    def action_match(self, reverse: bool) -> None:
        if not self.matches:
            self._set_status("No matches.")
            return
        self.match_index = (self.match_index + (-1 if reverse else 1)) % len(self.matches)
        row, start, end = self.matches[self.match_index]
        self.viewer.move_cursor((row, start), center=True)
        self.viewer.move_cursor((row, end), select=True)
        self._set_status(f"Match {self.match_index + 1}/{len(self.matches)} · n next · N previous")

    def action_copy(self) -> None:
        try:
            self.service.require_current()
        except AppError as error:
            self._set_status(safe_text(str(error)))
            return
        if self.result is None:
            return
        text = self.viewer.selected_text or self.viewer.text
        try:
            self.app.copy_to_clipboard(text)
        except AppError as error:
            self._set_status(str(error))
        else:
            self._set_status("Redacted text copied; clipboard write requested.")

    def back(self) -> None:
        if self.focused is self.search:
            self.set_focus(self.viewer)
        else:
            self.dismiss()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        identifier = event.button.id
        if identifier == "inspection-back":
            self.dismiss()
        elif identifier == "copy-view":
            self.action_copy()
        else:
            pages: dict[str | None, Page] = {
                "show-yaml": "yaml",
                "show-details": "details",
                "show-events": "events",
                "show-links": "links",
            }
            self.action_page(pages[identifier])
