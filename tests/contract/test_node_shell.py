"""Real loopback HTTP: reviewed create receipt, non-replay and exact-UID cleanup."""

import asyncio
import copy
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.mutations import MutationState
from kuberich.domain.node_shell_journal import JournalState
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import MutationManager
from kuberich.services.node_shell import NodeShellManager, NodeShellState
from tests.support.connections import catalog_fixture

IMAGE = "fixture/image@sha256:" + "a" * 64
NODES = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list"}))


class NodeApi:
    def __init__(self):
        self.node_uid, self.namespace_uid = "node-uid", "namespace-uid"
        self.pod = None
        self.posts, self.deletes, self.dry_runs = [], [], []
        self.create_status, self.delete_status = 201, 200
        self.dry_status = 201
        self.mode, self.ready = "normal", True
        self.pod_mode = "normal"
        self.created, self.release = asyncio.Event(), asyncio.Event()

    async def handle(self, request):
        if request.path == "/api/v1/nodes/owned-node":
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Node",
                    "metadata": {"name": "owned-node", "uid": self.node_uid},
                    "status": {"nodeInfo": {"operatingSystem": "linux"}},
                }
            )
        if request.path == "/api/v1/namespaces/team":
            return web.json_response(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": "team", "uid": self.namespace_uid},
                }
            )
        if request.method == "POST":
            body = await request.json()
            assert request.path == "/api/v1/namespaces/team/pods"
            assert request.query["fieldValidation"] == "Strict"
            if request.query.get("dryRun") == "All":
                self.dry_runs.append(body)
                if self.dry_status != 201:
                    return web.Response(status=self.dry_status)
                body["metadata"]["uid"] = "dry-run-not-owned"
                return web.json_response(body, status=201)
            self.posts.append(body)
            if self.create_status != 201:
                return web.Response(status=self.create_status, text="private-server-error")
            body["metadata"]["uid"] = (
                "returned-owned-uid" if len(self.posts) == 1 else "replacement-uid"
            )
            body["metadata"]["resourceVersion"] = "opaque-created"
            self.pod = copy.deepcopy(body)
            self.created.set()
            if self.mode == "drop":
                request.transport.abort()
                return web.Response()
            if self.mode == "stall":
                await self.release.wait()
            if self.mode == "drift":
                body["spec"]["containers"][0]["env"] = [{"name": "INJECTED", "value": "private"}]
                self.pod = copy.deepcopy(body)
            return web.json_response(body, status=201)
        if request.method == "DELETE":
            body = await request.json()
            self.deletes.append(body)
            assert body["preconditions"] == {"uid": "returned-owned-uid"}
            assert "resourceVersion" not in body["preconditions"]
            if self.delete_status != 200:
                return web.Response(status=self.delete_status)
            if self.mode == "bad-cleanup-observation":
                self.pod_mode = "malformed"
                return web.json_response({"kind": "Status", "status": "Success"})
            if self.pod and self.pod["metadata"]["uid"] != body["preconditions"]["uid"]:
                return web.Response(status=409)
            self.pod = None
            return web.json_response({"kind": "Status", "status": "Success"})
        if self.pod is None:
            return web.Response(status=404)
        value = copy.deepcopy(self.pod)
        if self.pod_mode == "malformed":
            return web.json_response({"metadata": {}})
        if self.ready:
            value["spec"]["nodeName"] = "owned-node"
            value["status"] = {
                "phase": "Running",
                "containerStatuses": [
                    {"name": "diagnostic", "state": {"running": {}}, "ready": True}
                ],
            }
        if self.pod_mode == "wrong-uid":
            value["metadata"]["uid"] = "other-uid"
        elif self.pod_mode == "deleting":
            value["metadata"]["deletionTimestamp"] = "2026-01-01T00:00:00Z"
        elif self.pod_mode == "wrong-node":
            value["spec"]["nodeName"] = "other-node"
        elif self.pod_mode == "bad-statuses":
            value["status"]["containerStatuses"] = {}
        elif self.pod_mode in {"null-running", "conflicting-state", "terminated", "image-failure"}:
            state = {
                "null-running": {"running": None},
                "conflicting-state": {"running": {}, "waiting": {}},
                "terminated": {"terminated": {"exitCode": 1}},
                "image-failure": {"waiting": {"reason": "ImagePullBackOff"}},
            }[self.pod_mode]
            value["status"]["containerStatuses"][0]["state"] = state
        elif self.pod_mode == "completed":
            value["status"]["phase"] = "Succeeded"
        elif self.pod_mode == "pull-secrets":
            value["spec"]["imagePullSecrets"] = [{"name": "changed-pull-secret"}]
        return web.json_response(value)


