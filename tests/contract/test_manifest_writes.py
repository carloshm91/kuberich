"""Actual HTTP manifest creates, conditional updates and dry-run receipts."""

import asyncio
import copy
import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.manifests import ManifestAdapter
from kuberich.domain.manifests import (
    ManifestScope,
    create_manifest_intent,
    manifest_documents,
    resolve_manifest,
)
from kuberich.domain.mutations import MutationState, annotation_intent
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from tests.support.connections import catalog_fixture

RESOURCE = ApiResource(
    "",
    "v1",
    "configmaps",
    "ConfigMap",
    True,
    frozenset({"get", "create", "patch", "delete", "watch"}),
)
SESSION = SessionIdentity("kuberich-test-one", 1)
SCOPE = ManifestScope(session=SESSION, namespace="team")
DOCUMENT = b'{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"owned-one"},"data":{"managed":"private-value"}}'


class ManifestApi:
    def __init__(self):
        self.value = None
        self.requests = []
        self.status = None
        self.write_status = None
        self.receipt_change = None
        self.mode = "normal"
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.read_entered = asyncio.Event()
        self.read_stall = False
        self.error_body = None
        self.status_receipt = False

    async def handle(self, request):
        if request.method == "GET":
            self.read_entered.set()
            if self.read_stall:
                await self.release.wait()
            if self.status is not None:
                return web.Response(status=self.status, text="private-error-value")
            return web.Response(status=404) if self.value is None else web.json_response(self.value)
        body = await request.json()
        self.requests.append(
            (request.method, request.path, dict(request.query), body, dict(request.headers))
        )
        status = self.write_status if self.write_status is not None else self.status
        if status is not None:
            if self.error_body is not None:
                return web.Response(status=status, body=self.error_body)
            return web.json_response(
                {"reason": "Forbidden", "message": "private-error-value"}, status=status
            )
        dry = request.query.get("dryRun") == "All"
        if request.method == "POST":
            if self.value is not None:
                return web.Response(status=409)
            value = copy.deepcopy(body)
            value["metadata"].update(uid="actual-server-uid", resourceVersion="1")
            if dry:
                value["metadata"].pop("resourceVersion")
            status = 201
        elif request.method == "PATCH":
            value = copy.deepcopy(self.value)
            for operation in body[:2]:
                key = operation["path"].split("/")[-1]
                if value["metadata"][key] != operation["value"]:
                    return web.Response(status=422)
            value["metadata"]["annotations"] = body[2]["value"]
            if not dry:
                value["metadata"]["resourceVersion"] = "2"
            status = 200
        else:
            assert request.method == "DELETE"
            if body["preconditions"] != {
                "uid": self.value["metadata"]["uid"],
                "resourceVersion": self.value["metadata"]["resourceVersion"],
            }:
                return web.Response(status=409)
            value = copy.deepcopy(self.value)
            status = 200
        if not dry:
            self.value = None if request.method == "DELETE" else copy.deepcopy(value)
        if self.receipt_change:
            self.receipt_change(value)
        self.entered.set()
        if self.mode == "stall":
            await self.release.wait()
        if self.mode == "drop":
            request.transport.abort()
            return web.Response()
        if self.mode == "bad-json":
            return web.Response(text="private-invalid-json")
        if self.mode == "oversized":
            return web.Response(body=b"x" * (8 * 1024 * 1024 + 1))
        if self.status_receipt and request.method == "DELETE":
            value = {
                "apiVersion": "v1",
                "kind": "Status",
                "status": "Success",
                "details": {"uid": value["metadata"]["uid"], "name": value["metadata"]["name"]},
            }
        return web.json_response(value, status=status)


@asynccontextmanager
async def adapter_fixture(tmp_path, *, read_only=False, timeout=2):
    fixture = ManifestApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    client = KubernetesSession(catalog_fixture(tmp_path, url).select(SESSION.context), timeout)
    await client.open()
    adapter = ManifestAdapter(client, AccessPolicy(read_only), {}, tmp_path)
    try:
        yield adapter, fixture
    finally:
        fixture.release.set()
        await adapter.close()
        await client.close()
        await runner.cleanup()


