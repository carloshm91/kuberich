"""Real resource views keep incomplete data visible and server queries explicit."""

import pytest
from aiohttp import web

from kuberich.config.schema import parse_document
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.services import resources
from kuberich.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.custom import roots
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.tables import custom_item, server_table
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_custom_resources import app_for, loaded
from tests.ui.test_navigation import make_app
from tests.ui.test_standard_resources import command


@pytest.mark.asyncio
async def test_incomplete_marker_survives_local_filter_empty_state_and_selection_notices(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 2)
    requests = []

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        requests.append(dict(request.query))
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            collection(*(pod(name, uid="owned-" + name) for name in ("one", "two", "three")))
        )

    async with workspace_api(ns, handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.state.status.name == "LIVE")
            await wait_for(lambda: app.resources.row_count == 2)
            assert "INCOMPLETE" in str(app.query_one("#resource-view").border_title)
            assert "2 retained pods" in str(app.status.content)
            app.presenter.notice("Selection reviewed")
            app.filter_input.value = "no-such-retained-pod"
            await wait_for(lambda: app.resources.row_count == 0)
            assert "INCOMPLETE" in str(app.query_one("#resource-view").border_title)
            assert "No retained pods match this filter" in str(
                app.query_one("#empty-title").content
            )
            assert "incomplete" in str(app.query_one("#empty-description").content)
            assert len([value for value in requests if "watch" not in value]) == 1
            await command(app, pilot, "server compact")
            assert "full objects" in str(app.status.content)
            assert app.workspace.selection.query == ResourceQuery()
        assert app.workspace.ownership.close_complete


@pytest.mark.asyncio
async def test_server_query_narrows_real_requests_and_history_preserves_its_separate_local_filter(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(resources, "MAX_ITEMS", 2)
    requests = []

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        requests.append(dict(request.query))
        if "watch" in request.query:
            return await stable_watch(request)
        names = (
            ("api-one",)
            if request.query.get("labelSelector") == "app=api"
            else ("api-one", "worker-two", "worker-three")
        )
        return web.json_response(collection(*(pod(name, uid="owned-" + name) for name in names)))

    async with workspace_api(ns, handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 30)) as pilot:
            await wait_for(lambda: app.resources.row_count == 2)
            app.filter_input.value = "api"
            await wait_for(lambda: app.resources.row_count == 1)
            await command(app, pilot, "server label app=api")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status.name == "LIVE"
                    and app.workspace.store.observation.scope.query.label_selector == "app=api"
                )
            )
            assert app.filter_input.value == "api"
            assert app.workspace.store.observation.snapshot.collection.complete
            assert "INCOMPLETE" not in str(app.query_one("#resource-view").border_title)
            assert all(
                "spec" in record.manifest and not record.metadata_only
                for record in app.workspace.store.observation.snapshot.items
            )
            await command(app, pilot, "server")
            assert "label: app=api" in str(app.status.content)
            before_noop = len(requests)
            revision = app.workspace.store.observation.revision
            await command(app, pilot, "server label app=api")
            assert len(requests) == before_noop
            assert app.workspace.store.observation.revision == revision
            await pilot.press("alt+left")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status.name == "LIVE"
                    and app.workspace.store.observation.scope.query.empty
                )
            )
            assert (
                app.filter_input.value == "api"
                and app.workspace.store.observation.snapshot.collection.limited
            )
            await pilot.press("alt+right")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status.name == "LIVE"
                    and app.workspace.store.observation.scope.query.label_selector == "app=api"
                )
            )
            assert app.filter_input.value == "api"
        assert app.workspace.ownership.close_complete
    assert any(
        value.get("watch") == "true" and value.get("labelSelector") == "app=api"
        for value in requests
    )


@pytest.mark.asyncio
async def test_server_query_survives_pod_namespace_changes_and_context_catalogue_is_local(tmp_path):
    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("one", uid="owned-one")))

    async with workspace_api(ns, handler) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(40, 12)) as pilot:
            await wait_for(lambda: app.state.status.name == "LIVE")
            await command(app, pilot, "server label app=api")
            await wait_for(
                lambda: (
                    app.state.status.name == "LIVE"
                    and app.state.scope.query.label_selector == "app=api"
                )
            )
            await command(app, pilot, "ns *")
            await wait_for(lambda: app.state.status.name == "LIVE" and app.state.namespace is None)
            assert app.state.scope.query == ResourceQuery("app=api")
            await command(app, pilot, "ctx")
            await wait_for(lambda: app.state.view_kind == "contexts")
            await command(app, pilot, "server clear")
            assert "open a resource view first" in str(app.status.content)
            assert app.workspace.selection.query == ResourceQuery("app=api")


@pytest.mark.asyncio
async def test_generic_compact_rows_keep_inspection_full_and_recover_full_payloads(tmp_path):
    requests = []

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        requests.append((request.path, dict(request.query)))
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/events"):
            return web.json_response(collection())
        obj = custom_item()
        if not request.path.endswith("/widgets"):
            return web.json_response(obj)
        if request.query.get("includeObject") == "Metadata":
            obj = {
                "apiVersion": "meta.k8s.io/v1",
                "kind": "PartialObjectMetadata",
                "metadata": obj["metadata"],
            }
        return web.json_response(server_table(obj))

    async with workspace_api(ns, handler, discovery_roots=roots) as url:
        app = app_for(tmp_path, url)
        app.jumps.configure(
            parse_document(
                {
                    "schema_version": 1,
                    "jumps": {
                        "schema_version": 1,
                        "definitions": {
                            "needs-spec": {
                                "source": "owned.example.test/v1/widgets",
                                "target": "owned.example.test/v1/widgets",
                                "labels": "level={{ spec.level }}",
                            }
                        },
                    },
                }
            )
        )
        async with app.run_test(size=(100, 30)) as pilot:
            await loaded(app, count=1)
            await command(app, pilot, "server compact")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status.name == "LIVE"
                    and app.workspace.store.observation.snapshot.items[0].metadata_only
                )
            )
            assert app.custom_table.get_cell("owned-one", "c2").plain == "3"
            await command(app, pilot, "jump needs-spec")
            assert "use :server full" in str(app.status.content)
            assert app.filter_input.value == "" and app.state.scope.resource.name == "widgets"
            await pilot.press("enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            await pilot.press("y")
            assert (
                "spec:" in app.screen.viewer.text
                and "PartialObjectMetadata" not in app.screen.viewer.text
            )
            await pilot.press("escape")
            await command(app, pilot, "server full")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status.name == "LIVE"
                    and not app.workspace.store.observation.snapshot.items[0].metadata_only
                )
            )
            assert app.workspace.store.observation.snapshot.items[0].manifest["spec"]
            await command(app, pilot, "jump needs-spec")
            assert app.filter_input.value == "label:level=3"
    assert any(value.get("includeObject") == "Metadata" for _, value in requests)
    assert any(path.endswith("/widgets/one") for path, _ in requests)
