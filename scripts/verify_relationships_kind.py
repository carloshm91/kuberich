"""O03: actual ownership, declarations, endpoints and native navigation on owned kind."""

import argparse
import asyncio
import hashlib
import json
import logging
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any
from unittest.mock import patch

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.relationships import (
    RelationKind,
    RelationshipMode,
    RelationshipRef,
    RelationshipRequest,
    RelationshipRow,
    RelationshipScope,
    RelationshipSnapshot,
    RelationshipStatus,
    relationship_path_key,
)
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.ownership import finish_owned
from kuberich.services.relationships import RelationshipService
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.ui.app import KubeRichApp
from scripts.owned_kind import NODE_IMAGE, SHELL_IMAGE, OwnedCluster, owned_cluster

NAMESPACE = "kuberich-owned-relationships"
FIXTURE_LABEL = "owned-relationships"
CUSTOM_GROUP = "relationships.kuberich.test"
CUSTOM_NAME = "ownedwidgets"
CUSTOM_KIND = "OwnedWidget"
CONFIGMAP = "owned-config"
SECRET = "owned-secret"
SERVICEACCOUNT = "owned-account"
PVC = "owned-claim"
PV = "owned-volume"
PRIORITYCLASS = "owned-priority"
DEPLOYMENT = "owned-running"
SERVICE = "owned-service"
SELECTORLESS = "owned-selectorless"
SYNTHETIC_VALUE = "synthetic-relationship-fixture-value"
VERIFY_SECONDS = 600


def pod_template(name: str) -> dict[str, Any]:
    """A pinned, live Pod declaration for all five supported UsedBy targets."""
    return {
        "metadata": {"labels": {FIXTURE_LABEL: name}},
        "spec": {
            "terminationGracePeriodSeconds": 0,
            "automountServiceAccountToken": False,
            "serviceAccountName": SERVICEACCOUNT,
            "priorityClassName": PRIORITYCLASS,
            "tolerations": [{"operator": "Exists"}],
            "volumes": [{"name": "storage", "persistentVolumeClaim": {"claimName": PVC}}],
            "containers": [
                {
                    "name": "app",
                    "image": SHELL_IMAGE,
                    "command": ["sh", "-c", "sleep 3600"],
                    "resources": {
                        "requests": {"cpu": "10m", "memory": "8Mi"},
                        "limits": {"cpu": "100m", "memory": "32Mi"},
                    },
                    "envFrom": [
                        {"configMapRef": {"name": CONFIGMAP}},
                        {"secretRef": {"name": SECRET}},
                    ],
                    "volumeMounts": [{"name": "storage", "mountPath": "/owned-storage"}],
                }
            ],
        },
    }


def fixture_manifests() -> tuple[dict[str, Any], ...]:
    manifests: list[dict[str, Any]] = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": CONFIGMAP},
            "data": {"OWNED_CONFIG": SYNTHETIC_VALUE},
        },
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": SECRET},
            "stringData": {"OWNED_SECRET": SYNTHETIC_VALUE},
        },
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {"name": SERVICEACCOUNT},
            "automountServiceAccountToken": False,
            "secrets": [{"name": SECRET}],
        },
        {
            "apiVersion": "scheduling.k8s.io/v1",
            "kind": "PriorityClass",
            "metadata": {"name": PRIORITYCLASS},
            "value": 1000,
            "globalDefault": False,
            "description": "Synthetic disposable relationship fixture",
        },
        {
            "apiVersion": "v1",
            "kind": "PersistentVolume",
            "metadata": {"name": PV},
            "spec": {
                "capacity": {"storage": "1Mi"},
                "accessModes": ["ReadWriteOnce"],
                "persistentVolumeReclaimPolicy": "Retain",
                "storageClassName": "",
                "claimRef": {"namespace": NAMESPACE, "name": PVC},
                "hostPath": {
                    "path": "/tmp/kuberich-owned-relationships",
                    "type": "DirectoryOrCreate",
                },
            },
        },
        {
            "apiVersion": "v1",
            "kind": "PersistentVolumeClaim",
            "metadata": {"name": PVC},
            "spec": {
                "accessModes": ["ReadWriteOnce"],
                "storageClassName": "",
                "volumeName": PV,
                "resources": {"requests": {"storage": "1Mi"}},
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": SERVICE},
            "spec": {
                "selector": {FIXTURE_LABEL: DEPLOYMENT},
                "ports": [{"name": "http", "port": 8080, "targetPort": 8080}],
            },
        },
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": SELECTORLESS},
            "spec": {"ports": [{"name": "http", "port": 8080}]},
        },
        {
            "apiVersion": "discovery.k8s.io/v1",
            "kind": "EndpointSlice",
            "metadata": {
                "name": "owned-address-only",
                "labels": {
                    "kubernetes.io/service-name": SELECTORLESS,
                    "endpointslice.kubernetes.io/managed-by": "kuberich-owned-verifier",
                },
            },
            "addressType": "IPv4",
            "endpoints": [
                {
                    "addresses": ["192.0.2.70"],
                    "conditions": {"ready": False, "serving": False, "terminating": False},
                }
            ],
            "ports": [{"name": "http", "protocol": "TCP", "port": 8080}],
        },
    ]
    for name, kind, api_version in (
        (DEPLOYMENT, "Deployment", "apps/v1"),
        ("owned-zero-deployment", "Deployment", "apps/v1"),
        ("owned-zero-replicaset", "ReplicaSet", "apps/v1"),
        ("owned-zero-statefulset", "StatefulSet", "apps/v1"),
        ("owned-zero-daemonset", "DaemonSet", "apps/v1"),
        ("owned-suspended-job", "Job", "batch/v1"),
        ("owned-suspended-cronjob", "CronJob", "batch/v1"),
        ("owned-zero-controller", "ReplicationController", "v1"),
    ):
        template = pod_template(name)
        spec: dict[str, Any] = {"template": template}
        if kind in {"Deployment", "ReplicaSet", "StatefulSet"}:
            spec.update(
                replicas=1 if name == DEPLOYMENT else 0,
                selector={"matchLabels": {FIXTURE_LABEL: name}},
            )
        if kind == "ReplicationController":
            spec.update(replicas=0, selector={FIXTURE_LABEL: name})
        if kind == "StatefulSet":
            spec["serviceName"] = SERVICE
        if kind == "DaemonSet":
            spec["selector"] = {"matchLabels": {FIXTURE_LABEL: name}}
            template["spec"]["nodeSelector"] = {"kuberich-owned-absent": "never"}
        if kind in {"Job", "CronJob"}:
            template["spec"]["restartPolicy"] = "Never"
            if kind == "Job":
                spec["suspend"] = True
            else:
                spec = {"schedule": "0 * * * *", "suspend": True, "jobTemplate": {"spec": spec}}
        manifests.append(
            {"apiVersion": api_version, "kind": kind, "metadata": {"name": name}, "spec": spec}
        )
    return tuple(manifests)


