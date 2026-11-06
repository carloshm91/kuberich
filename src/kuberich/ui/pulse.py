"""Native overview rows and bounded terminal charts with explicit missing samples."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import MAX_EMAX, MIN_EMIN, Decimal, localcontext

from rich.text import Text
from textual.widgets.data_table import RowKey

from kuberich.domain.history import HistorySeries, HistorySnapshot
from kuberich.domain.metrics import MetricReport
from kuberich.domain.navigation import Viewport
from kuberich.domain.pulse import (
    PulseDrilldown,
    PulsePredicate,
    PulseRow,
    PulseScope,
    PulseSnapshot,
    PulseSource,
    PulseStatus,
)
from kuberich.security.presentation import safe_text
from kuberich.ui.presentation import FrameTable

_COLUMNS = ("SUMMARY", "VALUE", "DATA / TIME (UTC)", "DETAIL")
_BLOCKS = "▁▂▃▄▅▆▇█"
_FAILED_SOURCES = frozenset({PulseStatus.FAILED, PulseStatus.FORBIDDEN, PulseStatus.UNAVAILABLE})


def timestamp(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds") if value is not None else "never"


def history_number(value: Decimal | None, unit: str) -> str:
    """Bound precision and output size, including adversarial Decimal exponents."""
    if value is None or not value.is_finite() or not 0 <= value <= Decimal("1e30"):
        return "N/A"
    with localcontext() as context:
        context.prec = 12
        context.Emax, context.Emin = MAX_EMAX, MIN_EMIN
        scaled = value * 1000 if unit == "cores" else value / 1048576 if unit == "bytes" else value
        rendered = format(scaled, ".4g")
        return (
            rendered.rstrip("0").rstrip(".")
            if "." in rendered and "e" not in rendered.lower()
            else rendered
        )


def history_unit(unit: str) -> str:
    return "mCPU" if unit == "cores" else "MiB" if unit == "bytes" else unit


def sparkline(series: HistorySeries, width: int = 32, *, ascii_only: bool = False) -> str:
    """Retain gaps when downsampling; neither missing nor zero implies health."""
    points = series.points
    if not points:
        return "no samples"
    size = min(max(1, width), len(points))
    values: list[Decimal | None] = []
    for index in range(size):
        bucket = points[index * len(points) // size : (index + 1) * len(points) // size]
        present = tuple(
            point.value
            for point in bucket
            if point.value is not None and point.value.is_finite() and point.value >= 0
        )
        values.append(max(present) if len(present) == len(bucket) else None)
    maximum = max((value for value in values if value is not None), default=Decimal(0))
    blocks, gap = ("._-:=+*#", "?") if ascii_only else (_BLOCKS, "·")
    with localcontext() as context:
        context.prec = 12
        return "".join(
            gap
            if value is None
            else blocks[min(7, int(value / maximum * 7))]
            if maximum
            else blocks[0]
            for value in values
        )


def history_cells(history: HistorySnapshot) -> tuple[tuple[str, str, str, str], ...]:
    scope_hint = (
        "backend unverified"
        if "binding unverified" in history.scope_label
        else "configured selector"
        if history.scope_label.startswith("Configured cluster selector")
        else ""
    )
    header = (
        "History",
        str(history.status) + (f"\n{scope_hint}" if scope_hint else ""),
        f"queried {timestamp(history.observed_at)}",
        f"{history.scope_label} · {timestamp(history.start)} → {timestamp(history.end)}"
        f" · step {history.step_seconds}s · {history.detail}"
        " · · = missing sample; query time does not establish scrape freshness",
    )
    charts = []
    for series in history.series:
        value = series.points[-1].value if series.points else None
        unit = history_unit(series.unit)
        maximum = max(
            (point.value for point in series.points if point.value is not None), default=None
        )
        charts.append(
            (
                series.label,
                f"{history_number(value, series.unit)} {unit} · 0..{history_number(maximum, series.unit)}\n{sparkline(series)}",
                str(history.status),
                f"{series.key} · scale uses available samples · {history.scope_label}",
            )
        )
    return (header, *charts)


@dataclass(frozen=True)
class _DisplayRow:
    key: str
    cells: tuple[str, str, str, str]


def _source_text(source: PulseSource | None) -> str:
    if source is None:
        return "loading · never"
    qualifier = " · INCOMPLETE" if source.limited or not source.complete else ""
    scope = (
        "cluster"
        if source.key in {"nodes", "node_metrics"}
        else source.namespace or "all namespaces"
    )
    attempted = (
        f" · {source.status} attempt {timestamp(source.attempted_at)}"
        if source.attempted_at is not None and source.status in _FAILED_SOURCES
        else ""
    )
    return f"{source.status}{qualifier} · {scope} · observed {timestamp(source.observed_at)}{attempted}"


def _api_observation(
    source: PulseSource | None, kind: str, stored: bool, observed_at: datetime | None
) -> str:
    observed = f"{kind} API observed {timestamp(observed_at)}"
    if source is None:
        return observed
    if source.status is not PulseStatus.VALID or observed_at != source.observed_at:
        if stored:
            observed += f" · retained {kind}"
        observed += f" · source {source.status}"
        if source.attempted_at is not None and source.status in _FAILED_SOURCES:
            observed += f" · {source.status} attempt {timestamp(source.attempted_at)}"
    return observed


def _metric_rows(
    report: MetricReport,
    title: str,
    key: str,
    source: PulseSource | None,
    observed_at: datetime | None,
) -> tuple[_DisplayRow, ...]:
    return tuple(
        _DisplayRow(
            f"metric:{key}:{unit}",
            (
                f"{title} {label}",
                f"{report.value(unit)[0]} {suffix}",
                f"{report.status} · {timestamp(report.timestamp)}",
                (
                    f"capacity {report.value(unit + '-capacity')[0]} {suffix}"
                    f" · allocatable {report.value(unit + '-allocatable')[0]} {suffix}"
                    if key == "node"
                    else f"requests {report.value(unit + '-req')[0]} {suffix}"
                    f" · limits {report.value(unit + '-lim')[0]} {suffix}"
                )
                + (" · partial" if amount.partial else "")
                + (" · uncertain budget" if amount.uncertain else "")
                + (" · allocation uncertain" if report.allocation_uncertain else "")
                + " · "
                + _api_observation(
                    source,
                    "capacity" if key == "node" else "budgets",
                    amount.capacity is not None or amount.allocatable is not None
                    if key == "node"
                    else amount.request is not None or amount.limit is not None or amount.unlimited,
                    observed_at,
                )
                + (f" · {report.detail}" if report.detail else ""),
            ),
        )
        for unit, label, suffix, amount in (
            ("cpu", "CPU", "mCPU", report.cpu),
            ("memory", "memory", "MiB", report.memory),
        )
    )


class PulseTable(FrameTable[Text]):
    """A real workspace table; aggregate rows never masquerade as API objects."""

    DEFAULT_CSS = "PulseTable { height: 1fr; min-height: 2; background: $background; }"

    def __init__(self) -> None:
        super().__init__(id="pulse", cursor_type="row", zebra_stripes=False)
        self._rows: dict[str, PulseRow] = {}
        self._display_rows: dict[str, _DisplayRow] = {}
        self._metric_drilldowns: dict[str, PulseDrilldown] = {}
        self._restoration = 0
        self.scope: PulseScope | None = None

    def setup(self) -> None:
        for column in _COLUMNS:
            self.add_column(column, key=column, width=36 if column == "VALUE" else None)

    def reset(self, revision: int) -> None:
        self.clear()
        self._rows.clear()
        self._display_rows.clear()
        self._metric_drilldowns.clear()
        self.scope = None

    def drilldown(self, key: str | None) -> PulseDrilldown | None:
        row = self._rows.get(key or "")
        return row.drilldown if row is not None else self._metric_drilldowns.get(key or "")

    def capture_viewport(self) -> Viewport:
        selected = (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )
        top, offset, position = None, 0.0, 0.0
        for row in self.ordered_rows:
            height = self.get_row_height(row.key)
            if position + height > self.scroll_y:
                top, offset = row.key.value, self.scroll_y - position
                break
            position += height
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top, offset)

    def _row_top(self, key: str | None) -> float | None:
        position = 0.0
        for row in self.ordered_rows:
            if row.key.value == key:
                return position
            position += self.get_row_height(row.key)
        return None

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected is not None and viewport.selected in self.rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        revision, selected = self._restoration, self.capture_viewport().selected

        def restore() -> None:
            if revision == self._restoration and selected == self.capture_viewport().selected:
                top = self._row_top(viewport.top)
                y = top + viewport.top_offset if top is not None else viewport.y
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)

    async def apply_rows(
        self,
        rows: tuple[PulseRow, ...],
        snapshot: PulseSnapshot | None,
        current: Callable[[], bool],
        *,
        filtered: bool = False,
    ) -> bool:
        if not current():
            return False
        now = datetime.now(UTC)
        sources = (
            {source.key: source for source in snapshot.sources} if snapshot is not None else {}
        )
        metric_drilldowns = {}
        if snapshot is not None and not filtered:
            for family, name, predicate in (
                ("node", "nodes", PulsePredicate.ALL),
                ("pod", "pods", PulsePredicate.POD_ACTIVE),
            ):
                source = sources.get(name)
                if source is not None and source.resource is not None:
                    for unit in ("cpu", "memory"):
                        metric_drilldowns[f"metric:{family}:{unit}"] = PulseDrilldown(
                            source.resource,
                            source.namespace,
                            predicate,
                            sort=unit,
                            query=predicate.query,
                            descending=True,
                        )
        summaries = [
            _DisplayRow(
                row.key,
                (
                    row.label,
                    str(row.count) if row.count is not None else "N/A",
                    _source_text(sources.get(row.source)),
                    row.detail,
                ),
            )
            for row in rows
        ]
        display = []
        if snapshot is not None and not filtered:
            display += [
                *_metric_rows(
                    snapshot.node_metrics.fresh(now),
                    "Node usage",
                    "node",
                    sources.get("nodes"),
                    snapshot.capacity_observed_at,
                ),
                *_metric_rows(
                    snapshot.pod_metrics.fresh(now),
                    "Pod usage",
                    "pod",
                    sources.get("pods"),
                    snapshot.budgets_observed_at,
                ),
            ]
            if snapshot.history is not None:
                display += [
                    _DisplayRow(f"history:{index}", cells)
                    for index, cells in enumerate(history_cells(snapshot.history.fresh(now)))
                ]
        display += summaries
        if not display and not filtered:
            display = [
                _DisplayRow(
                    "loading",
                    ("Pulse", "loading", "No observations yet", "Each source loads independently."),
                )
            ]
        viewport = self.capture_viewport()
        incoming = {row.key: row for row in display}
        for key in tuple(self._display_rows):
            if key not in incoming:
                self.remove_row(key)
        for item in display:
            cells = tuple(
                safe_text(value, multiline=item.key.startswith("history:")) for value in item.cells
            )
            height = max(1, *(len(value.plain.splitlines()) for value in cells))
            if (
                item.key not in self._display_rows
                or self.get_row_height(RowKey(item.key)) != height
            ):
                if item.key in self._display_rows:
                    self.remove_row(item.key)
                self.add_row(
                    *cells,
                    key=item.key,
                    height=height,
                )
            elif item != self._display_rows[item.key]:
                for column, value in zip(_COLUMNS, cells, strict=True):
                    self.update_cell(item.key, column, value, update_width=True)
        order = {
            tuple(
                safe_text(value, multiline=row.key.startswith("history:")).plain
                for value in row.cells
            ): index
            for index, row in enumerate(display)
        }
        # Domain keys and source order stay stable through progressive updates.
        self.sort(key=lambda cells: order[tuple(cell.plain for cell in cells)])
        self._display_rows, self._rows = incoming, {row.key: row for row in rows}
        self._metric_drilldowns = metric_drilldowns
        self.scope = snapshot.scope if snapshot is not None else None
        self.restore_viewport(viewport)
        return True
