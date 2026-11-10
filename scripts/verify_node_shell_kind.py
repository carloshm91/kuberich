"""Exercise production node-shell ownership in a newly owned disposable kind cluster."""

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import ssl
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell import session_fingerprint
from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.config.catalog import Entry, load_catalog
from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.mutations import MutationState
from kuberich.domain.resources import ApiResource, resource_text
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.node_shell import NodeShellManager, NodeShellService, NodeShellState
from kuberich.services.node_shell_recovery import NodeShellRecovery
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import (
    NODE_IMAGE,
    SHELL_IMAGE,
    OwnedCluster,
    capture_docker,
    owned_cluster,
    run_owned,
)

NAMESPACE = "kuberich-node-shell-fixture"
VERIFY_SECONDS = 600
KUBECTL_SHA256 = "8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a"


# Static, source-hashed producer: arguments only identify this owned fixture.
CRASH_PRODUCER = r"""
import asyncio, json, os, sys
from pathlib import Path
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.config.catalog import load_catalog
from kuberich.config.node_shell import NodeShellSettings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.mutations import MutationState
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.node_shell import NodeShellManager, NodeShellState

async def run():
    kubeconfig, context, namespace, node, uid, state, image = sys.argv[1:]
    selected = load_catalog(ConnectionRequest(kubeconfig=kubeconfig, context=context), {}).select(context)
    assert not selected.user.data.get('exec') and not selected.user.data.get('auth-provider')
    connection = KubernetesSession(selected, 15)
    assert Path(connection.directory.name).parent == Path(os.environ['TMPDIR'])
    manager = NodeShellManager(NodeShellJournal(Path(state)))
    try:
        await connection.open()
        assert connection.credentials is None
        assert connection.configuration.cert_file and connection.configuration.key_file
        owner = manager.create(connection,
            ApiResource('', 'v1', 'nodes', 'Node', False, frozenset({'get', 'list'})),
            ResourceTarget(SessionIdentity(context, 1), '', 'nodes', None, node, uid),
            AccessPolicy(False), lambda: True,
            settings=NodeShellSettings(enabled=True, image=image, namespace=namespace,
                startup_timeout_seconds=120, session_timeout_seconds=60),
            config_generation=1, current_config=lambda: 1,
            environment={}, directory=Path(state).parent)
        intent = await owner.prepare()
        result = await owner.execute(owner.confirm(intent))
        owner.raise_failure()
        assert result.state is MutationState.SUCCEEDED
        assert owner.observation.state is NodeShellState.READY
        record = await owner.durable_record()
        assert record is not None and record.pod_uid == owner.observation.pod_uid
        print(json.dumps({'state':'ready', 'operation_id':record.operation_id,
                          'pod_name':record.pod_name, 'pod_uid':record.pod_uid}), flush=True)
        await asyncio.Event().wait()
    finally:
        try:
            await manager.close()
        finally:
            await connection.close()

try:
    asyncio.run(run())
except BaseException as error:
    print(json.dumps({'state':'failed', 'failure_type':type(error).__name__}), flush=True)
    raise SystemExit(1) from None
"""


async def absent(connection: KubernetesSession, name: str, namespace: str = NAMESPACE) -> bool:
    try:
        await connection.get_json(f"/api/v1/namespaces/{namespace}/pods/{name}")
    except HttpProblem as error:
        if error.status == 404:
            return True
        raise
    return False


async def wait_absent(connection: KubernetesSession, name: str) -> None:
    async with asyncio.timeout(20):
        while not await absent(connection, name):
            await asyncio.sleep(0.2)


def producer_receipt(raw: bytes) -> dict[str, str]:
    """Accept only the bounded metadata handoff, never raw producer output."""
    try:
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 4096:
            raise ValueError
        pairs = json.loads(raw, object_pairs_hook=lambda items: items)
        if (
            not isinstance(pairs, list)
            or len(pairs) != 4
            or any(not isinstance(item, tuple) or len(item) != 2 for item in pairs)
        ):
            raise ValueError
        value = dict(pairs)
        if (
            set(value) != {"state", "operation_id", "pod_name", "pod_uid"}
            or value["state"] != "ready"
            or not all(isinstance(item, str) for item in value.values())
        ):
            raise ValueError
        operation = resource_text(value["operation_id"])
        pod_name, pod_uid = resource_text(value["pod_name"]), resource_text(value["pod_uid"])
        if (
            re.fullmatch(r"[a-f0-9]{32}", operation) is None
            or pod_name != "kuberich-node-shell-" + operation
            or len(pod_uid) > 253
        ):
            raise ValueError
        return {
            "state": "ready",
            "operation_id": operation,
            "pod_name": pod_name,
            "pod_uid": pod_uid,
        }
    except (AppError, ValueError, TypeError, UnicodeError, RecursionError):
        raise AppError("Owned crash-producer readiness could not be verified.") from None