def create_intent():
    resource, address, body = resolve_manifest(
        manifest_documents(DOCUMENT, source_path="source.yaml")[0], Discovery((RESOURCE,)), SCOPE
    )
    return create_manifest_intent(resource, address, body)


@pytest.mark.asyncio
async def test_named_create_strict_dry_run_uses_exact_reviewed_post_and_real_uid(tmp_path):
    intent = create_intent()
    async with adapter_fixture(tmp_path) as (adapter, api):
        assert await adapter.read(RESOURCE, intent.target, lambda: None) is None
        validation = await adapter.validate(intent, lambda: None)
        assert validation.result.state is MutationState.SUCCEEDED and validation.body
        assert api.value is None
        assert (await adapter.execute(intent, lambda: None)).state is MutationState.SUCCEEDED
        assert api.value["metadata"]["uid"] == "actual-server-uid"
        assert len(api.requests) == 2
        assert api.requests[0][2] == {"dryRun": "All", "fieldValidation": "Strict"}
        assert api.requests[1][2] == {"fieldValidation": "Strict"}
        assert api.requests[0][3] == api.requests[1][3] == json.loads(intent.body)
        assert "uid" not in api.requests[1][3]["metadata"]
        assert "resourceVersion" not in api.requests[1][3]["metadata"]
        assert "last-applied-configuration" in next(iter(api.value["metadata"]["annotations"]))
        assert api.requests[1][4]["Authorization"] == "Bearer synthetic"
        assert "private-value" not in repr(validation)
        assert (await adapter.execute(intent, lambda: None)).state is MutationState.CONFLICT
        assert len(api.requests) == 3


@pytest.mark.asyncio
async def test_existing_conditional_patch_strict_preview_does_not_persist_then_exact_apply(
    tmp_path,
):
    intent = create_intent()
    async with adapter_fixture(tmp_path) as (adapter, api):
        await adapter.execute(intent, lambda: None)
        record = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", record.uid)
        patch = annotation_intent(RESOURCE, target, record, "example.io/review", "private-new")
        validation = await adapter.validate(patch, lambda: None)
        assert validation.result.state is MutationState.SUCCEEDED
        assert api.value["metadata"]["resourceVersion"] == "1"
        assert "example.io/review" not in api.value["metadata"]["annotations"]
        assert (await adapter.execute(patch, lambda: None)).state is MutationState.SUCCEEDED
        assert api.value["metadata"]["resourceVersion"] == "2"
        assert api.value["metadata"]["annotations"]["example.io/review"] == "private-new"
        assert api.requests[1][3] == api.requests[2][3] == json.loads(patch.body)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 422, 500])
async def test_dry_run_failure_never_persists_or_exposes_freeform_messages(tmp_path, status):
    async with adapter_fixture(tmp_path) as (adapter, api):
        api.status = status
        validation = await adapter.validate(create_intent(), lambda: None)
        assert validation.result.state is not MutationState.SUCCEEDED
        assert validation.body is None and api.value is None
        assert "private-error-value" not in repr(validation)
        assert len(api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "Secret"),
        ("apiVersion", "other/v1"),
        ("metadata.name", "other-name"),
        ("metadata.namespace", "other-team"),
        ("metadata.uid", ""),
        ("metadata.resourceVersion", ""),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
async def test_create_receipt_must_match_exact_reviewed_identity(tmp_path, field, value, dry_run):
    async with adapter_fixture(tmp_path) as (adapter, api):

        def corrupt(body):
            if field.startswith("metadata."):
                body["metadata"][field.split(".")[1]] = value
            else:
                body[field] = value

        api.receipt_change = corrupt
        intent = create_intent()
        result = (
            (await adapter.validate(intent, lambda: None)).result
            if dry_run
            else await adapter.execute(intent, lambda: None)
        )
        transient_identity = dry_run and field in {"metadata.uid", "metadata.resourceVersion"}
        assert result.state is (
            MutationState.SUCCEEDED
            if transient_identity
            else MutationState.REJECTED
            if dry_run
            else MutationState.UNCERTAIN
        )
        assert "private" not in result.message and len(api.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 500])
