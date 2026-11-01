"""Construct only selected view adapters and retire inactive decoded records."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.ui.controllers.base import RenderPort


@dataclass(frozen=True)
class ViewEntry:
    driver: RenderPort
    retire: Callable[[], Awaitable[None]] | None = None
    close: Callable[[], Awaitable[None]] | None = None


class ViewRegistry:
    def __init__(self, factories: Mapping[ViewKind, Callable[[], ViewEntry]]) -> None:
        self._factories = dict(factories)
        self._entries: dict[ViewKind, ViewEntry] = {}

    def resolve(self, route: ViewRoute) -> RenderPort:
        entry = self._entries.get(route.kind)
        if entry is None:
            entry = self._factories[route.kind]()
            self._entries[route.kind] = entry
        return entry.driver

    async def retire_inactive(self, route: ViewRoute) -> None:
        for kind, entry in tuple(self._entries.items()):
            if kind is not route.kind and entry.retire is not None:
                await entry.retire()

    async def close(self) -> None:
        for entry in tuple(self._entries.values()):
            close = entry.close or entry.retire
            if close is not None:
                await close()
