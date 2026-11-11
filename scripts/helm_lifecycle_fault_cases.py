"""A held real owned API response proves uncertain lifecycle effects without replay."""

import asyncio
import base64
import json
import os
import ssl
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import yaml
from aiohttp import web

from kuberich.config.catalog import Entry, load_catalog
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.helm import (
    HelmDriver,
    HelmOutcome,
    HelmReleaseKey,
    HelmRequest,
    HelmScope,
    HelmSettings,
)
from kuberich.domain.helm_catalog import ChartSnapshot
from kuberich.domain.helm_lifecycle import HelmLifecycleKind, HelmLifecycleOptions
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.helm import HelmService
from kuberich.services.resources import parse_owned
from kuberich.services.sessions import SessionService
from scripts.owned_kind import OwnedCluster


def _owned_tls(cluster: OwnedCluster) -> tuple[str, ssl.SSLContext]:
    data = yaml.safe_load(cluster.path.read_bytes())
    assert data["current-context"] == cluster.context
    selected = next(item["context"] for item in data["contexts"] if item["name"] == cluster.context)
    peer = next(item["cluster"] for item in data["clusters"] if item["name"] == selected["cluster"])
    user = next(item["user"] for item in data["users"] if item["name"] == selected["user"])
    target = urlsplit(peer["server"])
    assert target.scheme == "https" and target.hostname == "127.0.0.1" and target.port
    assert not target.username and not target.password and not target.query and not target.fragment
    context = ssl.create_default_context(
        cadata=base64.b64decode(peer["certificate-authority-data"], validate=True).decode()
    )
    with tempfile.TemporaryDirectory(prefix="owned-held-api-", dir=cluster.directory) as temporary:
        root = Path(temporary)
        paths = []
        for key in ("client-certificate-data", "client-key-data"):
            path = root / key
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(base64.b64decode(user[key], validate=True))
            paths.append(path)
        context.load_cert_chain(paths[0], paths[1])
    assert not root.exists()
    return peer["server"], context


@dataclass
class HeldWrite:
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    active: set[asyncio.Task[Any]] = field(default_factory=set)
    persistent_writes: list[tuple[str, str]] = field(default_factory=list)
    validations: int = 0
    closed: bool = False


def owned_api_path(path: str) -> bool:
    return path in {"/api", "/apis", "/version", "/openapi/v2", "/openapi/v3"} or path.startswith(
        ("/api/", "/apis/", "/openapi/v3/")
    )


async def bounded_body(stream: aiohttp.StreamReader, limit: int) -> bytes:
    data = bytearray()
    async for chunk in stream.iter_chunked(65536):
        if len(data) + len(chunk) > limit:
            raise AssertionError("Owned API proxy body exceeded its fixture limit.")
        data.extend(chunk)
    return bytes(data)