async def test_only_genuine_not_found_can_establish_absence(tmp_path, status):
    from kuberich.domain.connections import HttpProblem

    async with adapter_fixture(tmp_path) as (adapter, api):
        api.status = status
        with pytest.raises(HttpProblem) as failure:
            await adapter.read(RESOURCE, create_intent().target, lambda: None)
        assert failure.value.status == status and not api.requests


@pytest.mark.asyncio
async def test_read_only_prevents_preparation_and_write_before_any_http(tmp_path):
    from kuberich.errors import AppError

    async with adapter_fixture(tmp_path, read_only=True) as (adapter, api):
        intent = create_intent()
        with pytest.raises(AppError, match="Read-only"):
            await adapter.read(RESOURCE, intent.target, lambda: None)
        with pytest.raises(AppError, match="Read-only"):
            await adapter.validate(intent, lambda: None)
        with pytest.raises(AppError, match="Read-only"):
            await adapter.execute(intent, lambda: None)
        assert not api.requests


async def delete_intent_fixture(adapter, api):
    from kuberich.domain.operations import DeleteOptions, delete_intent

    create = create_intent()
    assert (await adapter.execute(create, lambda: None)).state is MutationState.SUCCEEDED
    record = await adapter.read(RESOURCE, create.target, lambda: None)
    target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", record.uid)
    return delete_intent(RESOURCE, target, record, DeleteOptions(propagation="Background"))


