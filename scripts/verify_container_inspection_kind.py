"""O07: current API configuration versus fixture startup on an owned kind cluster."""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from kubernetes_asyncio.client.exceptions import ApiException

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.container_inspection import ContainerIdentity, InspectionSnapshot
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.container_inspection import ContainerInspectionService
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader
from scripts.diagnostics_tools import KIND_SHA256, sha256_file
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-owned-inspection"
POD = "owned-inspection"
CONFIG = "owned-config-first"
SECOND_CONFIG = "owned-config-second"
SECRET = "owned-synthetic-secret"
MISSING = "owned-optional-missing"
READER = "owned-inspection-reader"
RBAC_VERSION = "rbac.authorization.k8s.io/v1"
VERIFY_SECONDS = 600
_STATUS_REASONS = frozenset(
    {
        "Unknown",
        "Unauthorized",
        "Forbidden",
        "NotFound",
        "AlreadyExists",
        "Conflict",
        "Gone",
        "Invalid",
        "ServerTimeout",
        "Timeout",
        "TooManyRequests",
        "BadRequest",
        "MethodNotAllowed",
        "NotAcceptable",
        "RequestEntityTooLarge",
        "UnsupportedMediaType",
        "InternalError",
        "Expired",
        "ServiceUnavailable",
    }
)
_CAUSE_TYPES = frozenset(
    {
        "FieldValueNotFound",
        "FieldValueRequired",
        "FieldValueDuplicate",
        "FieldValueInvalid",
        "FieldValueNotSupported",
        "FieldValueForbidden",
        "FieldValueTooLong",
        "FieldValueTooMany",
        "InternalError",
        "UnexpectedServerResponse",
        "FieldValueTypeInvalid",
        "FieldManagerConflict",
        "ResourceVersionTooLarge",
    }
)
_FIELD_TOKENS = frozenset(
    {
        "apiVersion",
        "kind",
        "metadata",
        "name",
        "namespace",
        "uid",
        "resourceVersion",
        "labels",
        "annotations",
        "spec",
        "automountServiceAccountToken",
        "terminationGracePeriodSeconds",
        "restartPolicy",
        "initContainers",
        "containers",
        "ephemeralContainers",
        "targetContainerName",
        "image",
        "imagePullPolicy",
        "command",
        "args",
        "env",
        "envFrom",
        "value",
        "valueFrom",
        "fieldRef",
        "fieldPath",
        "resourceFieldRef",
        "resource",
        "divisor",
        "containerName",
        "secretKeyRef",
        "configMapKeyRef",
        "secretRef",
        "configMapRef",
        "key",
        "optional",
        "prefix",
        "resources",
        "requests",
        "limits",
        "cpu",
        "memory",
        "ephemeral-storage",
        "data",
        "stringData",
        "type",
        "rules",
        "apiGroups",
        "verbs",
        "resourceNames",
        "roleRef",
        "apiGroup",
        "subjects",
        "status",
        "resizePolicy",
        "securityContext",
        "ports",
        "volumeMounts",
        "volumes",
        "nodeName",
    }
)


def status_diagnostic(error: ApiException) -> dict[str, Any]:
    """Retain only bounded schema codes/field paths, never Status messages or values."""
    result: dict[str, Any] = {
        "http_status": error.status
        if type(error.status) is int and 100 <= error.status <= 599
        else None,
        "reason": None,
        "causes": [],
    }
    body = error.body
    try:
        if not isinstance(body, str) or len(body.encode()) > 65536:
            return result
        status = json.loads(body)
    except (ValueError, UnicodeError, RecursionError):
        return result
    if not isinstance(status, dict) or status.get("kind") != "Status":
        return result
    reason = status.get("reason")
    result["reason"] = (
        reason if isinstance(reason, str) and reason in _STATUS_REASONS else "unrecognized"
    )
    details = status.get("details")
    causes = details.get("causes") if isinstance(details, dict) else None
    if isinstance(causes, list):
        for cause in causes[:16]:
            if not isinstance(cause, dict):
                continue
            cause_type, field = cause.get("reason"), cause.get("field")
            valid_field = (
                isinstance(field, str)
                and len(field) <= 256
                and re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*|\[[0-9]{1,4}\])*", field
                )
                is not None
                and all(
                    token in _FIELD_TOKENS for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", field)
                )
            )
            result["causes"].append(
                {
                    "type": cause_type
                    if isinstance(cause_type, str) and cause_type in _CAUSE_TYPES
                    else "unrecognized",
                    "field": field if valid_field else "(field omitted)",
                }
            )
    return result


