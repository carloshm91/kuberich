"""Actual HTTP/TLS delete/create/patch semantics, partial batches and owned cancellation."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from uuid import uuid4

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.operations import operation_receipt
from kuberich.domain.mutations import MutationState
from kuberich.domain.operations import DeleteOptions, ResourceAction, operation_json
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import Confirmation, MutationManager
from kuberich.services.operations import BatchDeleteService, ResourceOperationService
from tests.support.connections import catalog_fixture, certificate
from tests.support.operations import operation_api


@asynccontextmanager
async def source_fixture(
    tmp_path, alias="cm", action=ResourceAction.DELETE, count=1, *, tls=False, readonly=False
):
    ssl, cluster = certificate(tmp_path) if tls else (None, None)
    async with operation_api(alias, count, tls=ssl) as (url, api):
        client = KubernetesSession(
            catalog_fixture(
                tmp_path, url, {"token": "synthetic-operation", "as": "owned-reader"}, cluster
            ).select("kuberich-test-one"),
            1,
        )
        await client.open()
        current = [True]
        sources = tuple(
            ResourceOperationService(
                client,
                api.resource,
                ResourceTarget(
                    api.target.session,
                    api.resource.group,
                    api.resource.name,
                    api.target.namespace,
                    name,
                    value["metadata"]["uid"],
                ),
                AccessPolicy(readonly),
                lambda: current[0],
                action,
            )
            for name, value in api.values.items()
        )
        try:
            yield sources, api, current
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["cm", "no"])
@pytest.mark.parametrize(
    "options", [DeleteOptions(), DeleteOptions("Background", 0), DeleteOptions("Orphan", 30)]
)
async def test_delete_real_tls_exact_scope_guarded_options_and_single_use(tmp_path, alias, options):
    async with source_fixture(tmp_path, alias, tls=True) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare(options)
        proof = source.confirm(intent)
        assert (await source.execute(proof)).state is MutationState.SUCCEEDED
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert len(api.requests) == 1 and not api.values
        method, path, headers, query, body = api.requests[0]
        assert method == "DELETE" and path == intent.path
        assert headers["Authorization"] == "Bearer synthetic-operation"
        assert headers["Impersonate-User"] == "owned-reader"
        assert query == {"fieldValidation": "Strict"}
        assert body["preconditions"] == {"uid": source.target.uid, "resourceVersion": "opaque-7"}


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", ["cj", "job"])
async def test_suspend_resume_and_manual_trigger_actual_effects(tmp_path, alias):
    async with source_fixture(tmp_path, alias, ResourceAction.SUSPEND, tls=True) as (
        sources,
        api,
        _,
    ):
        source = sources[0]
        intent = await source.prepare()
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED
        assert api.value["spec"]["suspend"] is True
        source.action = ResourceAction.RESUME
        intent = await source.prepare()
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED
        assert api.value["spec"]["suspend"] is False
        if alias == "cj":
            source.action = ResourceAction.TRIGGER
            intent = await source.prepare()
            proof = source.confirm(intent)
            one, two = await asyncio.gather(source.execute(proof), source.execute(proof))
            assert {one.state, two.state} == {MutationState.SUCCEEDED, MutationState.BLOCKED}
            assert intent.created_name in one.message
            assert "created-job-uid" in one.message
            assert len(api.jobs) == 1
            next_intent = await source.prepare()
            assert next_intent.created_name == intent.created_name
            result = await source.execute(source.confirm(next_intent))
            assert result.state is MutationState.CONFLICT and "already exists" in result.message
            assert len(api.jobs) == 1
        assert "private-template" not in repr(intent)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "readonly",
        "stale",
        "closed",
        "wrong-uid",
        "version",
        "denied",
        "missing",
        "unauthorized",
        "server",
    ],
)
async def test_revalidation_refuses_without_any_write(tmp_path, change):
    async with source_fixture(tmp_path) as (sources, api, current):
        source = sources[0]
        intent = await source.prepare()
        proof = source.confirm(intent)
        if change == "readonly":
            source.policy = AccessPolicy(True)
        elif change == "stale":
            current[0] = False
        elif change == "closed":
            await source.client.close()
        elif change == "wrong-uid":
            api.value["metadata"]["uid"] = "replacement"
        elif change == "version":
            api.value["metadata"]["resourceVersion"] = "changed"
        else:
            api.read_status["owned-one"] = {
                "denied": 403,
                "missing": 404,
                "unauthorized": 401,
                "server": 500,
            }[change]
        result = await source.execute(proof)
        assert result.state not in {MutationState.SUCCEEDED, MutationState.ACCEPTED}
        assert not api.requests
        assert "private" not in result.message


@pytest.mark.asyncio
async def test_confirmation_is_bound_to_exact_intent_proof_and_target(tmp_path):
    async with source_fixture(tmp_path) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        with pytest.raises(AppError):
            source.confirm(replace(intent, identity=uuid4()))
        with pytest.raises(AppError):
            source.confirm(None)
        proof = source.confirm(intent)
        assert (
            await source.execute(Confirmation(proof.intent, proof.token))
        ).state is MutationState.BLOCKED
        assert (await source.execute(None)).state is MutationState.BLOCKED
        source.intent = replace(intent, identity=uuid4())
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert not api.requests


@pytest.mark.asyncio
async def test_operation_change_during_preparation_or_after_confirmation_never_writes(tmp_path):
    async with source_fixture(tmp_path, "cj", ResourceAction.SUSPEND) as (sources, api, _):
        source = sources[0]
        api.read_delay = 0.05
        task = asyncio.create_task(source.prepare())
        await asyncio.sleep(0.01)
        source.action = ResourceAction.TRIGGER
        with pytest.raises(AppError, match="changed during preparation"):
            await task
        api.read_delay = 0
        source.action = ResourceAction.SUSPEND
        intent = await source.prepare()
        proof = source.confirm(intent)
        source.action = ResourceAction.TRIGGER
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        with pytest.raises(AppError):
            source.confirm(intent)
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (400, MutationState.REJECTED),
        (401, MutationState.AUTH_ERROR),
        (403, MutationState.DENIED),
        (404, MutationState.NOT_FOUND),
        (409, MutationState.CONFLICT),
        (413, MutationState.REJECTED),
        (422, MutationState.REJECTED),
        (500, MutationState.UNCERTAIN),
        (302, MutationState.UNCERTAIN),
    ],
)
async def test_write_status_is_visible_not_replayed_or_redirected(tmp_path, status, state):
    async with source_fixture(tmp_path) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        api.write_status["owned-one"] = status
        result = await source.execute(source.confirm(intent))
        assert result.state is state and len(api.requests) == 1
        assert "private" not in result.message and api.values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["drop", "stall", "bad-json", "oversized", "wrong-uid", "wrong-name"]
)
async def test_applied_delete_with_unverifiable_response_is_uncertain_and_not_retried(
    tmp_path, mode
):
    async with source_fixture(tmp_path) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        source.client.timeout = 0.1
        api.mode = mode
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.UNCERTAIN and len(api.requests) == 1
        assert not api.values  # Actual effect occurred despite ambiguous receipt.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["normal", "status", "denied-observation", "replacement", "stale-observation"]
)
async def test_finalizer_acceptance_is_distinct_from_observed_deletion(tmp_path, mode):
    async with source_fixture(tmp_path) as (sources, api, current):
        source = sources[0]
        api.value["metadata"]["finalizers"] = ["example.io/cleanup"]
        intent = await source.prepare()
        if mode == "status":
            api.mode = "status"
        elif mode == "denied-observation":
            api.before_write = lambda _: api.read_status.update({"owned-one": 403})
        elif mode == "replacement":
            # Simulate replacement only after an accepted receipt through its observation read.
            original = source.client.get_json
            reads = 0

            async def replaced(path, **kwargs):
                nonlocal reads
                reads += 1
                data = await original(path, **kwargs)
                if reads > 1:
                    data["metadata"]["uid"] = "replacement"
                return data

            source.client.get_json = replaced
        elif mode == "stale-observation":
            api.before_write = lambda _: current.__setitem__(0, False)
        result = await source.execute(source.confirm(intent))
        assert result.state is (
            MutationState.SUCCEEDED if mode == "replacement" else MutationState.ACCEPTED
        )
        assert api.value["metadata"]["finalizers"] == ["example.io/cleanup"]
        if mode in {"normal", "status"}:
            assert "example.io/cleanup" in result.message
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_delete_server_preconditions_close_last_moment_replacement_race(tmp_path):
    async with source_fixture(tmp_path) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        api.before_write = lambda values: values["owned-one"]["metadata"].update(uid="replacement")
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.CONFLICT and api.values


@pytest.mark.asyncio
async def test_mixed_batch_outcomes_and_per_item_history_are_retained(tmp_path):
    async with source_fixture(tmp_path, count=3) as (sources, api, _):
        batch = BatchDeleteService(sources)
        intent = await batch.prepare(DeleteOptions())
        assert "3 explicitly selected" in intent.effects[0]
        proof = batch.confirm(intent)
        api.write_status["owned-2"] = 403
        api.values["owned-3"]["metadata"]["uid"] = "replacement"
        manager = MutationManager()
        result = await manager.wait(manager.start(batch, proof))
        assert result.state is MutationState.REJECTED
        assert [item.state for _, item in batch.results] == [
            MutationState.SUCCEEDED,
            MutationState.DENIED,
            MutationState.STALE,
        ]
        assert "owned-one" not in api.values and len(api.requests) == 2
        assert "owned-2: Permission denied" in manager.records[-1].result.message
        assert (await batch.execute(proof)).state is MutationState.BLOCKED
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [False, True])
async def test_batch_success_and_finalizer_pending_summary(tmp_path, pending):
    async with source_fixture(tmp_path, count=2) as (sources, api, _):
        if pending:
            api.values["owned-2"]["metadata"]["finalizers"] = ["example.io/cleanup"]
        batch = BatchDeleteService(sources)
        intent = await batch.prepare(DeleteOptions("Background", 0))
        result = await batch.execute(batch.confirm(intent))
        assert result.state is (MutationState.ACCEPTED if pending else MutationState.SUCCEEDED)
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_close_cancels_one_ambiguous_batch_write_and_keeps_remaining_unsent(tmp_path):
    async with source_fixture(tmp_path, count=3) as (sources, api, _):
        batch = BatchDeleteService(sources)
        intent = await batch.prepare(DeleteOptions())
        api.mode = "stall"
        manager = MutationManager()
        identity = manager.start(batch, batch.confirm(intent))
        await api.entered.wait()
        await manager.stop_for_client(batch.client)
        result = await manager.wait(identity)
        assert result.state is MutationState.UNCERTAIN
        assert [item.state for _, item in batch.results] == [
            MutationState.UNCERTAIN,
            MutationState.CANCELLED,
            MutationState.CANCELLED,
        ]
        assert len(api.requests) == 1 and "owned-2" in api.values
        assert not manager._live
        await manager.close()


@pytest.mark.asyncio
async def test_cancellation_and_timeout_during_revalidation_never_write(tmp_path):
    async with source_fixture(tmp_path) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        api.read_delay = 0.2
        source.client.timeout = 0.04
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.TIMEOUT and not api.requests
        source.client.timeout = 1
        proof = source.confirm(intent)
        task = asyncio.create_task(source.execute(proof))
        await asyncio.sleep(0.02)
        task.cancel()
        assert (await task).state is MutationState.CANCELLED and not api.requests


@pytest.mark.asyncio
async def test_batch_preparation_and_confirmation_refuse_bad_scope_and_proofs(tmp_path):
    async with source_fixture(tmp_path, count=2) as (sources, api, _):
        for value in ((), (sources[0], sources[0]), tuple(sources[0] for _ in range(101))):
            with pytest.raises(AppError):
                BatchDeleteService(value)
        batch = BatchDeleteService(sources)
        intent = await batch.prepare(DeleteOptions())
        with pytest.raises(AppError):
            batch.confirm(replace(intent, identity=uuid4()))
        proof = batch.confirm(intent)
        batch.intent = replace(intent, identity=uuid4())
        assert (await batch.execute(proof)).state is MutationState.BLOCKED
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["wrong-name", "no-uid", "bad-json", "drop", "stall"])
async def test_created_job_ambiguous_receipt_preserves_exact_name_and_no_duplicate(tmp_path, mode):
    async with source_fixture(tmp_path, "cj", ResourceAction.TRIGGER) as (sources, api, _):
        source = sources[0]
        intent = await source.prepare()
        api.mode, source.client.timeout = mode, 0.1
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.UNCERTAIN and len(api.jobs) == 1
        assert len(api.requests) == 1
        # A deliberate repeat in the same captured service uses the same name.
        api.mode = "normal"
        next_intent = await source.prepare()
        assert next_intent.created_name == intent.created_name
        assert (await source.execute(source.confirm(next_intent))).state is MutationState.CONFLICT
        assert len(api.jobs) == 1


def test_status_receipt_rejects_failure_or_wrong_identity():
    from kuberich.domain.operations import delete_intent
    from tests.support.operations import selection

    resource, target, value = selection()
    intent = delete_intent(
        resource, target, resource_record(resource, value, "team"), DeleteOptions()
    )
    for status in (
        {"kind": "Status", "status": "Failure"},
        {"kind": "Status", "status": "Success", "details": {"uid": "other"}},
        {"kind": "Status", "status": "Success", "details": {"name": "other"}},
    ):
        with pytest.raises(AppError):
            operation_receipt(operation_json(status), intent)
    assert (
        operation_receipt(operation_json({"kind": "Status", "status": "Success"}), intent).state
        is MutationState.ACCEPTED
    )
