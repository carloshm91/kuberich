"""Prove reviewed append-only debugging and actual attach in one owned kind cluster."""

import argparse
import asyncio
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as sdk
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import Entry, load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.ephemeral_debug import EphemeralDebugOptions
from kuberich.domain.mutations import MutationState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.ephemeral_debug import EphemeralDebugService
from kuberich.services.logs import PODS
from kuberich.services.processes import ProcessRunner
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster, run_owned
from scripts.verify_node_maintenance_kind import KUBECTL_SHA256

NAMESPACE = "kuberich-ephemeral-debug"
VERIFY_SECONDS = 600
PROOF_INPUTS = (
    "pyproject.toml",
    "uv.lock",
    "scripts/diagnostics_tools.py",
    "scripts/owned_kind.py",
    "scripts/verify_node_maintenance_kind.py",
    "scripts/verify_ephemeral_debug_kind.py",
    "tests/support/ephemeral_debug_terminal.py",
)


class DebugProxy:
    """Count only production traffic; lose an actual committed append receipt on demand."""

    def __init__(self, upstream: Any, endpoint: str) -> None:
        self.upstream, self.endpoint = upstream, endpoint
        self.receipts: list[dict[str, Any]] = []
        self.drop_name: str | None = None

    async def handle(self, request: Any) -> Any:
        from aiohttp import web

        body = await request.read()
        if len(body) > 1024 * 1024:
            raise ValueError("Owned debug request exceeded its fixed bound.")
        receipt: dict[str, Any] = {"method": request.method, "path": request.path}
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self.websocket(request, receipt)
        append = request.method == "PATCH" and request.path.endswith("/ephemeralcontainers")
        name = None
        if append:
            value = json.loads(body)
            assert len(value) == 3
            assert value[0]["op"] == value[1]["op"] == "test"
            assert value[0]["path"] == "/metadata/uid"
            assert value[1]["path"] == "/metadata/resourceVersion"
            assert value[2]["op"] == "add"
            assert value[2]["path"] in {
                "/spec/ephemeralContainers",
                "/spec/ephemeralContainers/-",
            }
            declaration = value[2]["value"]
            if isinstance(declaration, list):
                assert len(declaration) == 1
                declaration = declaration[0]
            name = declaration["name"]
            receipt.update(
                uid=value[0]["value"],
                resource_version=value[1]["value"],
                name=name,
                append_path=value[2]["path"],
                body_sha256=hashlib.sha256(body).hexdigest(),
                dry_run=request.query.get("dryRun") == "All",
                strict=request.query.get("fieldValidation") == "Strict",
                content_type=request.headers.get("Content-Type"),
            )
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"accept", "content-type", "impersonate-user", "impersonate-group"}
        }
        async with self.upstream.request(
            request.method,
            self.endpoint + request.raw_path,
            data=body if body else None,
            headers=headers,
            allow_redirects=False,
        ) as response:
            payload = await response.read()
            assert len(payload) <= 8 * 1024 * 1024
            receipt["status"] = response.status
        self.receipts.append(receipt)
        if append and not receipt["dry_run"] and name == self.drop_name and response.status == 200:
            self.drop_name = None
            receipt["owned_fault"] = "post-commit-response-loss"
            request.transport.abort()
            return web.Response()
        return web.Response(status=response.status, body=payload, content_type="application/json")

    async def websocket(self, request: Any, receipt: dict[str, Any]) -> Any:
        """Relay the pinned kubectl WebSocket transport without recording terminal bytes."""
        import aiohttp
        from aiohttp import web

        assert request.method == "GET" and request.path.endswith("/attach")
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() in {"impersonate-user", "impersonate-group"}
        }
        protocols = tuple(
            part.strip() for part in request.headers.get("Sec-WebSocket-Protocol", "").split(",")
        )
        try:
            upstream = await self.upstream.ws_connect(
                self.endpoint + request.raw_path, headers=headers, protocols=protocols
            )
        except aiohttp.WSServerHandshakeError as error:
            receipt.update(status=error.status, transport="websocket")
            self.receipts.append(receipt)
            return web.Response(status=error.status)
        async with upstream:
            downstream = web.WebSocketResponse(
                protocols=(upstream.protocol,) if upstream.protocol else ()
            )
            await downstream.prepare(request)
            receipt.update(status=101, transport="websocket")
            self.receipts.append(receipt)

            async def relay(source: Any, destination: Any) -> None:
                async for message in source:
                    if message.type is aiohttp.WSMsgType.BINARY:
                        await destination.send_bytes(message.data)
                    elif message.type is aiohttp.WSMsgType.TEXT:
                        await destination.send_str(message.data)
                    elif message.type is aiohttp.WSMsgType.ERROR:
                        raise RuntimeError("Owned debug WebSocket relay failed.")

            tasks = [
                asyncio.create_task(relay(upstream, downstream)),
                asyncio.create_task(relay(downstream, upstream)),
            ]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                await downstream.close()
            for result in results:
                if isinstance(result, Exception):
                    raise result
            return downstream


