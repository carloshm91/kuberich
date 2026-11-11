"""Create-only admission reuses the owned real HTTP manifest transport."""

import asyncio
import json
import threading
from dataclasses import replace
from uuid import uuid4

import pytest

from kuberich.domain.manifests import (
    LAST_APPLIED,
    FrozenDraftSource,
    canonical_manifest,
    create_manifest_intent,
    manifest_documents,
)
from kuberich.domain.mutations import MutationState
from kuberich.errors import AppError
from tests.contract.test_manifest_writes import (
    adapter_fixture,
    create_intent,
    live_service_fixture,
)
from tests.support.workspace import wait_for


@pytest.mark.asyncio
async def test_create_only_strict_preview_and_persistent_receipt_keep_exact_submitted_bytes(
    tmp_path,
):
    original = create_intent()
    value = json.loads(original.body)
    value["metadata"]["annotations"] = {LAST_APPLIED: "private-old-value", "example.io/a": "b"}
    value["data"] = None
    intent = create_manifest_intent(
        original.resource, original.target, canonical_manifest(value), policy="create-only"
    )
    assert LAST_APPLIED not in json.loads(intent.body)["metadata"]["annotations"]
    assert json.loads(intent.body)["data"] is None
    async with adapter_fixture(tmp_path) as (adapter, api):
        preview = await adapter.validate(intent, lambda: None)
        assert preview.result.state is MutationState.SUCCEEDED and preview.created is None
        assert api.value is None
        response = await adapter.execute_creation(intent, lambda: None)
        assert response.result.state is MutationState.SUCCEEDED
        assert response.receipt.target.uid == api.value["metadata"]["uid"] == "actual-server-uid"
        assert response.receipt.resource_version == api.value["metadata"]["resourceVersion"] == "1"
        assert response.receipt.resource is intent.resource
        assert response.preview_pages and "actual-server-uid" in "".join(response.preview_pages)
        assert api.requests[0][3] == api.requests[1][3] == json.loads(intent.body)


@pytest.mark.asyncio
async def test_create_review_never_becomes_apply_and_approval_cannot_be_replayed(tmp_path):
    async with live_service_fixture(tmp_path) as (service, api):
        plan = await service.prepare("create")
        assert plan.ready and plan.items[0].request.policy == "create-only"
        assert not service.created_receipts and api.value is None
        proof = service.confirm(plan)
        result = await service.execute(proof)
        assert result.state is MutationState.SUCCEEDED
        assert service.created_receipts[0].target.uid == "actual-server-uid"
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        count = len(api.requests)
        conflict = await service.prepare("create")
        assert not conflict.ready and conflict.items[0].request is None
        assert conflict.items[0].validation.state is MutationState.CONFLICT
        assert "Apply/Edit" in conflict.items[0].validation.message
        with pytest.raises(AppError, match="fully validated"):
            service.confirm(conflict)
        assert len(api.requests) == count


@pytest.mark.asyncio
async def test_create_after_review_collision_refuses_before_post(tmp_path):
    async with live_service_fixture(tmp_path) as (service, api):
        plan = await service.prepare("create")
        await service.adapter.execute(create_intent(), lambda: None)
        count = len(api.requests)
        result = await service.execute(service.confirm(plan))
        assert result.state is MutationState.CONFLICT
        assert not service.created_receipts and len(api.requests) == count


