"""Structural read-only session ports for startup-independent export composition."""

from typing import Any, Protocol


class ExportClientContext(Protocol):
    @property
    def name(self) -> str: ...


class ResourceExportClient(Protocol):
    """The captured session's read-only port, without importing its transport."""

    @property
    def context(self) -> ExportClientContext: ...

    async def get_json(self, path: str) -> dict[str, Any]: ...