async def reap_producer(process: asyncio.subprocess.Process) -> None:
    """Kill the owned producer through its guarded handle and bound its reap.

    The certificate-only producer launches no external programs. Its SDK/file
    workers are threads and end with this one process; there is no child tree.
    """
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.kill()
    async with asyncio.timeout(5):
        await process.wait()


async def verify_crash_recovery(
    cluster: OwnedCluster,
    target: ResourceTarget,
    progress: dict[str, Any],
) -> str:
    private = cluster.directory / "crash-producer-private"
    private.mkdir(mode=0o700)
    state = cluster.directory / "state-producer-crash"
    journal = NodeShellJournal(state)
    process: asyncio.subprocess.Process | None = None
    fresh: KubernetesSession | None = None
    receipt: dict[str, Any] = {
        "producer_reaped": False,
        "fresh_session_closed": False,
        "crash_private_removed": False,
    }
    progress["crash_recovery"] = receipt
    try:
        environment = {**os.environ, "KUBECONFIG": str(cluster.path), "TMPDIR": str(private)}
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                CRASH_PRODUCER,
                str(cluster.path),
                cluster.context,
                NAMESPACE,
                target.name,
                target.uid,
                str(state),
                SHELL_IMAGE,
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
                limit=4096,
            )
        )
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            await finish_owned(launch)
            process = launch.result()
            raise
        assert process.stdout is not None
        async with asyncio.timeout(150):
            marker = producer_receipt(await process.stdout.readline())
        assert process.returncode is None
        await reap_producer(process)
        assert process.returncode == -signal.SIGKILL
        receipt["producer_reaped"], receipt["producer_exit_signal"] = True, "SIGKILL"
        (record,) = await journal.scan()
        assert record.operation_id == marker["operation_id"]
        assert record.pod_name == marker["pod_name"] and record.pod_uid == marker["pod_uid"]
        assert record.pod_uid is not None
        selected = load_catalog(
            ConnectionRequest(
                kubeconfig=str(cluster.path),
                context=cluster.context,
            ),
            {},
        ).select(cluster.context)
        assert not selected.user.data.get("exec") and not selected.user.data.get("auth-provider")
        fresh = KubernetesSession(selected, 15)
        await fresh.open()
        configuration = fresh.configuration
        assert fresh.credentials is None and configuration is not None and configuration.cert_file
        assert await session_fingerprint(fresh) == record.connection_fingerprint
        receipt["fresh_certificate_fingerprint_matches"] = True
        recovery = NodeShellRecovery(journal, fresh, AccessPolicy(False), lambda: True)
        try:
            assert (await recovery.inspect(record)).code == "present_owned"
            review = await recovery.prepare_cleanup(record)
            assert (
                await recovery.cleanup(recovery.confirm(review))
            ).state is MutationState.SUCCEEDED
        finally:
            await recovery.close()
        assert await absent(fresh, record.pod_name) and await journal.scan() == ()
        receipt["known_uid_deleted_and_journal_removed"] = True
        return "real-producer-sigkill-fresh-certificate-session-reviewed-uid-recovery"
    finally:
        try:
            if process is not None:
                await finish_owned(asyncio.create_task(reap_producer(process)))
                receipt["producer_reaped"] = process.returncode is not None
        finally:
            try:
                if fresh is not None:
                    fresh_private = Path(fresh.directory.name)
                    await finish_owned(asyncio.create_task(fresh.close()))
                    receipt["fresh_session_closed"] = not fresh_private.exists()
                    assert receipt["fresh_session_closed"]
            finally:
                # SIGKILL skips Python's private TemporaryDirectory cleanup.
                # Remove only this fixture subtree after its producer is reaped.
                if process is None or process.returncode is not None:
                    await finish_owned(
                        asyncio.create_task(asyncio.to_thread(shutil.rmtree, private))
                    )
                    receipt["crash_private_removed"] = not private.exists()
                    assert receipt["crash_private_removed"]