@asynccontextmanager
async def observed_client(
    connection: KubernetesSession, *, as_user: str | None = None
) -> AsyncIterator[tuple[KubernetesSession, DebugProxy]]:
    """Forward through the owned cluster's mTLS identity without retaining credentials."""
    import aiohttp
    from aiohttp import web

    configuration = connection.configuration
    assert configuration is not None and configuration.cert_file and configuration.key_file
    context = ssl.create_default_context(cafile=configuration.ssl_ca_cert)
    context.load_cert_chain(configuration.cert_file, configuration.key_file)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=context), timeout=aiohttp.ClientTimeout(total=20)
    ) as upstream:
        proxy = DebugProxy(upstream, str(configuration.host))
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_route("*", "/{path:.*}", proxy.handle)
        server = web.AppRunner(app, shutdown_timeout=1)
        await server.setup()
        try:
            site = web.TCPSite(server, "127.0.0.1", 0)
            await site.start()
            selected = replace(
                connection.context,
                cluster=Entry(
                    {"server": f"http://127.0.0.1:{server.addresses[0][1]}"},
                    connection.context.cluster.directory,
                ),
                user=Entry({"as": as_user} if as_user else {}, connection.context.user.directory),
            )
            client = KubernetesSession(selected, connection.timeout)
            private = Path(client.directory.name)
            try:
                await client.open()
                yield client, proxy
            finally:
                await client.close()
                assert not private.exists()
        finally:
            await server.cleanup()


