"""Live numeric metrics, stable UID sorting, and an open container across polls/expiry."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.containers import CONTAINER_COLUMNS
from kuberich.domain.pods import PodColumn
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.services.metrics import MetricsPoller
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from tests.support.connections import catalog_fixture
from tests.support.metrics import ExpiryGate, admitted, budgeted, metric_roots, sample, sample_list
from tests.support.resources import collection
from tests.support.standard import manifest
from tests.support.standard import roots as standard_roots
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_logs import app_for, ns


@pytest.mark.asyncio
@pytest.mark.parametrize("pod_cpu,unconfirmed", [("100m", False), ("99m", True)])
async def test_live_metrics_refresh_numeric_sort_keep_uid_and_container_status_across_polls_and_expiry(
    tmp_path, monkeypatch, pod_cpu, unconfirmed
):
    clock = [datetime.now(UTC)]
    state = {"cpu": "9m", "code": 200, "hold": False}
    blocked = asyncio.Event()
    release = asyncio.Event()
    requests = []

    class FastPoller(MetricsPoller):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, interval=0.03, now=lambda: clock[0])

    monkeypatch.setattr("kuberich.services.workspace.MetricsPoller", FastPoller)
    monkeypatch.setattr(
        "kuberich.ui.containers.datetime", SimpleNamespace(now=lambda timezone: clock[0])
    )
    values = tuple(
        admitted(name, created=clock[0] - timedelta(minutes=1)) for name in ("api", "worker")
    )
    values[0]["status"]["resources"]["requests"]["cpu"] = pod_cpu
    valid_label = "valid" + (
        " · configured budgets; active allocation unconfirmed · declared/enacted Pod resources differ"
        if unconfirmed
        else ""
    )

    async def handler(request):
        if request.path.startswith("/apis/metrics.k8s.io/"):
            requests.append(request.path)
            if state["hold"]:
                blocked.set()
                await release.wait()
            if state["code"] != 200:
                return web.Response(status=state["code"])
            return web.json_response(
                sample_list(
                    sample("api", cpu=state["cpu"], now=clock[0]),
                    sample("worker", cpu="100m", now=clock[0]),
                )
            )
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(*values))

    def cell(screen, key):
        return screen.table.get_cell("app", str(CONTAINER_COLUMNS.index(key))).plain

    async with workspace_api(ns, handler, discovery_roots=metric_roots) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(140, 30)) as pilot:
            try:
                await wait_for(
                    lambda: (
                        app.resources.row_count == 2
                        and str(app.resources.get_cell("owned-api", "cpu")) == "9"
                    )
                )
                assert str(app.resources.get_cell("owned-api", "cpu-req")) == "100"
                assert str(app.resources.get_cell("owned-api", "cpu-percent-request")) == "9"
                assert str(app.resources.get_cell("owned-api", "cpu-percent-limit")) == "0.9"
                assert str(app.resources.get_cell("owned-api", "metrics")) == valid_label
                app.resources.set_sort(PodColumn.CPU)
                await pilot.pause()
                assert [row.key.value for row in app.resources.ordered_rows] == [
                    "owned-api",
                    "owned-worker",
                ]
                app.resources.move_cursor(row=0)
                selected = app.resources.selected_uid
                state["cpu"] = "200m"
                await wait_for(lambda: str(app.resources.get_cell("owned-api", "cpu")) == "200")
                await pilot.pause()
                assert [row.key.value for row in app.resources.ordered_rows] == [
                    "owned-worker",
                    "owned-api",
                ]
                assert app.resources.selected_uid == selected == "owned-api"
                assert str(app.resources.get_cell("owned-api", "cpu-percent-request")) == "200"
                assert str(app.resources.get_cell("owned-api", "cpu-percent-limit")) == "20"
                await pilot.press("enter")
                screen = app.screen
                assert isinstance(screen, ContainerScreen)
                assert cell(screen, "CPU(m)") == "200" and cell(screen, "METRICS") == valid_label
                assert cell(screen, "CPU%REQ") == "200" and cell(screen, "CPU%LIM") == "20"
                state["cpu"] = "0"
                await wait_for(lambda: cell(screen, "CPU(m)") == "0")
                assert cell(screen, "METRICS") == valid_label
                state["code"] = 403
                await wait_for(lambda: cell(screen, "METRICS").startswith("forbidden"))
                assert cell(screen, "CPU(m)") == "N/A"
                state["code"] = 404
                await wait_for(lambda: cell(screen, "METRICS").startswith("API unavailable"))
                assert cell(screen, "CPU(m)") == "N/A"
                state.update(cpu="25m", code=200)
                await wait_for(lambda: cell(screen, "CPU(m)") == "25")
                state["hold"] = True
                await asyncio.wait_for(blocked.wait(), 5)
                # No new sample is delivered: the open modal must expire its own
                # successful cached sample as the clock crosses the fixed TTL.
                count = len(requests)
                clock[0] += timedelta(seconds=61)
                await wait_for(lambda: cell(screen, "METRICS").startswith("stale"))
                assert cell(screen, "CPU(m)") == "N/A" and cell(screen, "MEM(MiB)") == "N/A"
                assert len(requests) == count and app.screen is screen
                evidence = Path("artifacts/ui").resolve()
                evidence.mkdir(parents=True, exist_ok=True)
                app.save_screenshot(
                    filename="resource-metrics-live-expiry-unconfirmed.svg"
                    if unconfirmed
                    else "resource-metrics-live-expiry.svg",
                    path=str(evidence),
                )
                await pilot.press("escape")
                assert app.resources.selected_uid == selected
            finally:
                release.set()
        assert app.workspace.ownership.metrics_count == 0 and app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "nodes", "statefulsets"])
async def test_main_table_cache_expires_with_long_age_refresh_and_pending_read_then_accepts_fresh_batch(
    tmp_path, monkeypatch, kind
):
    clock = [datetime.now(UTC)]
    expiry = ExpiryGate()
    reads, held, releases = [], [], [asyncio.Event(), asyncio.Event()]

    class ControlledPoller(MetricsPoller):
        def __init__(self, *args, **kwargs):
            super().__init__(
                *args, **kwargs, interval=0.03, now=lambda: clock[0], expiry_sleep=expiry
            )

    monkeypatch.setattr("kuberich.services.workspace.MetricsPoller", ControlledPoller)
    monkeypatch.setattr(
        "kuberich.services.metrics_projection.datetime",
        SimpleNamespace(now=lambda timezone: clock[0]),
    )
    monkeypatch.setenv("KUBERICH_REFRESH", "3600")
    pods = [admitted(name, created=clock[0] - timedelta(minutes=2)) for name in ("api", "worker")]
    node = manifest(RESOURCE_ALIASES["nodes"], name="node", uid="owned-node")
    node["status"].update(
        capacity={"cpu": "4", "memory": "4Gi"}, allocatable={"cpu": "3", "memory": "3Gi"}
    )
    controller = manifest(
        RESOURCE_ALIASES["statefulsets"], name="controller", uid="owned-controller"
    )
    for pod in pods:
        pod["spec"]["nodeName"] = "node"
        pod["metadata"]["ownerReferences"] = [
            {
                "apiVersion": "apps/v1",
                "kind": "StatefulSet",
                "name": "controller",
                "uid": "owned-controller",
                "controller": True,
            }
        ]

    def roots():
        result, metrics = standard_roots(), metric_roots()
        result["/apis"]["groups"].extend(metrics["/apis"]["groups"])
        result["/apis/metrics.k8s.io/v1"] = metrics["/apis/metrics.k8s.io/v1"]
        return result

    async def handler(request):
        if request.path.startswith("/apis/metrics.k8s.io/"):
            reads.append(request.transport)
            # An empty progress snapshot can precede the usable resource list.
            # Hold only after a real sampled batch has armed its one-shot expiry.
            fresh = bool(expiry.waits)
            if fresh:
                index = len(held)
                held.append(request.transport)
                await releases[min(index, 1)].wait()
            if kind == "nodes":
                return web.json_response(
                    sample_list(
                        sample(
                            "node",
                            namespace=None,
                            cpu="700m" if fresh else "350m",
                            now=clock[0] if fresh else clock[0] - timedelta(seconds=45),
                        ),
                        name="nodes",
                    )
                )
            return web.json_response(
                sample_list(
                    sample(
                        "api",
                        cpu="500m" if fresh else "250m",
                        now=clock[0] if fresh else clock[0] - timedelta(seconds=45),
                    ),
                    sample(
                        "worker",
                        cpu="200m" if fresh else "100m",
                        now=clock[0] if fresh else clock[0] - timedelta(seconds=10),
                    ),
                )
            )
        if "watch" in request.query:
            return await stable_watch(request)
        payload = collection(
            *(
                pods
                if request.path.endswith("/pods")
                else [node]
                if request.path.endswith("/nodes")
                else [controller]
            )
        )
        if request.path.endswith("/statefulsets"):
            payload.update(apiVersion="apps/v1", kind="StatefulSetList")
        elif request.path.endswith("/nodes"):
            payload["kind"] = "NodeList"
        return web.json_response(payload)

    async with workspace_api(ns, handler, discovery_roots=roots) as url:
        app = KubeRichApp(
            Settings(read_only=True, refresh_seconds=3600),
            logging.Logger("metrics-expiry", level=100),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(timeout=300),
            initial_command=Command.EMPTY
            if kind == "pods"
            else ResourceCommand(RESOURCE_ALIASES[kind], "team"),
        )
        async with app.run_test(size=(100, 30)) as pilot:
            table = app.resources if kind == "pods" else app.standard_table
            uid = (
                "owned-worker"
                if kind == "pods"
                else "owned-node"
                if kind == "nodes"
                else "owned-controller"
            )
            expected_usage, request = ("100", "100") if kind == "pods" else ("350", "200")
            try:
                await wait_for(
                    lambda: (
                        uid in table.rows
                        and str(table.get_cell(uid, "cpu")) == expected_usage
                        and len(expiry.waits) == 1
                        and len(held) == 1
                    )
                )
                assert app.live_preferences.refresh_seconds == 3600
                assert expiry.waits[0][0] == 15
                call_count = len(reads)
                table.move_cursor(row=table.get_row_index(uid))
                table.scroll_to(x=20, animate=False)
                await pilot.pause()
                before = table.capture_viewport()
                assert before.selected == uid and before.x > 0
                captured = app.workspace.store.observation.metrics.report(uid, clock[0])
                clock[0] += timedelta(seconds=16)
                expiry.waits[0][1].set()
                # No input, watch event, AGE tick or completed API request can cause this update.
                await wait_for(lambda: str(table.get_cell(uid, "cpu")) == "N/A")
                assert str(table.get_cell(uid, "metrics")).startswith(
                    "stale · metrics cache expired"
                )
                assert str(table.get_cell(uid, "cpu-req")) == request
                assert str(table.get_cell(uid, "memory")) == "N/A"
                assert str(table.get_cell(uid, "memory-req")) == ("32" if kind == "pods" else "64")
                assert str(table.get_cell(uid, "cpu-lim")) == ("1000" if kind == "pods" else "2000")
                assert str(table.get_cell(uid, "memory-lim")) == (
                    "128" if kind == "pods" else "256"
                )
                assert str(table.get_cell(uid, "cpu-percent-request")) == "N/A"
                assert str(table.get_cell(uid, "memory-percent-limit")) == "N/A"
                assert app.live_preferences.refresh_seconds == 3600
                assert table.capture_viewport() == before
                cached = app.workspace.store.observation.metrics.report(uid, clock[0])
                assert cached.timestamp == captured.timestamp and cached.window == captured.window
                assert (
                    len(reads) == call_count and len(expiry.waits) == 1 and expiry.finished == {0}
                )
                if kind == "pods":
                    assert str(table.get_cell("owned-api", "cpu")) == "N/A"
                    assert (clock[0] - captured.timestamp).total_seconds() == 26
                releases[0].set()
                await wait_for(
                    lambda: (
                        str(table.get_cell(uid, "cpu")) == ("200" if kind == "pods" else "700")
                        and len(expiry.waits) == 2
                        and len(held) == 2
                    )
                )
                assert not app.workspace.store.observation.metrics.cache_expired
                assert table.selected_uid == uid and table.capture_viewport().x == before.x
                await app.workspace.close()  # Third read and the new expiry are both still held.
                assert expiry.finished == {0, 1} and held[1].is_closing()
            finally:
                for release in releases:
                    release.set()
        assert app.workspace.ownership.metrics_count == 0 and app.sessions.client is None
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "kuberich-metrics-expiry"
        ]


@pytest.mark.asyncio
async def test_initial_container_sample_expires_without_any_later_observation(
    tmp_path, monkeypatch
):
    clock = [datetime.now(UTC)]
    blocked, release = asyncio.Event(), asyncio.Event()
    reads = 0

    class FastPoller(MetricsPoller):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs, interval=0.03, now=lambda: clock[0])

    monkeypatch.setattr("kuberich.services.workspace.MetricsPoller", FastPoller)
    monkeypatch.setattr(
        "kuberich.ui.containers.datetime", SimpleNamespace(now=lambda timezone: clock[0])
    )

    async def handler(request):
        nonlocal reads
        if request.path.startswith("/apis/metrics.k8s.io/"):
            reads += 1
            if reads > 1:
                blocked.set()
                await release.wait()
            return web.json_response(sample_list(sample(now=clock[0])))
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(budgeted()))

    async with workspace_api(ns, handler, discovery_roots=metric_roots) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            try:
                await wait_for(
                    lambda: (
                        app.resources.row_count == 1
                        and str(app.resources.get_cell("owned-api", "cpu")) == "250"
                    )
                )
                await asyncio.wait_for(blocked.wait(), 5)
                await pilot.press("enter")
                screen = app.screen
                assert isinstance(screen, ContainerScreen)
                usage = str(CONTAINER_COLUMNS.index("CPU(m)"))
                status = str(CONTAINER_COLUMNS.index("METRICS"))
                assert screen.table.get_cell("app", usage).plain == "250"
                clock[0] += timedelta(seconds=61)
                await wait_for(
                    lambda: screen.table.get_cell("app", status).plain.startswith("stale")
                )
                assert screen.table.get_cell("app", usage).plain == "N/A"
                assert reads == 2 and app.screen is screen
            finally:
                release.set()
        assert app.workspace.ownership.metrics_count == 0 and app.sessions.client is None
