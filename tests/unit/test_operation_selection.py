"""A refused batch action must leave the user's marked selection intact."""

from pathlib import Path

import pytest
from textual.app import App

from kuberich.config.forwarding import ForwardPreferences
from kuberich.domain.interactions import RangeSelection
from kuberich.domain.operations import ResourceAction
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import MutationManager
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.resource_operations import OperationContext, ResourceOperations
from kuberich.ui.target_capture import CapturedResource
from tests.support.pods import pod, snapshot


@pytest.mark.parametrize("blocked", ["policy", "missing", "oversized", "explicit"])
def test_batch_prunes_only_after_policy_and_initial_capture(blocked):
    policy = AccessPolicy(read_only=blocked == "policy")
    processes = ProcessRunner(policy)
    selected = RangeSelection()
    selected.apply("mark", "owned-hidden", ("owned-hidden",))
    data = snapshot(pod("visible"))
    identity = SessionIdentity("owned", 1)
    target = ResourceTarget(identity, "", "pods", "team", "visible", "owned-visible")
    captured = CapturedResource(object(), data.resource, data.items[0], target, lambda: True)
    captures, statuses = [], []

    def capture(uid):
        captures.append(uid)
        return None if blocked == "missing" else captured

    async def stop_plugins(client):
        raise AssertionError("Opening a batch must not stop a client.")

    context = OperationContext(
        WorkspaceChrome(lambda: ("owned", "owned", "owned", "team", "Live"), "test"),
        ("pods",),
        ("sh",),
        {},
        Path("/"),
        ViewRoute.pods(),
        False,
    )
    operations = ResourceOperations(
        App(),
        capture,
        lambda: context,
        policy,
        MutationManager(),
        ForwardManager(processes),
        processes,
        statuses.append,
        session_current=lambda client, session: True,
        forwarding=ForwardPreferences,
        delete_context=lambda: pytest.fail("A pod batch cannot edit local contexts."),
        stop_plugins=stop_plugins,
    )
    too_many = tuple(f"owned-{index}" for index in range(101))
    operations.operate(
        ResourceAction.DELETE,
        batch=True,
        uids=too_many if blocked == "explicit" else None,
        visible_uids=("owned-visible",),
        all_uids=too_many,
        selection=selected,
    )
    if blocked in {"policy", "missing"}:
        assert selected.marked == frozenset({"owned-hidden"})
        assert selected.anchor == "owned-hidden"
    else:
        assert selected.marked == frozenset() and selected.anchor is None
        assert statuses == ["Filter this view to at most 100 rows before choosing a delete batch."]
    assert captures == ([] if blocked == "policy" else [None])
    assert processes.active_count == 0
