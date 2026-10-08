"""Actual HTTP PATCH: atomic conditions, single use, denied writes and uncertain effects."""

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.mutations import MutationState
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import Confirmation, MutationManager, MutationService
from tests.support.connections import catalog_fixture, certificate
from tests.support.mutations import mutation_api


@asynccontextmanager
async def source_fixture(tmp_path, *, timeout=2, tls=False, user=None, read_only=False):
    context, cluster = certificate(tmp_path) if tls else (None, None)
    async with mutation_api(tls=context) as (url, fixture):
        client = KubernetesSession(
            catalog_fixture(tmp_path, url, user, cluster).select("kuberich-test-one"), timeout
        )
        await client.open()
        current = [True]
        target = ResourceTarget(
            SessionIdentity("kuberich-test-one", 1),
            "",
            "configmaps",
            "team",
            "owned-one",
            fixture.value["metadata"]["uid"],
        )
        resource = ApiResource(
            "", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "patch"})
        )
        source = MutationService(
            client, resource, target, AccessPolicy(read_only), lambda: current[0]
        )
        try:
            yield source, fixture, current
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_real_tls_patch_captures_auth_impersonation_preserves_data_and_consumes_confirmation(
    tmp_path,
):
    user = {"token": "synthetic-token", "as": "synthetic-user", "as-groups": ["synthetic-group"]}
    async with source_fixture(tmp_path, tls=True, user=user) as (source, api, _):
        original = api.value["data"].copy()
        intent = await source.prepare_annotation("example.io/review", "private-new-value")
        proof = source.confirm(intent)
        assert (await source.execute(None)).state is MutationState.BLOCKED
        assert (
            await source.execute(Confirmation(intent.identity, uuid4()))
        ).state is MutationState.BLOCKED
        result = await source.execute(proof)
        assert result.state is MutationState.SUCCEEDED
        assert api.value["metadata"]["annotations"] == {
            "preserved": "private-existing",
            "example.io/review": "private-new-value",
        }
        assert api.value["data"] == original and len(api.requests) == 1
        headers = dict(api.requests[0][1])
        assert headers["Authorization"] == "Bearer synthetic-token"
        assert headers["Impersonate-User"] == "synthetic-user"
        assert headers["Impersonate-Group"] == "synthetic-group"
        assert headers["Content-Type"] == "application/json-patch+json"
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert len(api.requests) == 1 and "private-" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [
        (401, MutationState.AUTH_ERROR),
        (403, MutationState.DENIED),
        (404, MutationState.NOT_FOUND),
        (409, MutationState.CONFLICT),
        (400, MutationState.REJECTED),
        (413, MutationState.REJECTED),
        (422, MutationState.REJECTED),
        (429, MutationState.UNCERTAIN),
        (500, MutationState.UNCERTAIN),
        (302, MutationState.UNCERTAIN),
    ],
)
async def test_error_status_never_leaks_body_or_replays_write(tmp_path, status, state):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        api.patch_status = status
        result = await source.execute(source.confirm(intent))
        assert result.state is state and len(api.requests) == 1
        assert "private-error" not in result.message and "\x1b" not in result.message


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["uid", "resourceVersion"])
async def test_actual_server_race_rejects_entire_patch_atomically(tmp_path, field):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        api.before_patch = lambda value: value["metadata"].update(
            {field: "changed-before-server-test"}
        )
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.REJECTED and len(api.requests) == 1
        assert "key" not in api.value["metadata"]["annotations"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,state", [("uid", MutationState.STALE), ("resourceVersion", MutationState.CONFLICT)]
)
async def test_revalidation_refuses_changed_identity_or_version_before_send(tmp_path, field, state):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        proof = source.confirm(intent)
        api.value["metadata"][field] = "changed-after-confirmation"
        assert (await source.execute(proof)).state is state
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["drop", "bad-json", "oversized", "wrong-uid", "wrong-name", "no-version"]
)
async def test_applied_but_unconfirmed_result_is_uncertain_and_never_retried(tmp_path, mode):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        api.mode = mode
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.UNCERTAIN and len(api.requests) == 1
        assert api.value["metadata"]["annotations"]["key"] == "value"


@pytest.mark.asyncio
async def test_lost_response_timeout_is_uncertain_while_read_timeout_is_presend(tmp_path):
    async with source_fixture(tmp_path, timeout=0.1) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        api.mode = "stall"
        result = await source.execute(source.confirm(intent))
        assert result.state is MutationState.UNCERTAIN and len(api.requests) == 1
        api.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,state",
    [(403, MutationState.DENIED), (404, MutationState.NOT_FOUND), (500, MutationState.REJECTED)],
)
async def test_read_refusal_has_no_write_request(tmp_path, status, state):
    async with source_fixture(tmp_path) as (source, api, _):
        intent = await source.prepare_annotation("key", "value")
        proof = source.confirm(intent)
        api.read_status = status
        assert (await source.execute(proof)).state is state and not api.requests


@pytest.mark.asyncio
async def test_readonly_and_changed_context_block_every_service_entry(tmp_path):
    async with source_fixture(tmp_path, read_only=True) as (source, api, _):
        with pytest.raises(AppError, match="Read-only"):
            await source.prepare_annotation("key", "value")
        with pytest.raises(AppError, match="Read-only"):
            source.confirm(None)
        assert (await source.execute(None)).state is MutationState.BLOCKED and not api.requests
    async with source_fixture(tmp_path) as (source, api, current):
        intent = await source.prepare_annotation("key", "value")
        proof = source.confirm(intent)
        current[0] = False
        assert (await source.execute(proof)).state is MutationState.STALE and not api.requests


@pytest.mark.asyncio
async def test_owned_context_close_drains_pending_write_and_preserves_uncertain_public_record(
    tmp_path,
):
    async with source_fixture(tmp_path) as (source, api, _):
        manager = MutationManager()
        intent = await source.prepare_annotation("key", "private-write-value")
        api.mode = "stall"
        identity = manager.start(source, source.confirm(intent))
        await api.entered.wait()
        await manager.stop_for_client(source.client)
        result = await manager.wait(identity)
        assert result.state is MutationState.UNCERTAIN and len(api.requests) == 1
        assert "private-write" not in repr(manager.records)
        with pytest.raises(AppError, match="closing"):
            manager.start(source, source.confirm(intent))
        await manager.close()


@pytest.mark.asyncio
async def test_immediate_shutdown_and_repeated_start_consume_only_one_confirmation(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        manager = MutationManager()
        intent = await source.prepare_annotation("key", "value")
        proof = source.confirm(intent)
        first = manager.start(source, proof)
        second = manager.start(source, proof)
        assert (await manager.wait(first)).state is MutationState.SUCCEEDED
        assert (await manager.wait(second)).state is MutationState.BLOCKED
        assert len(api.requests) == 1
        intent = await source.prepare_annotation("key", "next")
        third = manager.start(source, source.confirm(intent))
        await manager.close()
        assert (await manager.wait(third)).state is MutationState.CANCELLED
