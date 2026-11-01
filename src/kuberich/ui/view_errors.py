"""A resource-view failure leaves the workspace and its owned operations running."""

from collections.abc import Callable

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Static


class ViewErrorPanel(Horizontal):
    DEFAULT_CSS = """
    ViewErrorPanel { display: none; height: auto; min-height: 3;
        border: solid $error; padding: 0 1; }
    ViewErrorPanel.failed { display: block; }
    ViewErrorPanel Static { width: 1fr; height: auto; }
    ViewErrorPanel Button { height: 1; min-width: 7; border: none; }
    """

    def __init__(self, retry: Callable[[], None]) -> None:
        super().__init__(id="view-error")
        self.retry = retry

    def compose(self) -> ComposeResult:
        yield Static(
            "This view could not be rendered. Retry or choose another resource. "
            "Existing rows may be incomplete; other sessions keep running.",
            markup=False,
        )
        yield Button("Retry", id="view-error-retry", compact=True)

    @on(Button.Pressed, "#view-error-retry")
    def pressed_retry(self, event: Button.Pressed) -> None:
        event.stop()
        self.retry()

    def show_failure(self, failed: bool) -> None:
        self.set_class(failed, "failed")
