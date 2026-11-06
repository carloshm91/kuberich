"""Exact served APIs and captured membership survive native navigation history."""

import copy
from dataclasses import replace

import pytest

from kuberich.domain.curated_navigation import PodRuntimeClass, ResolvedCollectionBookmark
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.view_routes import ViewKind
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, loaded, ordered_uids, started


@pytest.mark.asyncio
async def test_nonpreferred_hpa_version_keeps_typed_columns_api_identity_and_back_forward(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("resource horizontalpodautoscalers.autoscaling/v1 team")
            resource = api.resource("horizontalpodautoscalers", version="v1")
            await loaded(app, pilot, resource)
            assert app.views.route.kind is ViewKind.STANDARD
            assert app.views.route.selection.version == "v1"
            assert "desired" in app.standard_table.columns
            uid = ordered_uids(app.standard_table)[1]
            app.standard_table.move_cursor(row=app.standard_table.get_row_index(uid))
            app.filter_input.value = "owned-b"
            await wait_for(lambda: app.standard_table.row_count == 1)
            saved = app.navigator.capture()
            assert saved.curated.resource == resource and saved.selected == uid
            await app.run_command("cm team")
            await loaded(app, pilot, api.resource("configmaps"))
            app.navigator.history_back()
            await loaded(app, pilot, resource, count=1)
            await wait_for(lambda: app.standard_table.selected_uid == uid)
            assert app.filter_input.value == "owned-b" and app.workspace.selection.version == "v1"
            app.navigator.history_forward()
            await loaded(app, pilot, api.resource("configmaps"))
            assert app.filter_input.value == ""


@pytest.mark.asyncio
async def test_literal_membership_and_selected_uid_do_not_expand_when_a_named_pod_is_replaced(
    tmp_path,
):
    async with curated_resources_api(tmp_path) as (url, api):
        resource = api.resource("pods")
        original = api.objects(resource)[0]
        original["spec"]["runtimeClassName"] = "sandbox"
        api.put(resource, original)
        other = copy.deepcopy(original)
        other["metadata"].update(name="other", uid="other")
        other["spec"]["runtimeClassName"] = "native"
        api.put(resource, other)
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            bookmark = ResolvedCollectionBookmark(
                resource, "team", PodRuntimeClass("sandbox"), ResourceQuery()
            )
            app.navigator.open_resource(resource, "team", bookmark=bookmark)
            await wait_for(lambda: app.resources.row_count == 1)
            saved = app.navigator.capture()
            assert saved.curated == bookmark
            assert app.resources.selected_uid == original["metadata"]["uid"]
            await pilot.press("escape")
            await wait_for(lambda: app.resources.row_count == 2 and app.views.curated is None)
            app.navigator.history_forward()
            await wait_for(lambda: app.resources.display and app.resources.row_count == 1)
            assert app.navigator.capture().curated == bookmark
            app.navigator.open_resource(resource, "team", uid=original["metadata"]["uid"])
            await wait_for(lambda: app.resources.row_count == 1)
            replacement = copy.deepcopy(original)
            replacement["metadata"].update(uid="replacement", resourceVersion="object-2")
            api.emit(resource.path("team"), replacement)
            await wait_for(lambda: app.resources.row_count == 0)
            assert app.views.expected_uid == original["metadata"]["uid"]


@pytest.mark.asyncio
async def test_mismatched_collection_destination_is_rejected_before_scope_changes(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            before = app.workspace.selection
            resource = api.resource("pods")
            bookmark = ResolvedCollectionBookmark(
                resource, "team", PodRuntimeClass("sandbox"), ResourceQuery()
            )
            app.navigator.open_resource(replace(resource, version="v99"), "team", bookmark=bookmark)
            assert app.workspace.selection == before
