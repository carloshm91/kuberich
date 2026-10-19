"""Explicit per-key disclosure; scope changes and navigation clear visible values."""

import asyncio
from collections.abc import Callable
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Static, TextArea

from kuberich.domain.configuration_data import ConfigurationIndex, DataKey, clipboard_value
from kuberich.domain.connections import ConnectionProblem
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls
from kuberich.security.presentation import safe_text
from kuberich.services.configuration_data import ConfigurationService
from kuberich.services.inspection import read_error
from kuberich.services.processes import _finish_owned
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable


class ConfigurationKeyTable(FrameTable[str | Text]):
    BINDING_PROFILE = "data"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("data")


class ConfigurationScreen(ModalScreen[None]):
    AUTO_FOCUS = "#configuration-keys"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "reveal", "Reveal / hide"),
        Binding("x", "encoding", "Decoded / Base64"),
        Binding("ctrl+y", "copy", "Copy selected value", priority=True),
        Binding("R", "reload", "Reload", key_display="Shift+R"),
    ]
    DEFAULT_CSS = """
    ConfigurationScreen { align: center middle; background: $background 80%; }
    #configuration-view { width: 98%; height: 96%; border: solid $primary; padding: 0 1;
        background: $surface; }
    #configuration-title, #configuration-buttons, #configuration-status { height: 1; }
    #configuration-title, #configuration-status { text-overflow: ellipsis; }
    #configuration-keys { height: 1fr; min-height: 2; }
    #configuration-value { height: 1fr; min-height: 2; }
    #configuration-buttons Button { height: 1; border: none; min-width: 5;
        background: $surface; color: $text; }
    #configuration-buttons Button:focus { background: $primary; color: $background; }
    """

    def __init__(self, service: ConfigurationService) -> None:
        super().__init__()
        self.service = service
        self.index: ConfigurationIndex | None = None
        self.encoded = False
        self.revealed = False
        self._generation = 0
        self._metadata_generation = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self._data_stopped = False
        self.keys: DataTable[str | Text] = ConfigurationKeyTable(
            id="configuration-keys", cursor_type="row"
        )
        self.viewer = TextArea(read_only=True, soft_wrap=False, id="configuration-value")
        self.status = Static("Loading key metadata…", markup=False, id="configuration-status")

    def compose(self) -> ComposeResult:
        target = self.service.target
        with Vertical(id="configuration-view"):
            yield Static(
                safe_text(f"{target.session.context} · {target.namespace} / {target.name} · Data"),
                markup=False,
                id="configuration-title",
            )
            with Horizontal(id="configuration-buttons"):
                for label, identifier in (
                    ("Reveal", "reveal"),
                    ("Encoding", "encoding"),
                    ("Copy", "copy"),
                    ("Reload", "reload"),
                    ("Back", "back"),
                ):
                    yield Button(label, id="configuration-" + identifier, compact=True)
            yield self.keys
            yield self.viewer
            yield self.status

    def on_mount(self) -> None:
        self.keys.add_columns("Key", "Storage", "Type", "Bytes")
        self.action_reload()

    def _launch(self, operation: str) -> None:
        self.hide_value()
        if self._data_stopped:
            self.status.update("Configuration view stopped; close and select the resource again.")
            return
        if any(not task.done() for task in self._tasks):
            self.status.update("A read is in progress; retry after it completes.")
            return
        generation = self._generation
        if operation == "load":
            self._metadata_generation += 1
            generation = self._metadata_generation
        task = asyncio.create_task(
            self._load(generation) if operation == "load" else self._read(operation, generation)
        )
        self._tasks.add(task)
        task.add_done_callback(self._finished)

    def _finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and isinstance(error := task.exception(), Exception):
            self.app._handle_exception(error)

    def hide_value(self) -> None:
        self._generation += 1
        self.revealed = False
        self.viewer.load_text("")

    def _selected(self) -> DataKey | None:
        if self.index is None or not 0 <= self.keys.cursor_row < len(self.index.keys):
            return None
        return self.index.keys[self.keys.cursor_row]

    def _hint(self) -> None:
        mode = "Base64" if self.encoded else "Decoded UTF-8"
        self.status.update(
            f"{mode} · values hidden · r reveal · x encoding · Ctrl+Y copy · Esc back"
        )

    async def _load(self, generation: int) -> None:
        try:
            index = await self.service.index()
            if (
                generation != self._metadata_generation
                or not self.is_attached
                or self._data_stopped
            ):
                return
            self.service.require_current()
            selected = self._selected()
            identity = selected.identity if selected is not None else None
            self.index = index
            rows = tuple(
                (
                    safe_text(key.name),
                    key.section,
                    "Binary" if key.binary else "Text",
                    str(key.size),
                )
                for key in index.keys
            )
            # The immutable metadata already determines exact cell widths.
            # Do not paint key names at header width while native idle sizing
            # is pending after mount/resize; reload computes them anew.
            labels = ("Key", "Storage", "Type", "Bytes")
            widths = (
                max((row[0].cell_len for row in rows), default=0),
                *(max((len(row[i]) for row in rows), default=0) for i in (1, 2, 3)),
            )
            self.keys.clear(columns=True)
            for label, width in zip(labels, widths, strict=True):
                self.keys.add_column(label, width=max(len(label), width))
            for row in rows:
                self.keys.add_row(*row)
            if identity is not None:
                position = next(
                    (i for i, key in enumerate(index.keys) if key.identity == identity), 0
                )
                self.keys.move_cursor(row=position)
            self._hint()
            if not index.keys:
                self.status.update("No data keys returned for this resource.")
        except (AppError, ConnectionProblem) as error:
            self.status.update(safe_text(read_error(error)))

    async def _read(self, operation: str, generation: int) -> None:
        selected, index = self._selected(), self.index
        if selected is None or index is None:
            self.status.update("Select a current data key first.")
            return
        try:
            value = await self.service.value(
                selected.identity, index.resource_version, encoded=self.encoded
            )
            if generation != self._generation or not self.is_attached:
                return
            if operation == "copy":
                text = clipboard_value(value)
                try:
                    self.app.copy_to_clipboard(text)
                except Exception:
                    self.status.update(
                        "Clipboard write failed; no value was included in the error."
                    )
                    return
                self.status.update("Selected value copied; clipboard write requested.")
            else:
                preview = escape_controls(value[:16384], allow_newlines=True)
                if len(value) > 16384:
                    preview += "\n[Preview limited to 16384 characters]"
                self.viewer.load_text(preview)
                self.revealed = True
                self.status.update(
                    "Selected value revealed · r hide · changing key or encoding hides it."
                )
        except (AppError, ConnectionProblem) as error:
            self.status.update(safe_text(read_error(error)))

    def validate_target(self) -> None:
        try:
            self.service.require_current()
        except AppError as error:
            self.hide_value()
            self.index = None
            for task in self._tasks:
                task.cancel()
            self.status.update(safe_text(str(error)))

    def action_reveal(self) -> None:
        if self.revealed:
            self.hide_value()
            self._hint()
        else:
            self._launch("reveal")

    def action_encoding(self) -> None:
        self.hide_value()
        self.encoded = not self.encoded
        self._hint()

    def action_copy(self) -> None:
        self._launch("copy")

    def action_reload(self) -> None:
        self._launch("load")

    @on(DataTable.RowHighlighted, "#configuration-keys")
    def selected_key_changed(self) -> None:
        self.hide_value()
        self._hint()

    @on(DataTable.RowSelected, "#configuration-keys")
    def selected_key_opened(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.action_reveal()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        actions: dict[str, Callable[[], object]] = {
            "reveal": self.action_reveal,
            "encoding": self.action_encoding,
            "copy": self.action_copy,
            "reload": self.action_reload,
            "back": self.dismiss,
        }
        actions[(event.button.id or "").removeprefix("configuration-")]()

    async def stop_owned(self) -> None:
        self._data_stopped = True
        self.hide_value()
        self.index = None
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await _finish_owned(asyncio.gather(*tasks, return_exceptions=True))
        self._tasks.clear()

    async def on_unmount(self) -> None:
        await self.stop_owned()