async def write_owned(
    sdk: Any,
    path: str,
    body: dict[str, Any],
    method: str,
    progress: dict[str, Any],
    *,
    content_type: Literal[
        "application/json", "application/strategic-merge-patch+json"
    ] = "application/json",
) -> Any:
    """Keep the last authored fixture request and safe failure classification."""
    progress["last_write"] = {"method": method, "path": path, "state": "started"}
    try:
        result = await sdk.call_api(
            path,
            method,
            body=body,
            response_types_map={200: "object", 201: "object", 202: "object"},
            auth_settings=["BearerToken"],
            header_params={"Content-Type": content_type},
            _return_http_data_only=True,
            _request_timeout=15,
        )
    except ApiException as error:
        progress["last_write"]["state"] = "failed"
        progress["api_failure"] = status_diagnostic(error)
        raise
    progress["last_write"]["state"] = "completed"
    return result


def fixture_manifests() -> tuple[dict[str, Any], ...]:
    """Only synthetic declarations and a fixture-owned command emit startup facts."""

    def manifest(kind: str, name: str, **fields: Any) -> dict[str, Any]:
        return {
            "apiVersion": RBAC_VERSION if kind in {"Role", "RoleBinding"} else "v1",
            "kind": kind,
            "metadata": {"name": name, **({"namespace": NAMESPACE} if kind != "Namespace" else {})},
            **fields,
        }

    return (
        manifest("Namespace", NAMESPACE),
        manifest("ConfigMap", CONFIG, data={"BASE": "base-start", "ORDER": "first"}),
        manifest("ConfigMap", SECOND_CONFIG, data={"ORDER": "second"}),
        manifest(
            "Secret",
            SECRET,
            data={
                "ORDER": base64.b64encode(b"secret-order").decode(),
                "TOKEN": base64.b64encode(b"fixture-synthetic-token").decode(),
            },
        ),
        manifest(
            "Role",
            READER,
            rules=[
                {
                    "apiGroups": [""],
                    "resources": ["pods"],
                    "verbs": ["get"],
                    "resourceNames": [POD],
                },
                {
                    "apiGroups": [""],
                    "resources": ["configmaps"],
                    "verbs": ["get"],
                    "resourceNames": [CONFIG, SECOND_CONFIG, MISSING],
                },
            ],
        ),
        manifest(
            "RoleBinding",
            READER,
            roleRef={"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": READER},
            subjects=[{"apiGroup": "rbac.authorization.k8s.io", "kind": "User", "name": READER}],
        ),
        manifest(
            "Pod",
            POD,
            metadata={
                "name": POD,
                "namespace": NAMESPACE,
                "labels": {"inspection": "fixture-owned"},
            },
            spec={
                "automountServiceAccountToken": False,
                "terminationGracePeriodSeconds": 0,
                "restartPolicy": "Never",
                "initContainers": [
                    {
                        "name": "init",
                        "image": SHELL_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "env": [{"name": "FAMILY", "value": "Init"}],
                        "command": ["sh", "-c", "exit 0"],
                    },
                    {
                        "name": "sidecar",
                        "image": SHELL_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "restartPolicy": "Always",
                        "env": [{"name": "FAMILY", "value": "Sidecar"}],
                        "command": ["sh", "-c", "sleep 600"],
                    },
                ],
                "containers": [
                    {
                        "name": "app",
                        "image": SHELL_IMAGE,
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "sh",
                            "-c",
                            'printf "%s\\n" "BASE=$BASE" "ORDER=$ORDER" "SNAP=$SNAP" "POD_NAME=$POD_NAME" "CPU_MILLI=$CPU_MILLI" "MEMORY_MIB=$MEMORY_MIB"; sleep 600',
                        ],
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "8Mi"},
                            "limits": {"cpu": "250m", "memory": "32Mi"},
                        },
                        "envFrom": [
                            {"configMapRef": {"name": CONFIG}},
                            {"configMapRef": {"name": SECOND_CONFIG}},
                            {"secretRef": {"name": SECRET}, "prefix": "PFX_"},
                            {"configMapRef": {"name": MISSING, "optional": True}},
                        ],
                        "env": [
                            {"name": "ORDER", "value": "explicit"},
                            {"name": "SNAP", "value": "$(BASE)/$(ORDER)/$(PFX_ORDER)"},
                            {"name": "ESCAPED", "value": "$$(BASE)"},
                            {
                                "name": "TOKEN",
                                "valueFrom": {"secretKeyRef": {"name": SECRET, "key": "TOKEN"}},
                            },
                            {
                                "name": "POD_NAME",
                                "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}},
                            },
                            {
                                "name": "LABEL",
                                "valueFrom": {
                                    "fieldRef": {"fieldPath": "metadata.labels['inspection']"}
                                },
                            },
                            {
                                "name": "CPU_MILLI",
                                "valueFrom": {
                                    "resourceFieldRef": {"resource": "limits.cpu", "divisor": "1m"}
                                },
                            },
                            {
                                "name": "MEMORY_MIB",
                                "valueFrom": {
                                    "resourceFieldRef": {
                                        "resource": "limits.memory",
                                        "divisor": "1Mi",
                                    }
                                },
                            },
                        ],
                    }
                ],
            },
        ),
    )


