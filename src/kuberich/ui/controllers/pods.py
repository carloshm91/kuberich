"""Own incremental pod rows behind the common resource rendering contract."""

from collections.abc import Callable

from kuberich.domain.pods import PodRow
from kuberich.domain.views import ViewObservation
from kuberich.services.pods import PodProjection, ResourceProjection
from kuberich.ui.controllers.base import RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter
from kuberich.ui.controllers.resources import ResourceController, ResourceTable


class PodController(ResourceController[PodRow]):
    def __init__(
        self,
        table: ResourceTable[PodRow],
        filtering: ResourceFilter,
        prepare: Callable[[ViewObservation], object],
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: ResourceProjection[PodRow] | None = None,
    ) -> None:
        super().__init__(
            table,
            projection if projection is not None else PodProjection(),
            filtering,
            prepare,
            actions,
        )
