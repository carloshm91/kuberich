"""Public Textual Binding IDs and help share the validated effective key model."""

from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from kuberich.domain.keyboard import key_label, keys_for

type EffectiveKeys = tuple[tuple[str, str], ...]

_ACTIONS = {
    "down": ("cursor_down", "Down"),
    "up": ("cursor_up", "Up"),
    "first": ("scroll_top", "First row"),
    "last": ("scroll_bottom", "Last row"),
    "page_up": ("page_up", "Page up"),
    "page_down": ("page_down", "Page down"),
    "half_up": ("half_page(-1)", "Half page up"),
    "half_down": ("half_page(1)", "Half page down"),
    "left": ("scroll_left", "Scroll left"),
    "right": ("scroll_right", "Scroll right"),
    "sort": ("next_sort", "Next sort field"),
    "reverse_sort": ("reverse_sort", "Reverse sort"),
}


def table_bindings(profile: str) -> list[BindingType]:
    bindings: list[BindingType] = [
        Binding(key, _ACTIONS[name][0], _ACTIONS[name][1], show=False, id=f"{profile}.{name}")
        for name, key in keys_for((), profile).items()
    ]
    bindings.append(Binding("question_mark", "app.navigation_help", "Keys", show=False))
    return bindings


def key_hint(keymap: EffectiveKeys, profile: str, action: str) -> str:
    return key_label(dict(keymap).get(f"{profile}.{action}", keys_for((), profile)[action]))


def navigation_help(keymap: EffectiveKeys, profile: str) -> str:
    lines = [f"Navigation · {profile}"]
    for action in keys_for((), profile):
        description = _ACTIONS[action][1]
        lines.append(f"{key_hint(keymap, profile, action):18} {description}")
    lines.extend(
        (
            "",
            "Arrows, Home/End and PageUp/PageDown remain fixed fallbacks.",
            "Ctrl+Home/End select the first/last row. Letters remain literal in inputs.",
            "Ctrl+D reviews resource deletion; in logs it moves half a page down.",
            "Ctrl+Y belongs to copy views; it is not a navigation key.",
            "Escape goes back; Ctrl+Q quits.",
        )
    )
    return "\n".join(lines)


def shortcut_keys(
    shortcuts: tuple[tuple[str, str], ...], keymap: EffectiveKeys, profile: str
) -> tuple[tuple[str, str], ...]:
    pairs = {"j/k": ("down", "up"), "g/G": ("first", "last"), "s/S": ("sort", "reverse_sort")}
    available = keys_for((), profile)
    result = []
    for keys, title in shortcuts:
        actions = pairs.get(keys)
        if actions is not None and all(action in available for action in actions):
            keys = "/".join(key_hint(keymap, profile, action) for action in actions)
        result.append((keys, title))
    return tuple(result)


_FIXED_HELP = {
    "containers": "Enter/l logs · s/x shell · a attach · u upload · d download",
    "data": "r reveal/hide · x encoding · Shift+R reload · Ctrl+Y explicit copy",
    "themes": "Enter previews · Tab selects controls · Global/Context explicitly save",
    "forwards": "s stops the selected owned forward · / filters",
    "sources": "Space toggles admission · Enter only selected · r reopen · a automatic",
}


class NavigationHelpScreen(ModalScreen[None]):
    AUTO_FOCUS = "#navigation-help-scroll"
    BINDINGS: ClassVar[list[BindingType]] = []
    DEFAULT_CSS = """
    NavigationHelpScreen { align: center middle; background: $background 80%; }
    #navigation-help-dialog { width: 95%; height: 90%; border: solid $primary;
        background: $surface; padding: 0 1; }
    #navigation-help-scroll { height: 1fr; }
    #navigation-help-back { height: 1; border: none; }
    """

    def __init__(self, keymap: EffectiveKeys, profile: str) -> None:
        super().__init__()
        self.text = navigation_help(keymap, profile) + "\n\n" + _FIXED_HELP.get(profile, "")

    def compose(self) -> ComposeResult:
        with Vertical(id="navigation-help-dialog"):
            with VerticalScroll(id="navigation-help-scroll"):
                yield Static(self.text, markup=False)
            yield Button("Back", id="navigation-help-back", compact=True)

    @on(Button.Pressed, "#navigation-help-back")
    def close_help(self) -> None:
        self.dismiss()
