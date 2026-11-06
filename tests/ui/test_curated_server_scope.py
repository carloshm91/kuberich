"""Explicit server selectors narrow existing curated membership and Event presentation."""

import copy

import pytest

from kuberich.domain.curated_navigation import (
    IngressClassName,
    PodRuntimeClass,
    ResolvedCollectionBookmark,
)
from kuberich.domain.events import EventOptions
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.views import ViewStatus
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_resources import curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, started


def uids(table):
    return {row.key.value for row in table.ordered_rows}


async def ready_resource(app, query):
    await wait_for(
        lambda: (
            app.state.scope is not None
            and app.state.scope.query == query
            and app.state.status is ViewStatus.LIVE
        )
    )


async def ready_events(app, query):
    await ready_resource(app, query)
    await wait_for(
        lambda: (
            app.events_table.source is not None
            and app.events_table.source.scope == app.state.scope
            and app.events_table.source.revision == app.workspace.store.observation.revision
            and app.events_table.source.status is ViewStatus.LIVE
            and app.events_table.options == app.views.event_options
        )
    )


@pytest.mark.asyncio
async def test_server_query_keeps_authoritative_runtime_membership_and_back_forward(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        resource = api.resource("pods")
        included = api.objects(resource)[0]
        included["metadata"]["labels"] = {"curated.kind/narrow": "yes"}
        included["spec"]["runtimeClassName"] = "sandbox"
        api.put(resource, included)
        excluded = copy.deepcopy(included)
        excluded["metadata"].update(name="other-runtime", uid="owned-other-runtime")
        excluded["spec"]["runtimeClassName"] = "native"
        api.put(resource, excluded)
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            initial = ResolvedCollectionBookmark(
                resource, "team", PodRuntimeClass("sandbox"), ResourceQuery()
            )
            app.navigator.open_resource(resource, "team", bookmark=initial)
            await wait_for(
                lambda: (
                    app.resources.display and uids(app.resources) == {included["metadata"]["uid"]}
                )
            )
            before_context = app.state.context
            query = ResourceQuery(label_selector="curated.kind/narrow=yes")
            await app.run_command("server label curated.kind/narrow=yes")
            await ready_resource(app, query)
            await pilot.pause()
            assert uids(app.resources) == {included["metadata"]["uid"]}, (
                f"Server query widened membership: {uids(app.resources)}"
            )
            assert app.views.curated == ResolvedCollectionBookmark(
                resource, "team", initial.predicate, query
            )
            assert app.state.scope.resource == resource and app.state.scope.namespace == "team"
            assert app.state.context == before_context
            assert any(
                entry.path == resource.path("team")
                and entry.query.get("labelSelector") == "curated.kind/narrow=yes"
                for entry in api.requests
            )
            app.navigator.history_back()
            await ready_resource(app, ResourceQuery())
            await wait_for(lambda: uids(app.resources) == {included["metadata"]["uid"]})
            assert app.views.curated == initial
            app.navigator.history_forward()
            await ready_resource(app, query)
            await wait_for(lambda: uids(app.resources) == {included["metadata"]["uid"]})
            assert app.views.curated.query == query
            query = ResourceQuery(
                label_selector="curated.kind/narrow=yes", field_selector="metadata.namespace=team"
            )
            await app.run_command("server field metadata.namespace=team")
            await ready_resource(app, query)
            await pilot.pause()
            assert uids(app.resources) == {included["metadata"]["uid"]}
            assert (
                app.views.curated.query == query
                and app.views.curated.predicate == initial.predicate
            )
            await app.run_command("server clear")
            await ready_resource(app, ResourceQuery())
            await pilot.pause()
            assert uids(app.resources) == {included["metadata"]["uid"]}
            assert app.views.curated == initial


@pytest.mark.asyncio
async def test_disallowed_compact_ingress_keeps_full_payload_and_exact_class(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        resource = api.resource("ingresses")
        included, excluded = api.objects(resource)
        included["spec"]["ingressClassName"] = "sandbox"
        excluded["spec"]["ingressClassName"] = "native"
        api.put(resource, included)
        api.put(resource, excluded)
        api.metadata_only.add(api.key(resource))
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            initial = ResolvedCollectionBookmark(
                resource, "team", IngressClassName("sandbox"), ResourceQuery()
            )
            app.navigator.open_resource(resource, "team", bookmark=initial)
            expected = {included["metadata"]["uid"]}
            await wait_for(
                lambda: app.standard_table.display and uids(app.standard_table) == expected
            )
            await app.run_command("server compact")
            await pilot.pause()
            assert "Compact metadata requires" in str(app.status.content)
            assert app.views.curated == initial and uids(app.standard_table) == expected
            assert app.workspace.selection.query == ResourceQuery()
            assert app.state.scope.resource == resource and app.state.scope.namespace == "team"
            assert not any(
                record.metadata_only for record in app.workspace.store.observation.snapshot.items
            )
            await app.run_command("server full")
            await ready_resource(app, ResourceQuery())
            await wait_for(lambda: uids(app.standard_table) == expected)
            assert app.views.curated == initial


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,expected_count", [("warnings", 6), ("grouped", 4), ("members", 3)])
async def test_server_label_query_preserves_events_warnings_groups_and_exact_members(
    tmp_path, mode, expected_count
):
    api = CuratedEventsApi(modern_only=True)
    resource = api.resource("events", group="events.k8s.io")
    for body in api.objects(resource):
        body["metadata"]["labels"] = {"curated.kind/narrow": "yes"}
        api.put(resource, body)
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await ready_events(app, ResourceQuery())
            app.navigator.events_options(
                EventOptions(grouped=mode != "warnings", warnings_only=True)
            )
            await wait_for(
                lambda: (
                    app.events_table.options == app.views.event_options
                    and app.events_table.row_count == (6 if mode == "warnings" else 4)
                )
            )
            if mode == "members":
                for row in app.events_table.ordered_rows:
                    app.events_table.move_cursor(row=app.events_table.get_row_index(row.key))
                    group = app.events_table.selected_group()
                    if group is not None and len(group.member_uids) == 3:
                        break
                await pilot.press("enter")
                await wait_for(
                    lambda: (
                        app.events_table.options.members is not None
                        and app.events_table.row_count == 3
                    )
                )
            options, initial = app.views.event_options, app.views.curated
            parent_uids = uids(app.events_table)
            query = ResourceQuery(label_selector="curated.kind/narrow=yes")
            await app.run_command("server label curated.kind/narrow=yes")
            await ready_events(app, query)
            await pilot.pause()
            assert app.views.event_options == options
            assert (
                app.events_table.options == options and app.events_table.row_count == expected_count
            )
            assert uids(app.events_table) == parent_uids
            assert app.views.curated == ResolvedCollectionBookmark(
                resource, "team", initial.predicate, query
            )
            assert app.state.scope.resource == resource and app.state.scope.namespace == "team"
            app.navigator.history_back()
            await ready_events(app, ResourceQuery())
            assert app.views.event_options == options and app.views.curated == initial
            await wait_for(lambda: uids(app.events_table) == parent_uids)


@pytest.mark.asyncio
async def test_compact_full_events_preserves_member_scope_and_warns_when_metadata_cannot_classify(
    tmp_path,
):
    api = CuratedEventsApi(modern_only=True)
    resource = api.resource("events", group="events.k8s.io")
    api.metadata_only.add(api.key(resource))
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await ready_events(app, ResourceQuery())
            app.navigator.events_options(EventOptions(grouped=True, warnings_only=True))
            await wait_for(
                lambda: app.events_table.row_count == 4 and app.events_table.options.grouped
            )
            for row in app.events_table.ordered_rows:
                app.events_table.move_cursor(row=app.events_table.get_row_index(row.key))
                group = app.events_table.selected_group()
                if group is not None and len(group.member_uids) == 3:
                    break
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    app.events_table.options.members is not None and app.events_table.row_count == 3
                )
            )
            options = app.views.event_options
            expected = uids(app.events_table)
            await app.run_command("server compact")
            await ready_events(app, ResourceQuery(compact=True))
            await pilot.pause()
            assert app.views.event_options == options and app.events_table.options == options
            assert app.views.curated.query == ResourceQuery(compact=True)
            assert app.events_table.row_count == 0
            assert any("metadata" in notice.lower() for notice in app.events_table.notices)
            assert app.workspace.store.observation.snapshot.items and all(
                item.metadata_only for item in app.workspace.store.observation.snapshot.items
            )
            await app.run_command("server full")
            await ready_events(app, ResourceQuery())
            await wait_for(lambda: uids(app.events_table) == expected)
            assert app.views.event_options == options and app.views.curated.query == ResourceQuery()
