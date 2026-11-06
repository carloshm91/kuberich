"""An export lease cannot survive navigation to another literal membership."""

import copy
from datetime import UTC, datetime

import pytest

from kuberich.domain.curated_navigation import PodRuntimeClass, ResolvedCollectionBookmark
from kuberich.domain.resource_queries import ResourceQuery
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, started


@pytest.mark.asyncio
async def test_standard_resource_screen_capture_is_invalidated_by_same_scope_predicate_navigation(
    tmp_path,
):
    async with curated_resources_api(tmp_path) as (url, api):
        resource = api.resource("pods")
        first = api.objects(resource)[0]
        first["spec"]["runtimeClassName"] = "sandbox"
        api.put(resource, first)
        second = copy.deepcopy(first)
        second["metadata"].update(name="native", uid="native")
        second["spec"]["runtimeClassName"] = "native"
        api.put(resource, second)
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            app.navigator.open_resource(
                resource,
                "team",
                bookmark=ResolvedCollectionBookmark(
                    resource, "team", PodRuntimeClass("sandbox"), ResourceQuery()
                ),
            )
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.pause()
            lease = next(
                lease
                for kind, lease in app.export_sources.capture(datetime.now(UTC))
                if kind == "screen"
            )
            assert lease.current()
            app.navigator.open_resource(
                resource,
                "team",
                bookmark=ResolvedCollectionBookmark(
                    resource, "team", PodRuntimeClass("native"), ResourceQuery()
                ),
            )
            await wait_for(
                lambda: app.resources.row_count == 1 and app.resources.selected_uid == "native"
            )
            assert not lease.current()