@asynccontextmanager
async def held_owned_write(
    cluster: OwnedCluster, namespace: str, name: str
) -> AsyncIterator[tuple[str, HeldWrite]]:
    target, tls = await parse_owned(partial(_owned_tls, cluster))
    witness = HeldWrite()
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=tls),
        trust_env=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        auto_decompress=False,
        timeout=aiohttp.ClientTimeout(total=120),
    ) as upstream:

        async def handle(request: web.Request) -> web.Response:
            task = asyncio.current_task()
            assert task is not None
            witness.active.add(task)
            try:
                assert owned_api_path(request.path)
                body = await bounded_body(request.content, 4 * 1024 * 1024)
                headers = {
                    key: value
                    for key, value in request.headers.items()
                    if key.lower()
                    not in {
                        "host",
                        "connection",
                        "content-length",
                        "transfer-encoding",
                        "accept-encoding",
                    }
                }
                headers["Accept-Encoding"] = "identity"
                async with upstream.request(
                    request.method,
                    target + request.raw_path,
                    data=body,
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    data = await bounded_body(response.content, 8 * 1024 * 1024)
                    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
                        if request.query.get("dryRun") == "All":
                            witness.validations += 1
                        else:
                            witness.persistent_writes.append((request.method, request.path))
                    if (
                        request.method == "POST"
                        and request.path == f"/api/v1/namespaces/{namespace}/configmaps"
                        and request.query.get("dryRun") != "All"
                        and response.status == 201
                        and json.loads(body).get("metadata", {}).get("name") == name + "-settings"
                    ):
                        witness.entered.set()
                        await witness.release.wait()
                    return web.Response(
                        body=data,
                        status=response.status,
                        headers={
                            "Content-Type": response.headers.get("Content-Type", "application/json")
                        },
                    )
            finally:
                witness.active.discard(task)

        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", handle)
        listener = web.AppRunner(app, shutdown_timeout=1)
        await listener.setup()
        site = web.TCPSite(listener, "127.0.0.1", 0)
        await site.start()
        try:
            yield f"http://127.0.0.1:{listener.addresses[0][1]}", witness
        finally:
            witness.release.set()
            await listener.cleanup()
            assert not witness.active
    witness.closed = True


async def verify_uncertain_lifecycle(
    cluster: OwnedCluster,
    binary: Path,
    driver: HelmDriver,
    namespace: str,
    chart: ChartSnapshot,
    directory: Path,
) -> dict[str, Any]:
    name = "owned-uncertain"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=namespace, timeout=15
    )
    independent = SessionService(load_catalog(request, {}), request)
    await independent.connect(cluster.context)
    observer = independent.client
    assert observer is not None
    receipt: dict[str, Any] = {}
    try:
        async with held_owned_write(cluster, namespace, name) as (origin, witness):
            catalog = load_catalog(request, {})
            cluster_name = catalog.contexts[cluster.context].data["cluster"]
            catalog.clusters[cluster_name] = Entry({"server": origin}, cluster.directory)
            sessions = SessionService(catalog, request)
            service = None
            operation = None
            try:
                await sessions.connect(cluster.context)
                connection, identity = sessions.client, sessions.observation.identity
                assert connection is not None and identity is not None
                captured = HelmRequest(HelmScope(identity, namespace, driver), 1)
                service = HelmService(
                    connection,
                    AccessPolicy(False),
                    HelmSettings(str(binary), driver),
                    {"PATH": os.defpath},
                    directory,
                    lambda candidate: candidate == captured and sessions.client is connection,
                    catalog_directory=directory / "catalog",
                )
                await service.catalog.load()
                assert service.catalog.snapshot.generation == chart.catalog_generation
                intent = await service.prepare_lifecycle(
                    captured,
                    HelmReleaseKey(namespace, name),
                    HelmLifecycleKind.INSTALL,
                    chart,
                    options=HelmLifecycleOptions(wait=False),
                )
                assert not witness.persistent_writes and witness.validations == 1
                approval = service.confirm_lifecycle(intent)
                operation = service.execute_lifecycle(approval)
                async with asyncio.timeout(60):
                    await witness.entered.wait()
                resource = await observer.get_json(
                    f"/api/v1/namespaces/{namespace}/configmaps/{name}-settings"
                )
                assert (
                    resource["metadata"]["uid"] and resource["data"]["message"] == "synthetic-first"
                )
                operation.cancel()
                try:
                    await operation
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("Launched native lifecycle cancellation was suppressed.")
                assert (
                    service.last_operation is not None
                    and service.last_operation.outcome is HelmOutcome.UNKNOWN
                    and service.last_operation.may_have_started
                )
                before = len(witness.persistent_writes)
                try:
                    service.execute_lifecycle(approval)
                except AppError:
                    pass
                else:
                    raise AssertionError("An uncertain native write was replayed.")
                assert len(witness.persistent_writes) == before and before >= 2
                storage_plural = "secrets" if driver is HelmDriver.SECRET else "configmaps"
                storage = await observer.get_json(
                    f"/api/v1/namespaces/{namespace}/{storage_plural}/sh.helm.release.v1.{name}.v1",
                    accept="application/json;as=PartialObjectMetadata;g=meta.k8s.io;v=v1",
                )
                assert (
                    storage["kind"] == "PartialObjectMetadata"
                    and storage["metadata"]["labels"]["status"] == "pending-install"
                )
                receipt = {
                    "scope": "Production service; real native write response held after API persistence.",
                    "outcome": service.last_operation.outcome.value,
                    "may_have_started": True,
                    "resource_uid": resource["metadata"]["uid"],
                    "storage_uid": storage["metadata"]["uid"],
                    "storage_status": "pending-install",
                    "persistent_writes": before,
                    "separate_admission_validations": witness.validations,
                    "one_use_replay_refused": True,
                }
            finally:
                witness.release.set()
                if operation is not None and not operation.done():
                    operation.cancel()
                    await asyncio.gather(operation, return_exceptions=True)
                if service is not None:
                    await service.close()
                    assert service.operation_count == 0
                await sessions.close()
        assert witness.closed and not witness.active
        return {**receipt, "proxy_drained": True, "private_tls_staging_removed": True}
    finally:
        await independent.close()