@asynccontextmanager
async def source_fixture(tmp_path, *, read_only=False):
    fixture = NodeApi()
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", fixture.handle)
    runner = web.AppRunner(app, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    connection = KubernetesSession(
        catalog_fixture(tmp_path, f"http://127.0.0.1:{runner.addresses[0][1]}", None, None).select(
            "kuberich-test-one"
        ),
        1,
    )
    await connection.open()
    policy = AccessPolicy(read_only)
    manager = NodeShellManager(NodeShellJournal(tmp_path / "journal"))
    current, config = [True], [1]
    try:
        yield manager, connection, fixture, policy, current, config
    finally:
        fixture.release.set()
        await manager.close()
        await connection.close()
        await runner.cleanup()


def create(values, tmp_path):
    manager, client, _, policy, current, config = values
    return manager.create(
        client,
        NODES,
        ResourceTarget(
            SessionIdentity(client.context.name, 1), "", "nodes", None, "owned-node", "node-uid"
        ),
        policy,
        lambda: current[0],
        settings=NodeShellSettings(enabled=True, image=IMAGE, namespace="team"),
        config_generation=1,
        current_config=lambda: config[0],
        environment={},
        directory=tmp_path,
    )


@pytest.mark.asyncio
async def test_actual_http_review_create_durable_uid_and_uid_only_delete(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, policy, _, config = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        assert api.posts == api.deletes == [] and len(api.dry_runs) == 1
        assert owner.owned is None
        proof = owner.confirm(intent)
        assert (await owner.execute(proof)).state is MutationState.SUCCEEDED
        assert owner.observation.state is NodeShellState.READY
        records = await manager.scan()
        assert len(records) == 1 and records[0].pod_uid == "returned-owned-uid"
        assert records[0].state is JournalState.OWNED
        config[0] += 1  # Image/limit reloads apply to the next review.
        owner.require_current()
        policy.tighten()  # Already authorized UID cleanup remains available.
        await owner.close()
        assert owner.observation.state is NodeShellState.CLOSED
        assert manager.active_count == 0 and await manager.scan() == ()
        assert len(api.posts) == len(api.deletes) == 1
        assert (await owner.execute(proof)).state is MutationState.BLOCKED


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 409, 422, 500, 302])
async def test_post_refusal_never_replays_or_deletes_unowned_pod(tmp_path, status):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.create_status = status
        result = await owner.execute(owner.confirm(intent))
        assert result.state is not MutationState.SUCCEEDED
        assert len(api.posts) == 1 and api.deletes == []
        records = await manager.scan()
        assert (len(records) == 1) == (result.state is MutationState.UNCERTAIN)
        assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_response_loss_remains_unknown_uid_and_does_not_adopt_later_get(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "drop"
        result = await owner.execute(owner.confirm(intent))
        assert result.state is MutationState.UNCERTAIN
        assert owner.owned is None and api.pod is not None
        assert len(api.posts) == 1 and api.deletes == []
        (record,) = await manager.scan()
        assert record.state is JournalState.CREATE_UNCERTAIN and record.pod_uid is None


@pytest.mark.asyncio
async def test_profile_drift_preserves_returned_uid_and_cleans_it(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "drift"
        result = await owner.execute(owner.confirm(intent))
        assert result.state is MutationState.UNCERTAIN
        assert owner.observation.pod_uid == "returned-owned-uid"
        assert owner.observation.code == "admission_drift"
        assert api.pod is None and len(api.deletes) == 1 and await manager.scan() == ()


@pytest.mark.asyncio
async def test_cancel_during_create_drains_receipt_then_cleans_known_uid(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "stall"
        writes = MutationManager()
        key = writes.start(owner, owner.confirm(intent))
        await api.created.wait()
        cancelled = asyncio.create_task(writes.cancel(key))
        await asyncio.sleep(0)
        api.release.set()
        result = await cancelled
        assert result.state is MutationState.SUCCEEDED
        assert owner.observation.pod_uid == "returned-owned-uid"
        assert len(api.posts) == len(api.deletes) == 1
        assert await manager.scan() == () and manager.active_count == writes.active_count == 0
        await writes.close()


@pytest.mark.asyncio
async def test_preentry_cancellation_consumes_proof_without_any_post(tmp_path):
    async with source_fixture(tmp_path) as values:
        _, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        proof = owner.confirm(intent)
        operation = asyncio.create_task(owner.execute(proof))
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert (await owner.execute(proof)).state is MutationState.BLOCKED
        assert api.posts == api.deletes == []


@pytest.mark.asyncio
async def test_replacement_survives_atomic_uid_cleanup_and_journal_retires(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.pod["metadata"]["uid"] = "replacement-uid"
        await owner.close()
        assert api.pod["metadata"]["uid"] == "replacement-uid"
        assert len(api.deletes) == 1 and await manager.scan() == ()


@pytest.mark.asyncio
async def test_delete_denied_retains_owned_uid_for_explicit_recovery(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.delete_status = 403
        await owner.close()
        (record,) = await manager.scan()
        assert (
            record.pod_uid == "returned-owned-uid" and record.state is JournalState.CLEANUP_PENDING
        )
        assert owner.observation.state is NodeShellState.PENDING
        assert len(api.deletes) == 1


@pytest.mark.asyncio
async def test_readonly_stale_selection_and_config_are_rejected_before_post(tmp_path):
    async with source_fixture(tmp_path, read_only=True) as values:
        with pytest.raises(AppError, match="Read-only"):
            create(values, tmp_path)
    async with source_fixture(tmp_path) as values:
        _, _, api, _, current, config = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        config[0] = 2
        with pytest.raises(AppError, match="configuration"):
            owner.confirm(intent)
        config[0] = 1
        proof = owner.confirm(intent)
        current[0] = False
        assert (await owner.execute(proof)).state is MutationState.BLOCKED
        assert api.posts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["node", "namespace"])
async def test_precreate_revalidation_refuses_replaced_node_or_namespace(tmp_path, field):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        setattr(api, field + "_uid", "replacement")
        assert (await owner.execute(owner.confirm(intent))).state is MutationState.BLOCKED
        assert api.posts == api.deletes == [] and await manager.scan() == ()


@pytest.mark.asyncio
async def test_manager_reserves_one_owner_and_retires_compact_history(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, client, *_ = values
        owner = create(values, tmp_path)
        with pytest.raises(AppError, match="already active"):
            create(values, tmp_path)
        assert owner.observation.pod_name is None and manager.active_count == 1
        assert await owner.durable_record() is None
        with pytest.raises(AppError, match="Prepare"):
            _ = owner.target
        with pytest.raises(AppError, match="ready"):
            await owner.shell()
        assert manager.active_count == 0 and manager.records[-1].state is NodeShellState.CLOSED
        owner = create(values, tmp_path)
        await manager.close_for_client(object())
        assert manager.active_count == 1
        await manager.close_for_client(client)
        assert manager.active_count == 0
        await manager.close()
        with pytest.raises(AppError, match="closing"):
            create(values, tmp_path)


@pytest.mark.asyncio
async def test_immutable_prepare_and_confirmation_reject_unrelated_intent(tmp_path):
    from dataclasses import replace

    async with source_fixture(tmp_path) as values:
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        with pytest.raises(AppError, match="immutable"):
            await owner.prepare()
        with pytest.raises(AppError, match="exact"):
            owner.confirm(replace(intent))
        assert (await owner.execute(None)).state is MutationState.BLOCKED


@pytest.mark.asyncio
async def test_unresolved_unknown_uid_blocks_a_second_create_until_explicit_resolution(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "drop"
        await owner.execute(owner.confirm(intent))
        api.mode = "normal"
        second = create(values, tmp_path)
        intent = await second.prepare()
        assert (await second.execute(second.confirm(intent))).state is MutationState.BLOCKED
        assert len(api.posts) == 1 and api.deletes == []
        assert len(await manager.scan()) == 1


@pytest.mark.asyncio
async def test_shell_capture_uses_diagnostic_container_and_explicit_connection(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        terminal, request = await owner.shell()
        assert request.command.target.container == "diagnostic"
        assert request.command.argv[-1] == "/bin/sh"
        assert "--context=kuberich-test-one" in request.command.argv
        assert "--namespace=team" in request.command.argv
        assert request.command.target.uid == "returned-owned-uid"
        async with terminal.stage(request) as command:
            assert command is request.command
            assert owner.observation.state is NodeShellState.RUNNING
        assert manager.active_count == 0 and api.pod is None
        assert not request.path.exists()


@pytest.mark.asyncio
async def test_shell_fresh_node_revalidation_prevents_exec_and_still_cleans_owned_pod(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.node_uid = "replacement"
        with pytest.raises(AppError, match="Linux Node UID"):
            await owner.shell()
        assert manager.active_count == 0 and len(api.deletes) == 1


@pytest.mark.asyncio
async def test_stale_while_waiting_keeps_successful_create_history_and_cleans_uid(
    tmp_path, monkeypatch
):
    async with source_fixture(tmp_path) as values:
        manager, _, api, _, current, _ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.ready = False
        monkeypatch.setattr("kuberich.services.node_shell.POLL_SECONDS", 0.001)
        task = asyncio.create_task(owner.execute(owner.confirm(intent)))
        await api.created.wait()
        current[0] = False
        assert (await task).state is MutationState.SUCCEEDED
        assert len(api.deletes) == 1 and manager.active_count == 0


@pytest.mark.asyncio
async def test_cleanup_response_loss_is_observed_without_delete_replay(tmp_path, monkeypatch):
    from kuberich.domain.mutations import MutationResult

    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))

        async def lost_response(client, owned, authorize):
            from kuberich.adapters.node_shell import delete_pod

            await delete_pod(client, owned, authorize)
            return MutationResult(MutationState.UNCERTAIN, "Response lost.")

        monkeypatch.setattr("kuberich.services.node_shell.delete_pod", lost_response)
        await owner.close()
        assert len(api.deletes) == 1 and await manager.scan() == ()


@pytest.mark.asyncio
async def test_active_terminal_close_drains_before_uid_delete(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        terminal, request = await owner.shell()
        entered, exited = asyncio.Event(), asyncio.Event()

        async def session():
            async with terminal.stage(request):
                try:
                    entered.set()
                    await asyncio.Event().wait()
                finally:
                    assert api.deletes == []
                    exited.set()

        task = asyncio.create_task(session())
        await entered.wait()
        await owner.close()
        assert exited.is_set() and task.cancelled()
        assert len(api.deletes) == 1 and manager.active_count == 0


@pytest.mark.asyncio
async def test_uncertain_create_with_failed_journal_transition_preserves_prepared_evidence(
    tmp_path, monkeypatch
):
    from kuberich.adapters.node_shell_files import JournalLease

    original = JournalLease.write

    async def fail_uncertainty(self, record):
        if record.state is JournalState.CREATE_UNCERTAIN:
            raise OSError("synthetic durability fault")
        await original(self, record)

    monkeypatch.setattr(JournalLease, "write", fail_uncertainty)
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.mode = "drop"
        with pytest.raises(AppError, match="persistence failed"):
            await owner.execute(owner.confirm(intent))
        assert len(api.posts) == 1 and api.pod is not None and api.deletes == []
        (record,) = await manager.scan()
        assert record.state is JournalState.PREPARED and record.pod_uid is None


@pytest.mark.asyncio
async def test_malformed_cleanup_observation_cannot_discard_known_uid_record(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.mode = "bad-cleanup-observation"
        await owner.close()
        (record,) = await manager.scan()
        assert api.pod is not None and len(api.deletes) == 1
        assert (
            record.pod_uid == "returned-owned-uid" and record.state is JournalState.CLEANUP_PENDING
        )
        assert owner.observation.state is NodeShellState.PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "wrong-uid",
        "deleting",
        "wrong-node",
        "bad-statuses",
        "null-running",
        "conflicting-state",
        "terminated",
        "image-failure",
        "completed",
    ],
)
async def test_unverified_readiness_never_opens_exec_and_preserves_create_truth(tmp_path, mode):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.pod_mode = mode
        assert (await owner.execute(owner.confirm(intent))).state is MutationState.SUCCEEDED
        assert owner.observation.state is NodeShellState.CLOSED and len(api.deletes) == 1
        assert await manager.scan() == ()


@pytest.mark.asyncio
async def test_one_shot_review_and_terminal_admission_cannot_replace_live_owner(tmp_path):
    async with source_fixture(tmp_path) as values:
        _, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        with pytest.raises(AppError, match="exact immutable"):
            owner.confirm(intent)
        terminal, request = await owner.shell()
        with pytest.raises(AppError, match="already opening"):
            await owner.shell()
        async with terminal.stage(request):
            with pytest.raises(AppError, match="already been admitted"):
                async with terminal.stage(request):
                    raise AssertionError("Duplicate stage unexpectedly entered.")
            assert api.deletes == [] and owner.observation.state is NodeShellState.RUNNING
        assert len(api.deletes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["prepare", "shell"])
async def test_connection_teardown_drains_owned_preflight_before_cleanup(
    tmp_path, monkeypatch, operation
):
    async with source_fixture(tmp_path) as values:
        manager, connection, api, *_ = values
        owner = create(values, tmp_path)
        if operation == "shell":
            intent = await owner.prepare()
            await owner.execute(owner.confirm(intent))
        entered, drained = asyncio.Event(), asyncio.Event()
        original = connection.get_json

        async def block(path, **kwargs):
            if path == "/api/v1/nodes/owned-node":
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    drained.set()
            return await original(path, **kwargs)

        monkeypatch.setattr(connection, "get_json", block)
        task = asyncio.create_task(getattr(owner, operation)())
        await entered.wait()
        if operation == "prepare":
            with pytest.raises(AppError, match="already being prepared"):
                await owner.prepare()
        await manager.close_for_client(connection)
        assert task.cancelled() and drained.is_set() and manager.active_count == 0
        assert len(api.deletes) == (operation == "shell")


@pytest.mark.asyncio
async def test_owned_uid_persistence_failure_forbids_exec_attempts_cleanup_then_raises(
    tmp_path, monkeypatch
):
    from kuberich.adapters.node_shell_files import JournalLease

    original = JournalLease.write

    async def fail_owned(self, record):
        if record.state is JournalState.OWNED:
            raise OSError("synthetic fsync fault")
        await original(self, record)

    monkeypatch.setattr(JournalLease, "write", fail_owned)
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        writes = MutationManager()
        identity = writes.start(owner, owner.confirm(intent))
        assert (await writes.wait(identity)).state is MutationState.UNCERTAIN
        with pytest.raises(AppError, match="persistence failed"):
            owner.raise_failure()
        assert len(api.deletes) == 1 and api.pod is None and await manager.scan() == ()
        await writes.close()


@pytest.mark.asyncio
async def test_cleanup_deadline_retains_pending_uid_without_forced_delete(tmp_path, monkeypatch):
    monkeypatch.setattr("kuberich.services.node_shell.CLEANUP_SECONDS", 0.02)
    monkeypatch.setattr("kuberich.services.node_shell.POLL_SECONDS", 0.001)
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.delete_status = 202
        await owner.close()
        (record,) = await manager.scan()
        assert record.pod_uid == "returned-owned-uid" and api.pod is not None
        assert len(api.deletes) == 1 and owner.observation.state is NodeShellState.PENDING


@pytest.mark.asyncio
async def test_postownership_lease_close_failure_surfaces_after_remote_cleanup(
    tmp_path, monkeypatch
):
    from kuberich.adapters.node_shell_files import JournalLease

    original = JournalLease.close

    async def failed_close(self):
        await original(self)
        raise OSError("synthetic descriptor-close fault")

    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        monkeypatch.setattr(JournalLease, "close", failed_close)
        with pytest.raises(OSError, match="synthetic"):
            await owner.close()
        monkeypatch.setattr(JournalLease, "close", original)
        with pytest.raises(AppError, match="persistence failed"):
            owner.raise_failure()
        assert api.pod is None and len(api.deletes) == 1
        assert manager.active_count == 0 and await manager.scan() == ()
        assert manager.records[-1].code == "persistence_failed"


@pytest.mark.asyncio
async def test_server_dryrun_refusal_remains_before_any_durable_create(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        api.dry_status = 403
        with pytest.raises(AppError, match="dry-run refused"):
            await owner.prepare()
        assert api.posts == api.deletes == [] and await manager.scan() == ()


@pytest.mark.asyncio
async def test_allowed_admission_defaults_still_bind_the_reviewed_dryrun(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.pod_mode = "pull-secrets"
        assert (await owner.execute(owner.confirm(intent))).state is MutationState.SUCCEEDED
        assert owner.observation.code == "admission_drift" and await manager.scan() == ()


@pytest.mark.asyncio
async def test_no_longer_running_pod_is_refused_before_shell_capture(tmp_path):
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        api.ready = False
        with pytest.raises(AppError, match="no longer running"):
            await owner.shell()
        assert len(api.deletes) == 1 and await manager.scan() == ()


@pytest.mark.asyncio
async def test_startup_deadline_bounds_normal_scheduler_wait_and_cleans_uid(tmp_path, monkeypatch):
    timeout = asyncio.timeout
    monkeypatch.setattr(
        "kuberich.services.node_shell.asyncio.timeout",
        lambda duration: timeout(0.02 if duration == 60 else duration),
    )
    monkeypatch.setattr("kuberich.services.node_shell.POLL_SECONDS", 0.001)
    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        api.ready = False
        assert (await owner.execute(owner.confirm(intent))).state is MutationState.SUCCEEDED
        assert owner.observation.code == "startup_timeout" and await manager.scan() == ()


@pytest.mark.asyncio
async def test_session_deadline_drains_terminal_then_deletes_owned_uid(tmp_path, monkeypatch):
    timeout = asyncio.timeout
    monkeypatch.setattr(
        "kuberich.services.node_shell.asyncio.timeout",
        lambda duration: timeout(0.02 if duration == 3600 else duration),
    )
    async with source_fixture(tmp_path) as values:
        manager, connection, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        await owner.execute(owner.confirm(intent))
        terminal, request = await owner.shell()
        assert terminal.client is connection
        with pytest.raises(AppError, match="deadline expired"):
            async with terminal.stage(request):
                await asyncio.Event().wait()
        assert owner.observation.code == "session_timeout" and await manager.scan() == ()
        assert len(api.deletes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["prepared-write", "pending-write", "record-remove"])
async def test_journal_failure_keeps_local_failure_visible_after_attempted_drainage(
    tmp_path, monkeypatch, fault
):
    from kuberich.adapters.node_shell_files import JournalLease

    original_write, original_remove = JournalLease.write, JournalLease.remove

    async def write(self, record):
        if (fault == "prepared-write" and record.state is JournalState.PREPARED) or (
            fault == "pending-write" and record.state is JournalState.CLEANUP_PENDING
        ):
            raise OSError("synthetic journal fault")
        await original_write(self, record)

    async def remove(self, operation):
        raise OSError("synthetic remove fault")

    async with source_fixture(tmp_path) as values:
        manager, _, api, *_ = values
        owner = create(values, tmp_path)
        intent = await owner.prepare()
        if fault == "prepared-write":
            monkeypatch.setattr(JournalLease, "write", write)
            with pytest.raises(AppError, match="persistence failed"):
                await owner.execute(owner.confirm(intent))
            assert api.posts == api.deletes == []
        else:
            await owner.execute(owner.confirm(intent))
            if fault == "pending-write":
                monkeypatch.setattr(JournalLease, "write", write)
                api.delete_status = 403
            else:
                monkeypatch.setattr(JournalLease, "remove", remove)
            with pytest.raises(AppError, match="persistence failed"):
                await owner.close()
            assert len(api.deletes) == 1
        monkeypatch.setattr(JournalLease, "write", original_write)
        monkeypatch.setattr(JournalLease, "remove", original_remove)
        with pytest.raises(AppError, match="persistence failed"):
            owner.raise_failure()
        assert manager.active_count == 0
