"""Native overview, actual charts and exact keyboard navigation in the shared frame."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from aiohttp import web
from textual.app import App, ComposeResult

from kuberich.domain.history import HistoryPoint, HistorySeries, HistorySnapshot, HistoryStatus
from kuberich.domain.metrics import MetricReport, MetricStatus, ResourceAmount
from kuberich.domain.navigation import Viewport
from kuberich.domain.pulse import (
    PulsePredicate,
    PulseRow,
    PulseScope,
    PulseSnapshot,
    PulseSource,
    PulseStatus,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.services.commands import Command
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from kuberich.ui.controllers.pulse import PulseController
from kuberich.ui.pulse import PulseTable, history_cells, sparkline
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection, descriptor, legacy_roots, pod_resource
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_live_preferences import owned_app
from tests.ui.test_navigation import make_app


def history(now=None):
    now = now or datetime.now(UTC)
    return HistorySnapshot(
        HistoryStatus.PARTIAL,
        now,
        now - timedelta(seconds=45),
        now,
        15,
        (
            HistorySeries(
                "cpu",
                "CPU history",
                "cores",
                tuple(
                    HistoryPoint(now - timedelta(seconds=15 * index), value)
                    for index, value in enumerate((Decimal(0), None, Decimal("0.5"), Decimal(1)))
                ),
            ),
            HistorySeries(
                "memory", "Memory history", "bytes", (HistoryPoint(now, Decimal(2**20)),)
            ),
        ),
        "one query contains gaps",
        "Backend scope: Kubernetes cluster binding unverified",
    )


def roots():
    result = legacy_roots()
    result["/api/v1"]["resources"].append(descriptor("nodes", namespaced=False, kind="Node"))
    return result


class TableApp(App):
    def __init__(self):
        super().__init__()
        self.table = PulseTable()

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()


def test_sparks_keep_missing_zero_and_numeric_units_separate():
    data = history()
    assert sparkline(data.series[0]) == "▁·▄█"
    assert sparkline(data.series[0], 2) == "·█"
    assert sparkline(replace(data.series[0], points=())) == "no samples"
    assert (
        sparkline(replace(data.series[0], points=(HistoryPoint(datetime.now(UTC), Decimal(0)),)))
        == "▁"
    )
    cells = history_cells(data)
    assert "1000 mCPU" in cells[1][1] and "·" in cells[1][1].splitlines()[1]
    assert "1 MiB" in cells[2][1]
    assert "binding unverified" in cells[0][3] and "step 15s" in cells[0][3]
    assert "scrape freshness" in cells[0][3]
    assert (
        "configured selector"
        in history_cells(
            replace(
                data,
                scope_label="Configured cluster selector cluster=owned · selectors: cluster=owned",
            )
        )[0][1]
    )


@pytest.mark.asyncio
async def test_pulse_rows_distinguish_sources_budgets_and_stale_charts_escape_markup():
    app = TableApp()
    now = datetime.now(UTC)
    source = PulseSource("pods", pod_resource(), "team", PulseStatus.FORBIDDEN, now)
    rows = (
        PulseRow("denied", "[bold]Pods\x1b[31m", None, "pods", None, "Permission denied"),
        PulseRow("empty", "Known zero", 0, "missing", None),
    )
    snapshot = PulseSnapshot(
        PulseScope(SessionIdentity("owned", 0), "team"),
        (source,),
        rows,
        MetricReport(MetricStatus.FORBIDDEN),
        MetricReport(
            MetricStatus.PARTIAL,
            ResourceAmount(usage=Decimal(0), request=Decimal(1), uncertain=True, partial=True),
            allocation_uncertain=True,
        ),
        history(now - timedelta(seconds=90)),
    )
    async with app.run_test() as pilot:
        assert not await app.table.apply_rows(rows, snapshot, lambda: False)
        assert await app.table.apply_rows(rows, snapshot, lambda: True)
        await pilot.pause()
        assert app.table.get_cell("denied", "VALUE").plain == "N/A"
        assert "forbidden" in app.table.get_cell("denied", "DATA / TIME (UTC)").plain
        assert "[bold]Pods" in app.table.get_cell("denied", "SUMMARY").plain
        assert "\x1b" not in app.table.get_cell("denied", "SUMMARY").plain
        assert app.table.get_cell("empty", "VALUE").plain == "0"
        assert app.table.get_cell("metric:pod:cpu", "VALUE").plain == "0 mCPU"
        assert "uncertain budget" in app.table.get_cell("metric:pod:cpu", "DETAIL").plain
        assert "N/A mCPU" in app.table.get_cell("history:1", "VALUE").plain
        assert set(app.table.get_cell("history:1", "VALUE").plain.splitlines()[1]) == {"·"}
        app.table.restore_viewport(Viewport("empty", 0, 0, 0, None))
        await pilot.pause()
        assert app.table.capture_viewport().selected == "empty"
        changed = replace(rows[1], count=1)
        await app.table.apply_rows((changed,), snapshot, lambda: True, filtered=True)
        await pilot.pause()
        assert app.table.row_count == 1 and app.table.capture_viewport().selected == "empty"
        assert app.table.get_cell("empty", "VALUE").plain == "1"
        assert app.table.drilldown("missing") is None
        app.table.reset(2)
        await app.table.apply_rows((), None, lambda: True)
        assert app.table.row_count == 1 and app.table.scope is None


@pytest.mark.asyncio
async def test_cached_capacity_and_budgets_keep_projection_time_during_progress_and_failed_refresh():
    app = TableApp()
    observed = datetime.now(UTC) - timedelta(seconds=30)
    attempted = observed + timedelta(seconds=10)
    node = replace(pod_resource(), name="nodes", kind="Node", namespaced=False)
    sources = (
        PulseSource(
            "nodes", node, None, PulseStatus.VALID, observed, complete=True, attempted_at=observed
        ),
        PulseSource(
            "pods",
            pod_resource(),
            "team",
            PulseStatus.VALID,
            observed,
            complete=True,
            attempted_at=observed,
        ),
    )
    rows = (PulseRow("nodes:all", "Nodes", 1, "nodes", None),)
    snapshot = PulseSnapshot(
        PulseScope(SessionIdentity("owned", 0), "team"),
        sources,
        rows,
        MetricReport(cpu=ResourceAmount(capacity=Decimal(4), allocatable=Decimal(3))),
        MetricReport(cpu=ResourceAmount(request=Decimal(1), limit=Decimal(2))),
        capacity_observed_at=observed,
        budgets_observed_at=observed,
    )
    old_time, new_time = (value.isoformat(timespec="seconds") for value in (observed, attempted))
    async with app.run_test() as pilot:
        await app.table.apply_rows(rows, snapshot, lambda: True)
        assert "retained" not in app.table.get_cell("metric:node:cpu", "DETAIL").plain
        for status in (PulseStatus.PARTIAL, PulseStatus.VALID, PulseStatus.FORBIDDEN):
            refreshed_sources = tuple(
                replace(
                    source,
                    status=status,
                    observed_at=observed if status is PulseStatus.FORBIDDEN else attempted,
                    attempted_at=attempted,
                )
                for source in sources
            )
            refreshed = replace(snapshot, sources=refreshed_sources)
            await app.table.apply_rows(rows, refreshed, lambda: True)
            await pilot.pause()
            for key, kind in (("node", "capacity"), ("pod", "budgets")):
                text = app.table.get_cell(f"metric:{key}:cpu", "DETAIL").plain
                assert f"{kind} API observed {old_time}" in text
                assert f"{kind} API observed {new_time}" not in text
                assert f"retained {kind}" in text
                assert f"source {status}" in text
                if status is PulseStatus.FORBIDDEN:
                    assert f"forbidden attempt {new_time}" in text
            assert "capacity 4000 mCPU" in app.table.get_cell("metric:node:cpu", "DETAIL").plain
        source_text = app.table.get_cell("nodes:all", "DATA / TIME (UTC)").plain
        assert (
            f"observed {old_time}" in source_text and f"forbidden attempt {new_time}" in source_text
        )
        succeeded = replace(
            snapshot,
            sources=tuple(
                replace(source, observed_at=attempted, attempted_at=attempted) for source in sources
            ),
            capacity_observed_at=attempted,
            budgets_observed_at=attempted,
        )
        await app.table.apply_rows(rows, succeeded, lambda: True)
        assert "retained" not in app.table.get_cell("metric:node:cpu", "DETAIL").plain
        assert (
            f"capacity API observed {new_time}"
            in app.table.get_cell("metric:node:cpu", "DETAIL").plain
        )


@pytest.mark.asyncio
async def test_controller_restores_horizontal_and_multiline_chart_viewport_after_updates():
    app = TableApp()
    rows = tuple(
        PulseRow(f"row:{index}", f"Pod health {index}", index, "pods", None, "x" * 160)
        for index in range(35)
    )
    snapshot = PulseSnapshot(
        PulseScope(SessionIdentity("owned", 0), "team"), rows=rows, history=history()
    )
    request = RenderRequest(ViewObservation(pulse=snapshot), "", lambda: True, ViewRoute.pulse())
    async with app.run_test(size=(40, 12)) as pilot:
        driver = ViewDriver(PulseController(app.table, lambda _: frozenset({"history_back"})))
        assert (await driver.render(request)).applied
        app.table.move_cursor(row=app.table.get_row_index("row:20"))
        await pilot.pause()
        app.table.scroll_to(x=10, y=7, animate=False, immediate=True, force=True)
        await pilot.pause()
        viewport = driver.capture_viewport()
        assert viewport.x == 10 and viewport.y == 7 and viewport.top_offset == 1
        assert driver.available_actions(request) == frozenset({"history_back"})
        changed = replace(snapshot, rows=tuple(replace(row, count=99) for row in rows))
        await driver.render(replace(request, observation=ViewObservation(pulse=changed)))
        await pilot.pause()
        assert driver.capture_viewport() == viewport
        app.table.move_cursor(row=0)
        driver.restore_viewport(viewport)
        await pilot.pause()
        assert driver.capture_viewport() == viewport


@pytest.mark.asyncio
async def test_history_scope_hint_row_resizes_when_backend_availability_changes():
    app = TableApp()
    snapshot = PulseSnapshot(
        PulseScope(SessionIdentity("owned", 0), "team"), history=HistorySnapshot()
    )
    async with app.run_test() as pilot:
        await app.table.apply_rows((), snapshot, lambda: True)
        assert app.table.get_row_height("history:0") == 1
        app.table.move_cursor(row=app.table.get_row_index("history:0"))
        await app.table.apply_rows((), replace(snapshot, history=history()), lambda: True)
        await pilot.pause()
        assert app.table.get_row_height("history:0") == 2
        assert "backend unverified" in app.table.get_cell("history:0", "VALUE").plain
        assert app.table.capture_viewport().selected == "history:0"
        await app.table.apply_rows((), snapshot, lambda: True)
        await pilot.pause()
        assert app.table.get_row_height("history:0") == 1
        assert app.table.capture_viewport().selected == "history:0"


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_native_pulse_progressive_loading_exact_drilldown_and_history(tmp_path, size):
    pod_gate = asyncio.Event()
    calls = []

    async def ns(request):
        return namespaces("team", "default")

    async def resources(request):
        calls.append((request.path, dict(request.query)))
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/nodes"):
            return web.Response(status=403)
        if request.path.endswith("/pods"):
            if app.workspace.pulse_selected:
                await pod_gate.wait()
            namespace = "default" if "/namespaces/default/" in request.path else "team"
            pending = pod("pending", namespace=namespace)
            pending["status"]["phase"] = "Pending"
            return web.json_response(
                collection(
                    pod("ready", namespace=namespace),
                    pending,
                    pod("unready", namespace=namespace, ready=False),
                )
            )
        return web.json_response(collection())

    async with workspace_api(ns, resources, discovery_roots=roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 3)
            frame = app.query_one("#resource-view").region
            await pilot.press("colon", *"pulse", "enter")
            await wait_for(lambda: "pods:pod-pending" in app.pulse_table.rows)
            await wait_for(
                lambda: (
                    "forbidden" in app.pulse_table.get_cell("nodes:all", "DATA / TIME (UTC)").plain
                )
            )
            assert "loading" in app.pulse_table.get_cell("pods:all", "DATA / TIME (UTC)").plain
            pod_gate.set()
            await wait_for(
                lambda: app.pulse_table.get_cell("pods:pod-pending", "VALUE").plain == "1"
            )
            await pilot.pause()
            assert app.views.route.kind is ViewKind.PULSE and app.state.scope is None
            assert len(app.screen_stack) == 1 and app.focused is app.pulse_table
            assert app.query_one("#resource-view").region == frame
            assert not app.check_action("inspect_yaml", ()) and not app.check_action(
                "review_delete", ()
            )
            await pilot.press("y", "d", "E", "ctrl+d")
            assert len(app.screen_stack) == 1
            await wait_for(
                lambda: (
                    "forbidden" in app.pulse_table.get_cell("nodes:all", "DATA / TIME (UTC)").plain
                )
            )
            await pilot.press("slash", *"pending", "enter")
            await wait_for(lambda: app.pulse_table.row_count == 1)
            viewport = app.pulse_table.capture_viewport()
            await pilot.press("enter")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 1)
            assert app.resources.capture_viewport().selected == "owned-pending"
            assert app.workspace.selection.version == "v1"
            assert app.views.drilldown.predicate is PulsePredicate.POD_PENDING
            assert any(query.get("fieldSelector") == "status.phase=Pending" for _, query in calls)
            await pilot.press("escape")
            await wait_for(
                lambda: app.state.view_kind == "pulse" and app.pulse_table.row_count == 1
            )
            await pilot.pause()
            assert (
                app.filter_input.value == "pending"
                and app.pulse_table.capture_viewport() == viewport
            )
            await pilot.press("alt+right")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 1)
            await app.run_command("pods")
            await wait_for(lambda: app.resources.row_count == 3)
            assert app.views.drilldown is None
            await app.run_command("pulse")
            await wait_for(
                lambda: app.state.view_kind == "pulse" and app.pulse_table.scope is not None
            )
            await app.run_command("ns default")
            await wait_for(
                lambda: (
                    app.pulse_table.scope is not None
                    and app.pulse_table.scope.namespace == "default"
                )
            )
            assert app.state.view_kind == "pulse" and app.state.namespace == "default"
            await app.run_command("ns")
            await wait_for(lambda: app.namespace_table.row_count == 2)
            app.namespace_table.move_cursor(row=app.namespace_table.get_row_index("namespace-team"))
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    app.state.view_kind == "pulse"
                    and app.pulse_table.scope is not None
                    and app.pulse_table.scope.namespace == "team"
                )
            )
            app.pulse_table.move_cursor(row=app.pulse_table.get_row_index("metric:pod:cpu"))
            await pilot.press("enter")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 3)
            assert app.views.drilldown.predicate is PulsePredicate.POD_ACTIVE
            assert app.resources.sort_column == "cpu" and app.resources.descending
            await app.run_command("back")
            await wait_for(
                lambda: app.state.view_kind == "pulse" and app.pulse_table.scope is not None
            )
            await app.run_command("server field status.phase=Pending")
            assert app.state.view_kind == "pulse" and "open a resource view" in str(
                app.status.content
            )
        assert app.workspace.ownership.pulse_count == 0


@pytest.mark.asyncio
async def test_initial_pulse_and_stale_aggregate_activation(tmp_path):
    async def ns(request):
        return namespaces("team", "default")

    async with workspace_api(ns) as url:
        app = make_app(catalog_fixture(tmp_path, url), initial=Command.PULSE)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.pulse_table.scope is not None)
            original = app.pulse_table.scope
            app.pulse_table.scope = replace(
                original, session=SessionIdentity(original.session.context, 999)
            )
            app.navigator.pulse_selected("pods:all")
            assert app.state.view_kind == "pulse" and "scope changed" in str(app.status.content)
            app.pulse_table.scope = original
            app.navigator.pulse_selected("history:0")
            assert "no resource drill-down" in str(app.status.content)
            await app.run_command("mark")
            assert not app.interactions.selection.marked
            await pilot.press("colon", *"over", "tab")
            assert app.command_input.value == "overview"
            await pilot.press("enter")
            assert app.state.view_kind == "pulse" and len(app.screen_stack) == 1
            await app.run_command("ctx kuberich-test-Two")
            await wait_for(
                lambda: (
                    app.state.view_kind == "pods"
                    and app.state.context == "kuberich-test-Two"
                    and app.state.scope is not None
                )
            )
            assert not app.workspace.pulse_selected

            await app.run_command("back")
            await wait_for(
                lambda: (
                    app.state.view_kind == "pulse"
                    and app.pulse_table.scope is not None
                    and app.pulse_table.scope.session.context == "kuberich-test-one"
                )
            )
            await app.run_command("forward")
            await wait_for(
                lambda: (
                    app.state.view_kind == "pods"
                    and app.state.context == "kuberich-test-Two"
                    and app.state.scope is not None
                )
            )
            assert not app.workspace.pulse_selected


@pytest.mark.asyncio
async def test_errors_filter_is_captured_per_history_entry_and_remains_a_visible_toggle(tmp_path):
    async def ns(request):
        return namespaces("team")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("ready"), pod("unready", ready=False)))

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 2)
            await app.run_command("errors")
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command("pulse")
            await wait_for(
                lambda: (
                    "pods:pod-running" in app.pulse_table.rows
                    and app.pulse_table.get_cell("pods:pod-running", "VALUE").plain == "2"
                )
            )
            app.pulse_table.move_cursor(row=app.pulse_table.get_row_index("pods:pod-running"))
            await pilot.press("enter")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 2)
            assert not app.interactions.errors
            await app.run_command("back")
            await wait_for(lambda: app.state.view_kind == "pulse")
            assert app.interactions.errors
            await app.run_command("forward")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 2)
            assert not app.interactions.errors
            await app.run_command("errors")
            await wait_for(lambda: app.resources.row_count == 1)
            assert app.interactions.errors
            await app.run_command("back")
            await wait_for(lambda: app.state.view_kind == "pulse")
            await app.run_command("forward")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 1)
            assert app.interactions.errors


@pytest.mark.asyncio
async def test_configured_history_renders_real_service_proxy_data_and_scope(tmp_path):
    queries = []

    async def ns(request):
        return namespaces("team")

    async def resources(request):
        if request.path.endswith("/query_range"):
            queries.append((request.path, request.query["query"]))
            start, end, step = (float(request.query[name]) for name in ("start", "end", "step"))
            value = "0.5" if "container_cpu_usage" in request.query["query"] else str(2**24)
            values = [
                [start + index * step, value]
                for index in range(int((end - start) / step) + 1)
                if index != 3
            ]
            return web.json_response(
                {
                    "status": "success",
                    "data": {"resultType": "matrix", "result": [{"metric": {}, "values": values}]},
                }
            )
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection())

    async with workspace_api(ns, resources) as url:
        app, _, _ = owned_app(
            tmp_path,
            {"observability": {"history": {"namespace": "observability", "service": "prometheus"}}},
            url=url,
            initial=Command.PULSE,
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: "history:2" in app.pulse_table.rows)
            await pilot.pause()
            assert "500 mCPU" in app.pulse_table.get_cell("history:1", "VALUE").plain
            assert "16 MiB" in app.pulse_table.get_cell("history:2", "VALUE").plain
            assert "·" in app.pulse_table.get_cell("history:1", "VALUE").plain.splitlines()[1]
            assert app.pulse_table.get_cell("history:0", "VALUE").plain.startswith(
                "partial\nbackend unverified"
            )
            assert "binding unverified" in app.pulse_table.get_cell("history:0", "DETAIL").plain
            assert len(queries) == 2 and all(
                path.startswith(
                    "/api/v1/namespaces/observability/services/http:prometheus:9090/proxy/"
                )
                for path, _ in queries
            )
            assert all('namespace="team"' in query for _, query in queries)
            assert app.state.view_kind == "pulse" and len(app.screen_stack) == 1
            destination = Path("artifacts/issue69/ui").resolve()
            destination.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="pulse-history-100x30.svg", path=str(destination))
