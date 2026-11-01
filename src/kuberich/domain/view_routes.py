"""Keep typed view modes separate from canonical API and navigation identities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kuberich.domain.registry import ResourceDefinition
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError


class ViewKind(Enum):
    PODS = "pods"
    NAMESPACES = "namespaces"
    CONTEXTS = "contexts"
    STANDARD = "standard"
    CUSTOM = "custom"


@dataclass(frozen=True)
class ViewRoute:
    """Routing shape; discovery retains authority over requested API versions."""

    kind: ViewKind
    selection: ResourceSelection | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ViewKind):
            raise AppError("A view route requires a known view kind.")
        if self.selection is not None and not isinstance(self.selection, ResourceSelection):
            raise AppError("A view route requires a canonical resource selection value.")
        if self.kind is ViewKind.CONTEXTS:
            if self.selection is not None:
                raise AppError("The local contexts view has no API resource selection.")
            return
        selection = self.selection
        if selection is None:
            raise AppError("A resource view requires a canonical resource selection.")
        if selection.server_columns != (self.kind is ViewKind.CUSTOM):
            raise AppError("Server-column selection belongs to the custom resource view.")
        if self.kind in {ViewKind.PODS, ViewKind.NAMESPACES} and (
            selection.name != self.kind.value or selection.group
        ):
            raise AppError("A built-in view requires its matching core API resource.")
        if (
            self.kind is ViewKind.STANDARD
            and not selection.group
            and selection.name in {"pods", "namespaces"}
        ):
            raise AppError("Pods and namespaces use their dedicated view controllers.")

    @property
    def display_key(self) -> str:
        """Preserve existing public navigation keys without dispatching on them."""
        if self.selection is None:
            return self.kind.value
        if self.kind is ViewKind.CUSTOM:
            return self.selection.name + "." + (self.selection.group or "core")
        return self.selection.name

    @property
    def resource_name(self) -> str | None:
        return self.selection.name if self.selection is not None else None

    @classmethod
    def pods(cls) -> ViewRoute:
        return cls(ViewKind.PODS, ResourceSelection("pods"))

    @classmethod
    def namespaces(cls) -> ViewRoute:
        return cls(ViewKind.NAMESPACES, ResourceSelection("namespaces"))

    @classmethod
    def contexts(cls) -> ViewRoute:
        return cls(ViewKind.CONTEXTS)

    @classmethod
    def standard(cls, definition: ResourceDefinition) -> ViewRoute:
        return cls(ViewKind.STANDARD, definition.selection)

    @classmethod
    def custom(cls, selection: ResourceSelection) -> ViewRoute:
        return cls(ViewKind.CUSTOM, selection)
