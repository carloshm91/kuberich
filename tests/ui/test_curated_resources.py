"""Real App commands/discovery/list/watch expose typed curated rows and safe fallback."""

import asyncio
import copy
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from kuberich.config.schema import Settings
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture
from tests.support.curated_access import CANARY as ACCESS_CANARY
from tests.support.curated_policy import ANNOTATION_CANARY, CA_CANARY, URL_CANARIES
from tests.support.curated_resources import (
    ERROR_CANARY,
    PRINTER_CANARY,
    CuratedResourcesApi,
    curated_resources_api,
)
from tests.support.root_calls import root_calls as root_calls
from tests.support.workspace import wait_for

CURATED = tuple(definition for definition in STANDARD_RESOURCES if definition.curated)
CASES = {
    "horizontalpodautoscalers": ("desired", "2", "10", (0, 1)),
    "verticalpodautoscalers": ("recommended-containers", "1", "10", (0, 1)),
    "poddisruptionbudgets": ("current-healthy", "2", "10", (0, 1)),
    "priorityclasses": ("priority", "-10", "20", (0, 1)),
    "runtimeclasses": ("overhead-memory", "64Mi", "1Gi", (0, 1)),
    "leases": ("renew-time", "2026-11-06T10:00:01Z", "2026-11-06T11:00:00+01:00", (1, 0)),
    "networkpolicies": ("ingress-rules", "1", "0", (1, 0)),
    "endpointslices": ("endpoints", "3", "0", (1, 0)),
    "ingressclasses": ("default", "true", "false", (1, 0)),
    "resourcequotas": ("exceeded", "1", "0", (1, 0)),
    "limitranges": ("items", "2", "1", (1, 0)),
    "mutatingwebhookconfigurations": ("timeout-max", "20", "7", (1, 0)),
    "validatingwebhookconfigurations": ("timeout-max", "20", "7", (1, 0)),
    "serviceaccounts": ("secrets", "1", "2", (0, 1)),
    "roles": ("rules", "1", "2", (0, 1)),
    "clusterroles": ("rules", "1", "2", (0, 1)),
    "rolebindings": ("users", "0", "2", (0, 1)),
    "clusterrolebindings": ("users", "0", "2", (0, 1)),
}


def app_for(directory, url):
    return KubeRichApp(
        Settings(read_only=False),
        logging.Logger("owned-curated-ui", level=100),
        catalog=catalog_fixture(directory, url),
    )


async def started(app, pilot):
    await wait_for(lambda: app.state.status is ViewStatus.LIVE)
    await pilot.pause()


async def loaded(app, pilot, resource, *, namespace="team", count=2):
    await wait_for(
        lambda: (
            app.state.scope is not None
            and app.state.scope.resource == resource
            and app.state.status is ViewStatus.LIVE
            and app.standard_table.row_count == count
        )
    )
    await pilot.pause()
    assert app.state.scope.namespace == (namespace if resource.namespaced else None)


def ordered_uids(table):
    return tuple(row.key.value for row in table.ordered_rows)


def shown(table):
    return "\n".join(
        str(cell) for index in range(table.row_count) for cell in table.get_row_at(index)
    )


def assert_private_payloads_hidden(table):
    assert not any(
        value in shown(table)
        for value in (
            ACCESS_CANARY,
            ANNOTATION_CANARY,
            CA_CANARY,
            PRINTER_CANARY,
            ERROR_CANARY,
            *URL_CANARIES,
        )
    )


def save_receipt(name, payload):
    directory = Path("artifacts/issue232/ui-resources")
    directory.mkdir(parents=True, exist_ok=True)
    (directory / (name + ".json")).write_text(json.dumps(payload, indent=2, default=str) + "\n")


