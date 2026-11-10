"""Independent public regressions for manifest review cancellation and write ownership."""

import asyncio

import pytest

from kuberich.domain.mutations import MutationState
from kuberich.services.mutations import MutationManager
from tests.contract.test_manifest_service import service_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
async def test_stop_during_accepted_delete_observation_keeps_later_items_unsent(tmp_path, managed):
    async with service_fixture(tmp_path, count=2, existing=True) as (service, adapter, _, _):
        plan = await service.prepare("delete")
        adapter.write_states = [MutationState.ACCEPTED, MutationState.ACCEPTED]
        original_read = adapter.read
        observing = asyncio.Event()
        release = asyncio.Event()

        async def read(resource, address, guard):
            if adapter.writes and address.name == "0":
                observing.set()
                await release.wait()
            return await original_read(resource, address, guard)

        adapter.read = read
        manager = MutationManager()
        if managed:
            identity = manager.start(service, service.confirm(plan))
        else:
            execution = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(observing.wait(), 2)
        if managed:
            result = await asyncio.wait_for(manager.cancel(identity), 2)
            assert manager.records[-1].result == result
        else:
            execution.cancel()
            result = await asyncio.wait_for(execution, 2)
        assert len(adapter.writes) == 1
        assert result.items[0][1].state is MutationState.ACCEPTED
        assert result.items[1][1].state is MutationState.BLOCKED
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("managed", [False, True])
async def test_stop_after_known_completed_write_preserves_success_and_sends_no_later_request(
    tmp_path, managed
):
    """An owned transport can finish a verified receipt while draining cancellation."""
    from kuberich.domain.mutations import MutationResult

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        admitted = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if len(adapter.writes) == 1:
                admitted.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # Verified completion wins over an unproven uncertain result,
                    # but cancellation still ends the owning batch.
                    return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        if managed:
            identity = manager.start(service, service.confirm(plan))
        else:
            execution = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(admitted.wait(), 2)
        if managed:
            result = await asyncio.wait_for(manager.cancel(identity), 2)
        else:
            execution.cancel()
            result = await asyncio.wait_for(execution, 2)
        assert len(adapter.writes) == 1
        assert result.items[0][1].state is MutationState.SUCCEEDED
        assert result.items[1][1].state in {MutationState.CANCELLED, MutationState.BLOCKED}
        assert (
            "no request sent" in result.items[1][1].message
            or "Unsent" in result.items[1][1].message
        )
        assert result.items[2][1].state is MutationState.BLOCKED
        if managed:
            assert manager.records[-1].result == result
        await manager.close()


@pytest.mark.asyncio
async def test_helper_private_draft_cleanup_failure_is_safe_and_owner_close_retries(
    tmp_path, monkeypatch
):
    """A failed private-file removal remains owned after the preview task ends."""
    from kuberich.adapters.editing import ManifestFile
    from kuberich.domain.targets import ResourceTarget
    from kuberich.errors import AppError
    from tests.contract.test_manifest_preview import helper_environment
    from tests.contract.test_manifest_writes import (
        RESOURCE,
        SESSION,
        adapter_fixture,
        create_intent,
    )

    original = ManifestFile.close
    calls = 0

    def fail_once(draft):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("private-local-path-sentinel")
        return original(draft)

    async with adapter_fixture(tmp_path) as (adapter, api):
        intent = create_intent()
        await adapter.execute(intent, lambda: None)
        baseline = await adapter.read(RESOURCE, intent.target, lambda: None)
        target = ResourceTarget(SESSION, "", "configmaps", "team", "owned-one", baseline.uid)
        adapter.environment = helper_environment(tmp_path, api.value)
        monkeypatch.setattr(ManifestFile, "close", fail_once)
        with pytest.raises(Exception) as failure:
            await adapter.preview_update(RESOURCE, target, intent.body, baseline, lambda: None)
        await adapter.close()
        assert isinstance(failure.value, AppError) and "private-local-path-sentinel" not in str(
            failure.value
        )
        assert calls == 2


@pytest.mark.asyncio
async def test_cancel_before_operation_entry_consumes_the_admitted_confirmation(tmp_path):
    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        proof = service.confirm(plan)
        manager = MutationManager()
        identity = manager.start(service, proof)
        cancelled = await manager.cancel(identity)
        assert cancelled.state is MutationState.CANCELLED and not adapter.writes
        replay = await service.execute(proof)
        assert replay.state is MutationState.BLOCKED and not adapter.writes
        await manager.close()