@pytest.mark.asyncio
@pytest.mark.parametrize("status_receipt", [False, True])
async def test_delete_strict_preview_and_preconditioned_exact_request_do_not_observe_dry_run(
    tmp_path, status_receipt
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = await delete_intent_fixture(adapter, api)
        api.status_receipt = status_receipt
        preview = await adapter.validate(intent, lambda: None)
        assert preview.result.state is MutationState.SUCCEEDED and preview.body
        assert api.value is not None
        outcome = await adapter.execute(intent, lambda: None)
        assert outcome.state is MutationState.ACCEPTED and api.value is None
        assert api.requests[1][3] == api.requests[2][3] == json.loads(intent.body)
        assert api.requests[1][2] == {"fieldValidation": "Strict", "dryRun": "All"}
        assert api.requests[2][3]["preconditions"] == {
            "uid": "actual-server-uid",
            "resourceVersion": "1",
        }
        assert api.requests[2][3]["propagationPolicy"] == "Background"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "Secret"),
        ("apiVersion", "bad/v1"),
        ("namespace", "other-team"),
        ("uid", "replacement-uid"),
        ("resourceVersion", "changed"),
    ],
)
@pytest.mark.parametrize("dry_run", [False, True])
async def test_delete_resource_receipt_requires_exact_gvk_namespace_uid_and_preview_version(
    tmp_path, field, value, dry_run
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = await delete_intent_fixture(adapter, api)

        def corrupt(body):
            if field in {"kind", "apiVersion"}:
                body[field] = value
            else:
                body["metadata"][field] = value

        api.receipt_change = corrupt
        result = (
            (await adapter.validate(intent, lambda: None)).result
            if dry_run
            else await adapter.execute(intent, lambda: None)
        )
        if field == "resourceVersion" and not dry_run:
            assert result.state is MutationState.ACCEPTED
        else:
            assert result.state is (MutationState.REJECTED if dry_run else MutationState.UNCERTAIN)
        assert len(api.requests) == 2


@pytest.mark.asyncio
async def test_delete_atomic_preconditions_reject_replacement_that_appears_after_review(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = await delete_intent_fixture(adapter, api)
        api.value["metadata"]["uid"] = "replacement-uid"
        assert (await adapter.execute(intent, lambda: None)).state is MutationState.CONFLICT
        assert api.value["metadata"]["uid"] == "replacement-uid"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["drop", "bad-json", "oversized"])
async def test_applied_create_with_lost_or_invalid_receipt_is_uncertain_and_never_replayed(
    tmp_path, mode
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        api.mode = mode
        result = await adapter.execute(create_intent(), lambda: None)
        assert result.state is MutationState.UNCERTAIN
        assert api.value is not None and len(api.requests) == 1
        assert "private" not in result.message


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [False, True])
async def test_request_cancellation_drains_then_distinguishes_uncertain_write_from_nonpersisting_validation(
    tmp_path, dry_run
):
    async with adapter_fixture(tmp_path) as (adapter, api):
        api.mode = "stall"
        operation = (
            adapter.validate(create_intent(), lambda: None)
            if dry_run
            else adapter.execute(create_intent(), lambda: None)
        )
        task = asyncio.create_task(operation)
        await api.entered.wait()
        task.cancel()
        task.cancel()
        result = await task
        result = result.result if dry_run else result
        assert result.state is (MutationState.CANCELLED if dry_run else MutationState.UNCERTAIN)
        assert (api.value is None) is dry_run and len(api.requests) == 1


@pytest.mark.asyncio
async def test_adapter_close_drains_active_write_and_is_idempotent_under_repeated_cancellation(
    tmp_path,
):
    from kuberich.errors import AppError

    async with adapter_fixture(tmp_path) as (adapter, api):
        api.mode = "stall"
        task = asyncio.create_task(adapter.execute(create_intent(), lambda: None))
        await api.entered.wait()
        closing = asyncio.create_task(adapter.close())
        await asyncio.sleep(0)
        closing.cancel()
        await closing
        assert (await task).state is MutationState.UNCERTAIN
        await adapter.close()
        with pytest.raises(AppError, match="closed"):
            await adapter.execute(create_intent(), lambda: None)


@pytest.mark.asyncio
async def test_read_cancellation_is_drained_without_turning_absence_into_create(tmp_path):
    async with adapter_fixture(tmp_path) as (adapter, api):
        api.read_stall = True
        task = asyncio.create_task(adapter.read(RESOURCE, create_intent().target, lambda: None))
        await api.read_entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        b"private-malformed-json",
        b"x" * 65537,
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Status",
                "reason": "Forbidden",
                "message": "private-value",
                "details": {
                    "causes": [
                        {
                            "reason": "FieldValueInvalid",
                            "field": "spec.replicas",
                            "message": "private-value",
                        }
                    ]
                },
            }
        ).encode(),
    ],
)
async def test_bounded_error_receipts_never_expose_raw_body(tmp_path, body):
    async with adapter_fixture(tmp_path) as (adapter, api):
        api.status = 422
        api.error_body = body
        result = await adapter.validate(create_intent(), lambda: None)
        assert result.result.state is MutationState.REJECTED and result.body is None
        assert "private" not in repr(result) and len(api.requests) == 1
        if b"spec.replicas" in body:
            assert (
                "FieldValueInvalid" in result.result.message
                and "spec.replicas" in result.result.message
            )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes", [{"group": "apps"}, {"resource": "secrets"}, {"namespace": None}]
)
async def test_adapter_read_rejects_wrong_discovered_address_before_http(tmp_path, changes):
    from dataclasses import replace

    from kuberich.errors import AppError

    async with adapter_fixture(tmp_path) as (adapter, api):
        address = replace(create_intent().target, **changes)
        with pytest.raises(AppError, match="exact readable"):
            await adapter.read(RESOURCE, address, lambda: None)
        assert not api.read_entered.is_set() and not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["uid", "resourceVersion"])
async def test_manifest_reads_require_persistent_identity_even_for_nonwatch_discovery(
    tmp_path, missing
):
    from dataclasses import replace

    from kuberich.errors import AppError

    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        api.value["metadata"].pop(missing)
        resource = replace(RESOURCE, verbs=RESOURCE.verbs - {"watch"})
        with pytest.raises(AppError, match="persistent identity/version"):
            await adapter.read(resource, intent.target, lambda: None)


@pytest.mark.asyncio
async def test_non_manifest_job_trigger_intent_cannot_enter_manifest_write_port(tmp_path):
    from uuid import uuid4

    from kuberich.domain.operations import trigger_intent
    from kuberich.domain.resources import resource_record
    from kuberich.errors import AppError
    from tests.support.operations import selection

    resource, target, value = selection("cj")
    intent = trigger_intent(
        resource, target, resource_record(resource, value, target.namespace), uuid4()
    )
    async with adapter_fixture(tmp_path) as (adapter, api):
        with pytest.raises(AppError, match="only explicit deletion"):
            await adapter.execute(intent, lambda: None)
        assert not api.requests