@pytest.mark.asyncio
@pytest.mark.parametrize("definition", CURATED, ids=lambda definition: definition.name)
async def test_each_curated_family_uses_real_commands_served_schema_typed_sort_watch_and_read_only_hints(
    tmp_path, definition, root_calls
):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            await started(app, pilot)
            command = definition.aliases[0] + (" team" if definition.namespaced else "")
            await app.run_command(command)
            resource = api.resource(definition.name, group=definition.group)
            await loaded(app, pilot, resource)
            path = resource.path("team" if resource.namespaced else None)
            await asyncio.wait_for(api.watch(path).entered.wait(), 5)
            assert any(entry.path == path and "watch" not in entry.query for entry in api.requests)
            assert any(
                entry.path == path
                and entry.query.get("resourceVersion") == "owned/list-1"
                and entry.query.get("watch") == "true"
                for entry in api.requests
            )
            table = app.standard_table
            assert tuple(column.value for column in table.columns) == tuple(
                column.key for column in definition.columns
            )
            bodies = sorted(api.objects(resource), key=lambda body: body["metadata"]["name"])
            uids = tuple(body["metadata"]["uid"] for body in bodies)
            field, first, second, ascending = CASES[definition.name]
            assert (table.get_cell(uids[0], field).text, table.get_cell(uids[1], field).text) == (
                first,
                second,
            )
            table.restore_sort(field, False)
            await pilot.pause()
            expected = tuple(uids[index] for index in ascending)
            assert ordered_uids(table) == expected
            table.action_reverse_sort()
            await pilot.pause()
            assert ordered_uids(table) == tuple(reversed(expected))
            table.move_cursor(row=table.get_row_index(uids[1]))
            await pilot.pause()
            await pilot.press("slash", *"owned-b", "enter")
            await wait_for(lambda: table.row_count == 1)
            assert table.selected_uid == uids[1] and app.filter_input.value == "owned-b"
            changed = copy.deepcopy(bodies[1])
            changed["metadata"]["resourceVersion"] = "owned/update-1"
            api.emit(path, changed)
            await wait_for(
                lambda: (
                    app.workspace.store.observation.snapshot is not None
                    and app.workspace.store.observation.snapshot.resource_version
                    == "owned/update-1"
                )
            )
            assert table.selected_uid == uids[1] and table.row_count == 1
            await pilot.press("escape")
            await wait_for(lambda: table.row_count == 2)
            assert table.selected_uid == uids[1]
            assert (
                app.check_action("edit", ()) is False
                and app.check_action("review_delete", ()) is False
            )
            assert "Edit" not in str(app.header.shortcuts) and "Delete" not in str(
                app.header.shortcuts
            )
            await pilot.press("E", "ctrl+d")
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert_private_payloads_hidden(table)
            save_receipt(
                definition.name,
                {
                    "scope": asdict(app.state.scope),
                    "command": command,
                    "field": field,
                    "displayed_values": [first, second],
                    "ascending_uids": expected,
                    "descending_uids": tuple(reversed(expected)),
                    "selected_uid": table.selected_uid,
                    "edit_delete_unavailable_with_read_only_false": True,
                    "requests": [asdict(entry) for entry in api.requests],
                },
            )
        assert app.sessions.client is None
        assert root_calls.renders.latest.done() and root_calls.observations.latest.done()
        assert not any(entry.method != "GET" for entry in api.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("versions,metric", [(("v2", "v1"), "1"), (("v1", "v2"), "70")])
async def test_preferred_hpa_version_uses_its_actual_metric_schema(tmp_path, versions, metric):
    fixture = CuratedResourcesApi(hpa_versions=versions)
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("hpa team")
            resource = api.resource("horizontalpodautoscalers", version=versions[0])
            await loaded(app, pilot, resource)
            body = api.objects(resource)[0]
            assert app.standard_table.get_cell(body["metadata"]["uid"], "metrics").text == metric
            assert_private_payloads_hidden(app.standard_table)
            assert any(entry.path == resource.path("team") for entry in api.requests)


@pytest.mark.asyncio
async def test_exact_nonpreferred_hpa_version_stays_curated_and_back_restores_version(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("hpa team")
            latest = api.resource("horizontalpodautoscalers", version="v2")
            await loaded(app, pilot, latest)
            await app.run_command("resource horizontalpodautoscalers.autoscaling/v1 team")
            exact = api.resource("horizontalpodautoscalers", version="v1")
            await loaded(app, pilot, exact)
            assert not app.custom_table.display
            uid = api.objects(exact)[0]["metadata"]["uid"]
            assert app.standard_table.get_cell(uid, "metrics").text == "70"
            assert any(entry.path == exact.path("team") for entry in api.requests)
            await pilot.press("alt+left")
            await loaded(app, pilot, latest)
            assert (
                app.standard_table.get_cell(
                    api.objects(latest)[0]["metadata"]["uid"], "metrics"
                ).text
                == "1"
            )
            assert_private_payloads_hidden(app.standard_table)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["absent", "discovery-forbidden", "list-forbidden", "empty"])
async def test_vpa_absent_denied_and_empty_have_distinct_availability_evidence(tmp_path, mode):
    key = ("autoscaling.k8s.io", "v1", "verticalpodautoscalers")
    fixture = CuratedResourcesApi(
        absent={(key[0], key[2])} if mode == "absent" else frozenset(),
        empty={key} if mode == "empty" else frozenset(),
    )
    resource = fixture.resource(key[2])
    path = resource.path("team")
    if mode == "discovery-forbidden":
        fixture.denied_paths["/apis/autoscaling.k8s.io/v1"] = 403
    elif mode == "list-forbidden":
        fixture.denied_paths[path] = 403
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("vpa team")
            if mode == "empty":
                await loaded(app, pilot, resource, count=0)
                assert app.workspace.store.observation.snapshot.collection.complete
                assert app.workspace.store.observation.problem is None
                assert "unavailable" not in str(app.query_one("#empty-title").content).lower()
            else:
                await wait_for(lambda: app.state.status is ViewStatus.FAILED)
                await pilot.pause()
                assert app.standard_table.row_count == 0
                assert str(app.query_one("#empty-title").content) == "Resource data unavailable"
                assert not api.watch(path).entered.is_set()
                if mode in {"absent", "discovery-forbidden"}:
                    assert not any(entry.path == path for entry in api.requests)
                else:
                    assert "403" in str(app.status.content)
            if mode == "discovery-forbidden":
                assert any(issue.status == 403 for issue in app.workspace.discovery.issues)
            elif mode == "absent":
                assert not any(
                    issue.source == "autoscaling.k8s.io/v1"
                    for issue in app.workspace.discovery.issues
                )
            assert ERROR_CANARY not in str(app.status.content)


@pytest.mark.asyncio
async def test_compact_negotiation_retires_curated_fields_and_ignores_printer_canary(tmp_path):
    key = ("networking.k8s.io", "v1", "networkpolicies")
    async with curated_resources_api(tmp_path, CuratedResourcesApi(metadata_only={key})) as (
        url,
        api,
    ):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("netpol team")
            resource = api.resource("networkpolicies")
            await loaded(app, pilot, resource)
            assert "selector" in app.standard_table.columns
            await app.run_command("server compact")
            try:
                await wait_for(
                    lambda: (
                        app.state.scope is not None
                        and app.state.scope.query.compact
                        and app.standard_table.row_count == 2
                        and tuple(column.value for column in app.standard_table.columns)
                        == ("namespace", "name", "info", "age")
                    )
                )
            finally:
                snapshot = app.workspace.store.observation.snapshot
                save_receipt(
                    "compact-observation",
                    {
                        "scope": asdict(app.state.scope) if app.state.scope else None,
                        "state": app.state.status,
                        "columns": tuple(column.value for column in app.standard_table.columns),
                        "rows": app.standard_table.row_count,
                        "metadata_only": [item.metadata_only for item in snapshot.items]
                        if snapshot
                        else None,
                        "problem": str(app.workspace.store.observation.problem),
                        "requests": [asdict(entry) for entry in api.requests],
                    },
                )
            await pilot.pause()
            assert all(
                record.metadata_only for record in app.workspace.store.observation.snapshot.items
            )
            assert "Metadata only" in shown(app.standard_table)
            assert_private_payloads_hidden(app.standard_table)
            assert any(
                entry.query.get("includeObject") == "Metadata"
                for entry in api.requests
                if entry.path == resource.path("team")
            )
            await app.run_command("server full")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and not app.state.scope.query.compact
                    and "selector" in app.standard_table.columns
                    and app.standard_table.row_count == 2
                )
            )
            assert_private_payloads_hidden(app.standard_table)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"version": "v99"}, {"kind": "OtherKind"}, {"namespaced": False}]
)
async def test_unsupported_actual_descriptor_uses_metadata_columns_with_actual_scope(
    tmp_path, change
):
    original = CuratedResourcesApi().resource("networkpolicies")
    unsupported = replace(original, **change)
    fixture = CuratedResourcesApi(
        descriptor_overrides={CuratedResourcesApi.key(original): unsupported}
    )
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("netpol")
            await loaded(app, pilot, unsupported)
            assert tuple(column.value for column in app.standard_table.columns) == (
                *(("namespace",) if unsupported.namespaced else ()),
                "name",
                "info",
                "age",
            )
            assert "Unsupported" in shown(app.standard_table)
            assert_private_payloads_hidden(app.standard_table)
            assert any(
                entry.path == unsupported.path("team" if unsupported.namespaced else None)
                for entry in api.requests
            )