@pytest.mark.asyncio
async def test_concurrent_confirmation_cannot_replace_an_active_batchs_completed_outcomes(tmp_path):
    from kuberich.domain.mutations import MutationResult
    from kuberich.errors import AppError

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if intent.target.name == "1":
                second_entered.set()
                await release.wait()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        first = asyncio.create_task(service.execute(service.confirm(plan)))
        await asyncio.wait_for(second_entered.wait(), 2)
        assert len(service.results) == 1 and service.results[0][1].state is MutationState.SUCCEEDED
        try:
            proof = service.confirm(plan)
        except AppError:
            pass
        else:
            rejected = await service.execute(proof)
            assert rejected.state in {MutationState.BLOCKED, MutationState.STALE}
        finally:
            release.set()
        result = await asyncio.wait_for(first, 2)
        assert len(adapter.writes) == 3
        assert len(result.items) == 3
        assert [target.name for target, _ in result.items] == ["0", "1", "2"]
        assert all(item.state is MutationState.SUCCEEDED for _, item in result.items)


@pytest.mark.asyncio
async def test_pre_entry_double_admission_cannot_replace_the_winning_batchs_outcomes(tmp_path):
    from kuberich.domain.mutations import MutationResult
    from kuberich.errors import AppError

    async with service_fixture(tmp_path, count=3) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            if intent.target.name == "1":
                second_entered.set()
                await release.wait()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        first = manager.start(service, service.confirm(plan))
        try:
            proof = service.confirm(plan)
        except AppError:
            second = None
        else:
            second = manager.start(service, proof)
        await asyncio.wait_for(second_entered.wait(), 2)
        try:
            if second is not None:
                rejected = await asyncio.wait_for(manager.wait(second), 2)
                assert rejected.state in {MutationState.BLOCKED, MutationState.STALE}
        finally:
            release.set()
        result = await asyncio.wait_for(manager.wait(first), 2)
        assert len(adapter.writes) == 3 and len(result.items) == 3
        assert [target.name for target, _ in result.items] == ["0", "1", "2"]
        assert all(item.state is MutationState.SUCCEEDED for _, item in result.items)
        await manager.close()


@pytest.mark.asyncio
async def test_wait_publishes_a_just_completed_batch_before_done_callback_delivery(tmp_path):
    from kuberich.domain.mutations import MutationResult

    async with service_fixture(tmp_path) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        completed = asyncio.Event()

        async def execute(intent, guard):
            guard()
            adapter.writes.append(intent)
            completed.set()
            return MutationResult(MutationState.SUCCEEDED, "Verified completed write.")

        adapter.execute = execute
        manager = MutationManager()
        identity = manager.start(service, service.confirm(plan))
        await completed.wait()
        result = await manager.wait(identity)
        assert result.state is MutationState.SUCCEEDED and len(result.items) == 1
        assert manager.records[-1].result == result and manager.active_count == 0
        await manager.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_pre_entry_cancel_retains_two_exact_targets_and_scoped_history(tmp_path, existing):
    async with service_fixture(tmp_path, count=2, existing=existing) as (service, adapter, _, _):
        plan = await service.prepare("apply")
        manager = MutationManager()
        proof = service.confirm(plan)
        identity = manager.start(service, proof)
        result = await manager.cancel(identity)
        assert tuple(target for target, _ in result.items) == plan.targets
        assert len(result.items) == 2 and not adapter.writes
        assert all(
            item.state is MutationState.CANCELLED and "Unsent" in item.message
            for _, item in result.items
        )
        history = manager.records[-1]
        assert history.targets == plan.targets and history.result == result
        assert all(
            "namespace=team" in effect and "v1/configmaps/" in effect for effect in history.effects
        )
        assert tuple(target.uid for target in history.targets) == (
            ("uid-0", "uid-1") if existing else (None, None)
        )
        if existing:
            assert all("resourceVersion=1" in effect for effect in history.effects)
        else:
            assert all("UID=(not captured)" in effect for effect in history.effects)
        assert (await service.execute(proof)).state is MutationState.BLOCKED
        await manager.close()