class FaultProxy:
    """Forward one bounded request, then optionally lose its committed response."""

    def __init__(self, upstream: Any, endpoint: str, mode: str) -> None:
        self.upstream, self.endpoint, self.mode = upstream, endpoint, mode
        self.receipts: list[dict[str, Any]] = []
        self.created: dict[str, Any] | None = None
        self.replacement_uid: str | None = None

    async def handle(self, request: Any) -> Any:
        from aiohttp import web

        body = await request.read()
        if len(body) > 1024 * 1024:
            raise ValueError("Owned proxy request exceeded its fixed bound.")
        dry_run = request.query.get("dryRun") == "All"
        creating = request.method == "POST" and request.path.endswith("/pods") and not dry_run
        deleting = request.method == "DELETE" and "/pods/" in request.path
        if deleting and self.mode == "replace":
            assert self.created is not None
            original_uid = self.created["metadata"]["uid"]
            async with self.upstream.delete(
                self.endpoint + request.path,
                json={
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "gracePeriodSeconds": 0,
                    "preconditions": {"uid": original_uid},
                },
            ) as response:
                assert response.status in {200, 202}
                await response.read()
            async with asyncio.timeout(15):
                while True:
                    async with self.upstream.get(self.endpoint + request.path) as response:
                        await response.read()
                        if response.status == 404:
                            break
                    await asyncio.sleep(0.1)
            replacement = json.loads(body)
            assert replacement["preconditions"] == {"uid": original_uid}
            replacement = {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": self.created["metadata"]["name"],
                    "namespace": self.created["metadata"]["namespace"],
                },
                "spec": {
                    "containers": [
                        {
                            "name": "replacement",
                            "image": SHELL_IMAGE,
                            "command": ["/bin/sleep", "600"],
                        }
                    ]
                },
            }
            async with self.upstream.post(
                self.endpoint + request.path.rsplit("/pods/", 1)[0] + "/pods",
                json=replacement,
                params={"fieldValidation": "Strict"},
            ) as response:
                assert response.status == 201
                self.replacement_uid = (await response.json())["metadata"]["uid"]
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"accept", "content-type", "impersonate-user", "impersonate-group"}
        }
        async with self.upstream.request(
            request.method,
            self.endpoint + request.raw_path,
            data=body,
            headers=headers,
            allow_redirects=False,
        ) as response:
            payload = await response.read()
            assert len(payload) <= 8 * 1024 * 1024
            status = response.status
        self.receipts.append(
            {
                "method": request.method,
                "create": creating,
                "delete": deleting,
                "dry_run": dry_run,
                "status": status,
            }
        )
        if creating and status == 201:
            self.created = json.loads(payload)
        if (creating and self.mode == "drop_create") or (deleting and self.mode == "drop_delete"):
            request.transport.abort()
            return web.Response()
        return web.Response(status=status, body=payload, content_type="application/json")


