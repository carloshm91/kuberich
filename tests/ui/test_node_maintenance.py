"""Public command routes and real owned HTTP maintenance through Textual Pilot."""

import logging
from contextlib import asynccontextmanager

import pytest
from textual.widgets import Button, Checkbox, Input

from kuberich.config.schema import Settings
from kuberich.domain.node_maintenance import NodeState, PodState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.node_maintenance import NodeMaintenanceScreen
from tests.support.connections import catalog_fixture
from tests.support.node_maintenance_terminal import (
    MaintenanceHandler,
    maintenance_api,
    pod_manifest,
)
from tests.support.workspace import wait_for


@asynccontextmanager
async def maintenance_app(tmp_path, *, readonly=False):
    with maintenance_api() as api:
        app = KubeRichApp(
            Settings(read_only=readonly),
            logging.Logger("node-maintenance-ui", level=100),
            catalog=catalog_fixture(tmp_path, f"http://127.0.0.1:{api.server_port}"),
            initial_command=ResourceCommand(RESOURCE_ALIASES["nodes"]),
        )
        yield app, api


async def review(app, command=":drain"):
    await wait_for(lambda: app.state.status is ViewStatus.LIVE)
    await app.run_command(command)
    await wait_for(lambda: isinstance(app.screen, NodeMaintenanceScreen))
    screen = app.screen
    await wait_for(lambda: screen.review is not None and not screen.busy)
    return screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 36)])
