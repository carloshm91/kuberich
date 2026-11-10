"""Manifest review binds exact source, scope and sequential per-resource outcomes."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from kuberich.adapters.manifests import ManifestValidation
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.exports import DirectoryRef
from kuberich.domain.manifests import (
    FrozenManifestSource,
    ManifestScope,
    canonical_manifest,
    manifest_documents,
)
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.resources import ApiResource, Discovery, resource_record
from kuberich.domain.targets import ResourceAddress, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import Confirmation

RESOURCE = ApiResource(
    "", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "create", "patch", "delete"})
)
SESSION = SessionIdentity("kuberich-test-one", 1)


def manifest(name="one"):
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": name, "namespace": "team"},
        "data": {"managed": "private-value"},
    }


class Adapter:
    def __init__(self):
        self.values = {}
        self.writes = []
        self.reads = []
        self.validations = []
        self.write_states = []
        self.read_problem = None
        self.validation_state = MutationState.SUCCEEDED
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.stall = False
        self.closed = False
        self.preview_unchanged = False
        self.after_write = None
        self.on_read = None
        self.empty_preview = False
        self.no_validation_body = False
        self.write_problem = None

    async def read(self, resource, address, guard):
        guard()
        self.reads.append(address)
        if self.on_read is not None:
            self.on_read()
        if self.read_problem:
            raise self.read_problem
        value = self.values.get(address.name)
        return None if value is None else resource_record(resource, value, address.namespace)

    async def preview_update(self, resource, target, desired, baseline, guard):
        guard()
        value = baseline.manifest if self.preview_unchanged else json.loads(desired)
        if not self.preview_unchanged:
            value["metadata"].update(copy.deepcopy(baseline.manifest["metadata"]))
            value["metadata"].setdefault("annotations", {})["example.io/review"] = "private-mutable"
        if self.empty_preview:
            return ManifestValidation(MutationResult(MutationState.SUCCEEDED, "Safe empty preview"))
        return ManifestValidation(
            MutationResult(self.validation_state, "Safe server preview"), canonical_manifest(value)
        )

    async def validate(self, intent, guard):
        guard()
        self.validations.append(intent)
        body = json.loads(intent.body)
        if not isinstance(body, dict) or body.get("kind") == "DeleteOptions":
            body = self.values.get(intent.target.name, manifest(intent.target.name))
        if self.no_validation_body:
            return ManifestValidation(
                MutationResult(self.validation_state, "Safe validation outcome")
            )
        return ManifestValidation(
            MutationResult(self.validation_state, "Safe validation outcome"),
            canonical_manifest(body),
        )

    async def execute(self, intent, guard):
        guard()
        self.writes.append(intent)
        self.entered.set()
        if self.write_problem is not None:
            raise self.write_problem
        if self.stall:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                return MutationResult(
                    MutationState.UNCERTAIN, "Request started; inspect before retry."
                )
        if self.after_write is not None:
            self.after_write()
        return MutationResult(
            self.write_states.pop(0) if self.write_states else MutationState.SUCCEEDED,
            "Safe write outcome",
        )

    async def close(self):
        self.closed = True


@asynccontextmanager
async def service_fixture(
    tmp_path, *, count=1, existing=False, read_only=False, namespace="team", duplicate=False
):
    adapter = Adapter()
    documents = tuple(
        manifest_documents(canonical_manifest(manifest(str(index))), source_path=f"{index}.yaml")[0]
        for index in range(count)
    )
    if duplicate:
        documents = (documents[0], documents[0])
    root = DirectoryRef(path=tmp_path, device=1, inode=2)
    source = FrozenManifestSource(
        identity=uuid4(),
        root=root,
        kind="directory",
        relative_path=".",
        files=(),
        documents=documents,
        source_sha256="source-hash",
        rendered_sha256="rendered-hash",
    )
    current = [True]
    source_current = [True]

    async def require_source():
        if not source_current[0]:
            raise AppError("Captured source changed.")

    if existing:
        for index in range(count):
            value = manifest(str(index))
            value["metadata"].update(uid=f"uid-{index}", resourceVersion="1")
            adapter.values[str(index)] = value
    service = ManifestMutationService(
        SimpleNamespace(context=SimpleNamespace(name=SESSION.context)),
        ManifestScope(session=SESSION, namespace=namespace),
        Discovery((RESOURCE,)),
        AccessPolicy(read_only),
        source,
        lambda: current[0],
        require_source,
        {},
        tmp_path,
        adapter=adapter,
    )
    try:
        yield service, adapter, current, source_current
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_exact_create_plan_confirmation_consumed_before_concurrent_submit(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        assert plan.ready and plan.items[0].change == "create"
        assert isinstance(service.target, ResourceAddress) and service.target.uid is None
        proof = service.confirm(plan)
        one, two = await asyncio.gather(service.execute(proof), service.execute(proof))
        assert {one.state, two.state} == {MutationState.SUCCEEDED, MutationState.BLOCKED}
        assert len(adapter.writes) == 1
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        assert "private-value" not in repr(plan) + repr(service.results)


@pytest.mark.asyncio
async def test_forged_attempt_consumes_existing_proof_and_different_plan_refused(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        with pytest.raises(AppError):
            service.confirm(replace(plan, identity=uuid4()))
        proof = service.confirm(plan)
        forged = Confirmation(proof.intent, proof.token)
        assert (await service.execute(forged)).state is MutationState.BLOCKED
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        assert not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,state",
    [
        ("source", MutationState.STALE),
        ("context", MutationState.STALE),
        ("policy", MutationState.BLOCKED),
        ("appeared", MutationState.CONFLICT),
    ],
)
async def test_create_revalidation_blocks_changed_source_context_policy_or_new_name(
    tmp_path, change, state
):
    async with service_fixture(tmp_path) as (service, adapter, current, source_current):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        if change == "source":
            source_current[0] = False
        elif change == "context":
            current[0] = False
        elif change == "policy":
            service.policy.tighten()
        else:
            value = manifest("0")
            value["metadata"].update(uid="replacement", resourceVersion="1")
            adapter.values["0"] = value
        result = await service.execute(proof)
        assert result.state is state and not adapter.writes
        assert len(result.items) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,state", [("uid", MutationState.STALE), ("resourceVersion", MutationState.CONFLICT)]
)
async def test_existing_write_rechecks_real_uid_and_opaque_version(tmp_path, field, state):
    async with service_fixture(tmp_path, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        assert plan.items[0].change == "update" and plan.ready
        proof = service.confirm(plan)
        adapter.values["0"]["metadata"][field] = "changed"
        result = await service.execute(proof)
        assert result.state is state and not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,existing,change", [("delete", False, "absent"), ("apply", True, "unchanged")]
)
async def test_all_absent_or_unchanged_plan_is_explicit_no_request(
    tmp_path, action, existing, change
):
    async with service_fixture(tmp_path, existing=existing) as (service, adapter, _, _):
        adapter.preview_unchanged = True
        plan = await service.prepare(action)
        assert plan.ready and plan.items[0].change == change and plan.items[0].request is None
        assert plan.items[0].resource_version == ("1" if existing else None)
        assert (await service.execute(service.confirm(plan))).state is MutationState.SUCCEEDED
        assert not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        MutationState.DENIED,
        MutationState.CONFLICT,
        MutationState.UNCERTAIN,
        MutationState.CANCELLED,
    ],
)
async def test_batch_stops_at_first_failure_retains_prior_and_labels_remaining_unsent(
    tmp_path, failure
):
    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        adapter.write_states = [MutationState.SUCCEEDED, failure]
        result = await service.execute(service.confirm(plan))
        assert result.state is (
            MutationState.UNCERTAIN if failure is MutationState.UNCERTAIN else MutationState.PARTIAL
        )
        assert "Current operation: Safe write outcome" in result.message
        assert [state.state for _, state in result.items] == [
            MutationState.SUCCEEDED,
            failure,
            MutationState.BLOCKED,
        ]
        assert "Unsent" in result.items[2][1].message
        assert len(adapter.writes) == 2 and service.results == result.items


@pytest.mark.asyncio
async def test_failed_dry_run_denies_whole_batch_confirmation(tmp_path):
    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        adapter.validation_state = MutationState.DENIED
        plan = await service.prepare("apply")
        assert not plan.ready and len(plan.items) == 2 and len(adapter.validations) == 2
        with pytest.raises(AppError):
            service.confirm(plan)
        assert not adapter.writes


@pytest.mark.asyncio
async def test_set_namespace_retains_session_invalidates_exact_plan_and_refuses_active(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        service.set_namespace("other-team")
        assert service.scope.session is SESSION and service.scope.namespace == "other-team"
        assert service.intent is None
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        plan = await service.prepare("apply")
        # Explicit namespace from the source stays in team; fallback changes only missing namespaces.
        assert plan.items[0].target.namespace == "team"
        adapter.stall = True
        task = asyncio.create_task(service.execute(service.confirm(plan)))
        await adapter.entered.wait()
        with pytest.raises(AppError, match="Stop and drain"):
            service.set_namespace(None)
        task.cancel()
        assert (await task).state is MutationState.UNCERTAIN
        service.set_namespace(None)
        with pytest.raises(AppError):
            service.set_namespace("bad/namespace")


@pytest.mark.asyncio
async def test_close_drains_active_request_under_repeated_cancellation_and_retains_outcomes(
    tmp_path,
):
    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        adapter.stall = True
        task = asyncio.create_task(service.execute(service.confirm(plan)))
        await adapter.entered.wait()
        closing = asyncio.create_task(service.close())
        await asyncio.sleep(0)
        closing.cancel()
        await closing
        result = await task
        assert result.state is MutationState.UNCERTAIN and len(result.items) == 2
        assert service.operation_count == 0 and adapter.closed
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "problem,state",
    [
        (HttpProblem(403), MutationState.DENIED),
        (ConnectionProblem(ConnectionState.TIMEOUT, "Safe timeout"), MutationState.TIMEOUT),
    ],
)
async def test_read_failures_are_refused_not_converted_into_creates(tmp_path, problem, state):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        adapter.read_problem = problem
        plan = await service.prepare("apply")
        assert not plan.ready and plan.items[0].change == "refused"
        assert plan.items[0].validation.state is state
        assert not adapter.validations and not adapter.writes


@pytest.mark.asyncio
async def test_service_requires_prepared_target_valid_action_and_nonempty_unique_addresses(
    tmp_path,
):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        with pytest.raises(AppError, match="Prepare an exact"):
            _ = service.target
        with pytest.raises(AppError, match="Choose apply or delete"):
            await service.prepare("unsafe-action")
        assert not adapter.reads
    async with service_fixture(tmp_path, duplicate=True) as (service, adapter, _, _):
        with pytest.raises(AppError, match="distinct exact"):
            await service.prepare("apply")
        assert not adapter.reads
    async with service_fixture(tmp_path, count=0) as (service, adapter, _, _):
        with pytest.raises(AppError, match="distinct exact"):
            await service.prepare("apply")
        assert not adapter.reads


@pytest.mark.asyncio
async def test_read_only_service_refuses_prepare_confirm_and_execute_before_any_adapter_call(
    tmp_path,
):
    async with service_fixture(tmp_path, read_only=True) as (service, adapter, _, _):
        with pytest.raises(AppError, match="Read-only"):
            await service.prepare("apply")
        with pytest.raises(AppError, match="Read-only"):
            service.confirm(None)
        assert (await service.execute(None)).state is MutationState.BLOCKED
        assert not adapter.reads and not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["scope", "source", "client-context"])
async def test_public_state_replacement_cannot_retarget_reviewed_writes(tmp_path, change):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        if change == "scope":
            service.scope = replace(service.scope, namespace="other-team")
        elif change == "source":
            service.source = replace(service.source, source_sha256="changed")
        else:
            service.client.context.name = "other-context"
        result = await service.execute(proof)
        assert result.state is MutationState.STALE and not adapter.writes
        assert len(result.items) == 1 and "Unsent" in result.items[0][1].message


@pytest.mark.asyncio
async def test_source_generation_invalidation_during_read_refuses_plan_publication(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        adapter.on_read = service.invalidate
        with pytest.raises(AppError, match="invalidated"):
            await service.prepare("apply")
        assert service.intent is None and not adapter.validations and not adapter.writes


@pytest.mark.asyncio
async def test_execute_refuses_vanished_reviewed_uid_before_any_write(tmp_path):
    async with service_fixture(tmp_path, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        adapter.values.clear()
        result = await service.execute(service.confirm(plan))
        assert result.state is MutationState.NOT_FOUND and not adapter.writes


@pytest.mark.asyncio
async def test_cancellation_during_source_revalidation_is_known_unsent_and_retains_all_items(
    tmp_path,
):
    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        entered = asyncio.Event()

        async def require_source():
            entered.set()
            await asyncio.Event().wait()

        service.require_source = require_source
        task = asyncio.create_task(service.execute(service.confirm(plan)))
        await entered.wait()
        task.cancel()
        result = await task
        assert result.state is MutationState.CANCELLED
        assert [item.state for _, item in result.items] == [
            MutationState.CANCELLED,
            MutationState.BLOCKED,
        ]
        assert not adapter.writes


@pytest.mark.asyncio
async def test_concurrent_prepare_refused_while_batch_owns_a_request(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        adapter.stall = True
        task = asyncio.create_task(service.execute(service.confirm(plan)))
        await adapter.entered.wait()
        with pytest.raises(AppError, match="already active"):
            await service.prepare("delete")
        adapter.release.set()
        assert (await task).state is MutationState.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [MutationState.DENIED, MutationState.SUCCEEDED])
async def test_missing_or_failed_server_preview_never_constructs_conditional_write(tmp_path, state):
    async with service_fixture(tmp_path, existing=True) as (service, adapter, _, _):
        adapter.validation_state = state
        adapter.empty_preview = state is MutationState.SUCCEEDED
        plan = await service.prepare("apply")
        assert not plan.ready and plan.items[0].request is None
        assert not adapter.validations and not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("action,existing", [("apply", False), ("apply", True)])
async def test_validation_result_without_preview_bytes_is_refused(tmp_path, action, existing):
    async with service_fixture(tmp_path, existing=existing) as (service, adapter, _, _):
        adapter.no_validation_body = True
        plan = await service.prepare(action)
        assert not plan.ready
        with pytest.raises(AppError):
            service.confirm(plan)
        assert not adapter.writes


@pytest.mark.asyncio
@pytest.mark.parametrize("observation", ["absent", "replacement", "pending", "denied", "cancelled"])
async def test_delete_preserves_acceptance_and_distinguishes_observed_uid_disappearance(
    tmp_path, observation
):
    async with service_fixture(tmp_path, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("delete")
        assert plan.ready and plan.items[0].change == "delete"
        request = plan.items[0].request
        assert json.loads(request.body)["propagationPolicy"] == "Background"
        adapter.write_states = [MutationState.ACCEPTED]

        def observe():
            if observation == "absent":
                adapter.values.clear()
            elif observation == "replacement":
                adapter.values["0"]["metadata"]["uid"] = "replacement"
            elif observation == "denied":
                adapter.read_problem = HttpProblem(403)
            elif observation == "cancelled":
                adapter.read_problem = asyncio.CancelledError()

        adapter.after_write = observe
        result = await service.execute(service.confirm(plan))
        assert result.state is (
            MutationState.SUCCEEDED
            if observation in {"absent", "replacement"}
            else MutationState.PARTIAL
            if observation == "cancelled"
            else MutationState.ACCEPTED
        )
        assert len(adapter.writes) == 1
        assert (
            "Dependent cleanup" in result.items[0][1].message
            or "finalizers" in result.items[0][1].message
        )


@pytest.mark.asyncio
async def test_unexpected_adapter_failure_retains_uncertainty_and_labels_remaining_unsent(tmp_path):
    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        adapter.write_problem = RuntimeError("private-unsafe-error")
        result = await service.execute(service.confirm(plan))
        assert result.state is MutationState.UNCERTAIN and len(result.items) == 2
        assert result.items[1][1].state is MutationState.BLOCKED
        assert "private" not in repr(result) and len(adapter.writes) == 1


@pytest.mark.asyncio
async def test_consumed_helper_cancellation_cannot_resume_later_writes(tmp_path):
    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        entered = asyncio.Event()

        async def require_source():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return

        service.require_source = require_source
        task = asyncio.create_task(service.execute(service.confirm(plan)))
        await entered.wait()
        task.cancel()
        result = await task
        assert result.state is MutationState.CANCELLED and len(result.items) == 2
        assert not adapter.writes


@pytest.mark.asyncio
async def test_pre_entry_manager_cancel_retains_every_known_unsent_target_and_history(tmp_path):
    from kuberich.services.mutations import MutationManager

    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        manager = MutationManager()
        identity = manager.start(service, proof)
        result = await manager.cancel(identity)
        assert result.state is MutationState.CANCELLED
        assert tuple(target for target, _ in result.items) == plan.targets
        assert all(
            item.state is MutationState.CANCELLED and "Unsent" in item.message
            for _, item in result.items
        )
        assert manager.records[-1].targets == plan.targets and manager.records[-1].result == result
        assert not adapter.writes
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        await manager.close()


@pytest.mark.asyncio
async def test_manager_unexpected_failure_retains_all_targets_as_unknown_without_raw_exception(
    tmp_path,
):
    from kuberich.services.mutations import MutationManager

    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")

        async def broken(confirmation):
            raise RuntimeError("private-error-sentinel")

        service.execute = broken
        manager = MutationManager()
        identity = manager.start(service, service.confirm(plan))
        result = await manager.wait(identity)
        assert result.state is MutationState.UNCERTAIN
        assert tuple(target for target, _ in result.items) == plan.targets
        assert all(item.state is MutationState.UNCERTAIN for _, item in result.items)
        assert "private" not in repr(result) + repr(manager.records)
        assert not adapter.writes
        await manager.close()


@pytest.mark.asyncio
async def test_manager_forged_batch_confirmation_retains_known_unsent_rows(tmp_path):
    from kuberich.services.mutations import MutationManager

    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        manager = MutationManager()
        identity = manager.start(service, Confirmation(uuid4(), uuid4()))
        result = await manager.wait(identity)
        assert result.state is MutationState.BLOCKED
        assert tuple(target for target, _ in result.items) == plan.targets
        assert all(
            item.state is MutationState.BLOCKED and "Unsent" in item.message
            for _, item in result.items
        )
        assert not adapter.writes
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,problem,state",
    [
        ("apply", HttpProblem(403), MutationState.DENIED),
        ("delete", asyncio.CancelledError(), MutationState.CANCELLED),
    ],
)
async def test_noop_or_absent_rows_do_not_turn_a_before_write_stop_into_partial_batch(
    tmp_path, action, problem, state
):
    async with service_fixture(tmp_path, count=2, existing=action == "apply") as (
        service,
        adapter,
        _,
        _,
    ):
        adapter.preview_unchanged = True
        plan = await service.prepare(action)
        assert plan.ready and all(item.request is None for item in plan.items)

        def stop_second():
            if adapter.reads[-1].name == "1":
                raise problem

        adapter.on_read = stop_second
        result = await service.execute(service.confirm(plan))
        assert result.state is state and not adapter.writes
        assert result.items[0][1].state is MutationState.SUCCEEDED
        assert result.items[1][1].state is state


@pytest.mark.asyncio
async def test_accepted_delete_then_stop_is_partial_with_truthful_first_item_and_reason(tmp_path):
    async with service_fixture(tmp_path, count=2, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("delete")
        adapter.write_states = [MutationState.ACCEPTED]
        adapter.after_write = lambda: setattr(adapter, "read_problem", asyncio.CancelledError())
        result = await service.execute(service.confirm(plan))
        assert result.state is MutationState.PARTIAL and result.state.value == "Partial batch"
        assert [item.state for _, item in result.items] == [
            MutationState.ACCEPTED,
            MutationState.BLOCKED,
        ]
        assert "Stopped after accepted deletion" in result.message
        assert "Cancelled before write" not in result.message
        assert len(adapter.writes) == 1
