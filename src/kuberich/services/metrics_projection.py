"""Apply current UID-bound numeric samples after the cached manifest projection."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from kuberich.domain.metrics import METRIC_KEYS, MetricReport, MetricsSnapshot
from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.pods import PodRow
from kuberich.domain.registry import Column, ResourceRow, Value
from kuberich.domain.views import ViewObservation


def with_metrics[T: PodRow | NamespaceRow | ResourceRow](
    rows: tuple[T, ...], view: ViewObservation
) -> tuple[T, ...]:
    metrics = view.metrics or MetricsSnapshot()
    index, now = dict(metrics.reports), datetime.now(UTC)
    columns: tuple[Column, ...] = ()
    if view.scope is not None:
        from kuberich.domain.registry import STANDARD_RESOURCES

        columns = next(
            (
                definition.columns
                for definition in STANDARD_RESOURCES
                if definition.name == view.scope.resource.name
                and definition.group == view.scope.resource.group
                and not definition.curated
            ),
            (),
        )
    result: list[PodRow | NamespaceRow | ResourceRow] = []
    for row in rows:
        report = metrics.current(
            index.get(row.uid, MetricReport(metrics.status, detail=metrics.detail)), now
        )
        if isinstance(row, PodRow):
            result.append(replace(row, metrics=report))
        elif isinstance(row, ResourceRow) and len(columns) == len(row.values):
            result.append(
                replace(
                    row,
                    values=tuple(
                        Value(*report.value(column.key)) if column.key in METRIC_KEYS else value
                        for column, value in zip(columns, row.values, strict=True)
                    ),
                )
            )
        else:
            result.append(row)
    return cast(tuple[T, ...], tuple(result))
