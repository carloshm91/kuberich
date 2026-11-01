"""Read-only document and help navigation using independent configurable bindings."""

from typing import TYPE_CHECKING, ClassVar

from textual.binding import Binding, BindingType
from textual.containers import VerticalScroll

from kuberich.domain.keyboard import keys_for

if TYPE_CHECKING:
    from kuberich.ui.read_only_text import ReadOnlyText as ReadOnlyText

_ACTIONS = {
    "down": "cursor_down",
    "up": "cursor_up",
    "first": "document_edge(False)",
    "last": "document_edge(True)",
    "page_up": "cursor_page_up",
    "page_down": "cursor_page_down",
    "half_up": "document_half(-1)",
    "half_down": "document_half(1)",
    "left": "scroll_left",
    "right": "scroll_right",
}


def text_bindings() -> list[BindingType]:
    return [
        Binding(key, _ACTIONS[action], action, show=False, priority=True, id=f"text.{action}")
        for action, key in keys_for((), "text").items()
    ]


def __getattr__(name: str) -> object:
    if name == "ReadOnlyText":
        from kuberich.ui.read_only_text import ReadOnlyText

        return ReadOnlyText
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class ReadOnlyScroll(VerticalScroll):
    BINDING_PROFILE = "text"
    BINDINGS: ClassVar[list[BindingType]] = text_bindings()

    def action_cursor_down(self) -> None:
        self.scroll_relative(y=1, animate=False)

    def action_cursor_up(self) -> None:
        self.scroll_relative(y=-1, animate=False)

    def action_document_edge(self, last: bool) -> None:
        self.scroll_to(y=self.max_scroll_y if last else 0, animate=False)

    def action_cursor_page_up(self) -> None:
        self.scroll_relative(y=-max(1, self.content_region.height), animate=False)

    def action_cursor_page_down(self) -> None:
        self.scroll_relative(y=max(1, self.content_region.height), animate=False)

    def action_document_half(self, direction: int) -> None:
        self.scroll_relative(y=direction * max(1, self.content_region.height // 2), animate=False)
