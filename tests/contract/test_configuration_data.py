"""Actual HTTP reads, UID/version checks, cancellation and guarded Secret writes."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.configuration_data import configuration_value
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.mutations import MutationState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.configuration_data import ConfigurationService
from kuberich.services.editing import EditingService
from tests.support.configuration_data import TEXT, data_api
from tests.support.connections import catalog_fixture
from tests.unit.test_configuration_data import resource


@asynccontextmanager
async def data_source(tmp_path, kind="Secret", read_only=True):
    async with data_api(kind) as (url, api):
        client = KubernetesSession(catalog_fixture(tmp_path, url).select("kuberich-test-one"), 2)
        await client.open()
        target = ResourceTarget(
            SessionIdentity("kuberich-test-one", 1),
            "",
            api.resource,
            "team",
            "owned-one",
            "owned-data-uid",
        )
        current = [True]
        service = ConfigurationService(
            client, resource(kind), target, AccessPolicy(read_only), lambda: current[0]
        )
        try:
            yield service, api, current
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["Secret", "ConfigMap"])
async def test_each_disclosure_is_a_fresh_get_and_old_versions_never_rebind(tmp_path, kind):
    async with data_source(tmp_path, kind) as (source, api, _):
        index = await source.index()
        assert TEXT not in repr(index) and len(index.keys) == 2
        assert await source.value(("data", "chosen"), index.resource_version, encoded=False) == TEXT
        assert len(api.requests) == 2 and all(x[0] == "GET" for x in api.requests)
        api.value["metadata"]["resourceVersion"] = "changed"
        with pytest.raises(AppError, match="changed"):
            await source.value(("data", "chosen"), index.resource_version, encoded=False)
        assert len(api.requests) == 3
        refreshed = await source.index()
        assert (
            await source.value(("data", "chosen"), refreshed.resource_version, encoded=True)
            == base64.b64encode(TEXT.encode()).decode()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "context",
        "group",
        "resource",
        "kind",
        "cluster_scope",
        "namespace",
        "target_group",
        "target_resource",
        "verbs",
    ],
)
async def test_unsupported_or_stale_targets_fail_before_any_request(tmp_path, change):
    async with data_source(tmp_path) as (source, api, current):
        if change == "scope":
            current[0] = False
        elif change == "context":
            source.target = replace(source.target, session=SessionIdentity("other", 1))
        elif change == "namespace":
            source.target = replace(source.target, namespace=None)
        elif change == "target_group":
            source.target = replace(source.target, group="other")
        elif change == "target_resource":
            source.target = replace(source.target, resource="configmaps")
        else:
            kwargs = {
                "group": {"group": "other"},
                "resource": {"name": "pods"},
                "kind": {"kind": "ConfigMap"},
                "cluster_scope": {"namespaced": False},
                "verbs": {"verbs": frozenset()},
            }[change]
            source.resource = replace(source.resource, **kwargs)
        with pytest.raises(AppError):
            await source.index()
        assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500])
async def test_api_errors_do_not_include_payload_or_reveal_values(tmp_path, status):
    async with data_source(tmp_path) as (source, api, _):
        api.read_status = status
        with pytest.raises(ConnectionProblem) as error:
            await source.index()
        assert "owned-private-server-value" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "scope", "name", "namespace"])
async def test_held_read_cannot_publish_after_identity_or_scope_changes(tmp_path, change):
    async with data_source(tmp_path) as (source, api, current):
        api.hold = True
        task = asyncio.create_task(source.index())
        await asyncio.wait_for(api.started.wait(), 5)
        if change == "scope":
            current[0] = False
        else:
            api.value["metadata"][change] = "recreated"
        api.release.set()
        with pytest.raises((AppError, ConnectionProblem)):
            await task


@pytest.mark.asyncio
async def test_cancelled_disclosure_never_returns_a_value(tmp_path):
    async with data_source(tmp_path) as (source, api, _):
        index = await source.index()
        api.started.clear()
        api.hold = True
        task = asyncio.create_task(
            source.value(("data", "chosen"), index.resource_version, encoded=False)
        )
        await asyncio.wait_for(api.started.wait(), 5)
        task.cancel()
        api.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_secret_editor_uses_private_draft_redacted_review_dryrun_and_conditional_apply(
    tmp_path,
):
    async with data_source(tmp_path, read_only=False) as (source, api, _):
        editor = EditingService(
            source.client, source.resource, source.target, source.policy, source.current
        )
        original = json.loads(json.dumps(api.value))
        try:
            draft = await editor.open()
            assert draft.path.stat().st_mode & 0o777 == 0o600
            edited = json.loads(json.dumps(editor.snapshot.manifest))
            edited["data"]["chosen"] = base64.b64encode(b"owned-new-secret").decode()
            draft.path.write_text(json.dumps(edited))
            intent, preview = await editor.prepare()
            assert "owned-new-secret" not in preview and edited["data"]["chosen"] not in preview
            assert "owned-new-secret" not in repr(intent)
            with pytest.raises(AppError, match="dry-run"):
                editor.confirm(intent)
            assert (await editor.validate()).state is MutationState.SUCCEEDED
            assert api.value == original
            confirmation = editor.confirm(intent)
            assert (await editor.execute(confirmation)).state is MutationState.SUCCEEDED
            assert configuration_value(editor.snapshot, ("data", "chosen"), encoded=False) == TEXT
            assert base64.b64decode(api.value["data"]["chosen"]) == b"owned-new-secret"
            writes = [x for x in api.requests if x[0] == "PATCH"]
            assert writes[0][2]["dryRun"] == "All" and "dryRun" not in writes[1][2]
            assert (await editor.execute(confirmation)).state is MutationState.BLOCKED
        finally:
            path = editor.file.path if editor.file else None
            await editor.close_file()
            assert path is None or not path.exists()


@pytest.mark.asyncio
async def test_secret_edit_remains_blocked_by_readonly_policy(tmp_path):
    async with data_source(tmp_path) as (source, api, _):
        editor = EditingService(
            source.client, source.resource, source.target, source.policy, source.current
        )
        with pytest.raises(AppError, match="Read-only"):
            await editor.open()
        assert not api.requests and editor.file is None
