"""Actual discovery, Standard tables and finite admission links over an owned HTTP API."""

import asyncio
import copy
from datetime import UTC, datetime

import pytest

from kuberich.domain.curated_navigation import PolicyBindingMatch
from kuberich.domain.views import ViewStatus
from kuberich.ui.inspection import InspectionScreen
from tests.support.curated_admission import (
    BINDINGS,
    CANARIES,
    MUTATING_BINDINGS,
    MUTATING_POLICIES,
    POLICIES,
)
from tests.support.curated_resources import CuratedResourcesApi, curated_resources_api
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, loaded, started


async def inspector(app):
    app.action_inspect_details()
    await wait_for(
        lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
    )
    return app.screen


async def open_link(screen, pilot, key):
    assert screen.result.curated is not None
    index = next(index for index, link in enumerate(screen.result.curated.links) if link.key == key)
    await pilot.press("L")
    screen.links.highlighted = index
    await pilot.press("enter")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
@pytest.mark.parametrize("version", ["v1", "v1beta1"])
@pytest.mark.parametrize(
    "policy_plural,binding_plural,command,content_column",
    [
        (POLICIES, BINDINGS, "vap", "validations"),
        (MUTATING_POLICIES, MUTATING_BINDINGS, "map", "mutations"),
    ],
)
async def test_policy_discovery_table_details_links_and_history_keep_literal_membership(
    tmp_path, size, version, policy_plural, binding_plural, command, content_column
):
    fixture = CuratedResourcesApi(admission_versions=("v1", "v1beta1"))
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        policy, binding = (
            api.resource(policy_plural, version=version),
            api.resource(binding_plural, version=version),
        )
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await started(app, pilot)
            await app.run_command(
                f"resource {policy_plural}.admissionregistration.k8s.io/{version}"
            )
            await loaded(app, pilot, policy)
            assert {"match-rules", "match-conditions", content_column, "failure-policy"} <= set(
                app.standard_table.columns
            )
            selected = api.objects(policy)[0]["metadata"]["uid"]
            app.standard_table.move_cursor(row=app.standard_table.get_row_index(selected))
            app.filter_input.value = "owned-a"
            await wait_for(lambda: app.standard_table.row_count == 1)
            before = app.navigator.capture()
            screen = await inspector(app)
            assert screen.result.curated is not None
            for text in (
                screen.result.documents.yaml,
                screen.result.documents.managed_yaml,
                screen.viewer.text,
            ):
                assert all(canary not in text for canary in CANARIES)
            lease = screen.capture_export(datetime.now(UTC))[0][1]
            assert all(canary not in lease.capture.source.text for canary in CANARIES)
            await open_link(screen, pilot, "bindings")
            await loaded(app, pilot, binding, count=1)
            assert isinstance(app.views.curated.predicate, PolicyBindingMatch)
            assert app.standard_table.selected_uid == api.objects(binding)[0]["metadata"]["uid"]
            assert app.state.scope.namespace is None
            assert all(
                item.manifest["spec"]["policyName"] == "owned-a"
                for item in app.workspace.store.observation.snapshot.items
                if app.views.curated.predicate.matches(binding, item)
            )
            binding_screen = await inspector(app)
            await open_link(binding_screen, pilot, "policy")
            await loaded(app, pilot, policy, count=1)
            assert app.standard_table.selected_uid == selected
            app.navigator.history_back()
            await loaded(app, pilot, binding, count=1)
            app.navigator.history_back()
            await loaded(app, pilot, policy, count=1)
            assert app.filter_input.value == "owned-a"
            assert app.standard_table.selected_uid == before.selected
            after = app.navigator.capture()
            assert (after.x, after.y, after.top, after.top_offset) == (
                before.x,
                before.y,
                before.top,
                before.top_offset,
            )
            assert all(request.method == "GET" for request in api.requests)
            assert not any("podsecuritypolic" in request.path for request in api.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["source-rv", "source-uid", "observed-rv", "context"])
