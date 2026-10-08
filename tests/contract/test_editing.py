"""Actual local HTTP validation/apply, version conflicts and private draft lifecycle."""

import asyncio
import json
import stat
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.mutations import MutationState
from kubetrol.domain.resources import ApiResource
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.editing import EditingService
from kubetrol.services.mutations import MutationManager
from tests.support.connections import catalog_fixture, certificate
from tests.support.editing import editing_api


@asynccontextmanager
async def source_fixture(tmp_path, *, read_only=False, tls=False, timeout=2):
    tls_context, cluster = certificate(tmp_path) if tls else (None, None)
    async with editing_api(tls=tls_context) as (url, api):
        client = KubernetesSession(
            catalog_fixture(
                tmp_path,
                url,
                {
                    "token": "synthetic-edit-token",
                    "as": "owned-edit-user",
                    "as-groups": ["owned-edit-group"],
                },
                cluster,
            ).select("kubetrol-test-one"),
            timeout,
        )
        await client.open()
        target = ResourceTarget(
            SessionIdentity("kubetrol-test-one", 1),
            "",
            "configmaps",
            "team",
            "owned-one",
            api.value["metadata"]["uid"],
        )
        resource = ApiResource(
            "", "v1", "configmaps", "ConfigMap", True, frozenset({"get", "patch"})
        )
        current = [True]
        source = EditingService(
            client, resource, target, AccessPolicy(read_only), lambda: current[0]
        )
        try:
            yield source, api, current
        finally:
            try:
                await source.close_file()
            finally:
                await client.close()


async def draft(source, value="new-private-content"):
    file = await source.open()
    data = json.loads(json.dumps(source.snapshot.manifest))
    data.pop("status", None)
    data["metadata"].pop("managedFields", None)
    data["data"]["owned-edit"] = value
    file.path.write_text(json.dumps(data))
    intent, preview = await source.prepare()
    return file, intent, preview


@pytest.mark.asyncio
async def test_real_tls_dryrun_then_exact_one_use_apply_with_preserved_payload(tmp_path):
    async with source_fixture(tmp_path, tls=True) as (source, api, _):
        original = json.loads(json.dumps(api.value))
        file, intent, preview = await draft(source)
        assert stat.S_IMODE(file.path.stat().st_mode) == 0o600
        assert stat.S_IMODE(file.path.parent.stat().st_mode) == 0o700
        assert "new-private-content" not in preview and "new-private-content" not in repr(intent)
        with pytest.raises(AppError, match="dry-run"):
            source.confirm(intent)
        result = await source.validate()
        assert result.state is MutationState.SUCCEEDED and api.value == original
        assert api.requests[0][3] == {"fieldValidation": "Strict", "dryRun": "All"}
        headers = dict(api.requests[0][1])
        assert headers["Authorization"] == "Bearer synthetic-edit-token"
        assert headers["Impersonate-User"] == "owned-edit-user"
        assert headers["Impersonate-Group"] == "owned-edit-group"
        proof = source.confirm(intent)
        manager = MutationManager()
        identity = manager.start(source, proof)
        assert (await manager.wait(identity)).state is MutationState.SUCCEEDED
        assert api.requests[1][3] == {"fieldValidation": "Strict"}
        assert api.requests[0][2] == api.requests[1][2]
        assert api.value["data"]["owned-edit"] == "new-private-content"
        assert api.value["metadata"]["annotations"] == original["metadata"]["annotations"]
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        assert "new-private-content" not in repr(manager.records)
        await manager.close()
        path = file.path
        await source.close_file()
        assert not path.parent.exists()


