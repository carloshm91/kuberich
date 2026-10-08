"""Owned HTTP/TLS scale/history contracts, exact confirmation and monitoring cancellation."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.domain.mutations import MutationState
from kubetrol.domain.workloads import WorkloadAction
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.mutations import MutationManager
from kubetrol.services.workloads import WorkloadService
from tests.support.connections import catalog_fixture, certificate
from tests.support.workloads import workload_api


@asynccontextmanager
async def source_fixture(tmp_path, *, family="deployments", readonly=False, tls=False):
    ssl, cluster = certificate(tmp_path) if tls else (None, None)
    async with workload_api(family=family, tls=ssl) as (url, api):
        client = KubernetesSession(
            catalog_fixture(
                tmp_path, url, {"token": "synthetic-workload", "as": "owned-reader"}, cluster
            ).select("kubetrol-test-one"),
            2,
        )
        await client.open()
        current = [True]
        source = WorkloadService(
            client, api.resource, api.target, AccessPolicy(readonly), lambda: current[0]
        )
        try:
            yield source, api, current
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["deployments", "replicasets", "statefulsets"])
async def test_scale_real_tls_narrow_path_exact_body_and_single_use(tmp_path, family):
    async with source_fixture(tmp_path, family=family, tls=True) as (source, api, _):
        intent = await source.prepare(WorkloadAction.SCALE, "0")
        proof = source.confirm(intent)
        assert (await source.execute(proof)).state is MutationState.SUCCEEDED
        assert (await source.execute(proof)).state is MutationState.BLOCKED
        path, headers, query, body = api.requests[0]
        assert path.endswith(f"/{family}/owned-one/scale")
        assert query == {"fieldValidation": "Strict"}
        assert headers["Authorization"] == "Bearer synthetic-workload"
        assert headers["Impersonate-User"] == "owned-reader"
        assert body[-1] == {"op": "add", "path": "/spec/replicas", "value": 0}
        assert api.value["spec"]["replicas"] == 0
        assert len(api.requests) == 1 and "private-workload" not in repr(intent)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["deployments", "statefulsets", "daemonsets"])
async def test_restart_and_explicit_rollback_preserve_non_template_fields(tmp_path, family):
    async with source_fixture(tmp_path, family=family) as (source, api, _):
        intent = await source.prepare(WorkloadAction.RESTART)
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED
        assert (
            "kubectl.kubernetes.io/restartedAt"
            in api.value["spec"]["template"]["metadata"]["annotations"]
        )
        intent = await source.prepare(WorkloadAction.ROLLBACK, "1")
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED
        assert api.value["spec"]["replicas"] == 2
        assert api.value["spec"]["template"]["spec"]["containers"][0]["image"] == "owned-old-image"
        assert "$patch" not in api.value["spec"]["template"]
        assert "private-workload" not in source.preview


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "unchanged",
        "bad-count",
        "zero-revision",
        "no-revision",
        "ambiguous",
        "wrong-owner",
        "missing-history-uid",
        "paused",
        "on-delete",
        "readonly",
        "hpa",
        "hpa-denied",
    ],
)
async def test_preparation_refusals_never_patch(tmp_path, mode):
    async with source_fixture(tmp_path, readonly=mode == "readonly") as (source, api, _):
        action, arg = WorkloadAction.ROLLBACK, "1"
        if mode == "unchanged":
            action, arg = WorkloadAction.SCALE, "2"
        if mode == "bad-count":
            action, arg = WorkloadAction.SCALE, "-1"
        if mode == "zero-revision":
            arg = "0"
        if mode == "no-revision":
            arg = "7"
        if mode == "ambiguous":
            api.histories.append(api.histories[0])
        if mode == "wrong-owner":
            api.histories[0]["metadata"]["ownerReferences"][0]["uid"] = "other"
        if mode == "missing-history-uid":
            api.histories[0]["metadata"].pop("uid")
        if mode == "paused":
            api.value["spec"]["paused"] = True
        if mode == "on-delete":
            api.value["spec"]["updateStrategy"] = {"type": "OnDelete"}
        if mode in {"hpa", "hpa-denied"}:
            action, arg = WorkloadAction.SCALE, "3"
            if mode == "hpa":
                api.hpas = [
                    {
                        "spec": {
                            "scaleTargetRef": {
                                "apiVersion": "apps/v1",
                                "kind": "Deployment",
                                "name": "owned-one",
                            }
                        }
                    }
                ]
            else:
                api.hpa_status = 403
        with pytest.raises(AppError):
            await source.prepare(action, arg)
        assert source.intent is None and not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "history-version",
        "history-uid",
        "target-version",
        "target-uid",
        "context",
        "hpa-added",
        "denied",
        "drop",
    ],
)
async def test_post_confirmation_races_and_uncertain_response(tmp_path, mode):
    async with source_fixture(tmp_path) as (source, api, current):
        action = WorkloadAction.SCALE if mode == "hpa-added" else WorkloadAction.ROLLBACK
        intent = await source.prepare(action, "1")
        proof = source.confirm(intent)
        if mode == "history-version":
            api.histories[0]["metadata"]["resourceVersion"] = "changed"
        if mode == "history-uid":
            api.histories[0]["metadata"]["uid"] = "changed"
        if mode == "target-version":
            api.value["metadata"]["resourceVersion"] = "changed"
        if mode == "target-uid":
            api.value["metadata"]["uid"] = "changed"
        if mode == "context":
            current[0] = False
        if mode == "hpa-added":
            api.hpas = [
                {
                    "spec": {
                        "scaleTargetRef": {
                            "apiVersion": "apps/v1",
                            "kind": "Deployment",
                            "name": "owned-one",
                        }
                    }
                }
            ]
        if mode == "denied":
            api.patch_status = 403
        if mode == "drop":
            api.drop = True
        result = await source.execute(proof)
        assert result.state is not MutationState.SUCCEEDED
        assert len(api.requests) == int(mode in {"denied", "drop"})
        if mode == "drop":
            assert result.state is MutationState.UNCERTAIN
        assert "private-" not in result.message


@pytest.mark.asyncio
async def test_hpa_api_absence_and_unrelated_controller(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        api.hpa_status = 404
        assert (
            await source.execute(source.confirm(await source.prepare(WorkloadAction.SCALE, "3")))
        ).state is MutationState.SUCCEEDED
        api.hpa_status = None
        api.hpas = [
            {
                "spec": {
                    "scaleTargetRef": {
                        "apiVersion": "apps/v1",
                        "kind": "StatefulSet",
                        "name": "owned-one",
                    }
                }
            }
        ]
        assert await source.prepare(WorkloadAction.SCALE, "4")


@pytest.mark.asyncio
async def test_readonly_actual_status_timeout_and_cancel_leave_no_server_rollback(tmp_path):
    async with source_fixture(tmp_path, readonly=True) as (source, api, current):
        seen = []
        assert (await source.monitor(seen.append)).state == "Complete"
        api.value["status"]["updatedReplicas"] = 0
        assert (await source.monitor(seen.append, timeout=0.03, interval=0.01)).state == "Timed out"
        pending = asyncio.create_task(source.monitor(seen.append, interval=0.01))
        await asyncio.sleep(0.02)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        current[0] = False
        with pytest.raises(AppError):
            await source.monitor(seen.append)
        assert not api.requests


@pytest.mark.asyncio
async def test_stateful_scale_review_discloses_actual_pvc_retention_effect(tmp_path):
    async with source_fixture(tmp_path, family="statefulsets") as (source, api, _):
        api.value["spec"]["volumeClaimTemplates"] = [{"metadata": {"name": "owned-storage"}}]
        api.value["spec"]["persistentVolumeClaimRetentionPolicy"] = {"whenScaled": "Delete"}
        intent = await source.prepare(WorkloadAction.SCALE, "1")
        assert "deletes PVCs" in source.preview
        assert not api.requests
        assert (await source.execute(source.confirm(intent))).state is MutationState.SUCCEEDED


@pytest.mark.asyncio
async def test_manager_close_drains_write_and_retains_uncertain_outcome(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        manager = MutationManager()
        intent = await source.prepare(WorkloadAction.SCALE, "3")
        api.stall = True
        identity = manager.start(source, source.confirm(intent))
        await api.entered.wait()
        await manager.stop_for_client(source.client)
        assert (await manager.wait(identity)).state is MutationState.UNCERTAIN
        assert api.value["spec"]["replicas"] == 3
        assert "private-workload" not in repr(manager.records)
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"items": {}},
        {"items": [{}] * 10001},
        {"items": [], "metadata": {"continue": 1}},
        {"items": [], "metadata": {"continue": "x" * 4097}},
        {"items": [], "metadata": {"continue": "same"}},
    ],
)
async def test_invalid_or_unbounded_related_collection_is_refused(tmp_path, payload):
    async with source_fixture(tmp_path) as (source, api, _):
        api.collections["/apis/apps/v1/namespaces/team/replicasets"] = payload
        with pytest.raises(AppError):
            await source.prepare(WorkloadAction.ROLLBACK, "1")
        assert not api.requests


@pytest.mark.asyncio
async def test_related_pagination_accepts_distinct_tokens_and_refuses_excessive_pages(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        root = "/apis/apps/v1/namespaces/team/replicasets"
        api.collections[root] = lambda request: {
            "items": api.histories if request.query.get("continue") == "page2" else [],
            "metadata": {} if "continue" in request.query else {"continue": "page2"},
        }
        assert await source.prepare(WorkloadAction.ROLLBACK, "1")
        api.collections[root] = lambda request: {
            "items": [],
            "metadata": {"continue": str(int(request.query.get("continue", "0")) + 1)},
        }
        with pytest.raises(AppError, match="pagination"):
            await source.prepare(WorkloadAction.ROLLBACK, "1")
        assert not api.requests


@pytest.mark.asyncio
async def test_hpa_fallback_denial_and_same_template_status_limits_wrong_receipts(tmp_path):
    async with source_fixture(tmp_path) as (source, api, _):
        api.hpa_status = {"v2": 404, "v1": 403}
        with pytest.raises(AppError, match="HPA"):
            await source.prepare(WorkloadAction.SCALE, "3")
        api.hpa_status = None
        api.histories[0]["spec"]["template"] = api.value["spec"]["template"]
        with pytest.raises(AppError, match="already current"):
            await source.prepare(WorkloadAction.ROLLBACK, "1")
        with pytest.raises(AppError, match="read-only"):
            await source.prepare(WorkloadAction.STATUS)
        for kwargs in ({"timeout": 0}, {"timeout": 3601}, {"interval": 0}, {"interval": 31}):
            with pytest.raises(AppError):
                await source.monitor(lambda progress: None, **kwargs)
        api.value["metadata"]["name"] = "other"
        with pytest.raises(AppError, match="different target"):
            await source.monitor(lambda progress: None)
        assert not api.requests
    async with source_fixture(tmp_path) as (source, api, _):
        # The Scale receipt must independently match name as well as UID.
        scale = api.scale

        def wrong_scale():
            data = scale()
            data["metadata"]["name"] = "wrong"
            return data

        api.scale = wrong_scale
        with pytest.raises(AppError, match="different target"):
            await source.prepare(WorkloadAction.SCALE, "3")
        assert not api.requests


@pytest.mark.asyncio
async def test_readonly_rollout_scope_never_accepts_foreign_or_container_targets(tmp_path):
    async with source_fixture(tmp_path, readonly=True) as (source, api, _):
        original = source.target
        for update in (
            {"group": "other"},
            {"resource": "pods"},
            {"container": "app"},
            {"namespace": None},
        ):
            source.target = replace(original, **update)
            with pytest.raises(AppError, match="scope"):
                await source.monitor(lambda progress: None)
        source.target = original
        source.resource = replace(source.resource, verbs=frozenset())
        with pytest.raises(AppError, match="scope"):
            await source.monitor(lambda progress: None)
        assert not api.requests
