"""Live numeric metrics, stable UID sorting, and an open container across polls/expiry."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web

from kuberich.domain.containers import CONTAINER_COLUMNS
from kuberich.domain.pods import PodColumn
from kuberich.services.metrics import MetricsPoller
from kuberich.ui.containers import ContainerScreen
from tests.support.metrics import budgeted, metric_roots, sample, sample_list
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_logs import app_for, ns


@pytest.mark.asyncio
async def test_live_metrics_refresh_numeric_sort_keep_uid_and_container_status_across_polls_and_expiry(
    tmp_path, monkeypatch
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
    values = (budgeted("api"), budgeted("worker"))

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
                await pilot.press("enter")
                screen = app.screen
                assert isinstance(screen, ContainerScreen)
                assert cell(screen, "CPU(m)") == "200" and cell(screen, "METRICS") == "valid"
                state["cpu"] = "0"
                await wait_for(lambda: cell(screen, "CPU(m)") == "0")
                assert cell(screen, "METRICS") == "valid"
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
                app.save_screenshot(filename="resource-metrics-live-expiry.svg", path=str(evidence))
                await pilot.press("escape")
                assert app.resources.selected_uid == selected
            finally:
                release.set()
        assert app.workspace.ownership.metrics_count == 0 and app.sessions.client is None
