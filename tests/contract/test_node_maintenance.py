"""Real local HTTP proof of exact reviewed Node and eviction behavior."""

import asyncio

import pytest

from kuberich.domain.mutations import MutationState
from kuberich.domain.node_maintenance import DrainOptions, MaintenanceMode, NodeState, PodState
from kuberich.errors import AppError
from kuberich.services.mutations import MutationManager
from tests.support.node_maintenance import maintenance_source, pod


@pytest.mark.asyncio
async def test_exact_node_cordon_noop_and_separate_uncordon(tmp_path):
    async with maintenance_source(tmp_path) as (source, api, _):
        review = await source.prepare(MaintenanceMode.CORDON)
        assert not api.requests and not review.node_unschedulable
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
