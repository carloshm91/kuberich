"""Real Textual focus, finite intents, numeric gaps and export-origin ownership."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Button, Static

from kuberich.domain.exports import TableSource
from kuberich.domain.history import (
    BackendCandidate,
    BackendCandidates,
    EndpointIdentity,
    HistoryBackend,
    HistoryNotice,
    HistoryOptions,
    HistoryPoint,
    HistoryScope,
    HistorySeries,
    HistorySnapshot,
    HistoryStatus,
    MembershipEvidence,
    PointQuality,
)
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.ui.history import HistoryScreen
from kuberich.ui.nested import CommandWorkspace
from kuberich.ui.pulse import history_number, sparkline
from tests.support.pulse import pulse_object, pulse_resource
from tests.support.workspace import wait_for


class Owner:
    """Controlled async domain port; actual transport is covered by App/HTTP trials."""

    def __init__(self):
        self.config_revision = 0
        self.operation_count = 0
        self.requests = []
        self.detected = []
        self.entered = []
        self.left = 0
        self.current = True
        self.gate = None
        self.cancelled = asyncio.Event()
        self.ignore_cancel = False
        self.old = None
        self.status = HistoryStatus.PARTIAL

    def require_current(self, scope):
        if not self.current:
            raise AppError("The captured target is obsolete.")

    def observe_target(self, scope, record):
        if record is None or record.uid != scope.target.uid:
            self.current = False
            raise AppError("The captured target was replaced.")

    def invalidate(self):
        self.config_revision += 1

    def enter_detail(self, scope):
        self.entered.append(scope)
        self.invalidate()

    async def leave_detail(self):
        self.left += 1

    def selected_candidate(self, candidate, options=None):
        return HistoryOptions(
            HistoryBackend(candidate.namespace, candidate.service, candidate.port),
            provider=candidate.provider_hint,
        )

    async def detect(self, namespaces):
        self.detected.append(namespaces)
        return BackendCandidates(
            (
                BackendCandidate("team", "prometheus", "service-uid", 9090),
                BackendCandidate(
                    "team", "victoria", "vm-uid", 8428, provider_hint="victoriametrics"
                ),
            ),
            False,
            (("team", "partial"),),
        )

    async def collect(self, request):
        self.requests.append(request)
        self.operation_count += 1
        try:
            if self.gate is not None:
                while not self.gate.is_set():
                    try:
                        await self.gate.wait()
                    except asyncio.CancelledError:
                        self.cancelled.set()
                        if not self.ignore_cancel:
                            raise
            end = self.old or request.end
            points = (
                HistoryPoint(end - timedelta(seconds=30), Decimal(0)),
                HistoryPoint(end - timedelta(seconds=15), Decimal(2)),
                HistoryPoint(end, None),
            )
            quality = (PointQuality.OBSERVED, PointQuality.OBSERVED, PointQuality.NONFINITE)
            series = tuple(
                HistorySeries(key, label, unit, points, labels, quality, measurement)
                for key, label, unit, labels, measurement in (
                    (
                        "cpu",
                        "CPU",
                        "cores",
                        (),
                        "Host node CPU" if request.scope.kind == "node" else "Container CPU",
                    ),
                    (
                        "memory",
                        "Memory",
                        "bytes",
                        (),
                        "Host memory" if request.scope.kind == "node" else "Container working set",
                    ),
                    (
                        "network-rx",
                        "Receive",
                        "bytes/s",
                        (("interface", "eth0"),),
                        "Pod namespace receive",
                    ),
                    (
                        "network-tx",
                        "Transmit",
                        "bytes/s",
                        (("interface", "eth0"),),
                        "Pod namespace transmit",
                    ),
                    (
                        "filesystem",
                        "Filesystem",
                        "bytes",
                        (("device", "/dev/a"), ("mountpoint", "/")),
                        "Reported usage; not unique disk capacity",
                    ),
                    (
                        "filesystem",
                        "Filesystem",
                        "bytes",
                        (("device", "/dev/b"), ("mountpoint", "/data")),
                        "Reported usage; not PVC utilization",
                    ),
                )
            )
            return HistorySnapshot(
                self.status,
                self.old or datetime.now(UTC),
                request.start,
                request.end,
                request.step_seconds,
                series,
                "Some source samples are missing.",
                "Backend cluster binding unverified",
                request_id=request.id,
                endpoint_identity=EndpointIdentity(
                    "service",
                    namespace="team",
                    service="prometheus",
                    service_uid="service-uid",
                    compatibility="Prometheus-compatible; provider unverified",
                ),
                membership_evidence=MembershipEvidence(mode=request.scope.membership),
                source_status=(("cpu", "partial"),),
                notices=(HistoryNotice("lookback", "Evaluation is not scrape time."),),
            )
        finally:
            self.operation_count -= 1


class Overlay(CommandWorkspace):
    def compose(self) -> ComposeResult:
        yield Static("Owned export review overlay")


class HistoryApp(App):
    BINDINGS: ClassVar = [Binding("escape", "back", "Back", priority=True)]

    def __init__(self, owner, scope, options):
        super().__init__()
        self.history = HistoryScreen(owner, scope, options)

    def compose(self) -> ComposeResult:
        yield Button("Parent", id="parent")

    def on_mount(self):
        self.push_screen(self.history)

    def action_back(self):
        if self.screen is not self.screen_stack[0]:
            self.pop_screen()


def scope(kind="cluster", field="containers", name="app"):
    session = SessionIdentity("owned-history", 1)
    if kind == "cluster":
        return HistoryScope(session, kind, "team")
    resource = pulse_resource(
        "nodes" if kind == "node" else "deployments" if kind == "workload" else "pods"
    )
    target = ResourceTarget(
        session,
        resource.group,
        resource.name,
        "team" if resource.namespaced else None,
        "owned",
        "owned-uid",
        name if kind == "container" else None,
    )
    return HistoryScope(
        session,
        kind,
        target.namespace,
        target,
        resource,
        container_field=field if kind == "container" else None,
    )


def text(screen):
    return "\n".join(
        " ".join(cell.plain for cell in screen.table.get_row(row.key))
        for row in screen.table.ordered_rows
    )


async def loaded(app):
    await wait_for(lambda: app.history.snapshot is not None and app.history.operation_count == 0)
    assert await app.history.table.wait_for_refresh()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cluster", "node", "workload", "pod", "container"])
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_requested_scope_numeric_last_gaps_units_keys_and_small_geometry(kind, size):
    owner = Owner()
    app = HistoryApp(owner, scope(kind), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test(size=size) as pilot:
        await loaded(app)
        screen = app.history
        assert app.focused is screen.table
        assert owner.entered == [screen.scope]
        assert screen.table.content_region.height >= 1
        assert screen.query_one("#history-back", Button).region.bottom <= size[1]
        assert "last N/A mCPU" in text(screen)
        assert "min 0" in text(screen) and "max 2000" in text(screen)
        assert "nonfinite" in text(screen) and "provider unverified" in text(screen)
        assert kind in text(screen) and "binding unverified" in text(screen)
        before = len(owner.requests)
        await pilot.press("m", "n", "a")
        await pilot.pause()
        assert "bytes/s" in text(screen) and "? = gap" in text(screen)
        if kind == "container":
            assert "Pod network shared with this container" in text(screen)
        await pilot.press("f")
        await pilot.pause()
        assert screen.device == (("device", "/dev/a"), ("mountpoint", "/"))
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert screen.device == (("device", "/dev/b"), ("mountpoint", "/data"))
        assert len(owner.requests) == before  # family/device projection performs no HTTP read
        await pilot.resize_terminal(40, 12)
        await pilot.press("escape")
        await wait_for(lambda: owner.left == 1)
        assert app.focused.id == "parent" and screen.operation_count == 0
    assert owner.left == 1


@pytest.mark.asyncio
async def test_all_ranges_detection_backend_selection_membership_and_input_focus():
    owner = Owner()
    app = HistoryApp(owner, scope("workload"), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        for key, duration in zip(
            "1234567", (900, 1800, 3600, 10800, 21600, 43200, 86400), strict=True
        ):
            await pilot.press(key)
            await loaded(app)
            assert (owner.requests[-1].end - owner.requests[-1].start).total_seconds() == duration
        await pilot.press("d")
        await wait_for(lambda: len(screen.candidates.items) == 2 and screen.operation_count == 0)
        assert owner.detected == [("team",)] and "partial" in str(screen.status.content)
        await pilot.press("b")
        await loaded(app)
        await pilot.press("b")
        await loaded(app)
        assert screen.options.endpoint.service == "victoria"
        assert screen.options.provider == "victoriametrics"
        await pilot.press("u")
        await loaded(app)
        assert screen.scope.membership == "current-members"
        assert owner.requests[-1].scope.membership == "current-members"


@pytest.mark.asyncio
async def test_latest_intent_drains_delayed_cancel_and_never_publishes_old_result():
    owner = Owner()
    owner.gate = asyncio.Event()
    owner.ignore_cancel = True
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        try:
            await wait_for(lambda: len(owner.requests) == 1)
            screen = app.history
            first = owner.requests[0]
            await pilot.press("2", "3", "4", "5", "6", "7")
            await wait_for(owner.cancelled.is_set)
            assert len(owner.requests) == 1 and screen.snapshot is None
            assert screen.operation_count <= 2
        finally:
            owner.gate.set()
        await loaded(app)
        assert len(owner.requests) == 2
        assert screen.request.id != first.id
        assert (screen.snapshot.end - screen.snapshot.start).total_seconds() == 86400
        await asyncio.gather(screen.stop_owned(), screen.stop_owned())
        assert screen.operation_count == 0 and owner.left == 1


@pytest.mark.asyncio
async def test_export_lease_survives_own_overlay_then_invalidates_on_selection_and_refresh():
    owner = Owner()
    app = HistoryApp(
        owner, scope("container"), HistoryOptions(HistoryBackend("team", "prometheus"))
    )
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        await pilot.press("n")
        await pilot.pause()
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        assert isinstance(lease.capture.source, TableSource)
        exported = repr(lease.capture.source.rows)
        assert "N/A bytes/s" in exported and "nonfinite" in exported
        assert "Pod network shared" in exported and "queried" in exported
        assert lease.current()
        app.push_screen(Overlay())
        await pilot.pause()
        assert lease.current() and owner.left == 0
        app.pop_screen()
        await pilot.pause()
        assert lease.current()
        await pilot.press("f")
        await pilot.pause()
        assert not lease.current()
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        await pilot.press("r")
        assert not lease.current()
        await loaded(app)


@pytest.mark.asyncio
async def test_visible_expiry_during_held_read_preserves_times_and_target_change_revokes():
    owner = Owner()
    app = HistoryApp(owner, scope("pod"), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        observed = datetime.now(UTC) - timedelta(seconds=61)
        original = replace(screen.snapshot, observed_at=observed)
        screen.snapshot = original
        owner.gate = asyncio.Event()
        await pilot.press("r")
        await wait_for(lambda: owner.operation_count == 1)
        assert "stale" in str(screen.status.content)
        assert "last N/A" in text(screen)
        assert observed.isoformat(timespec="seconds") in text(screen)
        screen.observe_target(None)
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.invalidated and not screen.capture_export(datetime.now(UTC))
        assert screen.table.disabled and screen.snapshot is None
        owner.gate.set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [HistoryStatus.UNAVAILABLE, HistoryStatus.FORBIDDEN, HistoryStatus.NO_DATA]
)
async def test_absent_denied_and_empty_remain_distinct(status):
    owner = Owner()
    owner.status = status
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        assert str(status) in str(app.history.status.content)
        await pilot.press("u")
        assert "applies to workload" in str(app.history.status.content)


@pytest.mark.asyncio
async def test_unconfigured_and_all_namespace_detection_does_not_read_or_probe():
    owner = Owner()
    app = HistoryApp(owner, replace(scope(), namespace=None), None)
    async with app.run_test() as pilot:
        await loaded(app)
        assert not owner.requests
        await pilot.press("d")
        await wait_for(lambda: app.history.operation_count == 0)
        assert not owner.detected and "selected namespace" in str(app.history.status.content)
        await pilot.press("b")
        assert "No detected" in str(app.history.status.content)


def test_gap_preserving_chart_and_bounded_decimal_formatting():
    now = datetime.now(UTC)
    series = HistorySeries(
        "cpu",
        "CPU",
        "cores",
        tuple(HistoryPoint(now, value) for value in (Decimal(0), Decimal(4), None, Decimal(8))),
    )
    assert sparkline(series, width=2) == "█·"
    assert sparkline(series, width=2, ascii_only=True) == "#?"
    assert history_number(Decimal(0), "cores") == "0"
    assert len(history_number(Decimal("1e999999"), "cores")) < 20
    assert len(history_number(Decimal("1e-999999"), "bytes")) < 20
    assert Decimal(history_number(Decimal("1e-100"), "cores")) == Decimal("1e-97")
    assert Decimal(history_number(Decimal("1e-100"), "bytes")) == Decimal("9.537e-107")
    assert history_number(Decimal("NaN"), "cores") == "N/A"
    assert history_number(Decimal(-1), "bytes") == "N/A"


@pytest.mark.asyncio
async def test_valid_configuration_reload_under_overlay_revokes_lease_and_theme_equality_keeps_work():
    owner = Owner()
    options = HistoryOptions(HistoryBackend("team", "prometheus"))
    app = HistoryApp(owner, scope(), options)
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        before = len(owner.requests)
        screen.configure(options)
        app.theme = "textual-light"
        await pilot.pause()
        assert len(owner.requests) == before and lease.current()
        app.push_screen(Overlay())
        await pilot.pause()
        screen.configure(HistoryOptions(HistoryBackend("team", "replacement")))
        assert screen.snapshot is None and not lease.current()
        await loaded(app)
        assert owner.requests[-1].options.endpoint.service == "replacement"
        assert owner.left == 0 and screen in app.screen_stack
        app.pop_screen()
        await pilot.pause()
        assert app.focused is screen.table


@pytest.mark.asyncio
async def test_origin_predicate_revokes_held_result_and_cannot_revive_with_configuration():
    owner = Owner()
    owner.gate = asyncio.Event()
    current = True
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    app.history = HistoryScreen(
        owner, app.history.scope, app.history.options, current=lambda: current
    )
    async with app.run_test() as pilot:
        try:
            await wait_for(lambda: owner.operation_count == 1)
            current = False
            owner.gate.set()
            await wait_for(lambda: app.history.operation_count == 0)
            assert app.history.invalidated and app.history.snapshot is None
            assert "target changed" in str(app.history.status.content)
            current = True
            app.history.configure(HistoryOptions(HistoryBackend("team", "new")))
            await pilot.pause()
            assert app.history.invalidated and len(owner.requests) == 1
        finally:
            owner.gate.set()


@pytest.mark.asyncio
async def test_buttons_focus_viewport_and_fixed_failure_without_error_payload():
    owner = Owner()
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        screen.table.move_cursor(row=3, scroll=False)
        screen.table.scroll_to(x=9, y=2, animate=False, immediate=True, force=True)
        await pilot.pause()
        viewport = screen.table.capture_viewport()
        await pilot.click("#history-refresh")
        await loaded(app)
        assert screen.table.capture_viewport().selected == viewport.selected
        assert screen.table.scroll_x == viewport.x
        await pilot.click("#history-range")
        await loaded(app)
        assert screen.range_seconds == 1800
        await pilot.click("#history-metric")
        assert screen.family == "memory"
        await pilot.click("#history-device")
        await pilot.click("#history-detect")
        await wait_for(lambda: bool(screen.candidates.items) and screen.operation_count == 0)
        await pilot.click("#history-backend")
        await loaded(app)
        await pilot.click("#history-back")
        await wait_for(lambda: owner.left == 1)


@pytest.mark.asyncio
async def test_expiry_timer_marks_snapshot_without_a_new_read_and_origin_invalid_before_mount():
    owner = Owner()
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        screen.snapshot = replace(
            screen.snapshot, observed_at=datetime.now(UTC) - timedelta(seconds=61)
        )
        count = len(owner.requests)
        await wait_for(lambda: "stale" in str(screen.status.content))
        assert len(owner.requests) == count and "last N/A" in text(screen)
        await pilot.resize_terminal(40, 12)
        screen.table.move_cursor(row=5)
        screen.table.scroll_to(y=4, animate=False, immediate=True, force=True)
        await pilot.pause()
        viewport = screen.table.capture_viewport()
        assert viewport.top is not None and viewport.y > 0
        await pilot.press("a")
        assert await screen.table.wait_for_refresh()
        assert screen.table.capture_viewport().selected == viewport.selected
    owner = Owner()
    app = HistoryApp(owner, scope(), None)
    app.history = HistoryScreen(owner, app.history.scope, None, current=lambda: False)
    async with app.run_test():
        assert app.history.invalidated and not owner.entered and not owner.requests
        assert not app.history.capture_export(datetime.now(UTC))
        app.history.action_refresh()
        app.history.action_device(1)
        app.history.observe_target(None)
    assert owner.left == 1


@pytest.mark.asyncio
async def test_fixed_collection_error_recovers_and_same_uid_observation_keeps_capture():
    class FailingOwner(Owner):
        failing = True

        async def collect(self, request):
            if self.failing:
                raise RuntimeError("token=hidden-http-error /private/auth-file")
            return await super().collect(request)

    owner = FailingOwner()
    app = HistoryApp(owner, scope("pod"), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        assert screen.snapshot.status is HistoryStatus.FAILED
        assert "hidden-http-error" not in text(screen) and "auth-file" not in text(screen)
        assert not screen.capture_export(datetime.now(UTC))
        owner.failing = False
        await pilot.press("r")
        await loaded(app)
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        record = pulse_object("pods", "owned")
        record["metadata"]["uid"] = "owned-uid"
        from kuberich.domain.resources import resource_record

        screen.observe_target(resource_record(screen.scope.resource, record))
        assert lease.current()
        owner.current = False
        screen.validate_target()
        assert not lease.current() and screen.invalidated


@pytest.mark.asyncio
async def test_connection_revision_change_inside_read_rejects_result():
    class ReplacedOwner(Owner):
        async def collect(self, request):
            result = await super().collect(request)
            self.invalidate()
            return result

    owner = ReplacedOwner()
    app = HistoryApp(owner, scope(), HistoryOptions(HistoryBackend("team", "prometheus")))
    async with app.run_test():
        await wait_for(lambda: app.history.invalidated)
        assert app.history.snapshot is None and app.history.table.disabled
        assert not app.history.capture_export(datetime.now(UTC))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,discovery,expected",
    [
        ("node", "team", ("team",)),
        ("node", None, None),
        ("pod", None, ("team",)),
    ],
)
async def test_detection_namespace_is_independent_of_metric_scope_and_defaults_compatibly(
    kind, discovery, expected
):
    owner = Owner()
    app = HistoryApp(owner, scope(kind), HistoryOptions(HistoryBackend("team", "prometheus")))
    app.history = HistoryScreen(
        owner, app.history.scope, app.history.options, detection_namespace=discovery
    )
    async with app.run_test() as pilot:
        await loaded(app)
        screen = app.history
        metric_namespace = screen.scope.namespace
        reads = len(owner.requests)
        await pilot.press("d")
        await wait_for(lambda: screen.operation_count == 0)
        assert owner.detected == ([expected] if expected is not None else [])
        assert len(owner.requests) == reads and screen.scope.namespace == metric_namespace
        if expected is None:
            assert "selected namespace" in str(screen.status.content)
        else:
            assert len(screen.candidates.items) == 2