@pytest.mark.asyncio
async def test_same_plural_in_another_group_remains_a_generic_schema(tmp_path):
    original = CuratedResourcesApi().resource("networkpolicies")
    foreign = replace(original, group="foreign.synthetic.example.test")
    fixture = CuratedResourcesApi(descriptor_overrides={CuratedResourcesApi.key(original): foreign})
    fixture.printer_values[fixture.key(foreign)] = "ordinary-other-schema"
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("resource networkpolicies.foreign.synthetic.example.test team")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource == foreign
                    and app.state.status is ViewStatus.LIVE
                    and app.custom_table.row_count == 2
                )
            )
            await pilot.pause()
            assert app.custom_table.display and not app.standard_table.display
            assert "selector" not in app.custom_table.columns
            assert any(entry.path == foreign.path("team") for entry in api.requests)


@pytest.mark.asyncio
async def test_normalized_missing_type_words_use_the_served_factory_descriptor(tmp_path):
    key = ("networking.k8s.io", "v1", "networkpolicies")
    async with curated_resources_api(tmp_path, CuratedResourcesApi(normalized={key})) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("netpol team")
            resource = api.resource("networkpolicies")
            await loaded(app, pilot, resource)
            assert "selector" in app.standard_table.columns
            assert all(
                record.manifest["kind"] == "NetworkPolicy"
                and record.manifest["apiVersion"] == "networking.k8s.io/v1"
                for record in app.workspace.store.observation.snapshot.items
            )
            assert_private_payloads_hidden(app.standard_table)