def custom_resource_definition() -> dict[str, Any]:
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": CUSTOM_NAME + "." + CUSTOM_GROUP},
        "spec": {
            "group": CUSTOM_GROUP,
            "scope": "Namespaced",
            "names": {"plural": CUSTOM_NAME, "singular": "ownedwidget", "kind": CUSTOM_KIND},
            "versions": [
                {
                    "name": "v1",
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": {
                            "type": "object",
                            "properties": {
                                "spec": {
                                    "type": "object",
                                    "properties": {"purpose": {"type": "string"}},
                                }
                            },
                        }
                    },
                }
            ],
        },
    }


def checkpoint(directory: Path, stage: str, **receipt: Any) -> None:
    """Append the observed receipt before its associated acceptance assertion."""
    directory.mkdir(parents=True, exist_ok=True)
    entry = {"stage": stage, "observed_at": datetime.now(UTC).isoformat(), **receipt}
    (directory / "relationships-stage.json").write_text(json.dumps(entry, indent=2) + "\n")
    with (directory / "relationships-stages.jsonl").open("a") as stream:
        stream.write(json.dumps(entry) + "\n")


def graph_receipt(snapshot: RelationshipSnapshot) -> dict[str, Any]:
    def reference(ref: RelationshipRef) -> dict[str, Any]:
        return {
            "api_version": ref.api_version,
            "kind": ref.kind,
            "namespace": ref.namespace,
            "name": ref.name,
            "expected_uid": ref.uid,
            "resource": ref.resource.name if ref.resource else None,
        }

    return {
        "root": {"name": snapshot.request.scope.root.name, "uid": snapshot.request.scope.root.uid},
        "mode": str(snapshot.request.scope.mode),
        "revision": snapshot.request.revision,
        "requests_used": snapshot.requests_used,
        "rows": [
            {
                "path": row.path,
                "ref": reference(row.ref),
                "observed_uid": row.observed_uid,
                "status": str(row.status),
                "relation": str(row.relation) if row.relation else None,
                "direction": str(row.direction) if row.direction else None,
                "details": row.details,
            }
            for row in snapshot.rows
        ],
        "sources": [
            {
                "family": source.family,
                "namespace": source.namespace,
                "status": str(source.status),
                "collection": asdict(source.collection) if source.collection else None,
                "resource_version": source.resource_version,
                "observed_at": source.observed_at.isoformat() if source.observed_at else None,
                "detail": source.detail,
            }
            for source in snapshot.sources
        ],
    }


@contextmanager
def trace_reads(receipts: list[dict[str, Any]]) -> Iterator[None]:
    """Observe actual adapter reads without replacing the real network operation."""
    original = KubernetesSession.get_json

    async def observed(session: KubernetesSession, path: str, **kwargs: Any) -> dict[str, Any]:
        if len(receipts) >= 20000:
            raise AssertionError("Owned verification read trace exceeded its finite bound.")
        receipts.append({"path": path, "params": kwargs.get("params")})
        return await original(session, path, **kwargs)

    with patch.object(KubernetesSession, "get_json", observed):
        yield


async def until(predicate: Callable[[], Awaitable[bool]], *, timeout: float = 180) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.2)