async def test_review_is_read_only_default_cancel_and_independent_consents(tmp_path, size):
    async with maintenance_app(tmp_path) as (app, api):
        api.pods = {
            "unmanaged": pod_manifest("unmanaged", managed=False, emptydir=True),
            "daemon": pod_manifest("daemon", daemonset=True),
        }
        async with app.run_test(size=size) as pilot:
            await wait_for(
                lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
            )
            screen = await review(app)
            assert app.focused is screen.cancel_button and screen.confirm_button.disabled
            assert screen.review is not None and len(screen.review.pods) == 2
            assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)
            for selector in ("force", "emptydir", "daemonsets"):
                assert not screen.query_one("#node-maintenance-" + selector, Checkbox).value
            screen.query_one("#node-maintenance-force", Checkbox).value = True
            await pilot.pause()
            assert screen.review is None and screen.confirm_button.disabled
            screen.query_one("#node-maintenance-review", Button).press()
            await wait_for(lambda: screen.review is not None and not screen.busy)
            assert screen.confirm_button.disabled
            assert any("emptyDir" in blocker for blocker in screen.review.blockers)
            screen.query_one("#node-maintenance-emptydir", Checkbox).value = True
            screen.query_one("#node-maintenance-daemonsets", Checkbox).value = True
            await pilot.pause()
            screen.query_one("#node-maintenance-review", Button).press()
            await wait_for(lambda: screen.review is not None and not screen.busy)
            assert not screen.confirm_button.disabled and app.focused is screen.cancel_button
            assert any(pod.target.namespace == "team" for pod in screen.review.pods)
            assert any(
                path == "/api/v1/pods"
                and body.get("fieldSelector") == ["spec.nodeName=owned-maintenance-node"]
                for method, path, body in api.requests
                if method == "GET"
            )
            await pilot.press("enter")
            assert len(app.screen_stack) == 1
            assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_confirm_stop_retains_pdb_refusal_and_fresh_uncordon(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test(size=(120, 36)) as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        assert screen.review is not None and screen.review.pods[0].pdbs[0].disruptions_allowed == 0
        screen.confirm_button.press()
        screen.confirm_button.press()
        await wait_for(
            lambda: any(pod.state is PodState.RETRYING for pod in screen.owner.progress.pods)
        )
        uid = screen.table.coordinate_to_cell_key(screen.table.cursor_coordinate).row_key.value
        scroll = screen.table.scroll_offset
        await pilot.pause()
        assert (
            screen.table.coordinate_to_cell_key(screen.table.cursor_coordinate).row_key.value == uid
        )
        assert screen.table.scroll_offset == scroll
        screen.cancel_button.press()
        await wait_for(lambda: screen.finished and not screen.busy)
        assert screen.owner.progress.node.state is NodeState.CORDONED
        assert "Observed cordoned" in str(screen.progress.content)
        sent = sum(method == "POST" for method, *_ in api.requests)
        await pilot.pause(0.1)
        assert sent == sum(method == "POST" for method, *_ in api.requests)
        assert api.node["spec"]["unschedulable"]
        await pilot.press("escape")
        fresh = await review(app, ":uncordon")
        assert app.focused is fresh.cancel_button and not fresh.confirm_button.disabled
        assert api.node["spec"]["unschedulable"]
        fresh.confirm_button.press()
        await wait_for(lambda: fresh.finished)
        assert not api.node["spec"]["unschedulable"]
        assert fresh.owner.progress.node.state is NodeState.SCHEDULABLE


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", ""])
async def test_timeout_edit_invalidates_confirmation_and_rejects_invalid_range(tmp_path, value):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        screen.query_one("#node-maintenance-timeout", Input).value = value
        await pilot.pause()
        assert screen.review is None and screen.confirm_button.disabled
        screen.query_one("#node-maintenance-review", Button).press()
        await pilot.pause()
        await wait_for(lambda: not screen.busy)
        assert screen.review is None
        assert "Review unavailable" in str(screen.feedback.content)
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_policy_tightening_stops_live_drain_and_preserves_observation(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        screen.confirm_button.press()
        await wait_for(lambda: api.attempted.is_set())
        app.commands.policy.tighten()
        app.operations.observe_node_operations()
        await wait_for(lambda: screen.finished)
        assert screen.owner.operation_count == 0
        sent = sum(method == "POST" for method, *_ in api.requests)
        await pilot.pause(0.1)
        assert sent == sum(method == "POST" for method, *_ in api.requests)
        assert api.node["spec"]["unschedulable"]


@pytest.mark.asyncio
async def test_read_only_rejects_before_preparation(tmp_path):
    async with maintenance_app(tmp_path, readonly=True) as (app, api), app.run_test():
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        before = len(api.requests)
        for command in (":cordon", ":drain", ":uncordon"):
            await app.run_command(command)
        assert len(app.screen_stack) == 1
        assert not any(
            path == "/api/v1/nodes/owned-maintenance-node" for _, path, _ in api.requests[before:]
        )


@pytest.mark.asyncio
async def test_wrong_resource_and_generic_node_identity_use_actual_descriptor(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        await app.run_command(":pods")
        await wait_for(lambda: app.state.view_kind == "pods")
        before = len(api.requests)
        for command in (":cordon", ":drain", ":uncordon"):
            await app.run_command(command)
        await pilot.pause()
        assert app.retained_node_maintenance_view_count == 0
        assert not any(
            path == "/api/v1/nodes/owned-maintenance-node" for _, path, _ in api.requests[before:]
        )
        await app.run_command(":resource nodes.core/v1")
        await pilot.pause(0.3)
        assert app.state.view_kind == "nodes.core", (app.state, api.requests)
        await wait_for(lambda: app.custom_table.row_count == 1)
        screen = await review(app, ":cordon")
        assert screen.review is not None and not screen.review.node_unschedulable
        screen.confirm_button.press()
        await wait_for(lambda: screen.finished)
        assert api.node["spec"]["unschedulable"]
        assert screen.owner.progress.node.state is NodeState.CORDONED


@pytest.mark.asyncio
async def test_accepted_terminating_pod_is_not_replayed_and_stop_preserves_evidence(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test(size=(40, 12)) as pilot:
        api.blocked = False
        api.terminating = True
        api.pods["workload"]["metadata"]["finalizers"] = ["owned.example/retain"]
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        assert "Finalizers: 1" in str(screen.detail.content)
        screen.confirm_button.press()
        await wait_for(
            lambda: any(pod.state is PodState.ACCEPTED for pod in screen.owner.progress.pods)
        )
        assert not screen.finished
        await wait_for(
            lambda: any(pod.state is PodState.TERMINATING for pod in screen.owner.progress.pods)
        )
        assert sum(method == "POST" for method, *_ in api.requests) == 1
        await pilot.press("escape")
        assert app.retained_node_maintenance_view_count == 0
        assert screen.owner.operation_count == 0
        assert screen.owner.progress.pods[0].state is PodState.TERMINATING
        assert api.node["spec"]["unschedulable"]
        assert "workload" in api.pods
        # A queued second Back must not dismiss the root after the viewer is gone.
        await screen.action_back()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_observed_absence_finishes_http_drain_and_keeps_completed_outcomes(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        api.blocked = False
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        screen.confirm_button.press()
        await wait_for(lambda: screen.finished)
        assert screen.owner.progress.pods[0].state is PodState.ABSENT
        assert "Original UID absent" in str(screen.progress.content)
        final = screen.owner.progress
        app.workspace.connect("kuberich-test-Two")
        await wait_for(lambda: app.state.context == "kuberich-test-Two")
        assert screen.owner.progress == final
        await pilot.press("escape")
        assert app.retained_node_maintenance_view_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("preparing", [False, True])
async def test_context_replacement_drains_preparation_or_live_write_before_old_client_closes(
    tmp_path, preparing
):
    async with maintenance_app(tmp_path) as (app, api), app.run_test():
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        if preparing:
            api.node_gate.clear()
            api.node_requested.clear()
            await app.run_command(":drain")
            await wait_for(
                lambda: (
                    isinstance(app.screen, NodeMaintenanceScreen) and api.node_requested.is_set()
                )
            )
            screen = app.screen
        else:
            screen = await review(app)
            screen.confirm_button.press()
            await wait_for(
                lambda: any(pod.state is PodState.RETRYING for pod in screen.owner.progress.pods)
            )
        owner = screen.owner
        app.workspace.connect("kuberich-test-Two")
        await wait_for(lambda: app.retained_node_maintenance_view_count == 0)
        assert owner.operation_count == 0 and app.mutations.active_count == 0
        await wait_for(lambda: owner.client.api is None)
        assert screen.finished
        assert screen.query_one("#node-maintenance-review", Button).disabled
        assert owner.progress.node.state is NodeState.UNKNOWN
        if preparing:
            assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)
        else:
            assert api.node["spec"]["unschedulable"]


@pytest.mark.asyncio
async def test_options_changing_during_review_need_a_fresh_intent_and_enter_only_reviews(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        api.node_gate.clear()
        api.node_requested.clear()
        await app.run_command(":drain")
        await wait_for(
            lambda: isinstance(app.screen, NodeMaintenanceScreen) and api.node_requested.is_set()
        )
        screen = app.screen
        timeout = screen.query_one("#node-maintenance-timeout", Input)
        screen.review_button.press()
        screen.review_button.press()
        timeout.value = "2"
        await pilot.pause()
        api.node_gate.set()
        await wait_for(lambda: not screen.busy)
        assert screen.review is None and screen.confirm_button.disabled
        timeout.focus()
        await pilot.press("enter")
        await wait_for(lambda: screen.review is not None and not screen.busy)
        assert screen.review.options.timeout_seconds == 2
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_failed_node_read_cannot_confirm_and_cleanup_remains_owned(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        api.node_status = 403
        await app.run_command(":cordon")
        await wait_for(
            lambda: isinstance(app.screen, NodeMaintenanceScreen) and not app.screen.busy
        )
        screen = app.screen
        assert screen.review is None and screen.confirm_button.disabled
        await pilot.press("escape")
        assert app.retained_node_maintenance_view_count == 0
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_failed_final_read_shows_unknown_with_aged_last_known_cordon(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test():
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        screen.confirm_button.press()
        await wait_for(
            lambda: any(pod.state is PodState.RETRYING for pod in screen.owner.progress.pods)
        )
        api.node_status = 503
        screen.cancel_button.press()
        await wait_for(lambda: screen.finished)
        observation = screen.owner.progress.node
        assert observation.state is NodeState.UNKNOWN
        assert observation.last_known_state is NodeState.CORDONED
        assert observation.last_observed_at is not None
        assert "Last known: Observed cordoned" in str(screen.progress.content)
        assert "current state remains unknown" in str(screen.progress.content)
        assert api.node["spec"]["unschedulable"]


@pytest.mark.asyncio
async def test_empty_inventory_and_overlapping_stale_pdb_evidence_remain_explicit(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test():
        api.pods["workload"]["spec"]["volumes"] = [{"name": "cache", "emptyDir": {}}]
        api.extra_pdbs = [
            {
                "apiVersion": "policy/v1",
                "kind": "PodDisruptionBudget",
                "metadata": {
                    "name": "other-budget",
                    "namespace": "team",
                    "uid": "other-pdb-uid",
                    "resourceVersion": "pdb-v2",
                    "generation": 2,
                },
                "spec": {
                    "selector": {},
                    "maxUnavailable": "20%",
                    "unhealthyPodEvictionPolicy": "AlwaysAllow",
                },
                "status": {
                    "disruptionsAllowed": 1,
                    "currentHealthy": 1,
                    "desiredHealthy": 1,
                    "observedGeneration": 1,
                },
            }
        ]
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        details = str(screen.detail.content)
        assert "Multiple matching PDBs" in details and "status unknown/stale" in details
        assert "AlwaysAllow" in details and "maxUnavailable 20%" in details
        assert "workload-uid" in details and "other-pdb-uid" in details
        assert "cache: emptyDir" in details
        previous = screen.review
        api.pods.clear()
        screen.review_button.press()
        await wait_for(
            lambda: screen.review is not None and screen.review is not previous and not screen.busy
        )
        assert app.screen is screen
        assert (
            screen.review is not None
            and screen.review.pods == ()
            and not screen.confirm_button.disabled
        )
        assert screen.table.row_count == 0
        details = str(screen.detail.content)
        assert "current complete reviewed Node inventory is empty" in details
        for obsolete in ("workload-uid", "other-pdb-uid", "AlwaysAllow", "cache: emptyDir"):
            assert obsolete not in details
        screen.confirm_button.press()
        await wait_for(lambda: screen.finished)
        assert api.node["spec"]["unschedulable"]
        assert not any(method == "POST" for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_denied_pdb_rereview_clears_old_facts_without_claiming_empty_inventory(
    tmp_path, monkeypatch
):
    original_get = MaintenanceHandler.do_GET
    deny_pdb = [False]
    denied_reads = []

    def get_with_pdb_denial(handler):
        path = handler.path.split("?", 1)[0]
        if deny_pdb[0] and path.endswith("/poddisruptionbudgets"):
            denied_reads.append(path)
            handler.respond(status=403)
            return
        original_get(handler)

    monkeypatch.setattr(MaintenanceHandler, "do_GET", get_with_pdb_denial)
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app)
        assert "workload-uid" in str(screen.detail.content)
        assert "pdb-uid" in str(screen.detail.content)
        previous = screen.review
        deny_pdb[0] = True
        screen.review_button.press()
        await wait_for(
            lambda: screen.review is not None and screen.review is not previous and not screen.busy
        )
        assert denied_reads == ["/apis/policy/v1/namespaces/team/poddisruptionbudgets"]
        assert app.screen is screen and screen.review is not None
        assert screen.review.pods == () and screen.review.blockers
        assert screen.confirm_button.disabled and screen.table.row_count == 0
        details = str(screen.detail.content)
        assert "workload-uid" not in details and "pdb-uid" not in details
        assert "inventory is empty" not in details
        screen.confirm_button.press()
        await pilot.pause()
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_confirmation_rechecks_policy_before_start_even_without_ui_observation(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
        )
        screen = await review(app, ":cordon")
        app.commands.policy.tighten()
        screen.confirm_button.press()
        await pilot.pause()
        assert not screen.started and screen.confirm_button.disabled
        assert "policy changed" in str(screen.feedback.content)
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_quit_immediately_after_command_admission_drains_an_unmounted_owner(tmp_path):
    async with maintenance_app(tmp_path) as (app, api):
        async with app.run_test():
            await wait_for(
                lambda: app.standard_table.row_count == 1 and app.state.status is ViewStatus.LIVE
            )
            await app.run_command(":drain")
            assert app.retained_node_maintenance_view_count == 1
            app.exit()
        assert app.retained_node_maintenance_view_count == 0
        assert app.sessions.client is None and app.mutations.active_count == 0
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)
