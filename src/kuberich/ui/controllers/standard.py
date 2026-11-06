"""Track the selected standard definition without dispatching on display text."""

from collections.abc import Callable
from typing import Protocol

from kuberich.domain.registry import ResourceDefinition, ResourceRow, definition_for_resource
from kuberich.domain.resources import ApiResource
from kuberich.domain.views import ResourceScope, ViewObservation
from kuberich.services.pods import ResourceProjection, StandardProjection
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter
from kuberich.ui.controllers.resources import ResourceController, ResourceTable


class StandardTablePort(ResourceTable[ResourceRow], Protocol):
    def configure(self, definition: ResourceDefinition) -> None: ...


class StandardController(ResourceController[ResourceRow]):
    table: StandardTablePort

    def __init__(
        self,
        table: StandardTablePort,
        definition: Callable[[], ResourceDefinition],
        filtering: ResourceFilter,
        prepare: Callable[[ViewObservation], object],
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: Callable[
            [ResourceDefinition, ApiResource | None], ResourceProjection[ResourceRow]
        ] = StandardProjection,
    ) -> None:
        self.definition = definition
        self.selected = definition()
        self.selected_resource: ApiResource | None = None
        self.selected_scope: ResourceScope | None = None
        self.factory = projection
        super().__init__(
            table, self.factory(self.selected, None), filtering, prepare, actions, metrics=True
        )

    async def project(self, request: RenderRequest) -> ProjectedRows[ResourceRow]:
        definition = self.definition()
        scope, snapshot = request.observation.scope, request.observation.snapshot
        resource = (
            scope.resource
            if scope is not None
            else snapshot.resource
            if snapshot is not None
            else None
        )
        if resource is not None:
            metadata_only = bool(
                (scope is not None and scope.query.compact)
                or (
                    snapshot is not None
                    and snapshot.items
                    and all(record.metadata_only for record in snapshot.items)
                )
            )
            resolved = definition_for_resource(resource, metadata_only=metadata_only)
            if resolved is not None and resolved != definition:
                definition = resolved
                self.table.configure(definition)
        if (
            definition != self.selected
            or resource != self.selected_resource
            or scope != self.selected_scope
        ):
            await self.retire_projection()
            self.selected = definition
            self.selected_resource = resource
            self.selected_scope = scope
            self.projection = self.factory(definition, resource)
        return await super().project(request)
