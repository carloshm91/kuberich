"""Qualify local manifests against an explicitly owned, pinned disposable kind API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web
from kubernetes_asyncio import client
from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import Entry, load_catalog
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.manifests import (
    ManifestAction,
    ManifestPlan,
    ManifestScope,
    ManifestSourceKind,
)
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import (
    NODE_IMAGE,
    SHELL_IMAGE,
    OwnedCluster,
    capture_docker,
    owned_cluster,
    run_owned,
)

KUBECTL_SHA256 = "8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a"
VERIFY_SECONDS = 600
MAX_PROXY_BYTES = 8 * 1024 * 1024
NAMESPACE = "kuberich-owned-manifests"
OTHER_NAMESPACE = NAMESPACE + "-other"


def input_hashes(root: Path) -> dict[str, str]:
    paths = {
        root / "scripts/verify_manifests_kind.py",
        root / "scripts/owned_kind.py",
        root / "scripts/diagnostics_tools.py",
        root / "uv.lock",
        root / "pyproject.toml",
        *(root / "src/kuberich").rglob("*.py"),
    }
    return {
        str(path.relative_to(root)): sha256_file(path) for path in sorted(paths) if path.is_file()
    }


def fixture_manifest(
    name: str, *, namespace: str | None = None, data: dict[str, str] | None = None
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"name": name}
    if namespace is not None:
        metadata["namespace"] = namespace
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": metadata,
        "data": data or {"managed": "one"},
    }


def write_documents(path: Path, documents: tuple[dict[str, Any], ...]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text("\n---\n".join(json.dumps(value) for value in documents) + "\n")
    path.chmod(0o600)


def review_diagnostics(plan: ManifestPlan) -> list[dict[str, Any]]:
    """Only validated public identity/status fields enter bounded failure evidence."""
    return [
        {
            "api_version": sanitize_text(item.resource.api_version[:253]),
            "resource": sanitize_text(item.resource.name[:253]),
            "kind": sanitize_text(item.resource.kind[:128]),
            "namespace": sanitize_text(item.target.namespace[:63])
            if item.target.namespace
            else None,
            "name": sanitize_text(item.target.name[:253]),
            "uid": sanitize_text(item.target.uid[:253]) if item.target.uid else None,
            "resource_version": sanitize_text(item.resource_version[:1024])
            if item.resource_version
            else None,
            "change": item.change,
            "validation_state": item.validation.state.value,
            "safe_message": sanitize_text(item.validation.message[:2048])[:2048],
        }
        for item in plan.items[:100]
    ]


def result_diagnostics(result: MutationResult) -> dict[str, Any]:
    return {
        "state": result.state.value,
        "safe_message": sanitize_text(result.message[:2048])[:2048],
        "items": [
            {
                "resource": sanitize_text(target.resource[:253]),
                "namespace": sanitize_text(target.namespace[:63]) if target.namespace else None,
                "name": sanitize_text(target.name[:253]),
                "state": item.state.value,
                "safe_message": sanitize_text(item.message[:2048])[:2048],
            }
            for target, item in result.items[:100]
        ],
    }


class LoopbackProxy:
    """Own a bounded forwarder; fault barriers run only after the healthy API commits."""

    def __init__(self, healthy: KubernetesSession) -> None:
        self.healthy = healthy
        self.runner: web.AppRunner | None = None
        self.url = ""
        self.hold = False
        self.committed = asyncio.Event()
        self.release = asyncio.Event()
        self.before_write: Callable[[], Awaitable[None]] | None = None
        self.writes: list[tuple[str, str, int]] = []
        self.hold_after_delete_read: str | None = None
        self.delete_committed = False
        self.deletion_observed = asyncio.Event()
        self.observation_release = asyncio.Event()

    async def handle(self, request: web.Request) -> web.Response:
        if request.method not in {"GET", "POST", "PATCH", "DELETE"}:
            return web.Response(status=405)
        body = await request.read()
        if len(body) > 1024 * 1024:
            raise ValueError("Owned fault-proxy input exceeds its bound.")
        mutation = request.method in {"POST", "PATCH", "DELETE"} and "dryRun" not in request.query
        if mutation and self.before_write is not None:
            callback, self.before_write = self.before_write, None
            await callback()
        api, configuration = self.healthy.api, self.healthy.configuration
        assert api is not None and configuration is not None
        headers = [
            ("Accept", request.headers.get("Accept", "application/json")),
            *self.healthy.impersonation,
        ]
        if "Content-Type" in request.headers:
            headers.append(("Content-Type", request.headers["Content-Type"]))
        if authorization := self.healthy.authorization_header():
            headers.append(("Authorization", authorization))
        async with api.rest_client.pool_manager.request(
            request.method,
            str(configuration.host) + request.path,
            params=list(request.query.items()),
            data=body or None,
            headers=headers,
            proxy=self.healthy.request_proxy,
            server_hostname=configuration.tls_server_name,
            allow_redirects=False,
        ) as response:
            status = response.status
            data = bytearray()
            async for chunk in response.content.iter_chunked(16384):
                data.extend(chunk)
                if len(data) > MAX_PROXY_BYTES:
                    raise ValueError("Owned fault-proxy response exceeds its bound.")
            content_type = response.headers.get("Content-Type", "application/json")
        if mutation:
            self.writes.append((request.method, request.path, status))
            if request.method == "DELETE" and 200 <= status < 300:
                self.delete_committed = True
            if self.hold and 200 <= status < 300:
                self.committed.set()
                await self.release.wait()
        if (
            request.method == "GET"
            and self.delete_committed
            and request.path == self.hold_after_delete_read
        ):
            self.deletion_observed.set()
            await self.observation_release.wait()
        return web.Response(status=status, body=bytes(data), headers={"Content-Type": content_type})

    async def __aenter__(self) -> LoopbackProxy:
        app = web.Application(client_max_size=1024 * 1024 + 1)
        app.router.add_route("*", "/{path:.*}", self.handle)
        self.runner = web.AppRunner(app, shutdown_timeout=1)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = "http://127.0.0.1:" + str(self.runner.addresses[0][1])
        return self

    async def __aexit__(self, *unused: object) -> None:
        self.release.set()
        self.observation_release.set()
        if self.runner is not None:
            await self.runner.cleanup()


class Harness:
    def __init__(self, cluster: OwnedCluster, kubectl: Path, report: dict[str, Any]) -> None:
        self.cluster, self.kubectl, self.report = cluster, kubectl, report
        self.root = cluster.directory / "manifest-sources"
        self.root.mkdir(mode=0o700)
        self.sentinel = cluster.directory / "ambient-config-sentinel"
        self.sentinel.write_bytes(b"Owned sentinel; never a Kubernetes configuration.\n")
        self.environment = {
            **os.environ,
            "PATH": str(kubectl.parent) + os.pathsep + os.environ.get("PATH", os.defpath),
            "KUBECONFIG": str(self.sentinel),
            "KUBECTL_KUBERC": "false",
        }
        self.policy = AccessPolicy(False)
        self.local = LocalManifestService(self.policy, self.environment, self.root)
        self.manager = MutationManager()
        self.services: list[ManifestMutationService] = []
        self.request = ConnectionRequest(
            kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=20
        )
        self.sessions = SessionService(load_catalog(self.request, {}), self.request)
        self.connection: KubernetesSession
        self.identity: SessionIdentity
        self.discovery: Discovery
        self.core: Any

    def check(self, name: str, condition: bool) -> None:
        if not condition:
            raise AssertionError(name)
        self.report.setdefault("checks", []).append(name)
        print("manifests: " + name, flush=True)

    async def open(self) -> None:
        await self.sessions.connect(self.cluster.context)
        connection, identity = self.sessions.client, self.sessions.observation.identity
        assert connection is not None and connection.api is not None and identity is not None
        self.connection, self.identity = connection, identity
        self.core = client.CoreV1Api(connection.api)
        for namespace in (NAMESPACE, OTHER_NAMESPACE):
            await self.core.create_namespace(
                client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
            )
        self.discovery = await ResourceReader(connection).discover()
        await self.local.open_root(self.root)

    async def source(
        self,
        relative: str,
        kind: ManifestSourceKind = "file",
        *,
        namespace: str | None = NAMESPACE,
        owner: KubernetesSession | None = None,
    ) -> ManifestMutationService:
        captured = await self.local.capture(relative, kind)
        connection = owner or self.connection
        identity = (
            self.identity
            if connection is self.connection
            else SessionIdentity(self.cluster.context, 10)
        )
        service = ManifestMutationService(
            connection,
            ManifestScope(session=identity, namespace=namespace),
            self.discovery,
            self.policy,
            captured,
            lambda: self.sessions.client is self.connection and connection.api is not None,
            lambda: self.local.require_source(captured),
            self.environment,
            self.root,
        )
        self.services.append(service)
        return service

    async def reviewed(
        self,
        relative: str,
        documents: tuple[dict[str, Any], ...],
        *,
        action: ManifestAction = "apply",
        owner: KubernetesSession | None = None,
    ) -> tuple[ManifestMutationService, ManifestPlan]:
        write_documents(self.root / relative, documents)
        service = await self.source(relative, owner=owner)
        plan = await self.prepare(service, action)
        return service, plan

    async def prepare(
        self, service: ManifestMutationService, action: ManifestAction
    ) -> ManifestPlan:
        plan = await service.prepare(action)
        self.report["last_review"] = review_diagnostics(plan)
        return plan

    def record_result(self, result: MutationResult) -> None:
        self.report["last_execution"] = result_diagnostics(result)

    async def execute(self, service: ManifestMutationService, plan: ManifestPlan) -> MutationResult:
        self.check("review-fully-validated-before-confirmation", plan.ready)
        identity = self.manager.start(service, service.confirm(plan))
        result = await self.manager.wait(identity)
        self.record_result(result)
        return result

    async def cm(self, name: str, namespace: str = NAMESPACE) -> Any | None:
        try:
            return await self.core.read_namespaced_config_map(name, namespace)
        except ApiException as error:
            if error.status == 404:
                return None
            raise

    async def require_cm(self, name: str, namespace: str = NAMESPACE) -> Any:
        value = await self.cm(name, namespace)
        assert value is not None, "Expected owned ConfigMap is absent"
        return value

    async def absent(self, name: str, namespace: str = NAMESPACE) -> None:
        async with asyncio.timeout(30):
            while await self.cm(name, namespace) is not None:
                await asyncio.sleep(0.05)

    async def proxy_client(self, proxy: LoopbackProxy) -> KubernetesSession:
        catalog = load_catalog(self.request, {})
        context = catalog.contexts[self.cluster.context].data
        catalog.clusters[context["cluster"]] = Entry({"server": proxy.url}, self.cluster.directory)
        catalog.users[context["user"]] = Entry({}, self.cluster.directory)
        connection = KubernetesSession(catalog.select(self.cluster.context), 20)
        await connection.open()
        return connection

    async def close(self) -> None:
        await self.manager.close()
        for service in reversed(self.services):
            await service.close()
        await self.local.close()
        self.check(
            "all-owned-manifest-services-and-workers-drained",
            self.manager.active_count == 0
            and self.local.operation_count == 0
            and all(service.operation_count == 0 for service in self.services),
        )
        connection = self.sessions.client
        self.check(
            "private-delegated-connections-cleaned",
            connection is None or not list(Path(connection.directory.name).glob("manifest-*")),
        )
        await self.sessions.close()


async def apply_cases(h: Harness) -> None:
    h.report["active_case"] = "named-create-declarative-merge"
    name = "owned-merge"
    service, plan = await h.reviewed(
        "merge.yaml", (fixture_manifest(name, data={"managed": "one", "remove-later": "owned"}),)
    )
    h.check("create-has-address-without-fabricated-uid", plan.items[0].target.uid is None)
    h.check("create-dryrun-does-not-persist", await h.cm(name) is None)
    result = await h.execute(service, plan)
    first = await h.require_cm(name)
    h.check(
        "named-create-observed-real-uid-and-version",
        result.state is MutationState.SUCCEEDED
        and first is not None
        and bool(first.metadata.uid)
        and bool(first.metadata.resource_version),
    )
    await h.core.patch_namespaced_config_map(name, NAMESPACE, {"data": {"live-only": "preserved"}})
    for label, desired in (
        ("update", {"managed": "two", "remove-later": "owned"}),
        ("removal", {"managed": "three"}),
        ("next-update", {"managed": "four"}),
    ):
        before = await h.require_cm(name)
        service, plan = await h.reviewed("merge.yaml", (fixture_manifest(name, data=desired),))
        untouched = await h.require_cm(name)
        h.check(
            label + "-dryrun-preserves-live-version",
            untouched.metadata.resource_version == before.metadata.resource_version,
        )
        result = await h.execute(service, plan)
        after = await h.require_cm(name)
        h.check(
            label + "-client-side-merge-preserves-live-data-and-uid",
            result.state is MutationState.SUCCEEDED
            and after.data == {**desired, "live-only": "preserved"}
            and after.metadata.uid == first.metadata.uid
            and after.metadata.resource_version != before.metadata.resource_version,
        )
    service, plan = await h.reviewed(
        "merge.yaml", (fixture_manifest(name, data={"managed": "four"}),)
    )
    version = (await h.require_cm(name)).metadata.resource_version
    result = await h.execute(service, plan)
    h.check(
        "unchanged-review-sends-no-write-and-discloses-version",
        plan.items[0].change == "unchanged"
        and plan.items[0].resource_version == version
        and result.state is MutationState.SUCCEEDED
        and (await h.require_cm(name)).metadata.resource_version == version,
    )
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "owned-zero"},
        "spec": {
            "replicas": 0,
            "selector": {"matchLabels": {"app": "owned-zero"}},
            "template": {
                "metadata": {"labels": {"app": "owned-zero"}},
                "spec": {"containers": [{"name": "app", "image": SHELL_IMAGE}]},
            },
        },
    }
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "owned-secret"},
        "type": "Opaque",
        "stringData": {"password": "synthetic-private-fixture"},
    }
    service, plan = await h.reviewed(
        "multi.yaml", (fixture_manifest("owned-multi"), secret, deployment)
    )
    h.check(
        "multi-document-dryrun-keeps-all-objects-absent",
        plan.ready and await h.cm("owned-multi") is None,
    )
    result = await h.execute(service, plan)
    h.check(
        "multi-document-configmap-secret-deployment-applied",
        result.state is MutationState.SUCCEEDED and len(result.items) == 3,
    )
    write_documents(h.root / "ordinary" / "one.yaml", (fixture_manifest("owned-directory-one"),))
    write_documents(h.root / "ordinary" / "two.yaml", (fixture_manifest("owned-directory-two"),))
    service = await h.source("ordinary", "directory")
    plan = await h.prepare(service, "apply")
    result = await h.execute(service, plan)
    h.check(
        "ordinary-directory-applies-only-rendered-identities",
        result.state is MutationState.SUCCEEDED
        and {item.target.name for item in plan.items}
        == {"owned-directory-one", "owned-directory-two"},
    )


async def kustomize_and_scope(h: Harness) -> None:
    h.report["active_case"] = "nested-kustomize-and-exact-scope"
    root = h.root / "project"
    write_documents(root / "base" / "configmap.yaml", (fixture_manifest("owned-base"),))
    (root / "base" / "kustomization.yaml").write_text("resources: [configmap.yaml]\n")
    component = root / "components" / "labels"
    component.mkdir(parents=True, mode=0o700)
    (component / "kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\nlabels:\n- pairs: {owned-component: 'true'}\n"
    )
    overlay = root / "overlays" / "dev"
    overlay.mkdir(parents=True, mode=0o700)
    (overlay / "kustomization.yaml").write_text(
        "resources: [../../base]\nnamespace: "
        + NAMESPACE
        + "\nnamePrefix: dev-\ncomponents: [../../components/labels]\npatches:\n- path: patch.yaml\nconfigMapGenerator:\n- name: owned-generated\n  literals: [value=synthetic]\n"
    )
    write_documents(
        overlay / "patch.yaml", (fixture_manifest("owned-base", data={"managed": "patched"}),)
    )
    service = await h.source("project/overlays/dev", "kustomize")
    plan = await h.prepare(service, "apply")
    h.check(
        "nested-local-kustomize-base-patch-generator-resolved",
        plan.ready
        and len(plan.items) == 2
        and all(item.target.namespace == NAMESPACE for item in plan.items)
        and any(item.target.name.startswith("dev-owned-generated-") for item in plan.items),
    )
    result = await h.execute(service, plan)
    h.check(
        "actual-kustomize-apply-matches-rendered-set",
        result.state is MutationState.SUCCEEDED
        and (await h.require_cm("dev-owned-base")).data["managed"] == "patched"
        and (await h.require_cm("dev-owned-base")).metadata.labels["owned-component"] == "true",
    )
    role = {
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRole",
        "metadata": {"name": "kuberich-owned-manifest-role"},
        "rules": [],
    }
    service, plan = await h.reviewed(
        "scopes.yaml",
        (
            fixture_manifest("owned-scope-one", namespace=NAMESPACE),
            fixture_manifest("owned-scope-two", namespace=OTHER_NAMESPACE),
            role,
        ),
    )
    h.check(
        "review-discloses-two-explicit-namespaces-and-cluster-scope",
        plan.ready
        and tuple(item.target.namespace for item in plan.items)
        == (NAMESPACE, OTHER_NAMESPACE, None),
    )
    result = await h.execute(service, plan)
    h.check(
        "mixed-scoped-apply-keeps-exact-destinations",
        result.state is MutationState.SUCCEEDED
        and await h.cm("owned-scope-two", OTHER_NAMESPACE) is not None,
    )
    write_documents(h.root / "missing-namespace.yaml", (fixture_manifest("owned-no-ambient"),))
    service = await h.source("missing-namespace.yaml", namespace=None)
    try:
        await service.prepare("apply")
    except AppError:
        pass
    else:
        raise AssertionError("All-namespace review accepted an implicit destination")
    h.check("all-namespaces-requires-explicit-fallback", await h.cm("owned-no-ambient") is None)


async def refusal_and_races(h: Harness) -> None:
    h.report["active_case"] = "actual-schema-immutable-quota-and-conflicts"
    invalid = fixture_manifest("owned-invalid")
    invalid["unknownOwnedField"] = True
    service, plan = await h.reviewed("invalid.yaml", (invalid,))
    h.check(
        "strict-schema-refusal-does-not-persist",
        not plan.ready
        and plan.items[0].validation.state is MutationState.REJECTED
        and await h.cm("owned-invalid") is None,
    )
    await h.core.create_namespaced_config_map(
        NAMESPACE,
        client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name="owned-immutable"),
            immutable=True,
            data={"managed": "one"},
        ),
    )
    service, plan = await h.reviewed(
        "immutable.yaml", (fixture_manifest("owned-immutable", data={"managed": "two"}),)
    )
    h.check(
        "immutable-field-server-dryrun-refusal-preserves-live",
        not plan.ready and (await h.require_cm("owned-immutable")).data == {"managed": "one"},
    )
    quota_namespace = NAMESPACE + "-quota"
    await h.core.create_namespace(
        client.V1Namespace(metadata=client.V1ObjectMeta(name=quota_namespace))
    )
    await h.core.create_namespaced_resource_quota(
        quota_namespace,
        client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(name="owned-deny-configmaps"),
            spec=client.V1ResourceQuotaSpec(hard={"count/configmaps": "0"}),
        ),
    )
    service, plan = await h.reviewed(
        "quota.yaml", (fixture_manifest("owned-quota-denied", namespace=quota_namespace),)
    )
    h.check(
        "actual-resource-quota-admission-denies-valid-source",
        not plan.ready
        and plan.items[0].validation.state is MutationState.DENIED
        and await h.cm("owned-quota-denied", quota_namespace) is None,
    )
    for label in ("version", "replacement"):
        name = "owned-race-" + label
        await h.core.create_namespaced_config_map(
            NAMESPACE,
            client.V1ConfigMap(metadata=client.V1ObjectMeta(name=name), data={"managed": "one"}),
        )
        service, plan = await h.reviewed(
            "race.yaml", (fixture_manifest(name, data={"managed": "two"}),)
        )
        proof = service.confirm(plan)
        if label == "version":
            await h.core.patch_namespaced_config_map(
                name, NAMESPACE, {"metadata": {"annotations": {"fixture": "changed"}}}
            )
        else:
            await h.core.delete_namespaced_config_map(name, NAMESPACE)
            await h.absent(name)
            await h.core.create_namespaced_config_map(
                NAMESPACE,
                client.V1ConfigMap(
                    metadata=client.V1ObjectMeta(name=name), data={"managed": "replacement"}
                ),
            )
        before = await h.require_cm(name)
        result = await service.execute(proof)
        h.record_result(result)
        after = await h.require_cm(name)
        h.check(
            "actual-" + label + "-race-refuses-write",
            result.state is (MutationState.CONFLICT if label == "version" else MutationState.STALE)
            and before.metadata.resource_version == after.metadata.resource_version
            and before.data == after.data,
        )
    names = ("owned-partial-one", "owned-partial-two", "owned-partial-three")
    service, plan = await h.reviewed(
        "partial.yaml", tuple(fixture_manifest(name) for name in names)
    )
    await h.core.create_namespaced_config_map(
        NAMESPACE,
        client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name=names[1]), data={"fixture": "appeared"}
        ),
    )
    result = await h.execute(service, plan)
    h.check(
        "partial-batch-retains-first-success-second-conflict-third-unsent",
        result.state is MutationState.PARTIAL
        and tuple(item.state for _, item in result.items)
        == (MutationState.SUCCEEDED, MutationState.CONFLICT, MutationState.BLOCKED)
        and await h.cm(names[0]) is not None
        and (await h.require_cm(names[1])).data == {"fixture": "appeared"}
        and await h.cm(names[2]) is None,
    )


async def rbac_cases(h: Harness) -> None:
    h.report["active_case"] = "actual-serviceaccount-rbac-denial-and-revocation"
    assert h.connection.api is not None
    rbac = client.RbacAuthorizationV1Api(h.connection.api)
    name = "owned-manifest-serviceaccount"
    await h.core.create_namespaced_service_account(
        NAMESPACE, client.V1ServiceAccount(metadata=client.V1ObjectMeta(name=name))
    )
    role = client.V1Role(
        metadata=client.V1ObjectMeta(name=name),
        rules=[
            client.V1PolicyRule(
                api_groups=[""],
                resources=["configmaps"],
                verbs=["get", "create", "patch", "delete"],
            )
        ],
    )
    await rbac.create_namespaced_role(NAMESPACE, role)
    await rbac.create_namespaced_role_binding(
        NAMESPACE,
        client.V1RoleBinding(
            metadata=client.V1ObjectMeta(name=name),
            role_ref=client.V1RoleRef(
                api_group="rbac.authorization.k8s.io", kind="Role", name=name
            ),
            subjects=[client.RbacV1Subject(kind="ServiceAccount", name=name, namespace=NAMESPACE)],
        ),
    )
    token = await h.core.create_namespaced_service_account_token(
        name,
        NAMESPACE,
        client.AuthenticationV1TokenRequest(
            spec=client.V1TokenRequestSpec(audiences=[], expiration_seconds=600)
        ),
    )
    catalog = load_catalog(h.request, {})
    catalog.users[name] = Entry({"token": token.status.token}, h.cluster.directory)
    catalog.contexts[h.cluster.context].data["user"] = name
    restricted = KubernetesSession(catalog.select(h.cluster.context), 20)
    await restricted.open()
    try:
        async with asyncio.timeout(20):
            while True:
                service, plan = await h.reviewed(
                    "rbac.yaml", (fixture_manifest("owned-revoked-create"),), owner=restricted
                )
                if plan.ready:
                    break
                await asyncio.sleep(0.1)
        proof = service.confirm(plan)
        await rbac.patch_namespaced_role(
            name,
            NAMESPACE,
            {"rules": [{"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get"]}]},
        )
        request = plan.items[0].request
        assert request is not None
        async with asyncio.timeout(20):
            while (
                await service.adapter.validate(request, service.require_current)
            ).result.state is not MutationState.DENIED:
                await asyncio.sleep(0.05)
        result = await service.execute(proof)
        h.record_result(result)
        h.check(
            "actual-rbac-revoked-after-review-denies-commit",
            result.state is MutationState.DENIED and await h.cm("owned-revoked-create") is None,
        )
        for action in ("apply", "delete"):
            service, plan = await h.reviewed(
                "rbac-read-only.yaml",
                (fixture_manifest("owned-merge", data={"managed": "rbac-blocked"}),),
                action=action,
                owner=restricted,
            )
            h.check(
                "actual-get-only-serviceaccount-refuses-" + action,
                not plan.ready and plan.items[0].validation.state is MutationState.DENIED,
            )
    finally:
        for service in h.services:
            if service.client is restricted:
                await service.close()
        await restricted.close()


async def deletion_cases(h: Harness) -> None:
    h.report["active_case"] = "guarded-deletion-finalizers-and-absence"
    for name, finalizers in (
        ("owned-delete-one", None),
        ("owned-delete-finalizer", ["example.io/kuberich-owned"]),
    ):
        await h.core.create_namespaced_config_map(
            NAMESPACE,
            client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=name, finalizers=finalizers),
                data={"managed": "one"},
            ),
        )
    service, plan = await h.reviewed(
        "delete.yaml",
        tuple(
            fixture_manifest(name)
            for name in ("owned-delete-one", "owned-delete-finalizer", "owned-delete-absent")
        ),
        action="delete",
    )
    h.check(
        "delete-review-fresh-real-uids-and-explicit-absent-row",
        plan.ready
        and plan.items[2].change == "absent"
        and all(item.target.uid for item in plan.items[:2]),
    )
    result = await h.execute(service, plan)
    pending = await h.require_cm("owned-delete-finalizer")
    await h.absent("owned-delete-one")
    h.check(
        "actual-delete-preserves-finalizer-and-reports-pending",
        result.items[1][1].state is MutationState.ACCEPTED
        and pending.metadata.deletion_timestamp is not None
        and pending.metadata.finalizers == ["example.io/kuberich-owned"],
    )
    await h.core.patch_namespaced_config_map(
        "owned-delete-finalizer", NAMESPACE, {"metadata": {"finalizers": None}}
    )
    await h.absent("owned-delete-finalizer")
    service, plan = await h.reviewed(
        "delete-absent.yaml", (fixture_manifest("owned-delete-absent"),), action="delete"
    )
    result = await h.execute(service, plan)
    h.check(
        "all-absent-delete-is-successful-no-request",
        result.state is MutationState.SUCCEEDED and plan.items[0].request is None,
    )
    name = "owned-delete-replacement"
    await h.core.create_namespaced_config_map(
        NAMESPACE, client.V1ConfigMap(metadata=client.V1ObjectMeta(name=name))
    )
    service, plan = await h.reviewed(
        "delete-replacement.yaml", (fixture_manifest(name),), action="delete"
    )
    proof = service.confirm(plan)
    await h.core.delete_namespaced_config_map(name, NAMESPACE)
    await h.absent(name)
    replacement = await h.core.create_namespaced_config_map(
        NAMESPACE, client.V1ConfigMap(metadata=client.V1ObjectMeta(name=name))
    )
    result = await service.execute(proof)
    h.record_result(result)
    h.check(
        "delete-same-name-replacement-left-untouched",
        result.state is MutationState.STALE
        and (await h.require_cm(name)).metadata.uid == replacement.metadata.uid,
    )


async def proxy_cases(h: Harness) -> None:
    h.report["active_case"] = "actual-post-race-and-committed-patch-cancellation"
    async with LoopbackProxy(h.connection) as proxy:
        connection = await h.proxy_client(proxy)
        try:
            service, plan = await h.reviewed(
                "post-race.yaml", (fixture_manifest("owned-post-race"),), owner=connection
            )

            async def appear() -> None:
                await h.core.create_namespaced_config_map(
                    NAMESPACE,
                    client.V1ConfigMap(
                        metadata=client.V1ObjectMeta(name="owned-post-race"),
                        data={"fixture": "atomic-race"},
                    ),
                )

            proxy.before_write = appear
            result = await h.execute(service, plan)
            h.check(
                "atomic-post-conflict-never-turns-create-into-update",
                result.state is MutationState.CONFLICT
                and (await h.require_cm("owned-post-race")).data == {"fixture": "atomic-race"}
                and len(proxy.writes) == 1
                and proxy.writes[0][2] == 409,
            )
            for name in ("owned-cancel-one", "owned-cancel-two"):
                await h.core.create_namespaced_config_map(
                    NAMESPACE,
                    client.V1ConfigMap(
                        metadata=client.V1ObjectMeta(name=name), data={"managed": "one"}
                    ),
                )
            service, plan = await h.reviewed(
                "cancel.yaml",
                tuple(
                    fixture_manifest(name, data={"managed": "committed"})
                    for name in ("owned-cancel-one", "owned-cancel-two")
                ),
                owner=connection,
            )
            h.check("actual-proxy-batch-reviewed-before-fault", plan.ready)
            proxy.hold = True
            identity = h.manager.start(service, service.confirm(plan))
            await asyncio.wait_for(proxy.committed.wait(), 20)
            committed = await h.require_cm("owned-cancel-one")
            result = await h.manager.cancel(identity)
            h.record_result(result)
            h.check(
                "cancel-after-real-patch-commit-retains-uncertainty-and-unsent",
                committed.data["managed"] == "committed"
                and result.state is MutationState.UNCERTAIN
                and tuple(item.state for _, item in result.items)
                == (MutationState.UNCERTAIN, MutationState.BLOCKED)
                and (await h.require_cm("owned-cancel-two")).data["managed"] == "one",
            )
            h.check(
                "committed-write-cancellation-never-replayed",
                len([row for row in proxy.writes if row[0] == "PATCH"]) == 1
                and h.manager.records[-1].result == result,
            )
            proxy.release.set()
            proxy.hold = False
            for name in ("owned-stop-delete-one", "owned-stop-delete-two"):
                await h.core.create_namespaced_config_map(
                    NAMESPACE,
                    client.V1ConfigMap(
                        metadata=client.V1ObjectMeta(
                            name=name,
                            finalizers=["example.io/kuberich-stop"]
                            if name.endswith("one")
                            else None,
                        )
                    ),
                )
            service, plan = await h.reviewed(
                "stop-delete.yaml",
                tuple(
                    fixture_manifest(name)
                    for name in ("owned-stop-delete-one", "owned-stop-delete-two")
                ),
                action="delete",
                owner=connection,
            )
            proxy.hold_after_delete_read = (
                "/api/v1/namespaces/" + NAMESPACE + "/configmaps/owned-stop-delete-one"
            )
            identity = h.manager.start(service, service.confirm(plan))
            await asyncio.wait_for(proxy.deletion_observed.wait(), 20)
            result = await h.manager.cancel(identity)
            h.record_result(result)
            pending = await h.require_cm("owned-stop-delete-one")
            remaining = await h.require_cm("owned-stop-delete-two")
            h.check(
                "stop-after-accepted-delete-observation-keeps-later-delete-unsent",
                result.state is MutationState.PARTIAL
                and tuple(item.state for _, item in result.items)
                == (MutationState.ACCEPTED, MutationState.BLOCKED)
                and pending.metadata.deletion_timestamp is not None
                and remaining.metadata.deletion_timestamp is None
                and len([row for row in proxy.writes if row[0] == "DELETE"]) == 1,
            )
            proxy.observation_release.set()
            await h.core.patch_namespaced_config_map(
                "owned-stop-delete-one", NAMESPACE, {"metadata": {"finalizers": None}}
            )
            await h.absent("owned-stop-delete-one")
        finally:
            for service in h.services:
                if service.client is connection:
                    await service.close()
            await connection.close()


async def ui_case(h: Harness) -> None:
    from textual.app import App, ComposeResult
    from textual.widgets import Button, Static

    from kuberich.ui.manifest_review import ManifestReviewScreen

    class ReviewApp(App[None]):
        def __init__(self, screen: ManifestReviewScreen) -> None:
            super().__init__()
            self.review = screen

        def compose(self) -> ComposeResult:
            yield Static("Owned local-manifest qualification")

        def on_mount(self) -> None:
            self.push_screen(self.review)

    h.report["active_case"] = "actual-pilot-preview-apply-delete"
    for action in ("apply", "delete"):
        write_documents(h.root / "ui.yaml", (fixture_manifest("owned-ui"),))
        service = await h.source("ui.yaml")
        screen = ManifestReviewScreen(service=service, manager=h.manager, action=action)
        app = ReviewApp(screen)
        async with app.run_test(size=(120, 36)) as pilot:

            async def click(
                name: str, screen: ManifestReviewScreen = screen, app: ReviewApp = app
            ) -> None:
                button = screen.query_one(name, Button)
                async with asyncio.timeout(10):
                    while True:
                        await screen.wait_for_refresh()
                        if (
                            button.is_attached
                            and button.visible
                            and not button.disabled
                            and not button.has_class("-active")
                            and button.region.area
                            and app.get_widget_at(*(int(value) for value in button.region.center))[
                                0
                            ]
                            is button
                        ):
                            break
                        await asyncio.sleep(0.01)
                assert await pilot.click(button)

            await click("#manifest-review-validate")
            async with asyncio.timeout(30):
                while screen.plan is None or screen.operation_count:
                    await asyncio.sleep(0.01)
            h.report["last_review"] = review_diagnostics(screen.plan)
            h.check(
                "actual-ui-" + action + "-explicit-server-review",
                screen.plan.ready
                and (
                    await h.cm("owned-ui") is None
                    if action == "apply"
                    else await h.cm("owned-ui") is not None
                ),
            )
            await click("#manifest-review-confirm")
            async with asyncio.timeout(30):
                while screen.result is None or screen.operation_count:
                    await asyncio.sleep(0.01)
            h.record_result(screen.result)
            h.check(
                "actual-ui-" + action + "-confirmed-api-effect",
                screen.result.state in {MutationState.SUCCEEDED, MutationState.ACCEPTED}
                and (
                    await h.cm("owned-ui") is not None
                    if action == "apply"
                    else await h.cm("owned-ui") is None
                ),
            )


async def verify(cluster: OwnedCluster, kubectl: Path, report: dict[str, Any]) -> None:
    before = cluster.path.read_bytes()
    h = Harness(cluster, kubectl, report)
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            await h.open()
            await apply_cases(h)
            await kustomize_and_scope(h)
            await refusal_and_races(h)
            await rbac_cases(h)
            await deletion_cases(h)
            await proxy_cases(h)
            await ui_case(h)
            h.check(
                "owned-kubeconfig-and-ambient-sentinel-unchanged",
                cluster.path.read_bytes() == before
                and h.sentinel.read_bytes()
                == b"Owned sentinel; never a Kubernetes configuration.\n",
            )
    finally:
        await h.close()


def run(args: argparse.Namespace, root: Path) -> int:
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    report: dict[str, Any] = {
        "status": "in-progress",
        "checks": [],
        "node_image": NODE_IMAGE,
        "scope": "Owned Linux amd64 kind only; no provider, macOS or public-release qualification.",
        "owned_cluster_deleted": False,
        "source_unchanged": False,
    }
    failure: BaseException | None = None
    before: dict[str, str] = {}
    environment: dict[str, str] | None = None
    try:
        if sys.platform != "linux" or platform.machine() != "x86_64":
            raise ValueError("Owned manifest qualification requires Linux amd64.")
        for path, expected in ((args.kind, KIND_SHA256), (args.kubectl, KUBECTL_SHA256)):
            if (
                not path.is_absolute()
                or sha256_file(path) != expected
                or not path.stat().st_mode & 0o111
            ):
                raise ValueError("Use the pinned official executable kind/kubectl tools.")
        before = input_hashes(root)
        report.update(inputs=before, tool_sha256={"kind": KIND_SHA256, "kubectl": KUBECTL_SHA256})
        environment = capture_docker(args.docker)
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            report["owned_cluster_name"] = cluster.name
            asyncio.run(verify(cluster, args.kubectl, report))
        report["owned_cluster_deleted"] = True
        report["status"] = "passed"
    except BaseException as error:
        failure = error
        report.update(status="failed", error_type=type(error).__name__)
    finally:
        if before:
            try:
                report["source_unchanged"] = input_hashes(root) == before
            except BaseException:
                report["source_unchanged"] = False
            if not report["source_unchanged"]:
                report["status"] = "failed"
        if name := report.get("owned_cluster_name"):
            try:
                assert environment is not None
                remaining = run_owned(
                    [
                        args.docker,
                        "ps",
                        "--all",
                        "--filter",
                        "label=io.x-k8s.kind.cluster=" + name,
                        "--format",
                        "{{.ID}}",
                    ],
                    environment,
                ).splitlines()
                report["owned_cluster_deleted"] = not remaining
            except BaseException:
                report["owned_cluster_deleted"] = False
            if not report["owned_cluster_deleted"]:
                report["status"] = "failed"
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {key: report[key] for key in ("status", "source_unchanged", "owned_cluster_deleted")}
        ),
        flush=True,
    )
    return 1 if failure is not None or report["status"] != "passed" else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", type=Path, required=True)
    parser.add_argument("--kubectl", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args, Path(__file__).resolve().parent.parent))


if __name__ == "__main__":
    main()
