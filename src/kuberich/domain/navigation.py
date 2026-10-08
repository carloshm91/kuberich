"""Bounded keyboard navigation state, independent of terminal widgets."""

from dataclasses import dataclass

from kuberich.domain.connections import namespace_name
from kuberich.domain.pods import PodColumn

MAX_HISTORY = 32


@dataclass(frozen=True)
class ContextRow:
    name: str
    cluster: str
    user: str
    namespace: str
    current: bool = False

    def cells(self) -> tuple[str, ...]:
        return ("*" if self.current else "", self.name, self.cluster, self.user, self.namespace)


@dataclass(frozen=True)
class NamespaceChoice:
    namespace: str | None

    def __post_init__(self) -> None:
        if self.namespace is not None:
            namespace_name(self.namespace)


@dataclass(frozen=True)
class NavigationState:
    context: str
    namespace: str | None
    query: str = ""
    column: str = PodColumn.NAME
    descending: bool = False
    selected: str | None = None
    index: int = 0
    x: float = 0
    y: float = 0
    top: str | None = None
    resource: str = "pods"


class NavigationHistory:
    def __init__(self) -> None:
        self.previous: list[NavigationState] = []
        self.following: list[NavigationState] = []

    def visit(self, current: NavigationState) -> None:
        if not self.previous or self.previous[-1] != current:
            self.previous.append(current)
            del self.previous[:-MAX_HISTORY]
        self.following.clear()

    def move(self, current: NavigationState, *, forward: bool = False) -> NavigationState | None:
        source, destination = (
            (self.following, self.previous) if forward else (self.previous, self.following)
        )
        if not source:
            return None
        result = source.pop()
        destination.append(current)
        del destination[:-MAX_HISTORY]
        return result
