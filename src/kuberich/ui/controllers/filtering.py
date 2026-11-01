"""Share the existing metadata policy without retaining an application owner."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import ResourceRow
from kuberich.services.filtering import FilterResult
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.controllers.base import RenderRequest


@dataclass(frozen=True)
class FilterOptions:
    errors: bool = False
    favorites: bool = False
    namespaces: tuple[str, ...] = ()


class ResourceFilter:
    def __init__(
        self,
        metadata: MetadataFilter,
        options: Callable[[str | None], FilterOptions],
    ) -> None:
        self.metadata, self.options = metadata, options

    async def apply[T: PodRow | NamespaceRow | ResourceRow](
        self, rows: tuple[T, ...], request: RenderRequest
    ) -> FilterResult[T]:
        view, kind = request.observation, request.route.display_key
        records = view.snapshot.items if view.snapshot else ()
        result = await self.metadata.apply(
            rows, records, request.query, kind, errors=self.options(view.context).errors
        )
        # Preserve the existing live preference read after the owned filter
        # worker. The render guard separately refuses an obsolete revision.
        options = self.options(view.context)
        if kind == "namespaces" and options.favorites and result.problem is None:
            result = replace(
                result, rows=tuple(row for row in result.rows if row.name in options.namespaces)
            )
        if options.errors and result.problem is None:
            result = replace(
                result,
                problem=f"Errors only · {len(result.rows)}/{len(rows)} {kind} · {result.unknown} unknown omitted",
            )
        return result
