"""Read-only editor navigation loaded only by document inspection screens."""

from typing import ClassVar

from textual.binding import BindingType
from textual.widgets import TextArea

from kuberich.ui.text_navigation import text_bindings


class ReadOnlyText(TextArea):
    BINDING_PROFILE = "text"
    BINDINGS: ClassVar[list[BindingType]] = text_bindings()

    def action_document_edge(self, last: bool) -> None:
        self.move_cursor((self.document.line_count - 1, 0) if last else (0, 0))

    def action_document_half(self, direction: int) -> None:
        row, column = self.cursor_location
        self.move_cursor((row + direction * max(1, self.content_region.height // 2), column))