async def test_held_admission_source_or_target_never_opens_after_capture_changes(tmp_path, change):
    async with curated_resources_api(tmp_path) as (url, api):
        policy, binding = api.resource(POLICIES), api.resource(BINDINGS)
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("vapb")
            await loaded(app, pilot, binding)
            app.standard_table.move_cursor(row=0)
            screen = await inspector(app)
            source = api.objects(binding)[0]
            policy_path = policy.path(None) + "/owned-a"
            source_path = binding.path(None) + "/owned-a"
            held = api.hold(source_path if change in {"source-rv", "source-uid"} else policy_path)
            try:
                await open_link(screen, pilot, "policy")
                await asyncio.wait_for(held.entered.wait(), 2)
                if change == "context":
                    await app.run_command("ctx kuberich-test-Two")
                    await wait_for(
                        lambda: (
                            app.state.context == "kuberich-test-Two"
                            and app.state.status is ViewStatus.LIVE
                        )
                    )
                else:
                    changed = copy.deepcopy(source)
                    changed["metadata"]["uid" if change == "source-uid" else "resourceVersion"] = (
                        "replacement-opaque"
                    )
                    if change == "observed-rv":
                        api.emit(binding.path(None), changed)
                        await wait_for(
                            lambda: any(
                                item.resource_version == "replacement-opaque"
                                for item in app.workspace.store.observation.snapshot.items
                            )
                        )
                    else:
                        api.put(binding, changed)
                held.release.set()
                await wait_for(
                    lambda: (
                        screen.operation_count == 0
                        and (
                            change == "context"
                            or (
                                app.screen is screen
                                and any(
                                    text in str(screen.status.content)
                                    for text in ("changed", "obsolete")
                                )
                            )
                        )
                    )
                )
                assert app.state.scope.resource != policy
                if change != "context":
                    assert app.screen is screen
                    assert "changed" in str(screen.status.content) or "obsolete" in str(
                        screen.status.content
                    )
                assert all(request.method == "GET" for request in api.requests)
            finally:
                held.release.set()
                await screen.stop_owned()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["forbidden", "absent-api", "absent-object"])
async def test_admission_link_distinguishes_denial_missing_api_and_missing_object_without_downgrade(
    tmp_path, failure
):
    fixture = CuratedResourcesApi(
        absent={("admissionregistration.k8s.io", POLICIES)}
        if failure == "absent-api"
        else frozenset()
    )
    policy = fixture.resource(POLICIES)
    path = policy.path(None) + "/owned-a"
    if failure != "absent-api":
        fixture.denied_paths[path] = 403 if failure == "forbidden" else 404
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("vapb")
            await loaded(app, pilot, api.resource(BINDINGS))
            app.standard_table.move_cursor(row=0)
            screen = await inspector(app)
            await open_link(screen, pilot, "policy")
            expected = {
                "forbidden": "forbidden",
                "absent-api": "unavailable",
                "absent-object": "not found",
            }[failure]
            await wait_for(
                lambda: (
                    app.screen is screen
                    and screen.operation_count == 0
                    and expected in str(screen.status.content)
                )
            )
            assert app.screen is screen
            assert app.state.scope.resource.name == BINDINGS
            assert not any(
                "/v1beta1/" in request.path or "podsecuritypolic" in request.path
                for request in api.requests
            )
            if failure == "absent-api":
                assert not any(request.path == path for request in api.requests)
            await screen.stop_owned()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "versions,selected", [(("v1", "v1beta1"), "v1"), (("v1beta1",), "v1beta1")]
)
async def test_admission_preferred_or_absent_stable_version_uses_discovery_and_explicit_beta_is_preserved(
    tmp_path, versions, selected
):
    fixture = CuratedResourcesApi(admission_versions=versions)
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("vap")
            await loaded(app, pilot, api.resource(POLICIES, version=selected))
            await app.run_command(
                "resource validatingadmissionpolicybindings.admissionregistration.k8s.io/v1beta1"
            )
            resource = api.resource(BINDINGS, version="v1beta1")
            await loaded(app, pilot, resource)
            app.standard_table.move_cursor(row=0)
            screen = await inspector(app)
            await open_link(screen, pilot, "policy")
            await loaded(app, pilot, api.resource(POLICIES, version="v1beta1"), count=1)
            app.navigator.history_back()
            await loaded(app, pilot, resource)
            assert app.state.scope.resource.version == "v1beta1"


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_status", [False, True])
async def test_selected_stable_admission_list_forbidden_does_not_retry_known_beta(
    tmp_path, monkeypatch, hold_status
):
    fixture = CuratedResourcesApi(admission_versions=("v1", "v1beta1"))
    resource = fixture.resource(POLICIES, version="v1")
    fixture.denied_paths[resource.path(None)] = 403
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            root = app.screen
            publish = app.presenter.status
            held = []

            def status(message):
                if hold_status and "403" in message:
                    held.append(message)
                else:
                    publish(message)

            with monkeypatch.context() as patch:
                patch.setattr(app.presenter, "status", status)
                try:
                    await app.run_command("vap")
                    await wait_for(lambda: app.state.status is ViewStatus.FAILED)
                    if hold_status:
                        await wait_for(lambda: bool(held))
                        assert app.screen is root and app.state.scope.resource == resource
                        assert app.standard_table.row_count == 0
                        assert "403" not in str(app.status.content)
                        assert all(request.method == "GET" for request in api.requests)
                        assert not any(
                            request.path == fixture.resource(POLICIES, version="v1beta1").path(None)
                            for request in api.requests
                        )
                        assert not api.watch(resource.path(None)).entered.is_set()
                finally:
                    patch.undo()
                    for message in held:
                        publish(message)
            await wait_for(
                lambda: (
                    app.screen is root
                    and app.state.scope is not None
                    and app.state.scope.resource == resource
                    and app.state.status is ViewStatus.FAILED
                    and app.standard_table.row_count == 0
                    and "403" in str(app.status.content)
                )
            )
            assert app.standard_table.row_count == 0
            assert "403" in str(app.status.content)
            assert not any(
                request.path == fixture.resource(POLICIES, version="v1beta1").path(None)
                for request in api.requests
            )
            assert not api.watch(resource.path(None)).entered.is_set()
            assert any(request.path == resource.path(None) for request in api.requests)
            assert all(request.method == "GET" for request in api.requests)