class DeleteBodyApi:
    """Pinned API semantics: a nonempty DeleteOptions body replaces query options."""

    def __init__(self, finalizer, corrupt_receipt):
        import copy

        self.requests = []
        self.effects = []
        self.corrupt_receipt = corrupt_receipt
        self.values = {}
        for name in ("owned", "query-control"):
            metadata = {
                "name": name,
                "namespace": "team",
                "uid": "uid-" + name,
                "resourceVersion": "opaque-baseline",
            }
            if finalizer:
                metadata["finalizers"] = ["example.io/owned-review"]
            self.values[name] = {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": metadata,
                "data": {"managed": "fixture-value"},
            }
        self.original = copy.deepcopy(self.values["owned"])

    async def handle(self, request):
        import copy
        import json

        from aiohttp import web

        name = request.match_info["name"]
        value = self.values.get(name)
        if request.method == "GET":
            return web.Response(status=404) if value is None else web.json_response(value)
        assert request.method == "DELETE"
        raw = await request.read()
        # Kubernetes v1.36.4 delete.go decodes URL options only for an empty body.
        options = json.loads(raw) if raw else {"dryRun": request.query.getall("dryRun", [])}
        self.requests.append(
            {
                "method": request.method,
                "path": request.path,
                "query": dict(request.query),
                "body": copy.deepcopy(options),
            }
        )
        if value is None:
            return web.Response(status=404)
        if options.get("preconditions") != {
            "uid": value["metadata"]["uid"],
            "resourceVersion": value["metadata"]["resourceVersion"],
        }:
            return web.Response(status=409)
        dry = options.get("dryRun") == ["All"]
        if value["metadata"].get("finalizers"):
            response = copy.deepcopy(value)
            response["metadata"].update(
                deletionTimestamp="2026-11-10T00:00:00Z", deletionGracePeriodSeconds=0
            )
            if not dry:
                response["metadata"]["resourceVersion"] = "opaque-after-delete"
                self.values[name] = copy.deepcopy(response)
        else:
            response = {
                "apiVersion": "v1",
                "kind": "Status",
                "status": "Success",
                "details": {"name": name, "uid": value["metadata"]["uid"]},
            }
            if not dry:
                del self.values[name]
        if not dry:
            self.effects.append(name)
        if name == "owned" and self.corrupt_receipt is not None:
            response["metadata"][self.corrupt_receipt] = "wrong-receipt-identity"
        return web.json_response(response)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "finalizer,corrupt_receipt",
    [(False, None), (True, None), (True, "uid"), (True, "resourceVersion")],
)
async def test_delete_validation_uses_body_dry_run_and_close_without_confirmation_preserves_storage(
    tmp_path, finalizer, corrupt_receipt
):
    import json
    from pathlib import Path

    from aiohttp import ClientSession, web

    from kuberich.adapters.kubernetes import KubernetesSession
    from kuberich.adapters.manifests import ManifestAdapter
    from kuberich.domain.manifests import ManifestScope
    from kuberich.domain.resources import Discovery
    from kuberich.errors import AppError
    from kuberich.services.access import AccessPolicy
    from kuberich.services.local_manifests import LocalManifestService
    from kuberich.services.manifests import ManifestMutationService
    from tests.contract.test_manifest_writes import RESOURCE, SESSION
    from tests.support.connections import catalog_fixture

    api = DeleteBodyApi(finalizer, corrupt_receipt)
    server = web.Application()
    server.router.add_route("*", "/api/v1/namespaces/team/configmaps/{name}", api.handle)
    runner = web.AppRunner(server, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    url = f"http://127.0.0.1:{runner.addresses[0][1]}"
    policy = AccessPolicy(False)
    client = KubernetesSession(catalog_fixture(tmp_path, url).select(SESSION.context), 2)
    local = LocalManifestService(policy, {}, tmp_path)
    service = None
    adapter = None
    try:
        # This explicit positive control would expose the original query-only bug.
        control = api.values["query-control"]["metadata"]
        options = {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "preconditions": {"uid": control["uid"], "resourceVersion": control["resourceVersion"]},
            "propagationPolicy": "Background",
        }
        async with (
            ClientSession(trust_env=False) as http,
            http.delete(
                url + "/api/v1/namespaces/team/configmaps/query-control",
                params={"dryRun": "All"},
                json=options,
            ) as response,
        ):
            assert response.status == 200
            await response.read()
        assert api.effects == ["query-control"]
        if finalizer:
            assert api.values["query-control"]["metadata"]["deletionTimestamp"]
        else:
            assert "query-control" not in api.values
        (tmp_path / "owned.yaml").write_text(
            "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned, namespace: team}\n"
        )
        await client.open()
        await local.open_root(Path("."))
        source = await local.capture("owned.yaml", "file")
        adapter = ManifestAdapter(client, policy, {}, tmp_path)
        service = ManifestMutationService(
            client,
            ManifestScope(session=SESSION, namespace="team"),
            Discovery((RESOURCE,)),
            policy,
            source,
            lambda: True,
            lambda: local.require_source(source),
            {},
            tmp_path,
            adapter=adapter,
        )
        plan = await service.prepare("delete")
        assert plan.ready is (corrupt_receipt is None)
        assert (
            plan.items[0].target.uid == "uid-owned"
            and plan.items[0].resource_version == "opaque-baseline"
        )
        requests = [request for request in api.requests if request["path"].endswith("/owned")]
        assert len(requests) == 1
        assert requests[0]["body"]["dryRun"] == ["All"]
        assert requests[0]["body"]["preconditions"] == {
            "uid": "uid-owned",
            "resourceVersion": "opaque-baseline",
        }
        assert "dryRun" not in json.loads(plan.items[0].request.body)
        if corrupt_receipt is not None:
            with pytest.raises(AppError):
                service.confirm(plan)
        assert await client.get_json("/api/v1/namespaces/team/configmaps/owned") == api.original
        await service.close()  # No confirmation or execute call: stopping review cannot delete.
        assert service.operation_count == 0
        assert await client.get_json("/api/v1/namespaces/team/configmaps/owned") == api.original
        assert api.effects == ["query-control"]
        assert len([request for request in api.requests if request["path"].endswith("/owned")]) == 1
    finally:
        if service is not None:
            await service.close()
        elif adapter is not None:
            await adapter.close()
        await local.close()
        await client.close()
        await runner.cleanup()
