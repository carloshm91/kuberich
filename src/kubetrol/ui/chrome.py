"""Shared workspace identity, view shortcuts and literal navigation trails."""

from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.theme import Theme
from textual.widgets import Static

from kubetrol.security.presentation import safe_text
from kubetrol.ui.presentation import DEFAULT_PRESENTATION, Presentation

K9S_THEME = Theme(
    name="k9s",
    primary="#5fd7ff",
    secondary="#00afff",
    accent="#ffd700",
    foreground="#5fd7ff",
    background="#000000",
    surface="#000000",
    panel="#000000",
    warning="#ffd700",
    error="#ff5f5f",
    success="#5fff87",
    text_alpha=1.0,
    variables={
        "text": "#5fd7ff",
        "text-muted": "#b0b0b0",
        "block-cursor-background": "#5fd7ff",
        "block-cursor-foreground": "#000000",
        "block-cursor-text-style": "none",
        "input-selection-background": "#005f87",
        "input-cursor-background": "#5fd7ff",
        "border": "#5fd7ff",
        "border-blurred": "#00afff",
    },
)

POD_SHORTCUTS = (
    ("Enter", "Containers"),
    ("l", "Logs"),
    ("x", "Shell"),
    ("d", "Details"),
    ("y", "YAML"),
    ("e", "Events"),
    ("s/S", "Sort"),
    ("n / :ns", "Namespaces"),
    ("c / :ctx", "Contexts"),
    ("/", "Filter"),
    (":", "Command"),
    ("?", "Help"),
)
NS_SHORTCUTS = (
    ("Enter", "Use namespace"),
    ("0", "All namespaces"),
    ("d", "Details"),
    ("y", "YAML"),
    ("e", "Events"),
    ("g/G", "First / last"),
    ("/", "Filter"),
    (":", "Command"),
    ("Esc", "Pods"),
    ("?", "Help"),
)
CTX_SHORTCUTS = (
    ("Enter", "Connect"),
    ("j/k", "Down / up"),
    ("g/G", "First / last"),
    ("/", "Filter"),
    (":", "Command"),
    ("Esc", "Previous view"),
    ("?", "Help"),
)
CONTAINER_SHORTCUTS = (
    ("Enter / l", "Logs"),
    ("s / x", "Shell"),
    ("j/k", "Down / up"),
    ("g/G", "First / last"),
    ("Esc", "Pods"),
    ("Ctrl+Q", "Quit"),
)
LOG_SHORTCUTS = (
    ("c", "Container"),
    ("v", "Previous"),
    ("o", "Read window"),
    ("p", "Pause"),
    ("f", "Follow"),
    ("t", "Timestamps"),
    ("w", "Wrap"),
    ("/", "Search"),
    ("Ctrl+Y", "Copy"),
    ("Ctrl+S", "Save"),
    ("z", "Fullscreen"),
    ("?", "Controls"),
)


@dataclass(frozen=True)
class WorkspaceChrome:
    identity: Callable[[], tuple[str, str, str, str, str]]
    build: str
    presentation: Presentation = DEFAULT_PRESENTATION


class WorkspaceBars(Vertical):
    """Reserve consistent bordered/compact interaction space in each view."""

    DEFAULT_CSS = """
    WorkspaceBars { height: 4; margin: 0 1; }
    WorkspaceBars > Static, WorkspaceBars > Horizontal { height: 1; }
    WorkspaceBars .input-bar { margin: 0; }
    """


class WorkspaceFrame(Vertical):
    """Shared resource boundary, independent of its table or viewer contents."""

    DEFAULT_CSS = """
    WorkspaceFrame {
        width: 1fr; height: 1fr; min-height: 4;
        margin: 0 1; border: solid $primary; border-title-align: center;
    }
    """


class WorkspaceHeader(Horizontal):
    """Responsive shared header; identity comes from the owned workspace."""

    def __init__(self, chrome: WorkspaceChrome, shortcuts: tuple[tuple[str, str], ...]) -> None:
        super().__init__(id="workspace-top")
        self.chrome = chrome
        self.shortcuts = shortcuts

    def compose(self) -> ComposeResult:
        with Vertical(id="scope-bar"):
            for name in ("context", "cluster", "user", "namespace", "connection"):
                yield Static("", id=name, markup=False)
            yield Static(self.chrome.build, id="build-info", markup=False)
        with Horizontal(id="app-header"):
            yield Static("", id="view-actions", markup=False)
            yield Static("┌────────┐\n│kubetrol│\n└────────┘", id="brand", markup=False)

    def on_mount(self) -> None:
        self.update_identity()
        self.layout_header()

    def update_identity(self) -> None:
        for name, value in zip(
            ("context", "cluster", "user", "namespace", "connection"),
            self.chrome.identity(),
            strict=True,
        ):
            label = name.title() if name != "connection" else "State"
            text = safe_text(f"{label}: {value}")
            text.stylize(self.app.get_css_variables()["accent"], 0, len(label) + 1)
            self.query_one(f"#{name}", Static).update(text)

    def on_resize(self, event: Resize) -> None:
        self.layout_header()

    def layout_header(self) -> None:
        short = self.app.size.height < 16
        compact = self.app.size.width < 70
        self.set_class(short, "header-short")
        self.set_class(compact, "header-compact")
        self.screen.set_class(short, "short")
        self.screen.set_class(compact, "compact")
        self.styles.height = 3 if short else 4 if compact else 6
        self.query_one("#scope-bar").display = not self.chrome.presentation.crumbsless
        self.query_one("#app-header").display = not short and not self.chrome.presentation.headless
        self.query_one("#brand").display = not compact and not self.chrome.presentation.logoless
        self.call_after_refresh(self.render_shortcuts)

    def render_shortcuts(self) -> None:
        widget = self.query_one("#view-actions", Static)
        width = max(1, widget.content_region.width)
        columns = max(1, width // 24)
        rows = max(1, widget.content_region.height)
        output = Text()
        for row in range(min(rows, 6)):
            if row:
                output.append("\n")
            for column in range(columns):
                index = column * rows + row
                if index < len(self.shortcuts):
                    key, label = self.shortcuts[index]
                    cell = safe_text(f"<{key}> {label}")
                    cell.stylize(self.app.get_css_variables()["secondary"], 0, len(key) + 2)
                    cell.truncate(max(1, width // columns - 1), overflow="ellipsis")
                    cell.pad_right(max(0, width // columns - len(cell)))
                    output.append_text(cell)
        widget.update(output)


class Breadcrumbs(Static):
    """A view trail plus the exact local Escape action, independent of global history."""

    def __init__(self, trail: tuple[str, ...], destination: str, *, visible: bool = True) -> None:
        super().__init__("", id="breadcrumbs", markup=False)
        self.trail, self.destination = trail, destination
        self._destination_override: str | None = None
        self.display = visible

    def on_mount(self) -> None:
        self.show_trail()

    def show_trail(self, *, destination: str | None = None) -> None:
        self._destination_override = destination
        self._render_trail()

    def on_resize(self) -> None:
        self._render_trail()

    def _render_trail(self) -> None:
        route = safe_text(" > ".join(self.trail))
        action = safe_text("   Esc → " + (self._destination_override or self.destination))
        width = self.size.width
        if width and route.cell_len + action.cell_len > width:
            route = safe_text(self.trail[-1])
            route.truncate(max(0, width - action.cell_len), overflow="ellipsis")
        self.update(route + action)