@asynccontextmanager
async def fault_proxy(
    connection: KubernetesSession, mode: str
) -> AsyncIterator[tuple[str, FaultProxy]]:
    import aiohttp
    from aiohttp import web

    configuration = connection.configuration
    assert configuration is not None and configuration.cert_file and configuration.key_file
    context = ssl.create_default_context(cafile=configuration.ssl_ca_cert)
    context.load_cert_chain(configuration.cert_file, configuration.key_file)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=context), timeout=aiohttp.ClientTimeout(total=20)
    ) as upstream:
        fixture = FaultProxy(upstream, str(configuration.host), mode)
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_route("*", "/{path:.*}", fixture.handle)
        server = web.AppRunner(app, shutdown_timeout=1)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        try:
            yield f"http://127.0.0.1:{server.addresses[0][1]}", fixture
        finally:
            await server.cleanup()


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        *(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        root / "pyproject.toml",
        root / "uv.lock",
        root / "scripts/owned_kind.py",
        root / "scripts/verify_node_shell_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


async def verify_failures(
    cluster: OwnedCluster,
    connection: KubernetesSession,
    target: ResourceTarget,
    descriptor: ApiResource,
    settings: NodeShellSettings,
    kubectl: Path,
    progress: dict[str, Any],
    transcript: bytearray,
) -> list[str]:
    assert connection.api is not None
    api, rbac = sdk.CoreV1Api(connection.api), sdk.RbacAuthorizationV1Api(connection.api)
    environment = {
        **os.environ,
        "PATH": str(kubectl.parent) + os.pathsep + os.environ.get("PATH", ""),
    }
    checks: list[str] = []
    clients: list[KubernetesSession] = []
    managers: list[NodeShellManager] = []

    def owner(
        client: KubernetesSession, *, label: str, configuration: NodeShellSettings = settings
    ) -> tuple[NodeShellManager, NodeShellService]:
        manager = NodeShellManager(NodeShellJournal(cluster.directory / ("state-" + label)))
        managers.append(manager)
        service = manager.create(
            client,
            descriptor,
            target,
            AccessPolicy(False),
            lambda: True,
            settings=configuration,
            config_generation=1,
            current_config=lambda: 1,
            environment=environment,
            directory=cluster.directory,
        )
        return manager, service

    try:
        progress["phase"] = "real-psa-rejection"
        restricted_namespace = NAMESPACE + "-restricted"
        await api.create_namespace(
            sdk.V1Namespace(
                metadata=sdk.V1ObjectMeta(
                    name=restricted_namespace,
                    labels={"pod-security.kubernetes.io/enforce": "restricted"},
                )
            )
        )
        manager, service = owner(
            connection, label="psa", configuration=replace(settings, namespace=restricted_namespace)
        )
        try:
            await service.prepare()
        except AppError:
            pass
        else:
            raise AssertionError(
                "Restricted Pod Security unexpectedly admitted privileged node shell."
            )
        await service.close()
        assert manager.active_count == 0 and await manager.scan() == ()
        assert not (await api.list_namespaced_pod(restricted_namespace)).items
        checks.append("real-pod-security-denial-no-policy-relaxation-no-persisted-pod")

        progress["phase"] = "real-rbac-create-and-exec-denial"
        identity = "kuberich-owned-node-shell-operator"
        await rbac.create_cluster_role(
            sdk.V1ClusterRole(
                metadata=sdk.V1ObjectMeta(name=identity),
                rules=[
                    sdk.V1PolicyRule(
                        api_groups=[""],
                        resources=["nodes", "namespaces"],
                        verbs=["get"],
                        resource_names=[target.name, NAMESPACE],
                    ),
                ],
            )
        )
        await rbac.create_cluster_role_binding(
            sdk.V1ClusterRoleBinding(
                metadata=sdk.V1ObjectMeta(name=identity),
                role_ref=sdk.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="ClusterRole", name=identity
                ),
                subjects=[sdk.RbacV1Subject(kind="User", name=identity)],
            )
        )
        await rbac.create_namespaced_role(
            NAMESPACE,
            sdk.V1Role(
                metadata=sdk.V1ObjectMeta(name=identity),
                rules=[sdk.V1PolicyRule(api_groups=[""], resources=["pods"], verbs=["get"])],
            ),
        )
        await rbac.create_namespaced_role_binding(
            NAMESPACE,
            sdk.V1RoleBinding(
                metadata=sdk.V1ObjectMeta(name=identity),
                role_ref=sdk.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="Role", name=identity
                ),
                subjects=[sdk.RbacV1Subject(kind="User", name=identity)],
            ),
        )
        selected = load_catalog(
            ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context), {}
        ).select(cluster.context, ConnectionOverrides(as_user=identity))
        restricted = KubernetesSession(selected, 15)
        clients.append(restricted)
        await restricted.open()
        manager, service = owner(restricted, label="create-denied")
        try:
            await service.prepare()
        except AppError:
            pass
        else:
            raise AssertionError("Create-denied identity unexpectedly passed node-shell dry-run.")
        await service.close()
        assert await manager.scan() == ()
        checks.append("real-rbac-create-denied-before-persisted-pod")
        await rbac.patch_namespaced_role(
            identity,
            NAMESPACE,
            {
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods"],
                        "verbs": ["get", "create", "delete"],
                    }
                ]
            },
        )
        manager, service = owner(restricted, label="exec-denied")
        intent = await service.prepare()
        assert (await service.execute(service.confirm(intent))).state is MutationState.SUCCEEDED
        assert service.observation.state is NodeShellState.READY
        terminal, request = await service.shell()
        async with ProcessRunner(AccessPolicy(False)) as runner:
            async with (
                terminal.stage(request) as command,
                runner.terminal(command, width=90, height=28, guard=terminal.require_current) as (
                    endpoint,
                    process,
                ),
            ):
                async with asyncio.timeout(20):
                    while data := await endpoint.read():
                        transcript.extend(data)
                        assert len(transcript) <= 65536
                    assert (await process.wait()).returncode != 0
            assert runner.active_count == 0
        assert b"forbidden" in transcript.lower() and await absent(connection, intent.pod_name)
        checks.append("real-rbac-exec-denied-existing-pty-restored-owned-pod-cleaned")

        progress["phase"] = "real-delete-denial-and-explicit-known-uid-recovery"
        await rbac.patch_namespaced_role(
            identity,
            NAMESPACE,
            {
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods"],
                        "verbs": ["get", "create"],
                    }
                ]
            },
        )
        manager, service = owner(restricted, label="delete-denied")
        intent = await service.prepare()
        await service.execute(service.confirm(intent))
        assert service.observation.state is NodeShellState.READY
        await service.close()
        (record,) = await manager.scan()
        after_close = service.observation
        assert record.pod_uid is not None and after_close.state is NodeShellState.PENDING
        readonly = NodeShellRecovery(manager.journal, restricted, AccessPolicy(True), lambda: True)
        try:
            try:
                await readonly.prepare_cleanup(record)
            except AppError:
                pass
            else:
                raise AssertionError("Read-only recovery unexpectedly authorized DELETE.")
        finally:
            await readonly.close()
        assert not await absent(connection, intent.pod_name)
        await rbac.patch_namespaced_role(
            identity,
            NAMESPACE,
            {
                "rules": [
                    {
                        "apiGroups": [""],
                        "resources": ["pods"],
                        "verbs": ["get", "create", "delete"],
                    }
                ]
            },
        )
        recovery = NodeShellRecovery(manager.journal, restricted, AccessPolicy(False), lambda: True)
        try:
            review = await recovery.prepare_cleanup(record)
            result = await recovery.cleanup(recovery.confirm(review))
            assert result.state is MutationState.SUCCEEDED
        finally:
            await recovery.close()
        assert await manager.scan() == () and await absent(connection, intent.pod_name)
        checks.append("real-delete-denial-retained-uid-readonly-block-explicit-matching-recovery")

        progress["phase"] = "real-scheduler-cordon-startup-timeout"
        await api.patch_node(target.name, {"spec": {"unschedulable": True}})
        try:
            manager, service = owner(
                connection,
                label="timeout",
                configuration=replace(settings, startup_timeout_seconds=5),
            )
            intent = await service.prepare()
            result = await service.execute(service.confirm(intent))
            assert result.state is MutationState.SUCCEEDED
            assert (
                service.observation.code == "startup_timeout"
                and service.observation.state is NodeShellState.CLOSED
            )
            assert await absent(connection, intent.pod_name) and await manager.scan() == ()
            manager, service = owner(connection, label="wait-interrupted")
            intent = await service.prepare()
            wait_operation = asyncio.create_task(service.execute(service.confirm(intent)))
            async with asyncio.timeout(15):
                while service.observation.state is not NodeShellState.WAITING:
                    if wait_operation.done():
                        raise AssertionError(
                            "Interrupted scheduling fixture did not reach waiting."
                        )
                    await asyncio.sleep(0.05)
            wait_operation.cancel()
            assert (await wait_operation).state is MutationState.SUCCEEDED
            assert await absent(connection, intent.pod_name) and await manager.scan() == ()
        finally:
            await api.patch_node(target.name, {"spec": {"unschedulable": False}})
        checks.append("real-normal-scheduler-cordoned-node-timeout-no-toleration-or-policy-change")
        checks.append("real-interrupted-scheduling-wait-drains-create-receipt-and-owned-cleanup")

        progress["phase"] = "real-admission-drift-after-review-preserved-uid"
        manager, service = owner(connection, label="admission")
        intent = await service.prepare()
        await api.create_namespaced_limit_range(
            NAMESPACE,
            sdk.V1LimitRange(
                metadata=sdk.V1ObjectMeta(name="owned-inject-storage"),
                spec=sdk.V1LimitRangeSpec(
                    limits=[
                        sdk.V1LimitRangeItem(
                            type="Container",
                            default={"ephemeral-storage": "2Mi"},
                            default_request={"ephemeral-storage": "1Mi"},
                        )
                    ]
                ),
            ),
        )
        try:
            result = await service.execute(service.confirm(intent))
            assert result.state is MutationState.UNCERTAIN
            assert (
                service.observation.pod_uid is not None
                and service.observation.code == "admission_drift"
            )
            assert await absent(connection, intent.pod_name) and await manager.scan() == ()
        finally:
            await api.delete_namespaced_limit_range("owned-inject-storage", NAMESPACE)
        checks.append("real-limitranger-admission-drift-returned-uid-retained-no-exec-cleaned")

        progress["phase"] = "real-interrupted-exec-pty-drains-before-delete"
        manager, service = owner(connection, label="exec-interrupted")
        intent = await service.prepare()
        await service.execute(service.confirm(intent))
        terminal, request = await service.shell()
        entered = asyncio.Event()
        async with ProcessRunner(AccessPolicy(False)) as runner:

            async def interrupted_exec() -> None:
                async with (
                    terminal.stage(request) as command,
                    runner.terminal(
                        command, width=90, height=28, guard=terminal.require_current
                    ) as (endpoint, _),
                ):
                    endpoint.write(b"sleep 600\n")
                    entered.set()
                    while await endpoint.read():
                        pass

            exec_operation = asyncio.create_task(interrupted_exec())
            await entered.wait()
            await manager.close()
            assert exec_operation.cancelled() and runner.active_count == 0
        assert service.observation.code == "interrupted" and await manager.scan() == ()
        assert await absent(connection, intent.pod_name)
        checks.append("real-interrupted-live-exec-reaped-pty-before-uid-deletion")

        for mode in ("drop_create", "drop_delete", "replace"):
            progress["phase"] = "real-bounded-proxy-" + mode
            async with fault_proxy(connection, mode) as (proxy_endpoint, proxy):
                proxied = KubernetesSession(
                    replace(
                        connection.context,
                        cluster=Entry({"server": proxy_endpoint}, cluster.directory),
                        user=Entry({}, cluster.directory),
                    ),
                    15,
                )
                clients.append(proxied)
                await proxied.open()
                manager, service = owner(proxied, label=mode)
                intent = await service.prepare()
                result = await service.execute(service.confirm(intent))
                assert sum(receipt["create"] for receipt in proxy.receipts) == 1
                if mode == "drop_create":
                    assert (
                        result.state is MutationState.UNCERTAIN
                        and service.observation.pod_uid is None
                    )
                    (record,) = await manager.scan()
                    assert record.pod_uid is None and not any(
                        receipt["delete"] for receipt in proxy.receipts
                    )
                    assert not await absent(connection, intent.pod_name)
                    # Fixture teardown knows the upstream receipt. Product never
                    # adopts this identity; forgetting remains a local action.
                    assert proxy.created is not None
                    await api.delete_namespaced_pod(
                        intent.pod_name,
                        NAMESPACE,
                        body=sdk.V1DeleteOptions(
                            grace_period_seconds=0,
                            preconditions=sdk.V1Preconditions(uid=proxy.created["metadata"]["uid"]),
                        ),
                    )
                    await wait_absent(connection, intent.pod_name)
                    recovery = NodeShellRecovery(
                        manager.journal, None, AccessPolicy(True), lambda: False
                    )
                    try:
                        review = await recovery.prepare_forget(record)
                        assert (
                            await recovery.forget(recovery.confirm(review))
                        ).state is MutationState.SUCCEEDED
                    finally:
                        await recovery.close()
                else:
                    assert (
                        result.state is MutationState.SUCCEEDED
                        and service.observation.state is NodeShellState.READY
                    )
                    await service.close()
                    assert sum(receipt["delete"] for receipt in proxy.receipts) == 1
                    assert await manager.scan() == ()
                    if mode == "replace":
                        replacement = await api.read_namespaced_pod(intent.pod_name, NAMESPACE)
                        assert replacement.metadata.uid == proxy.replacement_uid
                        assert any(
                            receipt["delete"] and receipt["status"] == 409
                            for receipt in proxy.receipts
                        )
                    else:
                        assert await absent(connection, intent.pod_name)
                progress.setdefault("proxy_receipts", {})[mode] = proxy.receipts
            checks.append("real-single-attempt-proxy-" + mode)
        return checks
    finally:
        for manager in managers:
            await manager.close()
        for client in reversed(clients):
            private = Path(client.directory.name)
            await client.close()
            assert not private.exists()