@pytest.mark.asyncio
async def test_watch_value_change_reorders_typed_rows_without_rebinding_selected_uid(tmp_path):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("hpa team")
            resource = api.resource("horizontalpodautoscalers")
            await loaded(app, pilot, resource)
            path = resource.path("team")
            await asyncio.wait_for(api.watch(path).entered.wait(), 5)
            bodies = sorted(api.objects(resource), key=lambda body: body["metadata"]["name"])
            a, b = (body["metadata"]["uid"] for body in bodies)
            app.standard_table.restore_sort("desired", False)
            await pilot.pause()
            app.standard_table.move_cursor(row=app.standard_table.get_row_index(b))
            await pilot.pause()
            changed = copy.deepcopy(bodies[0])
            changed["metadata"]["resourceVersion"] = "owned/update-typed"
            changed["status"]["desiredReplicas"] = 20
            api.emit(path, changed)
            await wait_for(lambda: app.standard_table.get_cell(a, "desired").text == "20")
            assert ordered_uids(app.standard_table) == (b, a)
            assert app.standard_table.selected_uid == b


@pytest.mark.asyncio
async def test_namespace_change_cancels_and_drains_held_list_before_new_rows_publish(tmp_path):
    fixture = CuratedResourcesApi()
    resource = fixture.resource("networkpolicies")
    held = fixture.hold(resource.path("team"))
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            client = app.sessions.client
            await app.run_command("netpol team")
            await asyncio.wait_for(held.entered.wait(), 5)
            await app.run_command("netpol other")
            await loaded(app, pilot, resource, namespace="other")
            await asyncio.wait_for(held.finished.wait(), 5)
            assert held.cancelled and app.sessions.client is client
            assert set(ordered_uids(app.standard_table)) == {
                body["metadata"]["uid"] for body in api.objects(resource, "other")
            }
            assert not any(
                entry.path == resource.path("team") and entry.query.get("watch")
                for entry in api.requests
            )


@pytest.mark.asyncio
async def test_version_change_drains_exact_old_read_and_preserves_current_metric_schema(tmp_path):
    fixture = CuratedResourcesApi()
    old = fixture.resource("horizontalpodautoscalers", version="v1")
    current = fixture.resource("horizontalpodautoscalers", version="v2")
    held = fixture.hold(old.path("team"))
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("resource horizontalpodautoscalers.autoscaling/v1 team")
            await asyncio.wait_for(held.entered.wait(), 5)
            await app.run_command("resource horizontalpodautoscalers.autoscaling/v2 team")
            await loaded(app, pilot, current)
            await asyncio.wait_for(held.finished.wait(), 5)
            assert held.cancelled
            assert (
                app.standard_table.get_cell(
                    api.objects(current)[0]["metadata"]["uid"], "metrics"
                ).text
                == "1"
            )
            assert not any(
                entry.path == old.path("team") and entry.query.get("watch")
                for entry in api.requests
            )


@pytest.mark.asyncio
async def test_history_restores_filter_sort_cursor_and_selected_namespace_around_cluster_view(
    tmp_path,
):
    async with curated_resources_api(tmp_path) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("quota team")
            quotas = api.resource("resourcequotas")
            await loaded(app, pilot, quotas)
            app.standard_table.restore_sort("exceeded", True)
            await pilot.pause()
            await pilot.press("slash", *"owned-b", "enter")
            await wait_for(lambda: app.standard_table.row_count == 1)
            before = app.standard_table.capture_viewport()
            await app.run_command("ingressclass")
            ingress = api.resource("ingressclasses")
            await loaded(app, pilot, ingress)
            await app.run_command("quota other")
            await loaded(app, pilot, quotas, namespace="other")
            await pilot.press("alt+left")
            await loaded(app, pilot, ingress)
            await pilot.press("alt+left")
            await loaded(app, pilot, quotas, count=1)
            assert app.filter_input.value == "owned-b"
            assert app.standard_table.sort_column == "exceeded" and app.standard_table.descending
            assert app.standard_table.capture_viewport() == before
            await pilot.press("alt+right")
            await loaded(app, pilot, ingress)
            assert app.state.scope.namespace is None and app.state.namespace == "team"