@pytest.mark.asyncio
async def test_owner_close_rejects_late_credential_refresh_even_when_helper_suppresses_cancellation(
    tmp_path, monkeypatch
):
    entered = asyncio.Event()

    async def refresh():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return

    async with adapter_fixture(tmp_path) as (adapter, api):
        monkeypatch.setattr(adapter.client, "refresh_credentials", refresh)
        task = asyncio.create_task(adapter.execute(create_intent(), lambda: None))
        await entered.wait()
        await adapter.close()
        assert (await task).state is MutationState.REJECTED
        assert not api.requests and api.value is None


@asynccontextmanager
async def live_service_fixture(tmp_path):
    from uuid import uuid4

    from kuberich.domain.exports import DirectoryRef
    from kuberich.domain.manifests import FrozenManifestSource
    from kuberich.services.manifests import ManifestMutationService

    async with adapter_fixture(tmp_path) as (adapter, api):
        source = FrozenManifestSource(
            identity=uuid4(),
            root=DirectoryRef(path=tmp_path, device=1, inode=1),
            kind="file",
            relative_path="fixture.yaml",
            files=(),
            documents=manifest_documents(DOCUMENT, source_path="fixture.yaml"),
            source_sha256="source-digest",
            rendered_sha256="rendered-digest",
        )

        async def require_source():
            return None

        service = ManifestMutationService(
            adapter.client,
            SCOPE,
            Discovery((RESOURCE,)),
            adapter.policy,
            source,
            lambda: True,
            require_source,
            {},
            tmp_path,
            adapter=adapter,
        )
        try:
            yield service, api
        finally:
            await service.close()


@pytest.mark.asyncio
async def test_real_service_named_create_and_fresh_uid_delete_round_trip_through_manager(tmp_path):
    from kuberich.domain.targets import ResourceAddress
    from kuberich.services.mutations import MutationManager

    async with live_service_fixture(tmp_path) as (service, api):
        manager = MutationManager()
        plan = await service.prepare("apply")
        assert plan.ready and plan.items[0].change == "create"
        assert (
            isinstance(plan.items[0].target, ResourceAddress) and plan.items[0].target.uid is None
        )
        assert api.value is None and len(api.requests) == 1
        proof = service.confirm(plan)
        identity = manager.start(service, proof)
        result = await manager.wait(identity)
        assert result.state is MutationState.SUCCEEDED and len(result.items) == 1
        assert "actual-server-uid" in result.items[0][1].message
        assert api.value is not None and len(api.requests) == 2
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        delete = await service.prepare("delete")
        assert delete.ready and delete.items[0].target.uid == "actual-server-uid"
        assert delete.items[0].request.resource_version == "1"
        identity = manager.start(service, service.confirm(delete))
        result = await manager.wait(identity)
        assert result.state is MutationState.SUCCEEDED and api.value is None
        assert [request[0] for request in api.requests] == ["POST", "POST", "DELETE", "DELETE"]
        assert "private" not in repr(manager.records)
        await manager.close()


@pytest.mark.asyncio
async def test_real_service_refused_dry_run_cannot_be_confirmed_or_persisted(tmp_path):
    from kuberich.errors import AppError

    async with live_service_fixture(tmp_path) as (service, api):
        api.write_status = 403
        plan = await service.prepare("apply")
        assert not plan.ready and api.value is None
        assert plan.items[0].validation.state is MutationState.DENIED
        with pytest.raises(AppError):
            service.confirm(plan)
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_real_service_owner_cancellation_retains_uncertain_http_write_in_history(tmp_path):
    from kuberich.services.mutations import MutationManager

    async with live_service_fixture(tmp_path) as (service, api):
        manager = MutationManager()
        plan = await service.prepare("apply")
        api.entered.clear()
        api.mode = "stall"
        identity = manager.start(service, service.confirm(plan))
        await api.entered.wait()
        result = await manager.cancel(identity)
        assert result.state is MutationState.UNCERTAIN and len(result.items) == 1
        assert result.items[0][1].state is MutationState.UNCERTAIN
        assert service.operation_count == 0 and manager.active_count == 0
        assert manager.records[-1].result == result and api.value is not None
        await manager.close()