async def verify(
    cluster: OwnedCluster,
    evidence: Path,
    kubectl: Path,
    progress: dict[str, Any],
) -> dict[str, Any]:
    original = cluster.path.read_bytes()
    environment = dict(os.environ)
    policy = AccessPolicy(False)
    journal = NodeShellJournal(cluster.directory / "node-shell-state")
    manager, runner = NodeShellManager(journal), ProcessRunner(policy)
    selected = load_catalog(
        ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context), {}
    ).select(cluster.context)
    connection = KubernetesSession(selected, 15)
    private = Path(connection.directory.name)
    transcript = bytearray()
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            await connection.open()
            assert connection.api is not None
            api = sdk.CoreV1Api(connection.api)
            await api.create_namespace(sdk.V1Namespace(metadata=sdk.V1ObjectMeta(name=NAMESPACE)))
            sentinel = await api.create_namespaced_pod(
                NAMESPACE,
                sdk.V1Pod(
                    metadata=sdk.V1ObjectMeta(name="unrelated-sentinel", namespace=NAMESPACE),
                    spec=sdk.V1PodSpec(
                        containers=[
                            sdk.V1Container(
                                name="sentinel",
                                image=SHELL_IMAGE,
                                command=["/bin/sleep", "600"],
                            )
                        ]
                    ),
                ),
            )
            sentinel_uid = sentinel.metadata.uid
            nodes = await api.list_node()
            node = nodes.items[0]
            target = ResourceTarget(
                SessionIdentity(cluster.context, 1),
                "",
                "nodes",
                None,
                node.metadata.name,
                node.metadata.uid,
            )
            descriptor = ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list"}))
            settings = NodeShellSettings(
                enabled=True,
                namespace=NAMESPACE,
                image=SHELL_IMAGE,
                startup_timeout_seconds=120,
                session_timeout_seconds=60,
            )
            owner = manager.create(
                connection,
                descriptor,
                target,
                policy,
                lambda: True,
                settings=settings,
                config_generation=1,
                current_config=lambda: 1,
                environment={
                    **environment,
                    "PATH": str(kubectl.parent) + os.pathsep + environment.get("PATH", ""),
                },
                directory=cluster.directory,
            )
            progress["phase"] = "production-dry-run"
            intent = await owner.prepare()
            progress["pod_name"] = intent.pod_name
            progress["phase"] = "production-create-receipt-journal-readiness"
            result = await owner.execute(owner.confirm(intent))
            progress["create_state"] = result.state.value
            progress["owner_state"] = owner.observation.state.value
            progress["owner_code"] = owner.observation.code
            assert (
                result.state is MutationState.SUCCEEDED
                and owner.observation.state is NodeShellState.READY
            )
            record = await owner.durable_record()
            assert record is not None and record.pod_uid == owner.observation.pod_uid
            admitted = await api.read_namespaced_pod(intent.pod_name, NAMESPACE)
            assert admitted.spec.node_name == target.name
            terminal, request = await owner.shell()
            progress["phase"] = "production-owned-pty-exec"
            async with (
                terminal.stage(request) as command,
                runner.terminal(command, width=90, height=28, guard=terminal.require_current) as (
                    endpoint,
                    process,
                ),
            ):
                endpoint.write(
                    b"test -d /host/etc/kubernetes && "
                    b'test "$(readlink /proc/self/ns/pid)" = "$(readlink /proc/1/ns/pid)" && '
                    b'test "$(readlink /proc/self/ns/net)" = "$(readlink /proc/1/ns/net)" && '
                    b'test "$(readlink /proc/self/ns/ipc)" = "$(readlink /proc/1/ns/ipc)" && '
                    b"printf 'NODE_%s_OK\\n' SHELL; exit\n"
                )
                async with asyncio.timeout(30):
                    while data := await endpoint.read():
                        transcript.extend(data)
                        assert len(transcript) <= 65536
                    assert (await process.wait()).returncode == 0
            assert b"NODE_SHELL_OK" in transcript
            progress["phase"] = "asserting-uid-cleanup-and-sentinel"
            try:
                await connection.get_json(f"/api/v1/namespaces/{NAMESPACE}/pods/{intent.pod_name}")
            except HttpProblem as error:
                assert error.status == 404
            else:
                raise AssertionError(
                    "The production-owned diagnostic Pod remained after terminal return."
                )
            assert (
                await api.read_namespaced_pod("unrelated-sentinel", NAMESPACE)
            ).metadata.uid == sentinel_uid
            assert await journal.scan() == () and manager.active_count == runner.active_count == 0
            after_close = owner.observation
            assert after_close.state is NodeShellState.CLOSED
            failures = await verify_failures(
                cluster, connection, target, descriptor, settings, kubectl, progress, transcript
            )
            progress["phase"] = "real-producer-sigkill-fresh-certificate-recovery"
            failures.append(await verify_crash_recovery(cluster, target, progress))
            assert (
                await api.read_namespaced_pod("unrelated-sentinel", NAMESPACE)
            ).metadata.uid == sentinel_uid
            return {
                "checks": [
                    "real-profile-dry-run-create-durable-uid-readiness",
                    "real-owned-kubectl-pty-host-root-pid-network-ipc",
                    "real-uid-guarded-delete-observed-absence-journal-removal",
                    "unrelated-sentinel-uid-preserved-local-children-reaped",
                    *failures,
                ],
                "node_image": NODE_IMAGE,
                "shell_image": SHELL_IMAGE,
                "owned_kubeconfig_unchanged": cluster.path.read_bytes() == original,
                "environment_unchanged": dict(os.environ) == environment,
            }
    finally:
        await manager.close()
        await runner.close()
        await connection.close()
        assert not private.exists()
        assert cluster.path.read_bytes() == original and dict(os.environ) == environment
        progress["private_sessions_deleted"] = True
        progress["owners_drained"] = manager.active_count == runner.active_count == 0
        # Only this synthetic fixture terminal is recorded; no user context is used.
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.with_name("node-shell-pty.txt").write_bytes(transcript)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, type=Path)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    if args.evidence.exists() or args.evidence.with_name("node-shell-pty.txt").exists():
        raise ValueError("Use fresh node-shell evidence paths; preserve previous outcomes.")
    if not args.kind.is_absolute() or not args.kubectl.is_absolute():
        raise ValueError("Use explicit verified kind and kubectl fixture paths.")
    if sha256_file(args.kind) != KIND_SHA256:
        raise ValueError("Use the checksum-verified official kind v0.33.0 fixture.")
    if sha256_file(args.kubectl) != KUBECTL_SHA256:
        raise ValueError("Use the checksum-verified official kubectl v1.36.4 fixture.")
    root = Path(__file__).resolve().parents[1]
    captured = input_hashes(root)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "deadline_seconds": VERIFY_SECONDS,
        "owned_cluster_deleted": False,
        "tools": {
            "kind_sha256": hashlib.sha256(args.kind.read_bytes()).hexdigest(),
            "kubectl_sha256": hashlib.sha256(args.kubectl.read_bytes()).hexdigest(),
        },
    }
    started, cluster = time.monotonic(), None
    try:
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            result.update(asyncio.run(verify(cluster, args.evidence, args.kubectl, result)))
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        assert result["inputs_unchanged"] and result["private_directory_deleted"]
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
            try:
                remaining = run_owned(
                    [
                        args.docker,
                        "ps",
                        "--all",
                        "--filter",
                        "label=io.x-k8s.kind.cluster=" + cluster.name,
                        "--format",
                        "{{.ID}}",
                    ],
                    capture_docker(args.docker),
                )
                result["owned_cluster_deleted"] = not remaining.strip()
            except Exception:
                result["owned_cluster_deleted"] = False
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Owned-kind production node-shell proof passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned node-shell proof failed ({type(error).__name__}); retain evidence.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