def input_hashes(root: Path) -> dict[str, str]:
    """Bind the runtime, assets, locks, inherited tooling constants and actual proof code."""
    paths = [
        *(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        *(root / name for name in PROOF_INPUTS),
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def source_identity(root: Path) -> str:
    """Refuse measurements of uncommitted or untracked proof/runtime inputs."""
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        timeout=10,
    )
    if status.stdout:
        raise ValueError("Commit and freeze clean tracked source before creating a proof cluster.")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()


async def wait_for(predicate: Callable[[], Awaitable[bool]], *, seconds: float = 60) -> None:
    """Wait on fresh observed state under a finite fixture deadline."""
    async with asyncio.timeout(seconds):
        while not await predicate():
            await asyncio.sleep(0.1)


async def terminal_trial(
    service: EphemeralDebugService, name: str, *, detach: bool
) -> dict[str, Any]:
    """Run the production attach lease through the production PTY, then reap it."""
    terminal, request = await service.prepare_shell(name)
    transcript = bytearray()
    marker = b"OWNED-DEBUG-DETACH" if detach else b"OWNED-DEBUG-COMPLETE"
    async with ProcessRunner(AccessPolicy(False)) as runner:
        async with (
            terminal.stage(request) as command,
            runner.terminal(command, width=90, height=28, guard=terminal.require_current) as (
                endpoint,
                process,
            ),
        ):
            assert command.argv[4] == "attach" and "debug" not in command.argv
            pid = process.pid
            async with asyncio.timeout(30):
                while b"$" not in transcript and b"#" not in transcript:
                    data = await endpoint.read()
                    assert data, "Owned debug shell exited before attach input."
                    transcript.extend(data)
                    assert len(transcript) <= 65536
                endpoint.write(b"printf '%s%s\\n' 'OWNED-' '" + marker[6:] + b"'\r")
                while marker not in transcript:
                    transcript.extend(await endpoint.read())
                    assert len(transcript) <= 65536
                endpoint.resize(52, 18)
                endpoint.write(b"\x10\x11" if detach else b"exit 7\r")
                while data := await endpoint.read():
                    transcript.extend(data)
                    assert len(transcript) <= 65536
                result = await process.wait()
        assert runner.active_count == 0
    assert not request.path.exists()
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Owned kubectl attach survived terminal drainage.")
    assert result.returncode == (0 if detach else 7)
    return {
        "returncode": result.returncode,
        "input_output_observed": marker in transcript,
        "resize": [52, 18],
        "delegation_deleted": not request.path.exists(),
        "process_reaped": True,
        "transcript_sha256": hashlib.sha256(transcript).hexdigest(),
    }


async def verify(cluster: OwnedCluster, progress: dict[str, Any], kubectl: Path) -> dict[str, Any]:
    """Use direct fixture setup and separately observed production service operations."""
    original, environment = cluster.path.read_bytes(), dict(os.environ)
    sentinel = cluster.directory / "caller-kubeconfig-sentinel"
    sentinel_bytes = b"Owned synthetic ambient sentinel; never a kubeconfig.\n"
    sentinel.write_bytes(sentinel_bytes)
    selected = load_catalog(
        ConnectionRequest(kubeconfig=str(cluster.path), context=cluster.context),
        {**environment, "KUBECONFIG": str(sentinel)},
    ).select(cluster.context)
    connection = KubernetesSession(selected, 15)
    private = Path(connection.directory.name)
    stack = AsyncExitStack()
    owners: list[EphemeralDebugService] = []
    checks: list[str] = []
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            await connection.open()
            assert connection.api is not None and connection.credentials is None
            core: Any = sdk.CoreV1Api(connection.api)
            await core.create_namespace(sdk.V1Namespace(metadata=sdk.V1ObjectMeta(name=NAMESPACE)))
            progress["phase"] = "owned-live-pod-fixture"
            await core.create_namespaced_pod(
                NAMESPACE,
                {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {"name": "workload"},
                    "spec": {
                        "terminationGracePeriodSeconds": 1,
                        "initContainers": [
                            {"name": "setup", "image": SHELL_IMAGE, "command": ["/bin/true"]}
                        ],
                        "containers": [
                            {
                                "name": "app",
                                "image": SHELL_IMAGE,
                                "command": ["/bin/sleep", "600"],
                            }
                        ],
                    },
                },
            )

            async def manifest() -> dict[str, Any]:
                return await connection.get_json(f"/api/v1/namespaces/{NAMESPACE}/pods/workload")

            async def ready() -> bool:
                pod = await manifest()
                return any(
                    status.get("state", {}).get("running")
                    for status in pod.get("status", {}).get("containerStatuses", [])
                )

            await wait_for(ready, seconds=120)
            before = await manifest()
            uid = before["metadata"]["uid"]
            workload_spec = before["spec"]["containers"]
            product, proxy = await stack.enter_async_context(observed_client(connection))
            progress["production_http_receipts"] = proxy.receipts
            session = SessionIdentity(cluster.context, 1)
            target = ResourceTarget(session, "", "pods", NAMESPACE, "workload", uid)
            delegated_environment = {
                **environment,
                "KUBECONFIG": str(sentinel),
                "PATH": str(kubectl.parent) + os.pathsep + environment.get("PATH", ""),
            }

            def owner(client: KubernetesSession = product) -> EphemeralDebugService:
                service = EphemeralDebugService(
                    client,
                    PODS,
                    target,
                    AccessPolicy(False),
                    lambda: True,
                    environment=delegated_environment,
                    directory=cluster.directory,
                )
                owners.append(service)
                return service

            async def remote(name: str, state: str) -> bool:
                pod = await manifest()
                assert pod["metadata"]["uid"] == uid
                return any(
                    item.get("name") == name and state in item.get("state", {})
                    for item in pod.get("status", {}).get("ephemeralContainerStatuses", [])
                )

            service = owner()
            progress["phase"] = "production-strict-dry-run"
            options = EphemeralDebugOptions("debug-complete", SHELL_IMAGE, ("/bin/sh",), "app")
            review = await service.prepare(options)
            dry = await manifest()
            assert not dry["spec"].get("ephemeralContainers")
            assert dry["metadata"]["uid"] == uid
            checks.append("real-strict-conditional-dry-run-persists-nothing")
            progress["phase"] = "production-exact-confirmed-append"
            result = await service.execute(service.confirm(review))
            assert result.state is MutationState.SUCCEEDED
            persisted = await manifest()
            assert [item["name"] for item in persisted["spec"]["ephemeralContainers"]] == [
                options.name
            ]
            assert persisted["metadata"]["uid"] == uid
            assert persisted["spec"]["containers"] == workload_spec
            progress["first_append"] = {
                "uid": uid,
                "resource_version": persisted["metadata"]["resourceVersion"],
                "declaration": persisted["spec"]["ephemeralContainers"][0],
            }
            checks.append("real-exact-uid-resourceversion-one-entry-append-workload-unchanged")
            await wait_for(lambda: remote(options.name, "running"))
            progress["phase"] = "production-kubectl-attach-completion"
            progress["completion_pty"] = await terminal_trial(service, options.name, detach=False)
            await wait_for(lambda: remote(options.name, "terminated"))
            completed = await manifest()
            status = next(
                item
                for item in completed["status"]["ephemeralContainerStatuses"]
                if item["name"] == options.name
            )
            assert status["state"]["terminated"]["exitCode"] == 7
            checks.append("real-attach-literal-input-output-exit7-fresh-remote-completed")

            progress["phase"] = "real-completed-entry-immutable-server-contract"
            for label, operation in (
                (
                    "edit",
                    {"op": "replace", "path": "/spec/ephemeralContainers/0/image", "value": "no"},
                ),
                ("remove", {"op": "remove", "path": "/spec/ephemeralContainers/0"}),
            ):
                current = await manifest()
                patch = [
                    {"op": "test", "path": "/metadata/uid", "value": uid},
                    {
                        "op": "test",
                        "path": "/metadata/resourceVersion",
                        "value": current["metadata"]["resourceVersion"],
                    },
                    operation,
                ]
                try:
                    await core.patch_namespaced_pod_ephemeralcontainers(
                        "workload", NAMESPACE, patch, _content_type="application/json-patch+json"
                    )
                except ApiException as error:
                    assert error.status == 422
                    progress.setdefault("server_refusals", {})[label] = error.status
                else:
                    raise AssertionError("The server permitted changing an existing debug entry.")
                assert (await manifest())["spec"]["ephemeralContainers"] == completed["spec"][
                    "ephemeralContainers"
                ]
            checks.append("real-server-rejects-edit-and-removal-of-completed-entry")

            progress["phase"] = "real-uid-version-and-all-category-server-refusals"
            for label in ("uid", "resourceVersion", "app", "setup", options.name):
                current = await manifest()
                entry = dict(completed["spec"]["ephemeralContainers"][0])
                entry["name"] = (
                    label if label not in {"uid", "resourceVersion"} else "debug-conflict"
                )
                expected = {
                    "uid": uid,
                    "resourceVersion": current["metadata"]["resourceVersion"],
                }
                if label in expected:
                    expected[label] = "stale-" + expected[label]
                patch = [
                    {"op": "test", "path": "/metadata/uid", "value": expected["uid"]},
                    {
                        "op": "test",
                        "path": "/metadata/resourceVersion",
                        "value": expected["resourceVersion"],
                    },
                    {"op": "add", "path": "/spec/ephemeralContainers/-", "value": entry},
                ]
                try:
                    await core.patch_namespaced_pod_ephemeralcontainers(
                        "workload", NAMESPACE, patch, _content_type="application/json-patch+json"
                    )
                except ApiException as error:
                    assert error.status == 422
                    progress["server_refusals"][label] = error.status
                else:
                    raise AssertionError("The server accepted stale preconditions or a duplicate.")
                assert (await manifest())["spec"]["ephemeralContainers"] == completed["spec"][
                    "ephemeralContainers"
                ]
            checks.append(
                "real-server-failed-uid-resourceversion-tests-and-all-category-duplicates422"
            )

            progress["phase"] = "production-repeated-name-refusals"
            writes_before = len(proxy.receipts)
            for name in ("app", "setup", options.name):
                duplicate = owner()
                try:
                    await duplicate.prepare(replace(options, name=name))
                except AppError:
                    pass
                else:
                    raise AssertionError("Production accepted an existing container name.")
            assert not any(item["method"] == "PATCH" for item in proxy.receipts[writes_before:])
            checks.append("real-regular-init-completed-debug-name-collisions-no-write")

            stale = owner()
            stale_review = await stale.prepare(replace(options, name="debug-stale-review"))
            await core.patch_namespaced_pod(
                "workload",
                NAMESPACE,
                {"metadata": {"labels": {"owned-fixture-revision": "changed"}}},
            )
            sent = sum(
                item["method"] == "PATCH" and not item.get("dry_run") for item in proxy.receipts
            )
            assert (
                await stale.execute(stale.confirm(stale_review))
            ).state is MutationState.CONFLICT
            assert sent == sum(
                item["method"] == "PATCH" and not item.get("dry_run") for item in proxy.receipts
            )
            checks.append("production-fresh-read-refuses-stale-review-without-append-or-rebase")

            progress["phase"] = "production-detach-keeps-remote-running"
            detached = owner()
            detached_options = replace(options, name="debug-detach")
            detach_review = await detached.prepare(detached_options)
            assert (
                await detached.execute(detached.confirm(detach_review))
            ).state is MutationState.SUCCEEDED
            await wait_for(lambda: remote(detached_options.name, "running"))
            progress["detach_pty"] = await terminal_trial(
                detached, detached_options.name, detach=True
            )
            assert await remote(detached_options.name, "running")
            checks.append("real-ctrl-p-ctrl-q-detach-reaps-local-pty-remote-still-running")

            progress["phase"] = "production-response-loss-after-commit"
            uncertain = owner()
            uncertain_options = replace(options, name="debug-lost-receipt")
            uncertain_review = await uncertain.prepare(uncertain_options)
            proxy.drop_name = uncertain_options.name
            result = await uncertain.execute(uncertain.confirm(uncertain_review))
            assert result.state is MutationState.UNCERTAIN
            persisted_names = [
                item["name"] for item in (await manifest())["spec"]["ephemeralContainers"]
            ]
            assert persisted_names.count(uncertain_options.name) == 1
            try:
                await uncertain.prepare_shell(uncertain_options.name)
            except AppError:
                pass
            else:
                raise AssertionError("An uncertain append was adopted for attachment.")
            lost = [item for item in proxy.receipts if item.get("owned_fault")]
            assert len(lost) == 1 and lost[0]["status"] == 200
            checks.append(
                "real-response-lost-after-commit-one-append-uncertain-no-attach-no-replay"
            )

            progress["phase"] = "production-real-subresource-rbac-denial"
            rbac: Any = sdk.RbacAuthorizationV1Api(connection.api)
            identity = "kuberich-debug-reader"
            await rbac.create_namespaced_role(
                NAMESPACE,
                {
                    "metadata": {"name": identity},
                    "rules": [{"apiGroups": [""], "resources": ["pods"], "verbs": ["get"]}],
                },
            )
            await rbac.create_namespaced_role_binding(
                NAMESPACE,
                {
                    "metadata": {"name": identity},
                    "subjects": [{"kind": "User", "name": identity}],
                    "roleRef": {
                        "apiGroup": "rbac.authorization.k8s.io",
                        "kind": "Role",
                        "name": identity,
                    },
                },
            )
            denied_client, denied_proxy = await stack.enter_async_context(
                observed_client(connection, as_user=identity)
            )
            denied = owner(denied_client)
            try:
                await denied.prepare(replace(options, name="debug-denied"))
            except AppError:
                pass
            else:
                raise AssertionError("Subresource-denied dry-run unexpectedly succeeded.")
            denied_writes = [item for item in denied_proxy.receipts if item["method"] == "PATCH"]
            assert len(denied_writes) == 1 and denied_writes[0]["status"] == 403
            assert denied_writes[0]["dry_run"]
            assert "debug-denied" not in [
                item["name"] for item in (await manifest())["spec"]["ephemeralContainers"]
            ]
            progress["denied_http_receipts"] = denied_proxy.receipts
            checks.append("real-pods-ephemeralcontainers-rbac403-no-persisted-entry")

            progress["phase"] = "real-target-instance-restart-stops-local-attachment"
            attached = asyncio.Event()

            async def held_terminal() -> None:
                terminal, request = await detached.prepare_shell(detached_options.name)
                async with ProcessRunner(AccessPolicy(False)) as runner:
                    try:
                        async with (
                            terminal.stage(request) as command,
                            runner.terminal(
                                command, width=90, height=28, guard=terminal.require_current
                            ) as (endpoint, _process),
                        ):
                            data = bytearray()
                            while b"$" not in data and b"#" not in data:
                                data.extend(await endpoint.read())
                                assert len(data) <= 65536
                            attached.set()
                            await asyncio.Event().wait()
                    finally:
                        assert runner.active_count == 0 and not request.path.exists()

            task = asyncio.create_task(held_terminal())
            try:
                async with asyncio.timeout(20):
                    await attached.wait()
                previous_count = (await manifest())["status"]["containerStatuses"][0][
                    "restartCount"
                ]
                try:
                    await asyncio.to_thread(
                        run_owned,
                        [
                            str(kubectl),
                            f"--kubeconfig={cluster.path}",
                            f"--context={cluster.context}",
                            f"--namespace={NAMESPACE}",
                            "exec",
                            "--container=app",
                            "workload",
                            "--",
                            "/bin/sh",
                            "-c",
                            "kill -9 1",
                        ],
                        delegated_environment,
                        20,
                    )
                except subprocess.CalledProcessError as error:
                    assert error.returncode in {1, 137}

                async def restarted() -> bool:
                    pod = await manifest()
                    return any(
                        item.get("name") == "app" and item.get("restartCount", 0) > previous_count
                        for item in pod["status"].get("containerStatuses", [])
                    )

                await wait_for(restarted)
                async with asyncio.timeout(20):
                    terminal_result = (await asyncio.gather(task, return_exceptions=True))[0]
                assert isinstance(terminal_result, asyncio.CancelledError)
                try:
                    await detached.prepare_shell(detached_options.name)
                except AppError:
                    pass
                else:
                    raise AssertionError(
                        "A restarted target instance reused an old reviewed attach."
                    )
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            progress["target_restart"] = {
                "same_pod_uid": (await manifest())["metadata"]["uid"] == uid,
                "local_attachment_cancelled": True,
                "old_review_refused": True,
            }
            checks.append(
                "real-target-termination-restart-cancels-local-pty-old-instance-review-refused"
            )

            writes = [item for item in proxy.receipts if item["method"] != "GET"]
            assert all(
                item["method"] == "PATCH"
                and item["path"]
                == f"/api/v1/namespaces/{NAMESPACE}/pods/workload/ephemeralcontainers"
                and item["strict"]
                and item["content_type"] == "application/json-patch+json"
                for item in writes
            )
            assert [item["body_sha256"] for item in writes[:2]] == [
                hashlib.sha256(review.intent.body).hexdigest()
            ] * 2
            final = await manifest()
            assert final["metadata"]["uid"] == uid and final["spec"]["containers"] == workload_spec
            checks.append("production-never-deletes-pod-or-debug-entry-never-mutates-workload-spec")
            return {
                "checks": checks,
                "node_image": NODE_IMAGE,
                "shell_image": SHELL_IMAGE,
                "owned_kubeconfig_unchanged": cluster.path.read_bytes() == original,
                "environment_unchanged": dict(os.environ) == environment,
                "caller_sentinel_unchanged": sentinel.read_bytes() == sentinel_bytes,
            }
    finally:
        try:
            for service in owners:
                await service.stop_owned()
            progress["owners_drained"] = all(service.operation_count == 0 for service in owners)
            await stack.aclose()
        finally:
            await connection.close()
        progress["private_sessions_deleted"] = not private.exists()
        assert progress.get("owners_drained") and progress["private_sessions_deleted"]
        assert cluster.path.read_bytes() == original and dict(os.environ) == environment
        assert sentinel.read_bytes() == sentinel_bytes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, type=Path)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    if args.evidence.exists():
        raise ValueError("Use fresh ephemeral-debug evidence paths; preserve previous outcomes.")
    if not args.kind.is_absolute() or not args.kubectl.is_absolute():
        raise ValueError("Use explicit verified kind and kubectl fixture paths.")
    if sha256_file(args.kind) != KIND_SHA256 or sha256_file(args.kubectl) != KUBECTL_SHA256:
        raise ValueError(
            "Use checksum-verified official kind v0.33.0 and kubectl v1.36.4 fixtures."
        )
    root = Path(__file__).resolve().parents[1]
    commit, captured = source_identity(root), input_hashes(root)
    result: dict[str, Any] = {
        "status": "failed",
        "source_commit": commit,
        "input_hashes": captured,
        "deadline_seconds": VERIFY_SECONDS,
        "owned_cluster_deleted": False,
        "tools": {"kind_sha256": KIND_SHA256, "kubectl_sha256": KUBECTL_SHA256},
    }
    started, cluster = time.monotonic(), None
    failure: BaseException | None = None
    try:
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, result, args.kubectl)))
            except BaseException as error:
                failure = error
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = (
            input_hashes(root) == captured and source_identity(root) == commit
        )
        assert result["inputs_unchanged"] and result["private_directory_deleted"]
        if failure is not None:
            raise failure
        result["status"] = "passed"
    except BaseException as error:
        result["failure_type"] = type(error).__name__
        frames = []
        trace = error.__traceback__
        while trace is not None:
            filename = Path(trace.tb_frame.f_code.co_filename).resolve()
            if filename.is_relative_to(root):
                frames.append(
                    {
                        "file": str(filename.relative_to(root)),
                        "line": trace.tb_lineno,
                        "function": trace.tb_frame.f_code.co_name,
                    }
                )
            trace = trace.tb_next
        result["failure_locations"] = frames
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        with args.evidence.open("x") as output:
            output.write(json.dumps(result, indent=2) + "\n")
    print("Owned-kind production ephemeral-debug proof passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned ephemeral-debug proof failed ({type(error).__name__}); retain evidence.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
