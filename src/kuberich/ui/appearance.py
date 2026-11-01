"""Theme preview is temporary; persistence always needs an explicit scoped action."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Static

from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable


class ThemeTable(FrameTable[str]):
    BINDING_PROFILE = "themes"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("themes")


class ThemeScreen(ModalScreen[None]):
    AUTO_FOCUS = "#theme-list"
    DEFAULT_CSS = """
    ThemeScreen, AboutScreen { align: center middle; background: $background 80%; }
    #theme-dialog, #about-dialog { width: 95%; height: 90%; border: solid $primary;
        background: $surface; padding: 0 1; }
    #theme-title, #theme-status, #theme-buttons, #about-back { height: 1; }
    #theme-list { height: 1fr; min-height: 2; }
    #theme-updates { height: 1; border: none; padding: 0; }
    #theme-buttons Button { height: 1; border: none; min-width: 7; width: 1fr; }
    #theme-status { text-overflow: ellipsis; }
    #about-scroll { height: 1fr; min-height: 1; }
    #about-content { height: auto; }
    """

    def __init__(
        self,
        names: tuple[str, ...],
        selected: str,
        context: str | None,
        enabled: bool,
        preview: Callable[[str], None],
        restore: Callable[[], None],
        save: Callable[[str, str | None, bool], Awaitable[str]],
        *,
        writable: bool,
    ) -> None:
        super().__init__()
        self.names, self.selected, self.context = names, selected, context
        self.preview, self.restore, self.save = preview, restore, save
        self.writable = writable
        self._ready = False
        self._save_task: asyncio.Task[None] | None = None
        self.table: DataTable[str] = ThemeTable(id="theme-list", cursor_type="row")
        self.check = Checkbox(
            "Check releases: on (save Global)" if enabled else "Check releases: off (opt in)",
            value=enabled,
            id="theme-updates",
        )
        self.status = Static(
            "Select to preview · Global / Context saves · Esc cancels preview",
            markup=False,
            id="theme-status",
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Static(
                safe_text(f"Themes · context: {self.context or 'none'}"),
                id="theme-title",
                markup=False,
            )
            yield self.table
            yield self.check
            with Horizontal(id="theme-buttons"):
                yield Button("Global", id="theme-global", compact=True, disabled=not self.writable)
                yield Button(
                    "Context",
                    id="theme-context",
                    compact=True,
                    disabled=not self.writable or self.context is None,
                )
                yield Button("Back", id="theme-back", compact=True)
            yield self.status

    def on_mount(self) -> None:
        self.table.add_column("Theme", key="theme")
        self.table.add_column("State", key="state")
        for name in self.names:
            self.table.add_row(name, "Selected" if name == self.selected else "Available", key=name)
        self.table.move_cursor(row=self.names.index(self.selected))
        self._ready = True

    @on(DataTable.RowHighlighted, "#theme-list")
    @on(DataTable.RowSelected, "#theme-list")
    def selection(self) -> None:
        if self._ready:
            self.selected = self.names[self.table.cursor_row]
            for name in self.names:
                self.table.update_cell(
                    name, "state", "Selected" if name == self.selected else "Available"
                )
            self.preview(self.selected)
            self.status.update(
                safe_text(f"Preview: {self.selected} · Esc restores effective preferences")
            )

    @on(Checkbox.Changed, "#theme-updates")
    def update_check_label(self, event: Checkbox.Changed) -> None:
        self.check.label = (
            "Check releases: on (save Global)" if event.value else "Check releases: off (opt in)"
        )

    async def _save(self, context: str | None) -> None:
        try:
            message = await self.save(self.selected, context, self.check.value)
            if self.is_attached:
                self.status.update(safe_text(message))
        except AppError as error:
            if self.is_attached:
                self.status.update(safe_text(str(error)))

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "theme-back":
            self.back()
        elif self._save_task is None or self._save_task.done():
            self.status.update("Saving local preferences…")
            self._save_task = asyncio.create_task(
                self._save(self.context if event.button.id == "theme-context" else None)
            )
            self._save_task.add_done_callback(self.finished)

    def finished(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and isinstance(error := task.exception(), Exception):
            self.app._handle_exception(error)

    def back(self) -> None:
        if self._save_task is not None and not self._save_task.done():
            self.status.update("Wait for the requested preference save to finish.")
            return
        self._ready = False
        self.restore()
        self.dismiss()

    async def on_unmount(self) -> None:
        self._ready = False
        if self._save_task is not None:
            await finish_owned(self._save_task)


class AboutScreen(ModalScreen[None]):
    AUTO_FOCUS = "#about-scroll"
    DEFAULT_CSS = ThemeScreen.DEFAULT_CSS

    def __init__(self, build: str, notice: str) -> None:
        super().__init__()
        self._prefix = f"KubeRich {build}\n\nAn independent Python terminal workspace for Kubernetes.\nBuilt with Textual. Inspired by K9s.\n\nApache-2.0 · no paid capability tiers\nhttps://kuberich.com\n\n"
        self.content = Static(self._prefix + notice, markup=False, id="about-content")

    def compose(self) -> ComposeResult:
        with Vertical(id="about-dialog"):
            with VerticalScroll(id="about-scroll"):
                yield self.content
            yield Button("Back", id="about-back", compact=True)

    def update_notice(self, text: str) -> None:
        if self.content.is_attached:
            self.content.update(self._prefix + text)

    @on(Button.Pressed, "#about-back")
    def close_about(self) -> None:
        self.dismiss()
