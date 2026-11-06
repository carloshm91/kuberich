"""Finite metric exploration with explicit identity, gaps and owned cancellation."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar, Literal
from uuid import uuid4

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal
from textual.events import Resize, ScreenResume
from textual.widgets import Button, Input, Static

from kuberich.domain.exports import ExportPresentation, ExportScope, TableSource
from kuberich.domain.history import (
    BackendCandidates,
    ExternalHistoryBackend,
    HistoryBackend,
    HistoryOptions,
    HistoryRange,
    HistoryRequest,
    HistoryScope,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    MetricFamily,
    history_window,
)
from kuberich.domain.navigation import Viewport
from kuberich.domain.resources import ResourceRecord
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.ownership import finish_owned
from kuberich.ui.chrome import (
    Breadcrumbs,
    WorkspaceBars,
    WorkspaceChrome,
    WorkspaceFrame,
    WorkspaceHeader,
)
from kuberich.ui.export_captures import captured_lease, header_namespace
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.presentation import FrameTable
from kuberich.ui.pulse import history_number, history_unit, sparkline, timestamp

if TYPE_CHECKING:
    from kuberich.services.exports import ExportChoices
    from kuberich.services.history_workspace import HistoryWorkspace

_RANGES: tuple[tuple[HistoryRange, str], ...] = (
    (900, "15m"),
    (1800, "30m"),
    (3600, "1h"),
    (10800, "3h"),
    (21600, "6h"),
    (43200, "12h"),
    (86400, "24h"),
)
_FAMILIES: tuple[MetricFamily, ...] = ("cpu", "memory", "network", "filesystem")
_COLUMNS = ("METRIC / SOURCE", "LAST / MIN / MAX", "CHART / EVIDENCE")
_SHORTCUTS = (
    ("1-7", "Range"),
    ("c/m/n/f", "Metric"),
    ("[/]", "Device"),
    ("d / b", "Detect / backend"),
    ("r", "Refresh"),
    ("a", "ASCII"),
    ("u", "Membership"),
    ("Esc", "Back"),
    (":", "Command"),
)
type Row = tuple[str, tuple[str, str, str]]
type Device = tuple[tuple[str, str], ...]


def _text(value: str, limit: int = 512) -> str:
    return safe_text(value[:limit], multiline=False).plain + (" …" if len(value) > limit else "")


def _family(series: HistorySeries) -> str:
    return (
        "network"
        if series.key.startswith("network")
        else "filesystem"
        if series.key.startswith("filesystem")
        else series.key
    )


def _row_key(series: HistorySeries) -> str:
    return json.dumps((series.key, series.labels), ensure_ascii=True, separators=(",", ":"))


def _labels(labels: Device) -> str:
    return _text(", ".join(f"{key}={value}" for key, value in labels)) or "aggregate"


def _statistics(series: HistorySeries) -> str:
    present = tuple(point.value for point in series.points if point.value is not None)
    last = series.points[-1].value if series.points else None
    return (
        f"last {history_number(last, series.unit)} {history_unit(series.unit)}\n"
        f"min {history_number(min(present, default=None), series.unit)} · "
        f"max {history_number(max(present, default=None), series.unit)}"
    )


class HistoryTable(FrameTable[Text]):
    BINDING_PROFILE = "history"
    BINDINGS: ClassVar[list[BindingType]] = table_bindings("history")

    def __init__(self) -> None:
        super().__init__(id="history-table", cursor_type="row", zebra_stripes=True)
        self._restoration = 0

    def capture_viewport(self) -> Viewport:
        selected = (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )
        position, top, offset = 0.0, None, 0.0
        for row in self.ordered_rows:
            height = self.get_row_height(row.key)
            if position + height > self.scroll_y:
                top, offset = row.key.value, self.scroll_y - position
                break
            position += height
        return Viewport(selected, self.cursor_row, self.scroll_x, self.scroll_y, top, offset)

    def restore_viewport(self, viewport: Viewport) -> None:
        row = (
            self.get_row_index(viewport.selected)
            if viewport.selected is not None and viewport.selected in self.rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=row, scroll=False)
        self._restoration += 1
        revision = self._restoration

        def restore() -> None:
            if revision != self._restoration:
                return
            position = 0.0
            y = viewport.y
            for item in self.ordered_rows:
                if item.key.value == viewport.top:
                    y = position + viewport.top_offset
                    break
                position += self.get_row_height(item.key)
            self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore)


class HistoryScreen(CommandWorkspace):
    """One foreground claim survives overlays and ends only after callers drain."""

    AUTO_FOCUS = "#history-table"
    BINDINGS: ClassVar[list[BindingType]] = [
        *(
            Binding(str(index), f"range({seconds})", label)
            for index, (seconds, label) in enumerate(_RANGES, 1)
        ),
        Binding("c", "family('cpu')", "CPU"),
        Binding("m", "family('memory')", "Memory"),
        Binding("n", "family('network')", "Network"),
        Binding("f", "family('filesystem')", "Filesystem"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "detect", "Detect backend"),
        Binding("b", "backend", "Next backend"),
        Binding("left_square_bracket", "device(-1)", "Previous device"),
        Binding("right_square_bracket", "device(1)", "Next device"),
        Binding("a", "ascii", "ASCII chart"),
        Binding("u", "membership", "Membership basis"),
    ]
    DEFAULT_CSS = """
    HistoryScreen { layout: vertical; background: $background; }
    #history-title, #history-status, #history-controls { height: 1; }
    #history-title { color: $accent; text-overflow: ellipsis; }
    #history-status { text-overflow: ellipsis; }
    #history-controls Button { height: 1; border: none; min-width: 3; width: 1fr; }
    #history-table { height: 1fr; min-height: 1; }
    HistoryScreen.short #history-title { display: none; }
    """

    def __init__(
        self,
        owner: HistoryWorkspace,
        scope: HistoryScope,
        options: HistoryOptions | None,
        *,
        chrome: WorkspaceChrome | None = None,
        trail: tuple[str, ...] = (),
        stopped: Callable[[], None] = lambda: None,
        current: Callable[[], bool] = lambda: True,
        detection_namespace: str | None = None,
    ) -> None:
        super().__init__()
        self.owner, self.scope, self.options, self.chrome = owner, scope, options, chrome
        self.trail, self._notify_stopped = (*trail, "metric history"), stopped
        self._is_current = current
        self.detection_namespace = (
            scope.namespace if detection_namespace is None else detection_namespace
        )
        self.range_seconds: HistoryRange = 900
        self.family: MetricFamily = "cpu"
        self.device: Device | None = None
        self.ascii_only = False
        self.snapshot: HistorySnapshot | None = None
        self.request: HistoryRequest | None = None
        self.candidates = BackendCandidates()
        self._backend_index = -1
        self._message = ""
        self.invalidated = False
        self._generation = 0
        self._pending: Literal["collect", "detect"] | None = None
        self._runner: asyncio.Task[None] | None = None
        self._active: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._loading = False
        self._last_status: HistoryStatus | None = None
        self._rendered: dict[str, tuple[str, str, str]] = {}
        self.table = HistoryTable()
        self.status = Static("Metric history · loading", markup=False, id="history-status")

    @property
    def operation_count(self) -> int:
        return (
            int(self._runner is not None and not self._runner.done()) + self.owner.operation_count
        )

    def compose(self) -> ComposeResult:
        if self.chrome is not None:
            yield WorkspaceHeader(self.chrome, _SHORTCUTS, binding_profile="history")
        with WorkspaceBars():
            yield Static(_text(self._requested()), markup=False, id="history-title")
            with Horizontal(id="history-controls"):
                for label, action in (
                    ("Range", "range"),
                    ("Metric", "metric"),
                    ("Dev", "device"),
                    ("Backends", "backend"),
                    ("Detect", "detect"),
                    ("Refresh", "refresh"),
                    ("Back", "back"),
                ):
                    yield Button(label, id="history-" + action, compact=True)
            yield from self.command_bar()
        with WorkspaceFrame(id="history-dialog"):
            yield self.table
        yield self.status
        yield Breadcrumbs(
            self.trail,
            "Previous view",
            visible=self.chrome is None or not self.chrome.presentation.crumbsless,
        )

    def on_mount(self) -> None:
        for label, width in zip(_COLUMNS, (32, 32, 72), strict=True):
            self.table.add_column(label, key=label, width=width)
        self.validate_target()
        if self.invalidated:
            return
        self.owner.enter_detail(self.scope)
        self.set_interval(1, self._expire)
        self.call_after_refresh(self.action_refresh)

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.height < 16, "short")

    def _requested(self) -> str:
        target = self.scope.target
        entity = (
            "cluster"
            if target is None
            else (
                f"{self.scope.kind} {target.namespace + '/' if target.namespace else ''}{target.name}"
                + (
                    f" / {self.scope.container_field}:{target.container}"
                    if target.container
                    else ""
                )
                + f" · UID {target.uid}"
            )
        )
        return f"Requested {entity} · context {self.scope.session.context} · namespace {self.scope.namespace or 'All'}"

    def _ready(self) -> bool:
        self.validate_target()
        return (
            not self._stopped
            and not self.invalidated
            and self.is_mounted
            and self.app.screen is self
        )

    def _queue(self, intent: Literal["collect", "detect"], *, overlay: bool = False) -> None:
        if not self._ready() and not (
            overlay
            and self.is_mounted
            and self in self.app.screen_stack
            and not self._stopped
            and not self.invalidated
        ):
            return
        # Invalidate before cancelling. One runner drains one active call and consumes
        # only the latest pending intent, rather than spawning a chain per key press.
        self._generation += 1
        self.owner.invalidate()
        self._pending = intent
        self._message = ""
        self._loading = True
        if self._active is not None:
            self._active.cancel()
        self._render_history()
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._pending is not None and not self._stopped and not self.invalidated:
            intent, self._pending = self._pending, None
            generation = self._generation
            self._active = asyncio.create_task(self._load(intent, generation))
            await finish_owned(asyncio.gather(self._active, return_exceptions=True))
            self._active = None
        self._loading = False
        if self.is_mounted and not self._stopped:
            self._render_history()

    async def _load(self, intent: Literal["collect", "detect"], generation: int) -> None:
        try:
            if intent == "detect":
                if self.detection_namespace is None:
                    self._message = (
                        "Detect requires a selected namespace; choose one before opening history."
                    )
                    return
                candidates = await self.owner.detect((self.detection_namespace,))
                if not self._is_current():
                    self._invalidate_target()
                    return
                if generation == self._generation and not self._stopped:
                    self.candidates = candidates
                    self._backend_index = -1
                    self._message = (
                        f"Detected {len(candidates.items)} candidates · "
                        + ("complete" if candidates.complete else "partial / denied")
                        + " · b selects; no unselected endpoint was probed"
                    )
                return
            if self.options is None:
                self.snapshot = HistorySnapshot()
                self.request = None
                return
            start, end, step = history_window(datetime.now(UTC), self.range_seconds)
            request = HistoryRequest(
                uuid4(),
                self.scope,
                self.options,
                start,
                end,
                step,
                _FAMILIES,
                self.owner.config_revision,
            )
            self.request = request
            snapshot = await self.owner.collect(request)
            if not self._is_current():
                self._invalidate_target()
                return
            if (
                generation == self._generation
                and request.config_revision != self.owner.config_revision
            ):
                self._invalidate_target()
                return
            if (
                generation == self._generation
                and not self.invalidated
                and not self._stopped
                and self.is_mounted
                and self in self.app.screen_stack
                and self.request is request
                and snapshot.request_id == request.id
            ):
                self.owner.require_current(self.scope)
                self.snapshot = snapshot
                self._last_status = None
                self._render_history()
        except Exception:
            if generation == self._generation and not self._stopped:
                self.snapshot = HistorySnapshot(
                    status=HistoryStatus.FAILED,
                    detail="History collection failed; refresh or select another backend.",
                )
                self._render_history()

    def _expire(self) -> None:
        if self.snapshot is not None and self.is_mounted and not self._stopped:
            status = self.snapshot.fresh(datetime.now(UTC)).status
            if status != self._last_status:
                self._render_history()

    def _selected_series(self, snapshot: HistorySnapshot) -> tuple[HistorySeries, ...]:
        series = tuple(item for item in snapshot.series if _family(item) == self.family)
        devices = tuple(dict.fromkeys(item.labels for item in series))
        if self.device not in devices:
            self.device = next(
                (device for device in devices if dict(device).get("mountpoint") == "/"),
                devices[0] if devices else None,
            )
        return tuple(item for item in series if item.labels == self.device)

    def _rows(self, snapshot: HistorySnapshot) -> tuple[Row, ...]:
        membership = snapshot.membership_evidence
        endpoint = snapshot.endpoint_identity
        provider = self.options.provider if self.options is not None else "none"
        source = (
            f"{endpoint.transport} · {endpoint.namespace}/{endpoint.service} · Service UID {endpoint.service_uid}"
            if endpoint is not None and endpoint.transport == "service"
            else f"{endpoint.transport} · {endpoint.origin}{endpoint.prefix}"
            if endpoint is not None
            else "No observed endpoint"
        )
        if endpoint is None and self.options is not None:
            configured = self.options.endpoint
            source = (
                f"configured Service {configured.namespace}/{configured.service}:{configured.port}"
                if isinstance(configured, HistoryBackend)
                else f"configured external {configured.origin}{configured.prefix}"
                if isinstance(configured, ExternalHistoryBackend)
                else source
            )
        rows: list[Row] = [
            (
                "requested",
                ("Requested entity", _text(self._requested()), _text(self.scope.membership)),
            ),
            (
                "backend",
                (
                    "Selected backend",
                    _text(source),
                    f"configured {provider} · {_text(endpoint.compatibility) if endpoint else 'provider unverified'}",
                ),
            ),
            (
                "scope",
                (
                    "Backend binding / selectors",
                    _text(snapshot.scope_label),
                    "Kubernetes target identity does not establish historical UID binding",
                ),
            ),
            (
                "membership",
                (
                    "Membership / confidence",
                    f"{membership.mode} · {membership.status}"
                    if membership
                    else self.scope.membership,
                    _text(membership.detail_code)
                    + (
                        f" · current verified members {len(membership.members)} · captured {timestamp(membership.observed_at)}"
                        if membership.mode == "current-members"
                        else " · historical contributor completeness remains qualified by source evidence"
                    )
                    if membership
                    else "Contributor completeness unknown",
                ),
            ),
            (
                "evaluation",
                (
                    "Evaluation / queried at",
                    f"step {snapshot.step_seconds}s · rate window {self.options.rate_window_seconds if self.options else 300}s",
                    f"{timestamp(snapshot.start)} → {timestamp(snapshot.end)} · queried {timestamp(snapshot.observed_at)}",
                ),
            ),
            (
                "availability",
                (
                    "Availability / source states",
                    str(snapshot.status),
                    _text(snapshot.detail)
                    + " · "
                    + _text(", ".join(f"{key}: {state}" for key, state in snapshot.source_status)),
                ),
            ),
        ]
        if self.options is not None:
            rows.append(
                (
                    "profile",
                    (
                        "Query / measurement profile",
                        self.options.profile,
                        ("rate_prometheus" if provider == "victoriametrics" else "rate")
                        + (
                            " · dedup=true · partial_response=false · max_source_resolution=0s"
                            if provider == "thanos"
                            else ""
                        )
                        + " · node selectors: "
                        + _labels(self.options.node_matchers)
                        + " · state selectors: "
                        + _labels(self.options.state_matchers),
                    ),
                )
            )
        for candidate in self.candidates.items:
            rows.append(
                (
                    f"candidate:{candidate.namespace}/{candidate.service}:{candidate.uid}:{candidate.port}",
                    (
                        "Detected candidate · b selects",
                        _text(
                            f"{candidate.namespace}/{candidate.service}:{candidate.port}{candidate.prefix}"
                        ),
                        _text(f"hint {candidate.provider_hint} · Service UID {candidate.uid}")
                        + (" · incomplete detection" if not self.candidates.complete else ""),
                    ),
                )
            )
        for notice in snapshot.notices:
            rows.append(
                ("notice:" + notice.code, ("Notice", _text(notice.code), _text(notice.message)))
            )
        metadata, rows = rows, []
        selected = self._selected_series(snapshot)
        for series in selected:
            present = sum(point.value is not None for point in series.points)
            quality = ", ".join(
                dict.fromkeys(str(item) for item in series.quality if str(item) != "observed")
            )
            rows.append(
                (
                    _row_key(series),
                    (
                        _text(series.label) + "\n" + _labels(series.labels),
                        _statistics(series),
                        sparkline(series, ascii_only=self.ascii_only)
                        + f"\nobserved {present}/{len(series.points)} · "
                        + ("?" if self.ascii_only else "·")
                        + " = gap · "
                        + _text(series.measurement)
                        + (" · " + quality if quality else ""),
                    ),
                )
            )
        if not selected:
            rows.append(
                ("no-series", (self.family, "N/A", "No qualified series; unavailable is not zero."))
            )
        if self.scope.kind == "container" and self.family == "network":
            rows.append(
                (
                    "shared-network",
                    (
                        "Network attribution",
                        "Pod network shared with this container",
                        "Shared host network"
                        if self.scope.host_network
                        else "No exclusive per-container network attribution",
                    ),
                )
            )
        return (*rows, *metadata)

    def _render_history(self) -> None:
        if not self.is_mounted or self._stopped or self.invalidated:
            return
        snapshot = (self.snapshot or HistorySnapshot(status=HistoryStatus.LOADING)).fresh(
            datetime.now(UTC)
        )
        self._last_status = snapshot.status
        viewport = self.table.capture_viewport()
        rows = self._rows(snapshot)
        incoming = dict(rows)
        for key in self._rendered.keys() - incoming.keys():
            self.table.remove_row(key)
        for key, cells in rows:
            rendered = tuple(safe_text(cell, multiline=True) for cell in cells)
            height = max(len(cell.plain.splitlines()) for cell in rendered)
            if key not in self._rendered:
                self.table.add_row(*rendered, key=key, height=height)
            elif cells != self._rendered[key]:
                if (
                    self.table.get_row_height(
                        self.table.ordered_rows[self.table.get_row_index(key)].key
                    )
                    != height
                ):
                    self.table.remove_row(key)
                    self.table.add_row(*rendered, key=key, height=height)
                else:
                    for column, value in zip(_COLUMNS, rendered, strict=True):
                        self.table.update_cell(key, column, value)
        order = {
            tuple(safe_text(cell, multiline=True).plain for cell in cells): index
            for index, (_, cells) in enumerate(rows)
        }
        self.table.sort(key=lambda cells: order[tuple(cell.plain for cell in cells)])
        self._rendered = incoming
        self.table.restore_viewport(viewport)
        label = dict(_RANGES)[self.range_seconds]
        self.status.update(
            self._message
            or f"{snapshot.status} · {label} · {self.family} · {_labels(self.device or ())}"
            + (" · reading…" if self._loading else "")
            + (" · ASCII" if self.ascii_only else "")
        )
        self.query_one("#history-dialog", WorkspaceFrame).border_title = safe_text(
            f"Metric history · {label} · {self.family} · {snapshot.status}"
        )

    def action_refresh(self) -> None:
        self._queue("collect")

    def configure(self, options: HistoryOptions | None) -> None:
        """A valid observability change revokes captures, including under review."""
        if options == self.options or self._stopped or self.invalidated:
            return
        self.options = options
        self.snapshot = None
        self.request = None
        self.device = None
        self.candidates = BackendCandidates()
        self._backend_index = -1
        self._queue("collect", overlay=True)

    def action_range(self, seconds: HistoryRange) -> None:
        if seconds != self.range_seconds:
            self.snapshot = None
            self.request = None
        self.range_seconds = seconds
        self._queue("collect")

    def action_family(self, family: MetricFamily) -> None:
        self.family, self.device = family, None
        self._render_history()
        self.set_focus(self.table)

    def action_device(self, direction: int) -> None:
        if self.snapshot is None:
            return
        devices = tuple(
            dict.fromkeys(
                item.labels for item in self.snapshot.series if _family(item) == self.family
            )
        )
        if devices:
            index = devices.index(self.device) if self.device in devices else 0
            self.device = devices[(index + direction) % len(devices)]
            self._render_history()

    def action_detect(self) -> None:
        self._queue("detect")

    def action_backend(self) -> None:
        if not self.candidates.items:
            self.status.update(
                "No detected backend candidates · d Detect in the selected namespace"
            )
            return
        self._backend_index = (self._backend_index + 1) % len(self.candidates.items)
        self.options = self.owner.selected_candidate(
            self.candidates.items[self._backend_index], self.options
        )
        self.snapshot = None
        self.request = None
        self.device = None
        self._queue("collect")

    def action_membership(self) -> None:
        if self.scope.kind != "workload":
            self.status.update("Membership mode selection applies to workload history.")
            return
        self.scope = replace(
            self.scope,
            membership="current-members"
            if self.scope.membership == "backend-history"
            else "backend-history",
        )
        self.snapshot = None
        self.request = None
        self._queue("collect")

    def action_ascii(self) -> None:
        self.ascii_only = not self.ascii_only
        self._render_history()

    @on(Button.Pressed, "#history-controls Button")
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = (event.button.id or "").removeprefix("history-")
        if action == "range":
            ranges = tuple(seconds for seconds, _ in _RANGES)
            self.action_range(ranges[(ranges.index(self.range_seconds) + 1) % len(ranges)])
        elif action == "metric":
            self.action_family(_FAMILIES[(_FAMILIES.index(self.family) + 1) % len(_FAMILIES)])
        elif action == "device":
            self.action_device(1)
        elif action == "back":
            self.dismiss()
        elif action == "refresh":
            self.action_refresh()
        elif action == "detect":
            self.action_detect()
        elif action == "backend":
            self.action_backend()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not isinstance(self.focused, Input) and not self._stopped and not self.invalidated

    def _invalidate_target(self) -> None:
        self._generation += 1
        self.invalidated = True
        self._pending = None
        self.owner.invalidate()
        if self._active is not None:
            self._active.cancel()
        self.snapshot = None
        self.table.clear()
        self.table.disabled = True
        self.status.update("History target changed; select the resource again.")

    def validate_target(self) -> None:
        if self._stopped or self.invalidated:
            return
        try:
            if not self._is_current():
                raise AppError("The originating view changed.")
            self.owner.require_current(self.scope)
        except AppError:
            self._invalidate_target()

    def observe_target(self, record: ResourceRecord | None) -> None:
        if self.scope.target is None or self._stopped or self.invalidated:
            return
        try:
            self.owner.observe_target(self.scope, record)
        except AppError:
            self._invalidate_target()
            return
        self.validate_target()

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.validate_target()

    def capture_export(self, at: datetime) -> ExportChoices:
        self.validate_target()
        snapshot, request = self.snapshot, self.request
        if (
            snapshot is None
            or request is None
            or self.invalidated
            or not self.is_mounted
            or snapshot.request_id != request.id
            or request.config_revision != self.owner.config_revision
        ):
            return ()
        scope, family, device = self.scope, self.family, self.device
        generation, revision = self._generation, self.owner.config_revision
        observed = snapshot.fresh(at)
        rows = self._rows(observed)
        samples: list[Row] = []
        for series in self._selected_series(observed):
            for index, point in enumerate(series.points):
                quality = (
                    str(series.quality[index])
                    if index < len(series.quality)
                    else ("observed" if point.value is not None else "missing")
                )
                samples.append(
                    (
                        f"{_row_key(series)}:{index}",
                        (
                            timestamp(point.timestamp),
                            history_number(point.value, series.unit)
                            + " "
                            + history_unit(series.unit),
                            _text(series.key + " · " + _labels(series.labels) + " · " + quality),
                        ),
                    )
                )
        projection = (*rows, *samples)
        target, resource = scope.target, scope.resource
        export_scope = ExportScope(
            export_at=at,
            source_at=snapshot.observed_at,
            context=scope.session.context,
            header_namespace=header_namespace(self.chrome),
            collection_namespace=scope.namespace,
            namespace_mode="one"
            if scope.namespace
            else "all"
            if scope.kind == "cluster"
            else "cluster",
            api_version=resource.api_version if resource else None,
            resource=resource.name if resource else None,
            kind=resource.kind if resource else None,
            name=target.name if target else None,
            uid=target.uid if target else None,
            container=target.container if target else None,
        )

        def current() -> bool:
            return (
                self.is_mounted
                and self in self.app.screen_stack
                and not self.invalidated
                and not self._stopped
                and self.scope == scope
                and self.snapshot is snapshot
                and self.request is request
                and self.family == family
                and self.device == device
                and self._generation == generation
                and self.owner.config_revision == revision
                and self._is_current()
            )

        lease = captured_lease(
            export_scope,
            TableSource(
                columns=_COLUMNS,
                rows=tuple(cells for _, cells in projection),
                row_keys=tuple(key for key, _ in projection),
                concealed_columns=frozenset(),
            ),
            current,
            target=target,
            presentation=ExportPresentation(
                view="metric-history/" + family, viewport=self.table.capture_viewport()
            ),
            notices=(
                "Evaluation time is not scrape time; missing samples are never zero.",
                "Only the selected metric/device is captured; source and membership limits remain visible.",
            ),
        )
        return (("screen", replace(lease, session=scope.session)),)

    async def _stop(self) -> None:
        self._stopped = self.invalidated = True
        self._generation += 1
        self._pending = None
        self.owner.invalidate()
        if self._active is not None:
            self._active.cancel()
        if self._runner is not None:
            await finish_owned(self._runner)
        await self.owner.leave_detail()
        self.snapshot = None
        self.table.clear()
        self.table.disabled = True
        self._notify_stopped()

    async def stop_owned(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await finish_owned(self._stop_task)

    async def on_unmount(self) -> None:
        await self.stop_owned()