@pytest.mark.asyncio
async def test_unreviewed_alpha_admission_stays_metadata_only_and_default_documents_still_conceal_payloads(
    tmp_path,
):
    fixture = CuratedResourcesApi(admission_versions=("v1alpha1",))
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command(
                "resource mutatingadmissionpolicies.admissionregistration.k8s.io/v1alpha1"
            )
            await loaded(app, pilot, api.resource(MUTATING_POLICIES))
            assert tuple(app.standard_table.columns) == ("name", "info", "age")
            screen = await inspector(app)
            assert screen.result.curated is None
            assert "metadata only" in screen.viewer.text
            assert all(canary not in screen.result.documents.yaml for canary in CANARIES)
            await screen.stop_owned()


@pytest.mark.asyncio
async def test_denied_preferred_discovery_never_automatically_selects_beta_but_explicit_beta_remains_usable(
    tmp_path,
):
    fixture = CuratedResourcesApi(admission_versions=("v1", "v1beta1"))
    fixture.denied_paths["/apis/admissionregistration.k8s.io/v1"] = 403
    async with curated_resources_api(tmp_path, fixture) as (url, api):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await started(app, pilot)
            await app.run_command("vap")
            await wait_for(
                lambda: (
                    app.state.status is ViewStatus.FAILED
                    and len(app.screen_stack) == 1
                    and "Higher-preference" in str(app.status.content)
                )
            )
            beta = api.resource(POLICIES, version="v1beta1")
            assert not any(request.path == beta.path(None) for request in api.requests)
            assert app.workspace.discovery.partial
            await app.run_command(
                "resource validatingadmissionpolicies.admissionregistration.k8s.io/v1beta1"
            )
            try:
                await loaded(app, pilot, beta)
            except TimeoutError:
                raise AssertionError(
                    f"Explicit beta did not open: state={app.state!r}, selection={app.workspace.selection!r}, route={app.views.route!r}, status={app.status.content!s}, problem={app.workspace.store.observation.problem!s}, requests={[(entry.path, entry.query) for entry in api.requests]}"
                ) from None
            assert any(request.path == beta.path(None) for request in api.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["Pod", "Node"])
async def test_composed_pod_and_node_scheduling_sections_are_visible_and_default_captures_conceal_canaries(
    tmp_path, kind
):
    marker = "SYNTHETIC_SCHEDULING_PRIVATE_VALUE"
    async with curated_resources_api(tmp_path) as (url, api):
        resource = api.resource("pods" if kind == "Pod" else "nodes")
        raw = api.objects(resource)[0]
        raw["metadata"]["annotations"] = {"owned/private": marker}
        raw.setdefault("spec", {}).update(
            nodeName="observed-node",
            nodeSelector={"zone": "owned", "api-token": marker},
            affinity={
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {"key": "zone", "operator": "In", "values": ["owned"]}
                                ]
                            }
                        ]
                    }
                }
            },
            tolerations=[{"key": "dedicated", "operator": "Exists", "effect": "NoSchedule"}],
            taints=[{"key": "dedicated", "value": "owned", "effect": "NoSchedule"}],
        )
        api.put(resource, raw)
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("pods team" if kind == "Pod" else "nodes")
            if kind == "Pod":
                await wait_for(
                    lambda: app.state.view_kind == "pods" and app.resources.row_count == 1
                )
                app.resources.move_cursor(row=0)
            else:
                await loaded(app, pilot, resource)
                app.standard_table.move_cursor(row=0)
            screen = await inspector(app)
            text = screen.viewer.text
            if kind == "Pod":
                assert all(
                    title in text
                    for title in (
                        "Scheduling identity (declared)",
                        "Node selectors (declared)",
                        "Affinity declarations",
                        "Tolerations (declared)",
                    )
                )
                assert "observed-node" in text
            else:
                assert "Node scheduling (declared)" in text and "Node taints (declared)" in text
            assert "not scheduler feasibility" in screen.result.documents.details
            for page in ("details", "yaml"):
                screen.action_page(page)
                lease = screen.capture_export(datetime.now(UTC))[0][1]
                assert marker not in lease.capture.source.text
                assert marker not in screen.viewer.text
            assert marker not in screen.result.documents.managed_yaml
            assert all(entry.method == "GET" for entry in api.requests)
            await screen.stop_owned()
