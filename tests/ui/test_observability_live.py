"""Validated history reload cancels the old scope; unrelated preferences keep it."""

import asyncio

import pytest
from aiohttp import web

from kuberich.services.commands import Command
from tests.contract.test_history import payload
from tests.support.connections import namespaces
from tests.support.history import service
from tests.support.pulse import pulse_resource, pulse_roots
from tests.support.resources import descriptor
from tests.support.workspace import wait_for, workspace_api
from tests.ui.test_live_preferences import owned_app, save


def observability(service="one"):
    return {
        "history": {
            "namespace": "observability",
            "service": service,
            "cluster_label": "cluster",
            "cluster_value": "owned",
        }
    }


@pytest.mark.asyncio
async def test_history_reload_retires_held_query_but_theme_and_invalid_reload_keep_it(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def ns(request):
        return namespaces("team")

    async def resources(request):
        calls.append(request.path)
        if (
            request.path.startswith("/api/v1/namespaces/observability/services/")
            and "/proxy/" not in request.path
        ):
            return web.json_response(
                service(request.path.rsplit("/", 1)[-1], namespace="observability")
            )
        if request.path.endswith("query_range"):
            if ":one:" in request.path:
                entered.set()
                await release.wait()
            return web.json_response(
                payload(
                    request,
                    value="1"
                    if request.query["query"].startswith("count(")
                    else "0.5"
                    if "rate(" in request.query["query"]
                    else "1048576",
                )
            )
        name = request.path.rsplit("/", 1)[-1]
        resource = pulse_resource(name)
        metrics = "/metrics.k8s.io/" in request.path
        return web.json_response(
            {
                "apiVersion": "metrics.k8s.io/v1" if metrics else resource.api_version,
                "kind": ("NodeMetrics" if name == "nodes" else "PodMetrics") + "List"
                if metrics
                else resource.kind + "List",
                "metadata": {"resourceVersion": "owned-snapshot"},
                "items": [],
            }
        )

    def history_roots():
        roots = pulse_roots()
        roots["/api/v1"]["resources"].append(descriptor("services", kind="Service"))
        return roots

    async with workspace_api(ns, resources, discovery_roots=history_roots) as url:
        app, path, notes = owned_app(
            tmp_path, {"observability": observability()}, url=url, initial=Command.PULSE
        )
        async with app.run_test(size=(120, 36)) as pilot:
            try:
                await app.live_preferences.check()
                await asyncio.wait_for(entered.wait(), 5)
                initial_nodes = calls.count("/api/v1/nodes")
                save(path, {"theme": "textual-dark", "observability": observability()})
                await app.live_preferences.check()
                await pilot.pause()
                assert app.theme == "textual-dark" and calls.count("/api/v1/nodes") == initial_nodes
                document = app.preferences.document
                save(
                    path,
                    {
                        "observability": {
                            "history": {
                                "namespace": "observability",
                                "service": "one",
                                "port": True,
                            }
                        }
                    },
                )
                await app.live_preferences.check()
                assert app.preferences.document is document
                assert app.live_preferences.observability.history.endpoint.service == "one"
                assert calls.count("/api/v1/nodes") == initial_nodes
                assert "last valid preferences remain active" in notes[-1][0]

                updated = observability()
                updated["contexts"] = {"kuberich-test-one": observability("two")}
                save(path, {"observability": updated})
                await app.live_preferences.check()
                await wait_for(lambda: sum(":two:" in item for item in calls) == 5)
                await wait_for(
                    lambda: (
                        "history:1" in app.pulse_table.rows
                        and "500 mCPU" in app.pulse_table.get_cell("history:1", "VALUE").plain
                    )
                )
                assert app.state.view_kind == "pulse" and app.state.context == "kuberich-test-one"
                assert (
                    app.live_preferences.observability.for_context(
                        app.state.context
                    ).history.endpoint.service
                    == "two"
                )
                assert calls.count("/api/v1/nodes") > initial_nodes
                assert len(app.screen_stack) == 1
            finally:
                release.set()
        assert app.workspace.ownership.pulse_count == 0


@pytest.mark.asyncio
async def test_invalid_startup_history_keeps_disabled_defaults_and_warns(tmp_path):
    app, _, notes = owned_app(
        tmp_path,
        {
            "observability": {
                "history": {"namespace": "observability", "service": "prometheus", "port": True}
            }
        },
    )
    async with app.run_test():
        assert app.live_preferences.observability.history is None
    assert any("integer port" in text and "working defaults retained" in text for text, _ in notes)
