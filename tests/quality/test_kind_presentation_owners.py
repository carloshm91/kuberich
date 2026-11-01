"""Kind verifier observation preserves real public discovery and task lifetimes."""

import asyncio
from unittest.mock import patch

import pytest
from aiohttp import web

from kuberich.domain.views import ViewStatus
from kuberich.services.pods import PodProjection
from kuberich.services.resources import ResourceReader
from kuberich.ui import app as app_module
from scripts.standard_kind import presentation_owners
from scripts.verify_custom_resources_kind import refresh_browser
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod as resource_pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app


@pytest.mark.asyncio
async def test_public_refresh_waits_real_operation_and_observes_finished_render_subscription_owners(
    tmp_path, monkeypatch
):
    projection = PodProjection()
    monkeypatch.setattr(app_module, "PodProjection", lambda: projection)

    async def ns(request):
        return namespaces("team")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(resource_pod("api", namespace="team")))

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        with presentation_owners(app) as (observations, renders):
            async with app.run_test(size=(100, 35)):
                await wait_for(
                    lambda: app.state.status is ViewStatus.LIVE and app.resources.row_count == 1
                )
                assert observations.tasks and renders.tasks
                assert all(not task.done() for task in (*observations.tasks, *renders.tasks))
                assert app.views.renderer.active_count == 1
                assert projection.cached_count == 1
                assert app.workspace.ownership.subscription_count == 1
                entered, release = asyncio.Event(), asyncio.Event()
                original = ResourceReader.discover

                async def held(reader):
                    entered.set()
                    await release.wait()
                    return await original(reader)

                with patch.object(ResourceReader, "discover", held):
                    refresh = asyncio.create_task(refresh_browser(app))
                    try:
                        await asyncio.wait_for(entered.wait(), 3)
                        assert not refresh.done()
                        release.set()
                        await asyncio.wait_for(refresh, 3)
                    finally:
                        release.set()
                        await asyncio.gather(refresh, return_exceptions=True)
                await wait_for(
                    lambda: app.state.status is ViewStatus.LIVE and app.resources.row_count == 1
                )
        assert observations.tasks and all(task.done() for task in observations.tasks)
        assert renders.tasks and all(task.done() for task in renders.tasks)
        assert app.views.renderer.active_count == 0
        assert projection.cached_count == 0
        assert app.workspace.ownership.subscription_count == 0
        assert app.workspace.ownership.close_complete and app.sessions.client is None