def pod_wait_receipt(record: ResourceRecord | None) -> dict[str, Any] | None:
    """Retain useful owned-Pod state codes without arbitrary API messages or env."""
    if record is None:
        return None
    status = record.manifest.get("status", {})
    status = status if isinstance(status, dict) else {}
    phase = status.get("phase")
    containers = []
    entries = status.get("containerStatuses", [])
    reasons = {
        "ImagePullBackOff",
        "ErrImagePull",
        "ContainerCreating",
        "CreateContainerConfigError",
        "CrashLoopBackOff",
        "PodInitializing",
        "CreateContainerError",
        "InvalidImageName",
        "RunContainerError",
    }
    for entry in entries[:16] if isinstance(entries, list) else ():
        if not isinstance(entry, dict):
            continue
        state = entry.get("state")
        state = state if isinstance(state, dict) else {}
        waiting = state.get("waiting")
        waiting = waiting if isinstance(waiting, dict) else {}
        reason = waiting.get("reason")
        containers.append(
            {
                "ready": entry.get("ready") is True,
                "restart_count": entry.get("restartCount")
                if type(entry.get("restartCount")) is int
                else None,
                "waiting_reason": reason
                if isinstance(reason, str) and reason in reasons
                else "Other"
                if reason
                else None,
                "running": isinstance(state.get("running"), dict),
            }
        )
    return {
        "name": record.name,
        "uid": record.uid,
        "phase": phase
        if phase in {"Pending", "Running", "Succeeded", "Failed", "Unknown"}
        else None,
        "containers": containers,
    }


def target_for(
    identity: SessionIdentity, resource: ApiResource, record: ResourceRecord
) -> ResourceTarget:
    if record.uid is None:
        raise AssertionError("Owned API object did not supply a UID.")
    return ResourceTarget(
        identity, resource.group, resource.name, record.namespace, record.name, record.uid
    )


