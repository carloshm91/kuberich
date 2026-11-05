"""One typed render pipeline, independent of the controller's row representation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from kuberich.domain.authorization_rows import AuthorizationRow
from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import ContextRow, Viewport
from kuberich.domain.pods import PodRow
from kuberich.domain.pulse import PulseDrilldown, PulseRow
from kuberich.domain.registry import ResourceRow
from kuberich.domain.relationships import RelationshipRow
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.services.filtering import FilterResult

type ViewRow = (
    PodRow | NamespaceRow | ContextRow | ResourceRow | PulseRow | RelationshipRow | AuthorizationRow
)


@dataclass(frozen=True)
class RenderRequest:
    observation: ViewObservation
    query: str
    current: Callable[[], bool]
    route: ViewRoute
    drilldown: PulseDrilldown | None = None
    expected_uid: str | None = None


@dataclass(frozen=True)
class ProjectedRows[T: ViewRow]:
    """Rows plus an additional projection guard; live request checks always apply."""

    rows: tuple[T, ...]
    current: Callable[[], bool]


@dataclass(frozen=True)
class RenderOutcome:
    count: int
    filtered: int
    problem: str | None
    unknown: int
    applied: bool


class ViewController[T: ViewRow](Protocol):
    async def project(self, request: RenderRequest) -> ProjectedRows[T]: ...

    async def filter(self, rows: tuple[T, ...], request: RenderRequest) -> FilterResult[T]: ...

    async def apply(self, rows: tuple[T, ...], request: RenderRequest) -> bool: ...

    def capture_viewport(self) -> Viewport: ...

    def restore_viewport(self, viewport: Viewport) -> None: ...

    def available_actions(self, request: RenderRequest) -> frozenset[str]: ...


class RenderPort(Protocol):
    """The coordinator needs results and navigation, rather than an erased row type."""

    async def render(self, request: RenderRequest) -> RenderOutcome: ...

    def capture_viewport(self) -> Viewport: ...

    def restore_viewport(self, viewport: Viewport) -> None: ...

    def available_actions(self, request: RenderRequest) -> frozenset[str]: ...


class ViewDriver[T: ViewRow]:
    def __init__(self, controller: ViewController[T]) -> None:
        self.controller = controller

    async def render(self, request: RenderRequest) -> RenderOutcome:
        projected = await self.controller.project(request)
        guarded = replace(request, current=lambda: request.current() and projected.current())
        rows = projected.rows
        if request.expected_uid is not None:
            rows = tuple(
                row
                for row in rows
                if not isinstance(row, PodRow | NamespaceRow | ResourceRow)
                or row.uid == request.expected_uid
            )
        result = await self.controller.filter(rows, guarded)
        applied = await self.controller.apply(result.rows, guarded)
        return RenderOutcome(len(rows), len(result.rows), result.problem, result.unknown, applied)

    def capture_viewport(self) -> Viewport:
        return self.controller.capture_viewport()

    def restore_viewport(self, viewport: Viewport) -> None:
        self.controller.restore_viewport(viewport)

    def available_actions(self, request: RenderRequest) -> frozenset[str]:
        return self.controller.available_actions(request)
