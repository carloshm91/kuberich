"""Track the selected standard definition without dispatching on display text."""

from collections.abc import Callable

from kuberich.domain.registry import ResourceDefinition, ResourceRow
from kuberich.domain.views import ViewObservation
from kuberich.services.pods import ResourceProjection, StandardProjection
from kuberich.ui.controllers.base import ProjectedRows, RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter
from kuberich.ui.controllers.resources import ResourceController, ResourceTable


class StandardController(ResourceController[ResourceRow]):
    def __init__(
        self,
        table: ResourceTable[ResourceRow],
        definition: Callable[[], ResourceDefinition],
        filtering: ResourceFilter,
        prepare: Callable[[ViewObservation], object],
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: Callable[
            [ResourceDefinition], ResourceProjection[ResourceRow]
        ] = StandardProjection,
    ) -> None:
        self.definition = definition
        self.selected = definition()
        self.factory = projection
        super().__init__(table, self.factory(self.selected), filtering, prepare, actions)

    async def project(self, request: RenderRequest) -> ProjectedRows[ResourceRow]:
        definition = self.definition()
        if definition != self.selected:
            await self.retire_projection()
            self.selected = definition
            self.projection = self.factory(definition)
        return await super().project(request)
