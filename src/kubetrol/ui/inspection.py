"""Literal read-only resource viewer; owns reads and restores the underlying table."""

import asyncio
from typing import ClassVar, Literal

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TextArea

from kubetrol.domain.connections import ConnectionProblem
from kubetrol.domain.inspection import MAX_MATCHES, text_matches
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.inspection import InspectionResult, InspectionService, read_error
from kubetrol.ui.commands import NavigationInput

Page = Literal["yaml", "details", "events"]


class InspectionScreen(ModalScreen[None]):
    AUTO_FOCUS = "#inspection-text"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("y", "page('yaml')", "YAML"),
        Binding("d", "page('details')", "Details"),
        Binding("e", "page('events')", "Events"),
        Binding("m", "managed", "Managed fields"),
        Binding("slash", "search", "Search", key_display="/", priority=True),
        Binding("n", "match(False)", "Next match"),
        Binding("N", "match(True)", "Previous match", show=False),
        Binding("ctrl+y", "copy", "Copy", priority=True),
    ]
    DEFAULT_CSS = """
    InspectionScreen { align: center middle; background: $background 80%; }
    #inspection-dialog { width: 100%; height: 100%; border: round $primary; }
    #inspection-title, #inspection-status, #inspection-search { height: 1; }
    #inspection-title { color: $accent; padding: 0 1; text-overflow: ellipsis; }
    #inspection-buttons { height: 1; }
    #inspection-buttons Button { height: 1; min-width: 7; width: 1fr; border: none; }
    #inspection-text { height: 1fr; min-height: 1; border: none; }
    #inspection-status { padding: 0 1; text-overflow: ellipsis; color: $text-muted; }
    """

    def __init__(self, service: InspectionService, page: Page = "details") -> None:
        super().__init__()
        self.service = service
        self.page = page
        self.managed = False
        self.result: InspectionResult | None = None
        self._load_task: asyncio.Task[None] | None = None
        self.viewer = TextArea(
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

    def compose(self) -> ComposeResult:
        target = self.service.target
        with Vertical(id="inspection-dialog"):
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
                yield Button("Copy", id="copy-view", compact=True)
                yield Button("Back", id="inspection-back", compact=True)
            yield self.viewer
            yield self.search
            yield self.status

    def on_mount(self) -> None:
        self._load_task = asyncio.create_task(self._load())

    async def _load(self) -> None:
        try:
            self.result = await self.service.load()
        except (AppError, ConnectionProblem) as error:
            self.viewer.load_text("")
            self.status.update(safe_text(read_error(error)))
        except Exception as error:
            self.app._handle_exception(error)
        else:
            self.show_page()

    async def on_unmount(self) -> None:
        if self._load_task is not None:
            if not self._load_task.cancelling():
                self._load_task.cancel()
            await asyncio.gather(self._load_task, return_exceptions=True)

    def validate_target(self) -> None:
        try:
            self.service.require_current()
        except AppError as error:
            self.result = None
            self.viewer.load_text("")
            self.status.update(safe_text(str(error)))
            if self._load_task is not None and not self._load_task.cancelling():
                self._load_task.cancel()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"page", "managed", "match", "search"}:
            return not isinstance(self.focused, Input)
        return True

    def show_page(self) -> None:
        if self.result is None:
            return
        documents = self.result.documents
        text = (
            (documents.managed_yaml if self.managed else documents.yaml)
            if self.page == "yaml"
            else getattr(documents, self.page)
        )
        if self.page == "events" and self.result.events_error is not None:
            text = self.result.events_error
        self.viewer.load_text(text)
        self._search_changed()
        self.status.update(
            safe_text(
                f"{self.page.title()} · redacted · m managedFields · / search · Ctrl+Y copy · Esc back"
            )
        )

    def action_page(self, page: Page) -> None:
        self.page = page
        self.show_page()
        self.set_focus(self.viewer)

    def action_managed(self) -> None:
        self.managed = not self.managed
        self.page = "yaml"
        self.show_page()
        self.status.update(
            f"YAML · managedFields {'shown' if self.managed else 'hidden'} · sensitive field sets hidden"
        )

    def action_search(self) -> None:
        self.set_focus(self.search)

    @on(Input.Changed, "#inspection-search")
    def _search_changed(self) -> None:
        self.matches = text_matches(self.viewer.text, self.search.value)
        self.match_index = -1
        self.status.update(
            f"{len(self.matches)}{'+' if len(self.matches) == MAX_MATCHES else ''} matches · Enter then n / N · Esc leaves search"
        )

    @on(Input.Submitted, "#inspection-search")
    def search_submitted(self) -> None:
        self.action_match(False)

    def action_match(self, reverse: bool) -> None:
        if not self.matches:
            self.status.update("No matches.")
            return
        self.match_index = (self.match_index + (-1 if reverse else 1)) % len(self.matches)
        row, start, end = self.matches[self.match_index]
        self.viewer.move_cursor((row, start), center=True)
        self.viewer.move_cursor((row, end), select=True)
        self.status.update(
            f"Match {self.match_index + 1}/{len(self.matches)} · n next · N previous"
        )

    def action_copy(self) -> None:
        try:
            self.service.require_current()
        except AppError as error:
            self.status.update(safe_text(str(error)))
            return
        if self.result is None:
            return
        text = self.viewer.selected_text or self.viewer.text
        self.app.copy_to_clipboard(text)
        self.status.update("Redacted text copied; terminal clipboard support is required.")

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
            }
            self.action_page(pages[identifier])