async def verify(cluster: OwnedCluster, evidence_dir: Path) -> dict[str, Any]:
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    catalog = load_catalog(request, {})
    sessions = SessionService(catalog, request)
    before = cluster.path.read_bytes()
    delegated: KubernetesSession | None = None
    checks: list[str] = []
    paths: list[dict[str, Any]] = []
    identities: dict[str, dict[str, str | None]] = {}
    try:
        async with asyncio.timeout(VERIFY_SECONDS):
            with trace_reads(paths):
                checkpoint(
                    evidence_dir,
                    "connecting-verified-private-owned-context",
                    deadline_seconds=VERIFY_SECONDS,
                )
                await sessions.connect(cluster.context)
                connection, identity = sessions.client, sessions.observation.identity
                assert (
                    connection is not None and connection.api is not None and identity is not None
                )
                sdk = connection.api

                async def write(path: str, body: dict[str, Any], method: str = "POST") -> Any:
                    return await sdk.call_api(
                        path,
                        method,
                        body=body,
                        response_types_map={200: "object", 201: "object", 202: "object"},
                        auth_settings=["BearerToken"],
                        header_params={"Content-Type": "application/json"},
                        _return_http_data_only=True,
                        _request_timeout=15,
                    )

                checkpoint(evidence_dir, "creating-synthetic-owned-fixtures")
                await write("/api/v1/namespaces", {"metadata": {"name": NAMESPACE}})
                reader = ResourceReader(connection)
                discovery = await reader.discover()

                def descriptor(
                    manifest: dict[str, Any], current: Discovery = discovery
                ) -> ApiResource:
                    return next(
                        resource
                        for resource in current.resources
                        if resource.api_version == manifest["apiVersion"]
                        and resource.kind == manifest["kind"]
                    )

                for manifest in fixture_manifests():
                    resource = descriptor(manifest)
                    await write(resource.path(NAMESPACE if resource.namespaced else None), manifest)
                await write(
                    "/apis/apiextensions.k8s.io/v1/customresourcedefinitions",
                    custom_resource_definition(),
                )

                async def custom_ready() -> bool:
                    nonlocal discovery
                    discovery = await reader.discover()
                    return any(
                        resource.group == CUSTOM_GROUP and resource.name == CUSTOM_NAME
                        for resource in discovery.resources
                    )

                await until(custom_ready, timeout=30)
                custom = discovery.find(CUSTOM_NAME, group=CUSTOM_GROUP)
                await write(
                    custom.path(NAMESPACE),
                    {
                        "apiVersion": custom.api_version,
                        "kind": custom.kind,
                        "metadata": {"name": "owned-owner"},
                        "spec": {"purpose": "synthetic-owner"},
                    },
                )
                custom_record = await reader.get(custom, "owned-owner", NAMESPACE)
                await write(
                    "/api/v1/namespaces/" + NAMESPACE + "/configmaps",
                    {
                        "metadata": {
                            "name": "owned-custom-dependent",
                            "ownerReferences": [
                                {
                                    "apiVersion": custom.api_version,
                                    "kind": custom.kind,
                                    "name": custom_record.name,
                                    "uid": custom_record.uid,
                                    "controller": True,
                                }
                            ],
                        },
                        "data": {},
                    },
                )

                running: ResourceRecord | None = None
                replica: ResourceRecord | None = None
                pod: ResourceRecord | None = None
                node: ResourceRecord | None = None

                async def controllers_ready() -> bool:
                    nonlocal running, replica, pod, node
                    running = await reader.get(
                        discovery.find("deployments", group="apps"), DEPLOYMENT, NAMESPACE
                    )
                    replicas = await reader.list(
                        discovery.find("replicasets", group="apps"), NAMESPACE
                    )
                    pods = await reader.list(discovery.find("pods"), NAMESPACE)
                    replica = next(
                        (
                            record
                            for record in replicas.items
                            if any(
                                owner.get("uid") == running.uid
                                for owner in record.manifest["metadata"].get("ownerReferences", [])
                            )
                        ),
                        None,
                    )
                    pod = next(
                        (
                            record
                            for record in pods.items
                            if replica is not None
                            and any(
                                owner.get("uid") == replica.uid
                                for owner in record.manifest["metadata"].get("ownerReferences", [])
                            )
                        ),
                        None,
                    )
                    checkpoint(
                        evidence_dir,
                        "waiting-for-real-controller-uids-and-pod-placement",
                        deployment_uid=running.uid,
                        replica_uid=replica.uid if replica else None,
                        pod_uid=pod.uid if pod else None,
                        pod_state=pod_wait_receipt(pod),
                        node_name=pod.manifest.get("spec", {}).get("nodeName") if pod else None,
                    )
                    if pod is None or pod.manifest.get("status", {}).get("phase") != "Running":
                        return False
                    name = pod.manifest.get("spec", {}).get("nodeName")
                    if not isinstance(name, str) or not name:
                        return False
                    node = await reader.get(discovery.find("nodes"), name)
                    return True

                await until(controllers_ready)
                assert (
                    running is not None
                    and replica is not None
                    and pod is not None
                    and node is not None
                )
                for label, record in (
                    ("deployment", running),
                    ("replicaset", replica),
                    ("pod", pod),
                    ("node", node),
                    ("custom", custom_record),
                ):
                    identities[label] = {
                        "name": record.name,
                        "uid": record.uid,
                        "namespace": record.namespace,
                    }
                checkpoint(
                    evidence_dir, "real-controller-identities-read-back", identities=identities
                )

                async def graph(
                    resource: ApiResource,
                    record: ResourceRecord,
                    mode: RelationshipMode = RelationshipMode.XRAY,
                ) -> tuple[RelationshipService, RelationshipSnapshot]:
                    scope = RelationshipScope(
                        target_for(identity, resource, record), resource, NAMESPACE, mode
                    )
                    collector = RelationshipService(
                        reader, discovery, scope, lambda _: sessions.client is connection
                    )
                    snapshot = await collector.collect(
                        RelationshipRequest(scope, 1, frozenset({()})), lambda _: None
                    )
                    return collector, snapshot

                async def expand(
                    collector: RelationshipService,
                    snapshot: RelationshipSnapshot,
                    row: RelationshipRow,
                ) -> RelationshipSnapshot:
                    return await collector.collect(
                        replace(
                            snapshot.request,
                            revision=snapshot.request.revision + 1,
                            expanded=snapshot.request.expanded | {row.path},
                        ),
                        lambda _: None,
                    )

                checkpoint(evidence_dir, "collecting-actual-deployment-replicaset-pod-node")
                collector, snapshot = await graph(
                    discovery.find("deployments", group="apps"), running
                )
                checkpoint(evidence_dir, "deployment-graph-observed", graph=graph_receipt(snapshot))
                rs_row = next(
                    row
                    for row in snapshot.rows
                    if row.ref.uid == replica.uid and row.relation is RelationKind.CONTROLLER_OWNER
                )
                snapshot = await expand(collector, snapshot, rs_row)
                checkpoint(
                    evidence_dir,
                    "replicaset-owned-pod-graph-observed",
                    graph=graph_receipt(snapshot),
                )
                pod_row = next(
                    row
                    for row in snapshot.rows
                    if row.ref.uid == pod.uid
                    and row.relation is RelationKind.CONTROLLER_OWNER
                    and row.path[:-1] == rs_row.path
                )
                snapshot = await expand(collector, snapshot, pod_row)
                checkpoint(
                    evidence_dir, "pod-node-placement-graph-observed", graph=graph_receipt(snapshot)
                )
                node_row = next(
                    row
                    for row in snapshot.rows
                    if row.relation is RelationKind.NODE and row.ref.name == node.name
                )
                assert (
                    node_row.status is RelationshipStatus.READY
                    and node_row.observed_uid == node.uid
                )
                assert rs_row.observed_uid == replica.uid and pod_row.observed_uid == pod.uid
                assert any(
                    row.relation is RelationKind.SELECTOR and row.ref.uid == pod.uid
                    for row in snapshot.rows
                )
                checks.append(
                    "real-deployment-replicaset-pod-owner-uids-selector-distinction-and-node-placement"
                )

                service_resource = discovery.find("services")
                service_record = await reader.get(service_resource, SERVICE, NAMESPACE)
                endpoint_graph: RelationshipSnapshot | None = None

                async def endpoints_ready() -> bool:
                    nonlocal endpoint_graph
                    endpoint_collector, endpoint_graph = await graph(
                        service_resource, service_record
                    )
                    slice_row = next(
                        (
                            row
                            for row in endpoint_graph.rows
                            if row.ref.kind == "EndpointSlice"
                            and row.status is RelationshipStatus.READY
                        ),
                        None,
                    )
                    if slice_row is None:
                        checkpoint(
                            evidence_dir,
                            "waiting-for-generated-endpointslices",
                            graph=graph_receipt(endpoint_graph),
                        )
                        return False
                    endpoint_graph = await expand(endpoint_collector, endpoint_graph, slice_row)
                    checkpoint(
                        evidence_dir,
                        "generated-endpointslice-targets-observed",
                        graph=graph_receipt(endpoint_graph),
                    )
                    return any(
                        row.relation is RelationKind.ENDPOINT
                        and row.ref.kind == "Pod"
                        and row.ref.uid == pod.uid
                        and row.observed_uid == pod.uid
                        and row.status is RelationshipStatus.READY
                        for row in endpoint_graph.rows
                    )

                await until(endpoints_ready, timeout=60)
                assert endpoint_graph is not None
                selectorless_record = await reader.get(service_resource, SELECTORLESS, NAMESPACE)
                selectorless_collector, address_graph = await graph(
                    service_resource, selectorless_record
                )
                checkpoint(
                    evidence_dir, "selectorless-slice-observed", graph=graph_receipt(address_graph)
                )
                slice_row = next(
                    row for row in address_graph.rows if row.ref.kind == "EndpointSlice"
                )
                address_graph = await expand(selectorless_collector, address_graph, slice_row)
                checkpoint(
                    evidence_dir,
                    "selectorless-address-only-observed",
                    graph=graph_receipt(address_graph),
                )
                assert any(
                    row.ref.kind == "EndpointAddress"
                    and row.status is RelationshipStatus.UNAVAILABLE
                    and row.ref.uid is None
                    for row in address_graph.rows
                )
                checks.append(
                    "real-generated-slices-preserve-target-uids-and-selectorless-addresses-do-not-invent-pods"
                )

                usedby: dict[str, dict[str, Any]] = {}
                for group, name, target_name in (
                    ("", "configmaps", CONFIGMAP),
                    ("", "secrets", SECRET),
                    ("", "serviceaccounts", SERVICEACCOUNT),
                    ("", "persistentvolumeclaims", PVC),
                    ("scheduling.k8s.io", "priorityclasses", PRIORITYCLASS),
                ):
                    resource = discovery.find(name, group=group)
                    record = await reader.get(
                        resource, target_name, NAMESPACE if resource.namespaced else None
                    )
                    identities[name] = {
                        "name": record.name,
                        "uid": record.uid,
                        "namespace": record.namespace,
                    }
                    _, declarations = await graph(resource, record, RelationshipMode.USED_BY)
                    receipt = graph_receipt(declarations)
                    usedby[name] = receipt
                    checkpoint(evidence_dir, "usedby-" + name + "-observed", graph=receipt)
                    assert all(
                        source.status is RelationshipStatus.READY for source in declarations.sources
                    )
                    assert any(
                        row.ref.uid == running.uid and row.relation is RelationKind.REFERENCE
                        for row in declarations.rows
                    )
                    assert any(
                        row.ref.name == "owned-zero-deployment"
                        and row.relation is RelationKind.REFERENCE
                        for row in declarations.rows
                    )
                    expected_templates = {
                        "Deployment",
                        "ReplicaSet",
                        "StatefulSet",
                        "DaemonSet",
                        "Job",
                        "CronJob",
                        "ReplicationController",
                    }
                    assert expected_templates <= {row.ref.kind for row in declarations.rows}
                    assert SYNTHETIC_VALUE not in json.dumps(receipt)
                checks.append(
                    "real-all-five-usedby-targets-and-all-seven-zero-replica-or-suspended-template-families"
                )

                claim_resource, volume_resource = (
                    discovery.find("persistentvolumeclaims"),
                    discovery.find("persistentvolumes"),
                )
                claim = await reader.get(claim_resource, PVC, NAMESPACE)
                volume = await reader.get(volume_resource, PV)
                _, claim_graph = await graph(claim_resource, claim)
                _, volume_graph = await graph(volume_resource, volume)
                checkpoint(
                    evidence_dir,
                    "pv-pvc-declarations-observed",
                    claim_graph=graph_receipt(claim_graph),
                    volume_graph=graph_receipt(volume_graph),
                    claim_ref_uid=volume.manifest["spec"].get("claimRef", {}).get("uid"),
                    expected_claim_uid=claim.uid,
                )
                assert any(
                    row.ref.name == PV
                    and row.observed_uid == volume.uid
                    and row.relation is RelationKind.REFERENCE
                    for row in claim_graph.rows
                )
                assert any(
                    row.ref.uid == claim.uid
                    and row.observed_uid == claim.uid
                    and row.relation is RelationKind.REFERENCE
                    for row in volume_graph.rows
                )
                checks.append("real-bound-pv-pvc-explicit-volume-and-claim-uid-references")

                dependent_resource = discovery.find("configmaps")
                dependent = await reader.get(
                    dependent_resource, "owned-custom-dependent", NAMESPACE
                )
                _, custom_graph = await graph(dependent_resource, dependent)
                checkpoint(
                    evidence_dir, "custom-owner-gvk-observed", graph=graph_receipt(custom_graph)
                )
                assert any(
                    row.ref.resource == custom
                    and row.ref.uid == custom_record.uid
                    and row.observed_uid == custom_record.uid
                    for row in custom_graph.rows
                )
                original_scope = RelationshipScope(
                    target_for(identity, custom, custom_record),
                    custom,
                    NAMESPACE,
                    RelationshipMode.XRAY,
                )
                await write(
                    custom.path(NAMESPACE) + "/" + custom_record.name,
                    {
                        "apiVersion": "v1",
                        "kind": "DeleteOptions",
                        "preconditions": {"uid": custom_record.uid},
                    },
                    "DELETE",
                )

                async def custom_deleted() -> bool:
                    try:
                        await reader.get(custom, custom_record.name, NAMESPACE)
                    except HttpProblem as problem:
                        if problem.status == 404:
                            return True
                        raise
                    return False

                await until(custom_deleted, timeout=30)
                await write(
                    custom.path(NAMESPACE),
                    {
                        "apiVersion": custom.api_version,
                        "kind": custom.kind,
                        "metadata": {"name": custom_record.name},
                        "spec": {"purpose": "synthetic-replacement"},
                    },
                )
                replacement = await reader.get(custom, custom_record.name, NAMESPACE)
                replaced = await RelationshipService(
                    reader, discovery, original_scope, lambda _: True
                ).collect(RelationshipRequest(original_scope, 1, frozenset({()})), lambda _: None)
                checkpoint(
                    evidence_dir,
                    "custom-same-name-replacement-observed",
                    expected_uid=custom_record.uid,
                    replacement_uid=replacement.uid,
                    graph=graph_receipt(replaced),
                )
                assert (
                    replacement.uid != custom_record.uid
                    and replaced.rows[0].status is RelationshipStatus.REPLACED
                )
                assert (
                    replaced.rows[0].ref.uid == custom_record.uid
                    and replaced.rows[0].observed_uid == replacement.uid
                )
                checks.append("real-discovered-custom-owner-path-and-recreated-root-uid-rejected")

                user = "kuberich-owned-relationships-reader"
                rbac = "/apis/rbac.authorization.k8s.io/v1"
                await write(
                    rbac + "/clusterroles",
                    {
                        "metadata": {"name": "owned-relationships-discovery"},
                        "rules": [
                            {
                                "nonResourceURLs": ["/api", "/api/*", "/apis", "/apis/*"],
                                "verbs": ["get"],
                            }
                        ],
                    },
                )
                subject = [{"apiGroup": "rbac.authorization.k8s.io", "kind": "User", "name": user}]
                await write(
                    rbac + "/clusterrolebindings",
                    {
                        "metadata": {"name": "owned-relationships-discovery"},
                        "roleRef": {
                            "apiGroup": "rbac.authorization.k8s.io",
                            "kind": "ClusterRole",
                            "name": "owned-relationships-discovery",
                        },
                        "subjects": subject,
                    },
                )
                await write(
                    rbac + f"/namespaces/{NAMESPACE}/roles",
                    {
                        "metadata": {"name": "owned-relationships-reader"},
                        "rules": [
                            {
                                "apiGroups": [""],
                                "resources": ["configmaps", "pods"],
                                "verbs": ["get", "list"],
                            }
                        ],
                    },
                )
                await write(
                    rbac + f"/namespaces/{NAMESPACE}/rolebindings",
                    {
                        "metadata": {"name": "owned-relationships-reader"},
                        "roleRef": {
                            "apiGroup": "rbac.authorization.k8s.io",
                            "kind": "Role",
                            "name": "owned-relationships-reader",
                        },
                        "subjects": subject,
                    },
                )
                delegated = KubernetesSession(
                    catalog.select(cluster.context, ConnectionOverrides(as_user=user)), 15
                )
                await delegated.open()
                restricted_reader = ResourceReader(delegated)

                async def authorized() -> bool:
                    try:
                        await restricted_reader.get(
                            discovery.find("configmaps"), CONFIGMAP, NAMESPACE
                        )
                        return True
                    except HttpProblem as problem:
                        if problem.status != 403:
                            raise
                        return False

                await until(authorized, timeout=30)
                config = await restricted_reader.get(
                    discovery.find("configmaps"), CONFIGMAP, NAMESPACE
                )
                restricted_scope = RelationshipScope(
                    target_for(
                        SessionIdentity(cluster.context, identity.generation + 1),
                        discovery.find("configmaps"),
                        config,
                    ),
                    discovery.find("configmaps"),
                    NAMESPACE,
                    RelationshipMode.USED_BY,
                )
                limited = await RelationshipService(
                    restricted_reader,
                    await restricted_reader.discover(),
                    restricted_scope,
                    lambda _: delegated is not None,
                ).collect(RelationshipRequest(restricted_scope, 1, frozenset({()})), lambda _: None)
                checkpoint(
                    evidence_dir,
                    "restricted-rbac-supported-family-denial-observed",
                    graph=graph_receipt(limited),
                )
                assert any(
                    source.status is RelationshipStatus.FORBIDDEN for source in limited.sources
                )
                assert not any(
                    "completely scanned scope" in detail
                    for row in limited.rows
                    for detail in row.details
                )
                checks.append(
                    "real-restricted-reader-denied-family-remains-incomplete-never-unused"
                )

                checkpoint(evidence_dir, "opening-native-app-relationships-and-history")
                app = KubeRichApp(
                    Settings(read_only=True),
                    logging.Logger("owned-relationships", level=100),
                    catalog=catalog,
                    connection=request,
                    environment={},
                    directory=cluster.directory,
                )
                async with app.run_test(size=(120, 38)) as pilot:

                    async def connected() -> bool:
                        return app.workspace.store.observation.snapshot is not None

                    await until(connected, timeout=60)
                    await app.run_command("deployments")

                    async def deployments_ready() -> bool:
                        return (
                            app.state.view_kind == "deployments"
                            and running.uid in app.standard_table.rows
                        )

                    await until(deployments_ready, timeout=30)
                    assert running.uid is not None
                    app.standard_table.move_cursor(
                        row=app.standard_table.get_row_index(running.uid)
                    )
                    await pilot.pause()
                    original_viewport = app.standard_table.capture_viewport()
                    await app.run_command("xray")

                    async def graph_ready() -> bool:
                        current = app.workspace.store.observation.relationships
                        checkpoint(
                            evidence_dir,
                            "waiting-for-native-xray",
                            view_kind=app.state.view_kind,
                            graph_rows=len(current.rows) if current else 0,
                            table_rows=app.relationships_table.row_count,
                        )
                        return (
                            app.state.view_kind == "relationships"
                            and current is not None
                            and not app.workspace.relationship_collecting
                            and app.relationships_table.request == current.request
                            and any(
                                row.ref.uid == replica.uid
                                and relationship_path_key(row.path) in app.relationships_table.rows
                                for row in current.rows
                            )
                        )

                    await until(graph_ready, timeout=30)
                    current = app.workspace.store.observation.relationships
                    assert current is not None
                    checkpoint(
                        evidence_dir,
                        "native-xray-rendered",
                        graph=graph_receipt(current),
                        table_rows=app.relationships_table.row_count,
                    )
                    rs_ui = next(
                        row
                        for row in current.rows
                        if row.ref.uid == replica.uid
                        and row.relation is RelationKind.CONTROLLER_OWNER
                    )
                    app.relationships_table.move_cursor(
                        row=app.relationships_table.get_row_index(relationship_path_key(rs_ui.path))
                    )
                    await pilot.press("enter")

                    async def expanded_ready() -> bool:
                        current = app.workspace.store.observation.relationships
                        checkpoint(
                            evidence_dir,
                            "waiting-for-native-expanded-branch",
                            view_kind=app.state.view_kind,
                            graph_rows=len(current.rows) if current else 0,
                            table_rows=app.relationships_table.row_count,
                        )
                        return (
                            app.state.view_kind == "relationships"
                            and current is not None
                            and not app.workspace.relationship_collecting
                            and app.relationships_table.request == current.request
                            and any(
                                row.ref.uid == pod.uid
                                and row.path[:-1] == rs_ui.path
                                and relationship_path_key(row.path) in app.relationships_table.rows
                                for row in current.rows
                            )
                        )

                    await until(expanded_ready, timeout=30)
                    await pilot.pause()
                    graph_viewport = app.relationships_table.capture_viewport()
                    saved_request = app.workspace.relationship_request
                    checkpoint(
                        evidence_dir,
                        "native-expanded-graph-before-open",
                        selected_path=app.relationships_table.selected_path(),
                        table_rows=app.relationships_table.row_count,
                    )
                    (evidence_dir / "relationships-native-xray.svg").write_text(
                        app.export_screenshot()
                    )
                    await app.run_command("open")

                    async def replica_opened() -> bool:
                        return (
                            app.state.view_kind == "replicasets"
                            and replica.uid in app.standard_table.rows
                        )

                    await until(replica_opened, timeout=30)
                    await pilot.press("escape")
                    await until(expanded_ready, timeout=30)
                    await pilot.pause()
                    restored = app.workspace.relationship_request
                    checkpoint(
                        evidence_dir,
                        "native-graph-history-restored",
                        selected_path=app.relationships_table.selected_path(),
                        table_rows=app.relationships_table.row_count,
                        expanded=sorted(restored.expanded) if restored else None,
                    )
                    assert (
                        app.state.view_kind == "relationships"
                        and restored is not None
                        and saved_request is not None
                    )
                    assert restored.expanded == saved_request.expanded
                    assert app.relationships_table.capture_viewport() == graph_viewport
                    await app.run_command("back")
                    await until(deployments_ready, timeout=30)
                    await pilot.pause()
                    assert app.standard_table.capture_viewport() == original_viewport
                    await app.run_command("configmaps")

                    async def configmaps_ready() -> bool:
                        uid = identities["configmaps"]["uid"]
                        return (
                            app.state.view_kind == "configmaps" and uid in app.standard_table.rows
                        )

                    await until(configmaps_ready, timeout=30)
                    config_uid = identities["configmaps"]["uid"]
                    assert config_uid is not None
                    app.standard_table.move_cursor(row=app.standard_table.get_row_index(config_uid))
                    await app.run_command("usedby")

                    async def usedby_ready() -> bool:
                        current = app.workspace.store.observation.relationships
                        checkpoint(
                            evidence_dir,
                            "waiting-for-native-usedby",
                            view_kind=app.state.view_kind,
                            graph_rows=len(current.rows) if current else 0,
                            table_rows=app.relationships_table.row_count,
                        )
                        return (
                            app.state.view_kind == "relationships"
                            and current is not None
                            and current.request.scope.mode is RelationshipMode.USED_BY
                            and not app.workspace.relationship_collecting
                            and app.relationships_table.request == current.request
                            and any(
                                row.ref.name == "owned-zero-deployment"
                                and relationship_path_key(row.path) in app.relationships_table.rows
                                for row in current.rows
                            )
                        )

                    await until(usedby_ready, timeout=30)
                    current = app.workspace.store.observation.relationships
                    assert current is not None
                    checkpoint(
                        evidence_dir,
                        "native-usedby-rendered",
                        graph=graph_receipt(current),
                        table_rows=app.relationships_table.row_count,
                    )
                    (evidence_dir / "relationships-native-usedby.svg").write_text(
                        app.export_screenshot()
                    )
                checkpoint(
                    evidence_dir,
                    "native-app-owners-drained",
                    ownership=asdict(app.workspace.ownership),
                )
                assert (
                    app.workspace.ownership.relationships_count
                    == app.workspace.ownership.watch_count
                    == 0
                )
                checks.append("actual-native-xray-expand-open-history-viewport-and-usedby-commands")

                expected_paths = {
                    custom.path(NAMESPACE) + "/owned-owner",
                    discovery.find("deployments", group="apps").path(NAMESPACE) + "/" + DEPLOYMENT,
                    discovery.find("replicasets", group="apps").path(NAMESPACE),
                    discovery.find("pods").path(NAMESPACE),
                    discovery.find("nodes").path() + "/" + node.name,
                    discovery.find("endpointslices", group="discovery.k8s.io").path(NAMESPACE),
                }
                checkpoint(
                    evidence_dir,
                    "actual-api-paths-observed",
                    expected_paths=sorted(expected_paths),
                    reads=paths,
                )
                assert expected_paths <= {receipt["path"] for receipt in paths}
                assert any(
                    receipt["params"]
                    and receipt["params"].get("labelSelector")
                    == "kubernetes.io/service-name=" + SERVICE
                    for receipt in paths
                )
                checks.append("actual-discovered-resource-paths-and-service-slice-label-query")
                assert cluster.path.read_bytes() == before
                checks.append("private-owned-kubeconfig-unchanged")
                checkpoint(evidence_dir, "verified-awaiting-owned-cleanup", checks=checks)
                return {
                    "package_versions": {
                        name: version(name)
                        for name in ("kuberich", "textual", "kubernetes-asyncio")
                    },
                    "python_version": sys.version.split()[0],
                    "node_image": NODE_IMAGE,
                    "shell_image": SHELL_IMAGE,
                    "checks": checks,
                    "identities": identities,
                    "read_calls_observed": len(paths),
                    "usedby": usedby,
                    "deadline_seconds": VERIFY_SECONDS,
                }
    finally:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "relationships-api-reads.json").write_text(
            json.dumps(paths, indent=2) + "\n"
        )

        async def close() -> None:
            try:
                if delegated is not None:
                    await delegated.close()
            finally:
                await sessions.close()

        cleanup = asyncio.create_task(close(), name="owned-relationships-close")
        await finish_owned(asyncio.gather(cleanup, return_exceptions=True))
        cleanup.result()


