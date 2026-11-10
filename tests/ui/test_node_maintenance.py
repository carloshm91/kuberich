"""Public command routes and real owned HTTP maintenance through Textual Pilot."""

import logging
from contextlib import asynccontextmanager

import pytest
from textual.widgets import Checkbox, Input

from kuberich.config.schema import Settings
from kuberich.domain.node_maintenance import NodeState, PodState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.node_maintenance import NodeMaintenanceScreen
from tests.support.connections import catalog_fixture
from tests.support.node_maintenance_terminal import maintenance_api, pod_manifest
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
    await app.run_command(command)
    await wait_for(lambda: isinstance(app.screen, NodeMaintenanceScreen))
    screen = app.screen
    await wait_for(lambda: screen.review is not None and not screen.busy)
    return screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(44, 14), (120, 36)])
async def test_review_is_read_only_default_cancel_and_independent_consents(tmp_path, size):
    async with maintenance_app(tmp_path) as (app, api):
        api.pods = {
            "unmanaged": pod_manifest("unmanaged", managed=False, emptydir=True),
            "daemon": pod_manifest("daemon", daemonset=True),
        }
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            screen = await review(app)
            assert app.focused is screen.cancel_button and screen.confirm_button.disabled
            assert screen.review is not None and len(screen.review.pods) == 2
            assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)
            for selector in ("force", "emptydir", "daemonsets"):
                assert not screen.query_one("#node-maintenance-" + selector, Checkbox).value
            screen.query_one("#node-maintenance-force", Checkbox).value = True
            await pilot.pause()
            assert screen.review is None and screen.confirm_button.disabled
            screen.prepare()
            await wait_for(lambda: screen.review is not None and not screen.busy)
            assert screen.confirm_button.disabled
            assert any("emptyDir" in blocker for blocker in screen.review.blockers)
            screen.query_one("#node-maintenance-emptydir", Checkbox).value = True
            screen.query_one("#node-maintenance-daemonsets", Checkbox).value = True
            await pilot.pause()
            screen.prepare()
            await wait_for(lambda: screen.review is not None and not screen.busy)
            assert not screen.confirm_button.disabled and app.focused is screen.cancel_button
            assert any(pod.target.namespace == "team" for pod in screen.review.pods)
            assert any(
                path == "/api/v1/pods"
                and body.get("fieldSelector") == ["spec.nodeName=owned-maintenance-node"]
                for method, path, body in api.requests
                if method == "GET"
            )
            await pilot.press("escape")
            assert len(app.screen_stack) == 1
            assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_confirm_stop_retains_pdb_refusal_and_fresh_uncordon(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test(size=(120, 36)) as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        assert screen.review is not None and screen.review.pods[0].pdbs[0].disruptions_allowed == 0
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
async def test_timeout_edit_invalidates_confirmation_and_rejects_invalid_range(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        screen.query_one("#node-maintenance-timeout", Input).value = "0"
        await pilot.pause()
        assert screen.review is None and screen.confirm_button.disabled
        screen.prepare()
        await wait_for(lambda: not screen.busy)
        assert screen.review is None
        assert "Review unavailable" in str(screen.feedback.content)
        assert not any(method in {"POST", "PATCH"} for method, *_ in api.requests)


@pytest.mark.asyncio
async def test_policy_tightening_stops_live_drain_and_preserves_observation(tmp_path):
    async with maintenance_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
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
async def test_read_only_and_wrong_resource_reject_before_preparation(tmp_path):
    async with maintenance_app(tmp_path, readonly=True) as (app, api), app.run_test():
        await wait_for(lambda: app.standard_table.row_count == 1)
        before = len(api.requests)
        for command in (":cordon", ":drain", ":uncordon"):
            await app.run_command(command)
        assert len(app.screen_stack) == 1
        assert not any(
            path == "/api/v1/nodes/owned-maintenance-node" for _, path, _ in api.requests[before:]
        )
