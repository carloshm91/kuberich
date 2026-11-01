"""Own incremental namespace rows behind the common rendering contract."""

from collections.abc import Callable

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.views import ViewObservation
from kuberich.services.pods import NamespaceProjection, ResourceProjection
from kuberich.ui.controllers.base import RenderRequest
from kuberich.ui.controllers.filtering import ResourceFilter
from kuberich.ui.controllers.resources import ResourceController, ResourceTable


class NamespaceController(ResourceController[NamespaceRow]):
    def __init__(
        self,
        table: ResourceTable[NamespaceRow],
        filtering: ResourceFilter,
        prepare: Callable[[ViewObservation], object],
        actions: Callable[[RenderRequest], frozenset[str]],
        *,
        projection: ResourceProjection[NamespaceRow] | None = None,
    ) -> None:
        super().__init__(
            table,
            projection if projection is not None else NamespaceProjection(),
            filtering,
            prepare,
            actions,
        )
