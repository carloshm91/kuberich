"""Real local HTTP proof of exact reviewed Node and eviction behavior."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.domain.mutations import MutationState
from kuberich.domain.node_maintenance import DrainOptions, MaintenanceMode, NodeState, PodState
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services.mutations import MutationManager
from kuberich.services.node_maintenance import NodeMaintenanceService
from tests.support.node_maintenance import NODE, maintenance_source, pod


@pytest.mark.asyncio
async def test_exact_node_cordon_noop_and_separate_uncordon(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        assert not api.requests and not review.node_unschedulable
        assert "cordon" in review.effects[0]
        proof = source.confirm(review)
        result = await source.execute(proof)
        assert result.state is MutationState.SUCCEEDED
        assert api.requests[0][2] == [
            {"op": "test", "path": "/metadata/uid", "value": "node-uid"},
            {"op": "test", "path": "/metadata/resourceVersion", "value": "opaque/node"},
            {"op": "add", "path": "/spec/unschedulable", "value": True},
        ]
        assert source.progress.node.state is NodeState.CORDONED
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        with pytest.raises(AppError):
            source.confirm(review)
        review = await source.prepare(MaintenanceMode.CORDON)
        assert (await source.execute(source.confirm(review))).state is MutationState.SUCCEEDED
        assert len(api.requests) == 1
        review = await source.prepare(MaintenanceMode.UNCORDON)
        assert (await source.execute(source.confirm(review))).state is MutationState.SUCCEEDED
        assert source.progress.node.state is NodeState.SCHEDULABLE
        assert api.requests[-1][2][-1]["value"] is False


@pytest.mark.asyncio
async def test_complete_review_and_exact_conditional_policy_eviction(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert not review.blockers and review.pods[0].managed and not api.requests
        assert any(
            params.get("fieldSelector") == "spec.nodeName=node-one" for _, params in api.reads
        )
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.SUCCEEDED
        assert [r[0] for r in api.requests] == ["PATCH", "POST"]
        eviction = api.requests[1]
        assert eviction[1] == "/api/v1/namespaces/team/pods/one/eviction"
        assert eviction[2] == {
            "apiVersion": "policy/v1",
            "kind": "Eviction",
            "metadata": {"name": "one", "namespace": "team"},
            "deleteOptions": {
                "preconditions": {"uid": "pod-one", "resourceVersion": "opaque/pod-one"}
            },
        }
        assert source.progress.pods[0].state is PodState.ABSENT
        assert source.progress.node.state is NodeState.CORDONED
        assert not source.operation_count


@pytest.mark.asyncio
async def test_actual_named_create_201_eviction_receipt_is_accepted_then_observed_absent(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.success_status = 201
        review = await source.prepare(MaintenanceMode.DRAIN)
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.SUCCEEDED
        assert source.progress.pods[0].state is PodState.ABSENT
        assert source.progress.pods[0].http_status == 201
        assert len(api.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_status,receipt",
    [
        (200, {"apiVersion": "v1", "kind": "Status", "status": "Success"}),
        (201, {"apiVersion": "v1", "kind": "Status", "status": "Success"}),
    ],
)
async def test_optional_status_code_may_be_omitted(http_status, receipt, tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.success_status, api.receipt_override = http_status, receipt
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert (await source.execute(source.confirm(review))).state is MutationState.SUCCEEDED
        assert source.progress.pods[0].http_status == http_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_status,receipt",
    [
        (201, {"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 200}),
        (200, {"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 201}),
        (200, {"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 200.0}),
        (201, {"apiVersion": "v1", "kind": "Status", "status": "Failure", "code": 201}),
        (201, {"apiVersion": "policy/v1", "kind": "Status", "status": "Success", "code": 201}),
        (201, {"apiVersion": "v1", "kind": "Eviction", "status": "Success", "code": 201}),
        (202, {"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 202}),
        (204, {}),
    ],
)
async def test_success_shape_or_status_mismatch_is_uncertain_without_replay(
    http_status, receipt, tmp_path
):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.success_status, api.receipt_override = http_status, receipt
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert (await source.execute(source.confirm(review))).state is MutationState.UNCERTAIN
        assert source.progress.pods[0].state is PodState.UNCERTAIN
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_429_does_not_stall_other_pods_and_reuses_exact_body(tmp_path):
    now = [0.0]
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
        await asyncio.sleep(0)

    async with maintenance_source(tmp_path, clock=lambda: now[0], sleep=sleep) as (source, api, _):
        api.pods.append(pod("two"))
        api.statuses["one"] = [429, 200]
        api.retry_after = "9"
        review = await source.prepare(MaintenanceMode.DRAIN)
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.SUCCEEDED
        posts = [r for r in api.requests if r[0] == "POST"]
        assert [r[2]["metadata"]["name"] for r in posts] == ["one", "two", "one"]
        assert posts[0][2] == posts[-1][2] and sum(sleeps) >= 9


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (401, MutationState.AUTH_ERROR),
        (403, MutationState.DENIED),
        (409, MutationState.CONFLICT),
        (500, MutationState.UNCERTAIN),
        (302, MutationState.UNCERTAIN),
    ],
)
async def test_nonretryable_write_refusals_stop_without_delete(tmp_path, status, state):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.statuses["one"] = [status]
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert (await source.execute(source.confirm(review))).state is state
        assert [r[0] for r in api.requests] == ["PATCH", "POST"]
        assert source.progress.node.state is NodeState.CORDONED


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["drop", "bad-json", "bad-receipt"])
async def test_ambiguous_acceptance_is_not_replayed(tmp_path, mode):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.post_mode = mode
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert (await source.execute(source.confirm(review))).state is MutationState.UNCERTAIN
        assert source.progress.pods[0].state is PodState.UNCERTAIN
        assert len(api.requests) == 2 and source.progress.node.state is NodeState.CORDONED


@pytest.mark.asyncio
async def test_cancel_inflight_retains_uncertainty_and_manager_history(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.post_mode = "stall"
        review = await source.prepare(MaintenanceMode.DRAIN)
        manager = MutationManager()
        identity = manager.start(source, source.confirm(review))
        await api.entered.wait()
        result = await manager.cancel(identity)
        assert result.state is MutationState.UNCERTAIN
        assert source.progress.pods[0].state is PodState.UNCERTAIN
        assert source.progress.node.state is NodeState.CORDONED
        assert not source.is_live and not manager.active_count
        assert manager.records[0].targets == ()
        api.release.set()


@pytest.mark.asyncio
async def test_confirmation_consumed_even_before_task_entry(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        proof = source.confirm(review)
        work = source.execute(proof)
        task = asyncio.create_task(work)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert not api.requests
        assert source.operation_count == 0 and not source.is_live


@pytest.mark.asyncio
async def test_cancel_after_cordon_before_first_eviction_reports_partial_and_last_known(tmp_path):
    async with maintenance_source(tmp_path, timeout=0.15) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.block_node_after_patch = True
        work = asyncio.create_task(source.execute(source.confirm(review)))
        await api.node_entered.wait()
        work.cancel()
        result = await work
        assert result.state is MutationState.PARTIAL
        assert [r[0] for r in api.requests] == ["PATCH"]
        assert source.progress.node.state is NodeState.UNKNOWN
        assert source.progress.node.last_known_state is NodeState.CORDONED
        assert source.progress.node.last_observed_at is not None
        assert source.progress.pods[0].state is PodState.NOT_SENT


@pytest.mark.asyncio
async def test_stop_racing_validated_receipt_retains_acceptance_and_never_sends_next_pod(
    tmp_path, monkeypatch
):
    from kuberich.adapters import node_maintenance as adapter

    entered, release = threading.Event(), threading.Event()
    original = adapter.eviction_receipt

    def receipt(data, status):
        entered.set()
        assert release.wait(2)
        return original(data, status)

    monkeypatch.setattr(adapter, "eviction_receipt", receipt)
    async with maintenance_source(tmp_path) as (source, api, _):
        api.pods.append(pod("two"))
        review = await source.prepare(MaintenanceMode.DRAIN)
        work = asyncio.create_task(source.execute(source.confirm(review)))
        assert await asyncio.to_thread(entered.wait, 2)
        work.cancel()
        release.set()
        result = await work
        assert result.state is MutationState.PARTIAL
        assert [r[0] for r in api.requests] == ["PATCH", "POST"]
        assert source.progress.pods[0].state is PodState.ACCEPTED
        assert source.progress.pods[1].state is PodState.NOT_SENT
        assert source.progress.node.state is NodeState.CORDONED
        assert not source.is_live


@pytest.mark.asyncio
async def test_withheld_execution_is_consumed_and_new_review_supersedes_it(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        old = source.execute(source.confirm(review))
        fresh = await source.prepare(MaintenanceMode.UNCORDON)
        assert (await old).state is MutationState.BLOCKED
        assert (await source.execute(source.confirm(fresh))).state is MutationState.SUCCEEDED
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("hazard", ["unmanaged", "emptydir", "both", "daemonset"])
async def test_consents_independent_and_daemonsets_retained(tmp_path, hazard):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.pods = [
            pod(
                managed=hazard not in {"unmanaged", "both"},
                emptydir=hazard in {"emptydir", "both"},
                daemonset=hazard == "daemonset",
            )
        ]
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert review.blockers and not api.requests
        with pytest.raises(AppError):
            source.confirm(review)
        review = await source.prepare(
            MaintenanceMode.DRAIN,
            DrainOptions(force=True, delete_emptydir_data=True, leave_daemonsets=True),
        )
        assert not review.blockers
        assert (await source.execute(source.confirm(review))).state is MutationState.SUCCEEDED
        assert len(api.requests) == (1 if hazard == "daemonset" else 2)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["owner-denied", "pdb-denied", "unsupported", "duplicate", "wrong-node"]
)
async def test_incomplete_preview_cannot_be_forced(tmp_path, failure):
    async with maintenance_source(tmp_path) as (source, api, _):
        if failure == "owner-denied":
            api.owner_status = 403
        elif failure == "pdb-denied":
            api.pdb_status = 403
        elif failure == "unsupported":
            api.eviction_supported = False
        else:
            api.list_mode = failure
        review = await source.prepare(MaintenanceMode.DRAIN, DrainOptions(force=True))
        assert review.blockers and not api.requests


@pytest.mark.asyncio
async def test_version_membership_and_external_uncordon_stop_before_further_writes(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.pods.append(pod("new"))
        assert (await source.execute(source.confirm(review))).state is MutationState.CONFLICT
        assert not api.requests
        api.pods.pop()
        api.pods.append(pod("two"))
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.after_post = lambda api, name: api.node["spec"].update(unschedulable=False)
        assert (await source.execute(source.confirm(review))).state is MutationState.STALE
        assert len(api.requests) == 2
        assert source.progress.node.state is NodeState.SCHEDULABLE
        assert source.progress.pods[1].state is PodState.NOT_SENT


@pytest.mark.asyncio
async def test_readonly_and_retired_client_block_service_boundary(tmp_path):
    async with maintenance_source(tmp_path, read_only=True) as (source, api, _):
        with pytest.raises(AppError):
            await source.prepare(MaintenanceMode.CORDON)
        assert not api.requests
    async with maintenance_source(tmp_path) as (source, api, current):
        review = await source.prepare(MaintenanceMode.CORDON)
        proof = source.confirm(review)
        current[0] = False
        assert (await source.execute(proof)).state is MutationState.STALE


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["wrong-state", "missing-kind", "drop"])
async def test_invalid_patch_receipt_remains_uncertain_and_final_state_is_separately_observed(
    tmp_path, mode
):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.patch_mode = mode
        review = await source.prepare(MaintenanceMode.CORDON)
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.UNCERTAIN
        assert source.progress.node.state is NodeState.CORDONED
        assert len(api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["missing", "replaced", "denied", "unknown", "malformed", "multiple"]
)
async def test_owner_identity_failure_is_not_hidden_by_force(tmp_path, mode):
    async with maintenance_source(tmp_path) as (source, api, _):
        if mode == "missing":
            api.owner_status = 404
        elif mode == "replaced":
            api.owner_uid = "replacement"
        elif mode == "denied":
            api.owner_status = 403
        elif mode == "unknown":
            api.pods[0]["metadata"]["ownerReferences"][0]["kind"] = "Undiscovered"
        elif mode == "malformed":
            api.owner_version = None
        else:
            api.pods[0]["metadata"]["ownerReferences"] *= 2
        review = await source.prepare(MaintenanceMode.DRAIN, DrainOptions(force=True))
        if mode in {"missing", "replaced"}:
            assert not review.blockers and not review.pods[0].managed
            assert (await source.execute(source.confirm(review))).state is MutationState.SUCCEEDED
        else:
            assert review.blockers and not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "storage", "pod-version"])
async def test_risk_or_version_change_after_cordon_requires_fresh_review(tmp_path, change):
    async with maintenance_source(tmp_path) as (source, api, _):
        if change == "storage":
            api.pods[0]["spec"]["volumes"] = [
                {"name": "disk", "persistentVolumeClaim": {"claimName": "claim"}}
            ]
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert not review.blockers

        def after_patch(api):
            if change == "owner":
                api.owner_uid = "new-owner"
            elif change == "storage":
                api.pv["spec"]["claimRef"]["uid"] = "replacement-claim"
            else:
                api.pods[0]["metadata"]["resourceVersion"] = "changed-pod-version"

        api.before_patch = after_patch
        assert (await source.execute(source.confirm(review))).state is MutationState.CONFLICT
        assert [r[0] for r in api.requests] == ["PATCH"]
        assert source.progress.pods[0].state is PodState.STALE


@pytest.mark.asyncio
async def test_owner_risk_change_before_cordon_refuses_all_writes(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.owner_uid = "replacement"
        assert (await source.execute(source.confirm(review))).state is MutationState.CONFLICT
        assert not api.requests


@pytest.mark.asyncio
async def test_external_uncordon_during_owner_read_is_observed_before_eviction_post(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        observed = []

        def uncordon_during_owner_read(api, path):
            if "/replicasets/" in path and any(request[0] == "PATCH" for request in api.requests):
                observed.append(path)
                api.node["spec"]["unschedulable"] = False

        api.after_read = uncordon_during_owner_read
        result = await source.execute(source.confirm(review))
        assert observed and result.state is MutationState.STALE
        assert [request[0] for request in api.requests] == ["PATCH"]
        assert source.progress.node.state is NodeState.SCHEDULABLE
        assert source.progress.pods[0].state is PodState.NOT_SENT


@pytest.mark.asyncio
async def test_controller_version_and_pdb_allowance_recovery_preserve_reviewed_pod_version(
    tmp_path,
):
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        api.owner_version = "recovery-controller-version"
        api.pdbs[0]["status"]["disruptionsAllowed"] = 1
        api.pdbs[0]["metadata"]["resourceVersion"] = "recovery-budget-version"
        await asyncio.sleep(0)

    async with maintenance_source(tmp_path, clock=lambda: now[0], sleep=sleep) as (source, api, _):
        api.statuses["one"] = [429, 200]
        api.pdbs = [budget()]
        review = await source.prepare(MaintenanceMode.DRAIN)
        frozen = review.pods[0].resource_version
        assert review.pods[0].pdbs[0].disruptions_allowed == 0
        api.owner_version = "controller-scale-two-version"
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.SUCCEEDED
        posts = [request for request in api.requests if request[0] == "POST"]
        assert len(posts) == 2 and posts[0][2] == posts[1][2]
        assert posts[1][2]["deleteOptions"]["preconditions"]["resourceVersion"] == frozen


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "condition", ["bound", "unbound", "denied", "bad-discovery", "no-discovery"]
)
async def test_storage_preview_uses_uid_binding_and_bounded_unknowns(tmp_path, condition):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.pods[0]["spec"]["volumes"] = [
            {"name": "disk", "persistentVolumeClaim": {"claimName": "claim"}},
            {"name": "shared", "persistentVolumeClaim": {"claimName": "claim"}},
        ]
        if condition == "unbound":
            api.pvc["spec"] = {}
        elif condition == "denied":
            api.storage_status = 403
        elif condition == "bad-discovery":
            source.discovery = Discovery(
                tuple(
                    replace(r, kind="Wrong") if r.name == "persistentvolumes" else r
                    for r in source.discovery.resources
                )
            )
        elif condition == "no-discovery":
            source.discovery = Discovery(
                tuple(r for r in source.discovery.resources if r.name != "persistentvolumes")
            )
        review = await source.prepare(MaintenanceMode.DRAIN)
        assert not review.blockers and "private-host-value" not in repr(review.pods[0].storage)
        detail = " ".join(review.pods[0].storage)
        assert ("local PV" if condition == "bound" else "portability unknown") in detail
        assert sum(path.endswith("/persistentvolumeclaims/claim") for path, _ in api.reads) <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["node-version", "node-uid", "node-absent", "node-denied"])
async def test_node_revalidation_and_final_observations_remain_honest(tmp_path, mode):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        if mode == "node-version":
            api.node["metadata"]["resourceVersion"] = "new-version"
        elif mode == "node-uid":
            api.node["metadata"]["uid"] = "replacement-node"
        else:
            api.read_status = 404 if mode == "node-absent" else 403
        result = await source.execute(source.confirm(review))
        assert result.state is not MutationState.SUCCEEDED and not api.requests
        assert (
            source.progress.node.state
            is {
                "node-version": NodeState.SCHEDULABLE,
                "node-uid": NodeState.REPLACED,
                "node-absent": NodeState.ABSENT,
                "node-denied": NodeState.UNKNOWN,
            }[mode]
        )


@pytest.mark.asyncio
async def test_read_policy_tightening_and_context_retirement_keep_completed_evidence(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, current):
        api.pods.append(pod("two"))
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.after_post = lambda api, name: current.__setitem__(0, False)
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.STALE and len(api.requests) == 2
        assert source.progress.pods[0].state is PodState.ACCEPTED
        assert source.progress.node.state is NodeState.UNKNOWN
        assert source.progress.node.last_known_state is NodeState.CORDONED


@pytest.mark.asyncio
async def test_final_inventory_rejects_unreviewed_arrivals_and_replacements(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)

        def replacement(api, name):
            item = pod(name)
            item["metadata"]["uid"] = "replacement-uid"
            api.pods.append(item)

        api.after_post = replacement
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.PARTIAL
        assert source.progress.pods[0].state is PodState.ABSENT
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_accepted_or_already_terminating_is_never_replayed_and_expires(tmp_path):
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        await asyncio.sleep(0)

    async with maintenance_source(tmp_path, clock=lambda: now[0], sleep=sleep) as (source, api, _):
        api.delete_accepted = False
        api.pods.append(pod("terminating"))
        api.pods[1]["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
        api.pods[1]["metadata"]["finalizers"] = ["synthetic/hold"]
        review = await source.prepare(MaintenanceMode.DRAIN, DrainOptions(timeout_seconds=2))
        assert review.pods[1].finalizer_count == 1
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.PARTIAL
        assert source.progress.pods[0].state is PodState.ACCEPTED
        assert source.progress.pods[1].state is PodState.TERMINATING
        assert len(api.requests) == 2 and now[0] == 2


@pytest.mark.asyncio
async def test_malformed_429_body_uses_valid_header_without_early_retry(tmp_path):
    now = [0.0]

    async def sleep(seconds):
        now[0] += seconds
        await asyncio.sleep(0)

    async with maintenance_source(tmp_path, clock=lambda: now[0], sleep=sleep) as (source, api, _):
        api.post_mode = "bad-refusal"
        api.retry_after = "10"
        api.statuses["one"] = [429]
        review = await source.prepare(MaintenanceMode.DRAIN, DrainOptions(timeout_seconds=2))
        assert (await source.execute(source.confirm(review))).state is MutationState.PARTIAL
        assert len(api.requests) == 2 and now[0] == 2


@pytest.mark.asyncio
async def test_competing_node_owners_and_repeated_teardown_are_drained(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        competitor = NodeMaintenanceService(
            source.client, NODE, source.target, source.discovery, source.policy, lambda: True
        )
        first, second = (
            await source.prepare(MaintenanceMode.DRAIN),
            await competitor.prepare(MaintenanceMode.DRAIN),
        )
        api.post_mode = "stall"
        work = asyncio.create_task(source.execute(source.confirm(first)))
        await api.entered.wait()
        assert (await competitor.execute(competitor.confirm(second))).state is MutationState.BLOCKED
        with pytest.raises(AppError):
            await competitor.prepare(MaintenanceMode.UNCORDON)
        await asyncio.gather(source.close(), source.close())
        assert (await work).state is MutationState.UNCERTAIN
        assert source.operation_count == 0
        await competitor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("descriptor", ["node", "pods", "pdb", "discovery", "options"])
async def test_invalid_discovery_or_review_options_never_admit_a_write(tmp_path, descriptor):
    async with maintenance_source(tmp_path) as (source, api, _):
        if descriptor == "node":
            source.resource = replace(source.resource, kind="NotNode")
        elif descriptor == "options":
            with pytest.raises(AppError):
                await source.prepare("cordon")
            assert not api.requests
            return
        elif descriptor == "discovery":
            api.discovery_body = {"resources": None}
        else:
            source.discovery = Discovery(
                tuple(
                    replace(r, kind="Wrong")
                    if r.name == ("pods" if descriptor == "pods" else "poddisruptionbudgets")
                    else r
                    for r in source.discovery.resources
                )
            )
        if descriptor == "node":
            with pytest.raises(AppError):
                await source.prepare(MaintenanceMode.DRAIN)
        else:
            assert (await source.prepare(MaintenanceMode.DRAIN)).blockers
        assert not api.requests


def budget(name="budget", namespace="team"):
    return {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "uid": f"{namespace}-{name}",
            "resourceVersion": "budget-rv",
            "generation": 1,
        },
        "spec": {"selector": {}, "minAvailable": 1},
        "status": {
            "observedGeneration": 1,
            "disruptionsAllowed": 0,
            "currentHealthy": 1,
            "desiredHealthy": 1,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ["pods", "pdb", "combined-count", "combined-bytes"])
async def test_incomplete_or_combined_preview_limit_cannot_authorize_a_prefix(
    tmp_path, monkeypatch, limit
):
    async with maintenance_source(tmp_path) as (source, api, _):
        if limit == "pods":
            api.pods.append(pod("two"))
            monkeypatch.setattr("kuberich.services.resources.MAX_ITEMS", 1)
        elif limit == "pdb":
            api.pdbs = [budget("one"), budget("two")]
            monkeypatch.setattr("kuberich.services.resources.MAX_ITEMS", 1)
        elif limit == "combined-count":
            item = pod("other")
            item["metadata"]["namespace"] = "other"
            api.pods.append(item)
            api.pdbs_by_namespace = {"team": [budget()], "other": [budget(namespace="other")]}
            monkeypatch.setattr("kuberich.services.node_maintenance.MAX_RESOURCE_ITEMS", 1)
        else:
            api.pdbs = [budget()]
            monkeypatch.setattr("kuberich.services.node_maintenance.MAX_RESOURCE_BYTES", 1)
        assert (await source.prepare(MaintenanceMode.DRAIN)).blockers
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("gone", [True, False])
async def test_eviction_404_is_distinguished_from_missing_original_pod(tmp_path, gone):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.statuses["one"] = [404]

        def after_read(api, path):
            if gone and any(r[0] == "POST" for r in api.requests):
                api.pods = []

        api.after_read = after_read
        result = await source.execute(source.confirm(review))
        assert result.state is (MutationState.SUCCEEDED if gone else MutationState.REJECTED)
        assert len(api.requests) == 2
        assert source.progress.pods[0].state is (PodState.ABSENT if gone else PodState.FAILED)


@pytest.mark.asyncio
async def test_api_read_denied_after_cordon_stops_without_eviction(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.pod_read_status = 403
        assert (await source.execute(source.confirm(review))).state is MutationState.DENIED
        assert [r[0] for r in api.requests] == ["PATCH"]


@pytest.mark.asyncio
async def test_uncertain_receipt_stays_uncertain_when_followup_pod_read_is_denied(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.post_mode = "bad-receipt"
        api.after_post = lambda api, name: setattr(api, "pod_read_status", 403)
        assert (await source.execute(source.confirm(review))).state is MutationState.UNCERTAIN
        assert source.progress.pods[0].state is PodState.UNCERTAIN
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_external_uncordon_after_patch_is_not_credited_as_success(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)

        def after_read(api, path):
            if api.requests:
                api.node["spec"]["unschedulable"] = False

        api.after_read = after_read
        assert (await source.execute(source.confirm(review))).state is MutationState.CONFLICT
        assert source.progress.node.state is NodeState.SCHEDULABLE
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_unavailable_read_after_cordon_reports_partial_and_unknown(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.DRAIN)
        api.before_patch = lambda api: setattr(api, "node_mode", "bad-json")
        assert (await source.execute(source.confirm(review))).state is MutationState.PARTIAL
        assert source.progress.node.state is NodeState.UNKNOWN
        assert source.progress.node.last_known_state is NodeState.CORDONED
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_closed_client_and_readonly_tightening_refuse_before_effect(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        proof = source.confirm(review)
        await source.client.close()
        assert (await source.execute(proof)).state is MutationState.UNREACHABLE
        assert source.progress.node.state is NodeState.UNKNOWN and not api.requests
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        proof = source.confirm(review)
        source.policy.tighten()
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert not api.requests


@pytest.mark.asyncio
async def test_real_total_deadline_preserves_accepted_uid_without_replay(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        api.delete_accepted = False
        review = await source.prepare(MaintenanceMode.DRAIN, DrainOptions(timeout_seconds=1))
        result = await source.execute(source.confirm(review))
        assert result.state is MutationState.PARTIAL
        assert source.progress.pods[0].state is PodState.ACCEPTED
        assert source.progress.node.state is NodeState.CORDONED
        assert len(api.requests) == 2