def ephemeral_fixture() -> dict[str, Any]:
    return {
        "name": "debug",
        "image": SHELL_IMAGE,
        "imagePullPolicy": "IfNotPresent",
        "targetContainerName": "app",
        "command": ["sh", "-c", "sleep 600"],
        "env": [{"name": "FAMILY", "value": "Ephemeral"}],
    }


def ephemeral_patch(uid: str | None) -> dict[str, Any]:
    """Bind the one owned subresource patch to UID without a status-version race."""
    if (
        not isinstance(uid, str)
        or not uid
        or len(uid) > 4096
        or any(ord(char) < 32 for char in uid)
    ):
        raise ValueError("A bounded owned Pod UID is required for the ephemeral fixture patch.")
    return {"metadata": {"uid": uid}, "spec": {"ephemeralContainers": [ephemeral_fixture()]}}


async def until(check: Callable[[], Awaitable[bool]], *, timeout: float = 90) -> None:
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(0.1)


@contextmanager
def inspection_receipts(receipts: list[dict[str, Any]]) -> Iterator[None]:
    """Observe actual product GETs without recording response values or credentials."""
    original = KubernetesSession.get_json

    async def traced(client: KubernetesSession, path: str, **kwargs: Any) -> dict[str, Any]:
        if len(receipts) >= 4096:
            raise AssertionError("Container inspection receipt limit exceeded.")
        receipt: dict[str, Any] = {
            "method": "GET",
            "path": path,
            "max_bytes": kwargs.get("max_bytes"),
        }
        receipts.append(receipt)
        try:
            result = await original(client, path, **kwargs)
        except HttpProblem as error:
            receipt["status"] = error.status
            raise
        else:
            receipt["status"] = 200
            return result

    with patch.object(KubernetesSession, "get_json", traced):
        yield


async def selected(
    service: ContainerInspectionService, snapshot: InspectionSnapshot, name: str
) -> str:
    item = next(
        entry
        for entry in snapshot.entries
        if entry.name == name and entry.precedence == "effective"
    )
    result = await service.disclose(service.new_intent(snapshot.id, item.id, "reveal"))
    if not result.complete or result.text is None:
        raise AssertionError("Expected synthetic fixture value was unresolved.")
    return result.text


async def close_owned(
    services: list[ContainerInspectionService], clients: list[KubernetesSession]
) -> None:
    """Drain service workers before any owned transport or private credentials close."""
    service_results = await asyncio.gather(
        *(service.close() for service in services), return_exceptions=True
    )
    client_results = await asyncio.gather(
        *(client.close() for client in reversed(clients)), return_exceptions=True
    )
    if any(isinstance(result, BaseException) for result in (*service_results, *client_results)):
        raise AssertionError("Owned container inspection cleanup failed.")