@pytest.mark.asyncio
async def test_noop_and_invalid_draft_cause_no_patch_or_confirmation(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        with pytest.raises(AppError):
            source.command({}, tmp_path)
        with pytest.raises(AppError):
            await source.prepare()
        assert (await source.validate()).state is MutationState.BLOCKED
        file = await source.open()
        assert await source.open() is file
        assert (await source.prepare())[0] is None and not api.requests
        command = source.command({"EDITOR": "vi -n"}, tmp_path)
        assert (
            command.argv == ("vi", "-n", "--", str(file.path)) and command.target == source.target
        )
        file.path.write_text("invalid: [sensitive")
        with pytest.raises(AppError) as error:
            await source.prepare()
        assert "sensitive" not in str(error.value) and source.intent is None and not api.requests
        file.path.unlink()
        file.path.symlink_to(tmp_path / "outside")
        with pytest.raises(AppError):
            await source.prepare()
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["validation", "apply", "uid", "scope"])
async def test_conflict_and_replacement_never_rebind_old_edits_to_new_snapshot(tmp_path, phase):
    async with source_fixture(tmp_path) as (source, api, current):
        _, intent, _ = await draft(source)
        if phase == "apply":
            assert (await source.validate()).state is MutationState.SUCCEEDED
            proof = source.confirm(intent)
        if phase == "uid":
            api.value["metadata"]["uid"] = "same-name-new-uid"
        elif phase == "scope":
            current[0] = False
        else:
            api.value["metadata"]["resourceVersion"] = "concurrent-99"
        if phase == "apply":
            assert (await source.execute(proof)).state is MutationState.CONFLICT
            assert len(api.requests) == 1
        else:
            result = await source.validate()
            assert result.state in {MutationState.CONFLICT, MutationState.STALE}
            assert not api.requests
        assert "owned-edit" not in api.value["data"]
        with pytest.raises(AppError):
            source.confirm(intent)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 500, 307])
async def test_server_validation_rejection_never_applies_or_exposes_status_body(tmp_path, status):
    async with source_fixture(tmp_path) as (source, api, _):
        _, intent, _ = await draft(source)
        api.validation_status = status
        result = await source.validate()
        assert result.state is not MutationState.SUCCEEDED
        assert result.state is not MutationState.UNCERTAIN
        assert "sensitive" not in result.message and "owned-edit" not in api.value["data"]
        assert len(api.requests) == 1 and api.requests[0][3]["dryRun"] == "All"
        with pytest.raises(AppError):
            source.confirm(intent)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["drop", "bad-json", "wrong-uid", "cancel", "timeout"])
async def test_interrupted_or_invalid_validation_does_not_persist(tmp_path, mode):
    async with source_fixture(tmp_path, timeout=0.15 if mode == "timeout" else 2) as (
        source,
        api,
        _,
    ):
        await draft(source)
        api.mode = "stall" if mode in {"cancel", "timeout"} else mode
        validation = asyncio.create_task(source.validate())
        await api.entered.wait()
        if mode == "cancel":
            validation.cancel()
        result = await validation
        assert result.state in {
            MutationState.CANCELLED,
            MutationState.TIMEOUT,
            MutationState.REJECTED,
        }
        assert source.validated is None and "owned-edit" not in api.value["data"]
        assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_readonly_secret_guard_revalidation_denial_and_new_draft_invalidate_proof(tmp_path):
    async with source_fixture(tmp_path, read_only=True) as (source, api, _):
        with pytest.raises(AppError, match="Read-only"):
            await source.open()
        assert source.file is None and not api.requests
    async with source_fixture(tmp_path) as (source, api, _):
        source.resource = replace(source.resource, kind="Secret")
        with pytest.raises(AppError, match="Secret"):
            await source.open()
        source.resource = replace(source.resource, kind="ConfigMap")
        _, intent, _ = await draft(source)
        api.read_status = 403
        assert (await source.validate()).state is MutationState.DENIED
        api.read_status = None
        assert (await source.validate()).state is MutationState.SUCCEEDED
        proof = source.confirm(intent)
        api.validation_status = 422
        await source.validate()
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        api.validation_status = None
        await source.prepare()
        with pytest.raises(AppError):
            source.confirm(intent)
        assert "owned-edit" not in api.value["data"]


@pytest.mark.asyncio
async def test_failed_or_cancelled_validation_read_cannot_authorize_apply(tmp_path):
    async with source_fixture(tmp_path, timeout=0.1) as (source, api, _):
        await draft(source)
        api.read_delay = 0.3
        assert (await source.validate()).state is MutationState.UNREACHABLE
        api.read_delay = 1
        validation = asyncio.create_task(source.validate())
        await asyncio.sleep(0.02)
        validation.cancel()
        assert (await validation).state is MutationState.CANCELLED
        assert source.validated is None and not api.requests
