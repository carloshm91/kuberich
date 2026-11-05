"""Share the existing metadata policy without retaining an application owner."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import PodRow
from kuberich.domain.pulse import PulseDrilldown
from kuberich.domain.registry import ResourceRow
from kuberich.domain.resources import ResourceRecord
from kuberich.services.filtering import FilterResult
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.services.resources import parse_owned
from kuberich.ui.controllers.base import RenderRequest


@dataclass(frozen=True)
class FilterOptions:
    errors: bool = False
    favorites: bool = False
    namespaces: tuple[str, ...] = ()


def _drilldown_rows[T: PodRow | NamespaceRow | ResourceRow](
    rows: tuple[T, ...], records: tuple[ResourceRecord, ...], drilldown: PulseDrilldown
) -> tuple[T, ...]:
    matches = {
        record.uid
        for record in records
        if (drilldown.uid is None or record.uid == drilldown.uid)
        and drilldown.predicate.matches(record)
    }
    return tuple(row for row in rows if row.uid in matches)


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
        if request.drilldown is not None:
            rows = await parse_owned(partial(_drilldown_rows, rows, records, request.drilldown))
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