@pytest.mark.asyncio
async def test_create_only_receipt_is_absent_after_committed_but_unreadable_response(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        original = create_intent()
        intent = create_manifest_intent(
            original.resource, original.target, original.body, policy="create-only"
        )
        api.mode = "bad-json"
        response = await adapter.execute_creation(intent, lambda: None)
        assert response.result.state is MutationState.UNCERTAIN and response.receipt is None
        assert api.value is not None and len(api.requests) == 1


@pytest.mark.asyncio
async def test_create_only_transport_refuses_apply_policy_without_http(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        with pytest.raises(AppError, match="create-only"):
            await adapter.execute_creation(create_intent(), lambda: None)
        assert not api.requests


@pytest.mark.asyncio
async def test_forged_create_only_body_cannot_bypass_literal_input_policy_at_transport(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        original = create_intent()
        forged = replace(original, policy="create-only")
        with pytest.raises(AppError, match="canonical reviewed"):
            await adapter.execute_creation(forged, lambda: None)
        assert not api.requests


@pytest.mark.asyncio
async def test_readonly_after_create_review_blocks_confirmation_and_execution(tmp_path):
    async with live_service_fixture(tmp_path) as (service, api):
        plan = await service.prepare("create")
        proof = service.confirm(plan)
        service.policy.tighten()
        with pytest.raises(AppError, match="Read-only"):
            service.confirm(plan)
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        assert api.value is None and len(api.requests) == 1


@pytest.mark.asyncio
async def test_cancelled_create_retains_uncertainty_without_persistent_receipt_or_replay(tmp_path):
    async with live_service_fixture(tmp_path) as (service, api):
        plan = await service.prepare("create")
        proof = service.confirm(plan)
        api.entered.clear()
        api.mode = "stall"
        task = asyncio.create_task(service.execute(proof))
        await api.entered.wait()
        task.cancel()
        result = await task
        assert result.state is MutationState.UNCERTAIN
        assert api.value is not None and not service.created_receipts
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_cancellation_during_verified_201_decode_preserves_known_receipt_and_uncertainty(
    tmp_path, monkeypatch
):
    from kuberich.domain.resources import resource_record

    entered, release = threading.Event(), threading.Event()

    def decode(resource, value, namespace):
        record = resource_record(resource, value, namespace)
        entered.set()
        assert release.wait(10)
        return record

    async with live_service_fixture(tmp_path) as (service, api):
        plan = await service.prepare("create")
        monkeypatch.setattr("kuberich.adapters.manifests.resource_record", decode)
        proof = service.confirm(plan)
        task = asyncio.create_task(service.execute(proof))
        try:
            await wait_for(entered.is_set)
            task.cancel()
            release.set()
            result = await task
            assert result.state is MutationState.UNCERTAIN
            assert service.created_receipts[0].target.uid == api.value["metadata"]["uid"]
            assert service.created_receipts[0].resource_version == "1"
            assert (await service.execute(proof)).state is MutationState.BLOCKED
            assert len(api.requests) == 2
        finally:
            release.set()


@pytest.mark.asyncio
async def test_private_template_server_copies_never_enter_submitted_or_default_review(tmp_path):
    from kuberich.services.manifests import ManifestMutationService

    async with live_service_fixture(tmp_path) as (existing, api):
        body = canonical_manifest(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "owned-one"},
                "data": {"private-key-sentinel": "private-value-sentinel"},
                "spec": {"literal": "private-arbitrary-sentinel"},
            }
        )
        source = FrozenDraftSource(
            identity=uuid4(),
            kind="template",
            title="Owned private template",
            generation=1,
            documents=manifest_documents(body, source_path="owned private template"),
            source_sha256="private-source-digest",
            rendered_sha256="private-rendered-digest",
            body=body,
            private_preview=True,
        )

        async def current():
            return None

        service = ManifestMutationService(
            existing.client,
            existing.scope,
            existing.discovery,
            existing.policy,
            source,
            lambda: True,
            current,
            {},
            tmp_path,
            adapter=existing.adapter,
        )

        def copy_to_other_parent(value):
            value["metadata"].setdefault("annotations", {})["example.io/copied"] = (
                "private-arbitrary-sentinel"
            )

        api.receipt_change = copy_to_other_parent
        try:
            plan = await service.prepare("create")
            assert plan.ready and api.value is None
            assert "Content withheld" in "".join(plan.items[0].preview_pages)
            assert "private-" not in repr(plan)
            result = await service.execute(service.confirm(plan))
            assert result.state is MutationState.SUCCEEDED
            assert "private-" not in repr(result)
            assert service.created_previews[0][0] is service.created_receipts[0]
            assert "Content withheld" in "".join(service.created_previews[0][1])
            assert "private-" not in repr(service.created_previews)
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_create_service_refuses_success_without_persistent_receipt_and_stops_later_items(
    tmp_path,
):
    from kuberich.adapters.manifests import ManifestCreationResult
    from kuberich.domain.mutations import MutationResult
    from tests.contract.test_manifest_service import service_fixture

    async with service_fixture(tmp_path, count=2) as (service, adapter, _, _):
        calls = []

        async def missing_receipt(intent, guard, *, private_preview=False):
            guard()
            calls.append(intent)
            return ManifestCreationResult(
                MutationResult(MutationState.SUCCEEDED, "Missing receipt")
            )

        adapter.execute_creation = missing_receipt
        plan = await service.prepare("create")
        result = await service.execute(service.confirm(plan))
        assert result.state is MutationState.UNCERTAIN
        assert [item.state for _, item in result.items] == [
            MutationState.UNCERTAIN,
            MutationState.BLOCKED,
        ]
        assert len(calls) == 1 and not service.created_receipts


@pytest.mark.asyncio
async def test_known_cancelled_201_metadata_survives_in_safe_session_history(tmp_path, monkeypatch):
    from kuberich.domain.resources import resource_record
    from kuberich.services.mutations import MutationManager

    entered, release = threading.Event(), threading.Event()

    def decode(resource, value, namespace):
        record = resource_record(resource, value, namespace)
        entered.set()
        assert release.wait(10)
        return record

    async with live_service_fixture(tmp_path) as (service, api):
        manager = MutationManager()
        plan = await service.prepare("create")
        owners = []
        initial_current = service.current

        def current():
            owners.append(asyncio.current_task())
            return initial_current()

        service.current = current
        monkeypatch.setattr("kuberich.adapters.manifests.resource_record", decode)
        operation = manager.start(service, service.confirm(plan))
        try:
            await wait_for(entered.is_set)
            decoder_owner = owners[-1]
            stopping = asyncio.create_task(manager.cancel(operation))
            await wait_for(lambda: decoder_owner.cancelling() > 0)
            release.set()
            result = await stopping
            assert result.state is MutationState.UNCERTAIN
            assert service.created_receipts[0].target.uid == api.value["metadata"]["uid"]
            history = repr(manager.records)
            assert "actual-server-uid" in history and "resourceVersion 1" in history
            assert "private-value" not in history
        finally:
            release.set()
            await manager.close()