def input_hashes(root: Path) -> dict[str, str]:
    paths = [
        *sorted(
            path
            for path in (root / "src/kuberich").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        ),
        root / "uv.lock",
        root / "pyproject.toml",
        root / "scripts/owned_kind.py",
        root / "scripts/verify_relationships_kind.py",
    ]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.exists() or (args.evidence.parent / "relationships-stages.jsonl").exists():
        raise ValueError("Use a fresh evidence path; earlier outcomes must be preserved.")
    root = Path(__file__).resolve().parent.parent
    captured = input_hashes(root)
    result: dict[str, Any] = {
        "status": "failed",
        "input_hashes": captured,
        "owned_cluster_deleted": False,
        "deadline_seconds": VERIFY_SECONDS,
    }
    started = time.monotonic()
    problem: BaseException | None = None
    try:
        checkpoint(args.evidence.parent, "creating-owned-disposable-cluster")
        with owned_cluster(args.kind, docker=args.docker) as cluster:
            result["cluster"] = cluster.name
            try:
                result.update(asyncio.run(verify(cluster, args.evidence.parent)))
            except BaseException as error:
                problem = error
                result["failure_type"] = type(error).__name__
        result["owned_cluster_deleted"] = True
        result["private_directory_deleted"] = not cluster.directory.exists()
        result["inputs_unchanged"] = input_hashes(root) == captured
        if problem is not None:
            raise problem
        if not result["inputs_unchanged"] or not result["private_directory_deleted"]:
            raise AssertionError("Qualification source or private cleanup changed.")
        result["status"] = "passed"
        checkpoint(args.evidence.parent, "passed-owned-cluster-absence-verified")
    except BaseException as error:
        result.setdefault("failure_type", type(error).__name__)
        raise
    finally:
        result["duration_seconds"] = time.monotonic() - started
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind relationship and native navigation checks passed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            f"Owned relationships verification failed ({type(error).__name__}); inspect retained stage/UID/read receipts.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
