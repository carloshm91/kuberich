"""Bounded command entry, explicit local commands and UID range decisions."""

from dataclasses import dataclass

from kuberich.domain.connections import namespace_name
from kuberich.errors import AppError

INTERACTION_VERBS = frozenset(
    {
        "!!",
        "copy",
        "copyns",
        "copytext",
        "wide",
        "errors",
        "favorites",
        "favorite",
        "mark",
        "range",
        "selectall",
        "selectnone",
        "headless",
        "crumbsless",
        "fullscreen",
    }
)


@dataclass(frozen=True)
class InteractionCommand:
    verb: str
    argument: str = ""


def interaction_command(text: str) -> InteractionCommand | None:
    parts = text.split(maxsplit=1)
    verb = parts[0].lower()
    if verb not in INTERACTION_VERBS:
        return None
    argument = parts[1] if len(parts) == 2 else ""
    if verb == "favorite":
        action, _, name = argument.partition(" ")
        if action not in {"add", "remove"} or not name:
            raise AppError("Use :favorite add NAMESPACE or :favorite remove NAMESPACE.")
        namespace_name(name)
    elif argument:
        raise AppError("This navigation command takes no arguments.")
    return InteractionCommand(verb, argument)


class CommandHistory:
    """Memory-only entries; selection keeps an unfinished draft intact."""

    def __init__(self) -> None:
        self.entries: list[str] = []
        self.position: int | None = None
        self.draft = ""

    def record(self, value: str) -> None:
        value = value.strip().removeprefix(":").strip()
        if value and value != "!!" and (not self.entries or self.entries[-1] != value):
            self.entries.append(value)
            del self.entries[:-32]
        self.position = None

    def repeat(self) -> str:
        if not self.entries:
            raise AppError("There is no previous command in this session.")
        return self.entries[-1]

    def move(self, value: str, direction: int) -> str:
        if not self.entries:
            return value
        if self.position is None:
            if direction > 0:
                return value
            self.draft, self.position = value, len(self.entries)
        self.position = max(0, min(len(self.entries), self.position + direction))
        if self.position == len(self.entries):
            self.position = None
            return self.draft
        return self.entries[self.position]


class RangeSelection:
    """Only currently visible UID identities can be marked; batches stay bounded."""

    def __init__(self) -> None:
        self.marked: frozenset[str] = frozenset()
        self.anchor: str | None = None

    def prune(self, visible: tuple[str, ...]) -> None:
        self.marked &= frozenset(visible)
        if self.anchor not in visible:
            self.anchor = None

    def apply(self, action: str, uid: str | None, visible: tuple[str, ...]) -> None:
        self.prune(visible)
        selected = set(self.marked)
        if action == "selectnone":
            selected.clear()
            self.anchor = None
        elif action == "selectall":
            selected = set(visible)
        elif uid is not None and uid in visible:
            if action == "range" and self.anchor in visible:
                start, end = sorted((visible.index(self.anchor), visible.index(uid)))
                selected.update(visible[start : end + 1])
            else:
                selected.symmetric_difference_update((uid,))
                self.anchor = uid
        if len(selected) > 100:
            raise AppError("Selection is limited to 100 visible resources; filter first.")
        self.marked = frozenset(selected)