async def verify(
    cluster: OwnedCluster,
    evidence_dir: Path,
    *,
    progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    progress = {} if progress is None else progress
    progress["phase"] = "opening-owned-client"
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    catalog = load_catalog(request, {})
    original_config, environment = cluster.path.read_bytes(), dict(os.environ)
    clients: list[KubernetesSession] = []
    services: list[ContainerInspectionService] = []
    private_paths: list[Path] = []
    receipts: list[dict[str, Any]] = []
    checks: list[str] = []
    evidence_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with asyncio.timeout(VERIFY_SECONDS - 45):
            admin = KubernetesSession(catalog.select(cluster.context), 15)
            clients.append(admin)
            private_paths.append(Path(admin.directory.name))
            await admin.open()
            sdk = admin.api
            assert sdk is not None

            async def write(path: str, body: dict[str, Any], method: str = "POST") -> Any:
                return await write_owned(sdk, path, body, method, progress)

            reader = ResourceReader(admin)
            progress["phase"] = "discovering-owned-api"
            discovered = await reader.discover()
            for manifest in fixture_manifests():
                progress["phase"] = "creating-" + manifest["kind"]
                resource = next(
                    item
                    for item in discovered.resources
                    if item.api_version == manifest["apiVersion"] and item.kind == manifest["kind"]
                )
                await write(resource.path(manifest["metadata"].get("namespace")), manifest)
            pods = discovered.find("pods", version="v1")
            pod_path = pods.path(NAMESPACE) + "/" + POD
            pod_record = await reader.get(pods, POD, NAMESPACE)
            progress["phase"] = "adding-precreated-ephemeral"
            await write_owned(
                sdk,
                pod_path + "/ephemeralcontainers",
                ephemeral_patch(pod_record.uid),
                "PATCH",
                progress,
                content_type="application/strategic-merge-patch+json",
            )

            async def ready() -> bool:
                record = await reader.get(pods, POD, NAMESPACE)
                status = record.manifest.get("status", {})
                app = status.get("containerStatuses", [])
                init = status.get("initContainerStatuses", [])
                ephemeral = status.get("ephemeralContainerStatuses", [])
                return (
                    bool(app)
                    and all(value.get("ready") is True for value in app)
                    and any(
                        value.get("name") == "init"
                        and value.get("state", {}).get("terminated", {}).get("exitCode") == 0
                        for value in init
                    )
                    and any(
                        value.get("name") == "sidecar" and "running" in value.get("state", {})
                        for value in init
                    )
                    and any(
                        value.get("name") == "debug" and "running" in value.get("state", {})
                        for value in ephemeral
                    )
                )

            progress["phase"] = "waiting-for-fixture-readiness"
            await until(ready)
            await asyncio.sleep(0.5)
            pod_record = await reader.get(pods, POD, NAMESPACE)
            assert pod_record.uid is not None
            target = ResourceTarget(
                SessionIdentity(cluster.context, 1), "", "pods", NAMESPACE, POD, pod_record.uid
            )
            core_discovery = Discovery(
                tuple(
                    item
                    for item in discovered.resources
                    if item.group == ""
                    and item.version == "v1"
                    and item.name in {"pods", "configmaps", "secrets"}
                )
            )

            def service(
                client: KubernetesSession, identity: ContainerIdentity
            ) -> ContainerInspectionService:
                owner = ContainerInspectionService(
                    client,
                    pods,
                    target,
                    identity,
                    core_discovery,
                    AccessPolicy(True),
                    lambda: True,
                    now=lambda: datetime.now(UTC),
                )
                services.append(owner)
                return owner

            app = service(admin, ContainerIdentity("containers", "app", "App"))
            progress["phase"] = "checking-product-environment-and-container-families"
            with inspection_receipts(receipts):
                snapshot = await app.index()
                assert len(snapshot.sources) == 4
                assert (
                    next(item.state for item in snapshot.sources if item.ref.name == MISSING)
                    == "not-found"
                )
                expected = {
                    "BASE": "base-start",
                    "ORDER": "explicit",
                    "PFX_ORDER": "secret-order",
                    "SNAP": "base-start/explicit/secret-order",
                    "ESCAPED": "$(BASE)",
                    "TOKEN": "fixture-synthetic-token",
                    "POD_NAME": POD,
                    "LABEL": "fixture-owned",
                    "CPU_MILLI": "250",
                    "MEMORY_MIB": "32",
                }
                for name, value in expected.items():
                    assert await selected(app, snapshot, name) == value
                assert snapshot.image.declared == SHELL_IMAGE
                assert snapshot.image.pull_policy == "IfNotPresent"
                assert (
                    snapshot.image.status_image
                    and snapshot.image.image_id
                    and snapshot.image.container_id
                )
                assert "fixture-synthetic-token" not in repr(snapshot)
                checks.append(
                    "real-env-envFrom-order-prefix-expansion-secret-field-resource-and-image-facts"
                )
                for identity in (
                    ContainerIdentity("initContainers", "init", "Init"),
                    ContainerIdentity("initContainers", "sidecar", "Sidecar"),
                    ContainerIdentity("ephemeralContainers", "debug", "Ephemeral"),
                ):
                    owner = service(admin, identity)
                    family_snapshot = await owner.index()
                    assert await selected(owner, family_snapshot, "FAMILY") == identity.kind
                checks.append(
                    "regular-init-restartable-init-sidecar-and-precreated-ephemeral-identity"
                )

            async def startup_log() -> str:
                value = await sdk.call_api(
                    pod_path + "/log",
                    "GET",
                    query_params=[("container", "app"), ("limitBytes", 16384)],
                    response_types_map={200: "str"},
                    auth_settings=["BearerToken"],
                    _return_http_data_only=True,
                    _request_timeout=15,
                )
                if not isinstance(value, str):
                    raise AssertionError("Owned fixture startup log is not text.")
                return value

            progress["phase"] = "checking-fixture-startup-log"
            startup = await startup_log()
            assert (
                "BASE=base-start" in startup and "SNAP=base-start/explicit/secret-order" in startup
            )
            assert "CPU_MILLI=250" in startup and "MEMORY_MIB=32" in startup
            config_resource = discovered.find("configmaps", version="v1")
            config = await reader.get(config_resource, CONFIG, NAMESPACE)
            config_body = config.manifest
            config_body["data"]["BASE"] = "base-current-api"
            progress["phase"] = "updating-owned-configuration"
            await write(config_resource.path(NAMESPACE) + "/" + CONFIG, config_body, "PUT")
            with inspection_receipts(receipts):
                try:
                    await selected(app, snapshot, "SNAP")
                except AppError:
                    pass
                else:
                    raise AssertionError("Changed source unexpectedly reused the old binding.")
                refreshed = await app.index()
                assert await selected(app, refreshed, "BASE") == "base-current-api"
                assert (
                    await selected(app, refreshed, "SNAP")
                    == "base-current-api/explicit/secret-order"
                )
            assert await startup_log() == startup
            checks.append(
                "source-refresh-current-api-differs-from-unchanged-fixture-startup-environment"
            )

            low = KubernetesSession(
                catalog.select(cluster.context, ConnectionOverrides(as_user=READER)), 15
            )
            clients.append(low)
            private_paths.append(Path(low.directory.name))
            await low.open()
            restricted = service(low, ContainerIdentity("containers", "app", "App"))
            progress["phase"] = "checking-restricted-source-reads"
            with inspection_receipts(receipts):
                denied = await restricted.index()
                assert (
                    next(item.state for item in denied.sources if item.ref.name == SECRET)
                    == "forbidden"
                )
                assert await selected(restricted, denied, "ORDER") == "explicit"
                token_entry = next(item for item in denied.entries if item.name == "TOKEN")
                result = await restricted.disclose(
                    restricted.new_intent(denied.id, token_entry.id, "copy")
                )
                assert result.text is None and not result.complete
            checks.append(
                "real-rbac-denied-secret-get-preserves-independent-literal-and-no-value-copy"
            )

            progress["phase"] = "creating-formerly-absent-optional-source"
            await write(
                config_resource.path(NAMESPACE),
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": MISSING, "namespace": NAMESPACE},
                    "data": {"LATER": "synthetic"},
                },
            )
            with inspection_receipts(receipts):
                try:
                    await selected(app, refreshed, "ORDER")
                except AppError:
                    pass
                else:
                    raise AssertionError("Formerly absent optional source did not require reload.")
                before_recreation = await app.index()
            checks.append("formerly-absent-optional-source-appearance-requires-reload")

            progress["phase"] = "recreating-owned-pod"
            await write(
                pod_path,
                {
                    "apiVersion": "v1",
                    "kind": "DeleteOptions",
                    "gracePeriodSeconds": 0,
                    "preconditions": {"uid": target.uid},
                },
                "DELETE",
            )

            async def removed() -> bool:
                try:
                    await reader.get(pods, POD, NAMESPACE)
                except HttpProblem as error:
                    if error.status == 404:
                        return True
                    raise
                return False

            await until(removed)
            original_pod = next(value for value in fixture_manifests() if value["kind"] == "Pod")
            await write(pods.path(NAMESPACE), original_pod)
            replacement = await reader.get(pods, POD, NAMESPACE)
            assert replacement.uid != target.uid
            with inspection_receipts(receipts):
                try:
                    await selected(app, before_recreation, "ORDER")
                except AppError:
                    pass
                else:
                    raise AssertionError("Same-name replacement rebound the captured inspector.")
            checks.append("same-name-pod-recreation-never-rebinds-captured-uid")
            progress["phase"] = "checking-product-get-ledger"
            allowed = {
                pod_path,
                *(
                    f"/api/v1/namespaces/{NAMESPACE}/configmaps/{name}"
                    for name in (CONFIG, SECOND_CONFIG, MISSING)
                ),
                f"/api/v1/namespaces/{NAMESPACE}/secrets/{SECRET}",
            }
            assert receipts and all(
                item["method"] == "GET"
                and item["path"] in allowed
                and type(item["max_bytes"]) is int
                and 0 < item["max_bytes"] <= 2 * 1024 * 1024
                for item in receipts
            )
            checks.append(
                "product-only-exact-core-object-get-no-list-watch-exec-log-registry-node-service-access"
            )
    except ApiException as error:
        progress["api_failure"] = status_diagnostic(error)
        raise
    finally:
        await finish_owned(asyncio.create_task(close_owned(services, clients)))
        (evidence_dir / "container-inspection-api.json").write_text(
            json.dumps(receipts, indent=2) + "\n"
        )
        assert all(owner.operation_count == 0 for owner in services)
        assert all(not path.exists() for path in private_paths)
        assert cluster.path.read_bytes() == original_config and dict(os.environ) == environment
        progress["owned_sessions_drained"] = True
    return {
        "checks": checks,
        "product_get_count": len(receipts),
        "owned_kubeconfig_unchanged": True,
        "environment_unchanged": True,
        "private_sessions_deleted": True,
        "all_operations_drained": True,
        "node_image": NODE_IMAGE,
        "shell_image": SHELL_IMAGE,
    }


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
        root / "scripts/verify_container_inspection_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, type=Path)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    if args.evidence.exists() or (args.evidence.parent / "container-inspection-api.json").exists():
        raise ValueError("Use a fresh evidence directory; earlier outcomes must be preserved.")
    if not args.kind.is_absolute() or sha256_file(args.kind) != KIND_SHA256:
        raise ValueError("Use the official checksum-verified kind v0.33.0 Linux amd64 fixture.")
    root = Path(__file__).resolve().parents[1]
    captured, environment = input_hashes(root), dict(os.environ)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "owned_cluster_deleted": False,
        "private_directory_deleted": False,
        "deadline_seconds": VERIFY_SECONDS,
    }
    started, cluster, problem = time.monotonic(), None, None
    try:
        with owned_cluster(str(args.kind), docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, args.evidence.parent, progress=result)))
            except BaseException as error:
                problem = error
                result["failure_type"] = type(error).__name__
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        result["environment_unchanged"] = dict(os.environ) == environment
        if problem is not None:
            raise problem
        assert (
            result["inputs_unchanged"]
            and result["environment_unchanged"]
            and result["private_directory_deleted"]
        )
        result["status"] = "passed"
    except BaseException as error:
        result.setdefault("failure_type", type(error).__name__)
        if cluster is not None:
            result["private_directory_deleted"] = not cluster.directory.exists()
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind container inspection checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned container inspection verification failed ({type(error).__name__}); retain original receipts.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
