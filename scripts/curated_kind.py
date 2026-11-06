"""Controlled declarations and actual API/App contracts for the nineteen #232 families.

The VPA schema is an owned test CRD with no controller. Endpoint conditions and
Events are authored fixtures accepted/read by the real apiserver, not observations
of network health, autoscaler operation, or Event-controller durability.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem, namespace_name
from kuberich.domain.curated import curated_cells, curated_details, curated_families
from kuberich.domain.curated_navigation import (
    AuthorizationDestination,
    ReferenceDestination,
)
from kuberich.domain.events import EventGroupMembers, EventOptions, event_fact, group_events
from kuberich.domain.registry import RESOURCE_ALIASES, ResourceDefinition
from kuberich.domain.resources import ApiResource, Discovery, ResourceRecord
from kuberich.domain.tables import TABLE_ACCEPT
from kuberich.domain.views import ViewStatus
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned
from kuberich.services.resources import ResourceReader
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from scripts.owned_kind import SHELL_IMAGE, OwnedCluster

VPA_GROUP = "autoscaling.k8s.io"
VPA_PLURAL = "verticalpodautoscalers"
CANARY = "SYNTHETIC_CURATED_KIND_PRIVATE_PAYLOAD"
LINK_PATH = "/synthetic-curated-kind-private-path"
VERIFY_SECONDS = 300
READ_SECONDS = 15
RAW_REPRESENTATION_BYTES = 1024 * 1024

# Exact apiserver sources, rather than moving documentation, define this fixture.
SOURCE_PINS = {
    "schema": "https://github.com/kubernetes/kubernetes/tree/v1.36.4/staging/src/k8s.io/api",
    "webhooks": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/apis/admissionregistration/validation/validation.go",
    "networking": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/apis/networking/validation/validation.go",
    "crd": "https://v1-36.docs.kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/",
    "protected_crd_group": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/apiextensions-apiserver/pkg/apihelpers/helpers.go#L52-L65",
    "events": "https://v1-36.docs.kubernetes.io/docs/reference/kubernetes-api/events/event-v1/",
    "label_values": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/apimachinery/pkg/util/validation/validation.go#L134-L143",
    "events_validation": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/apis/core/validation/events.go",
    "endpoint_slice_lists": "https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/api/discovery/v1/types.go#L49-L63",
}


@dataclass(frozen=True)
class FamilyCase:
    resource: str
    field: str
    first: str
    second: str
    ascending: tuple[int, int] = (0, 1)


CASES = (
    FamilyCase("horizontalpodautoscalers", "max", "5", "15"),
    FamilyCase("verticalpodautoscalers", "mode", "Off", "Initial", (1, 0)),
    FamilyCase("poddisruptionbudgets", "min-available", "1", "50%"),
    FamilyCase("networkpolicies", "ingress-rules", "1", "0", (1, 0)),
    FamilyCase("endpointslices", "endpoints", "3", "0", (1, 0)),
    FamilyCase("ingressclasses", "default", "true", "false", (1, 0)),
    FamilyCase("priorityclasses", "priority", "-10", "20"),
    FamilyCase("runtimeclasses", "overhead-memory", "64Mi", "1Gi"),
    FamilyCase("leases", "duration-seconds", "15", "30"),
    FamilyCase("resourcequotas", "resources", "2", "3"),
    FamilyCase("limitranges", "items", "2", "1", (1, 0)),
    FamilyCase("mutatingwebhookconfigurations", "timeout-max", "7", "20"),
    FamilyCase("validatingwebhookconfigurations", "timeout-max", "7", "20"),
    FamilyCase("serviceaccounts", "secrets", "1", "2"),
    FamilyCase("roles", "rules", "1", "2"),
    FamilyCase("clusterroles", "rules", "1", "2"),
    FamilyCase("rolebindings", "users", "0", "2"),
    FamilyCase("clusterrolebindings", "users", "0", "2"),
)


def vpa_crd() -> dict[str, Any]:
    """A minimal structural schema, deliberately not a VPA controller installation."""
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {
            "name": VPA_PLURAL + "." + VPA_GROUP,
            # Explicitly experimental; no official approval or VPA-controller claim.
            "annotations": {"api-approved.kubernetes.io": "unapproved, experimental-only"},
        },
        "spec": {
            "group": VPA_GROUP,
            "scope": "Namespaced",
            "names": {
                "plural": VPA_PLURAL,
                "singular": "verticalpodautoscaler",
                "kind": "VerticalPodAutoscaler",
                "shortNames": ["vpa"],
            },
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
                                    "x-kubernetes-preserve-unknown-fields": True,
                                },
                                "status": {
                                    "type": "object",
                                    "x-kubernetes-preserve-unknown-fields": True,
                                },
                            },
                        }
                    },
                    "subresources": {"status": {}},
                }
            ],
        },
    }


def fixture_manifests(namespace: str, other_namespace: str) -> tuple[dict[str, Any], ...]:
    """Real Kubernetes declarations, with no fabricated UID/status or external image tags."""
    namespace_name(namespace)
    namespace_name(other_namespace)
    if namespace == other_namespace:
        raise ValueError("Owned namespace controls must be distinct.")
    result: list[dict[str, Any]] = []

    def add(version: str, kind: str, name: str, *, scoped: bool = True, **fields: Any) -> None:
        result.append(
            {
                "apiVersion": version,
                "kind": kind,
                "metadata": {
                    "name": name,
                    **({"namespace": namespace} if scoped else {}),
                    "labels": {"curated.kind/owned": namespace},
                    "annotations": {"curated.kind/private": CANARY},
                },
                **copy.deepcopy(fields),
            }
        )

    for name in (namespace, other_namespace):
        add("v1", "Namespace", name, scoped=False)
    # Dependencies precede consumers. Pods cannot be scheduled, so fixtures never
    # depend on a pull, running workload, runtime handler, or external controller.
    for ordinal, suffix in enumerate(("a", "b")):
        name, global_name = "owned-" + suffix, namespace + "-" + suffix
        add(
            "node.k8s.io/v1",
            "RuntimeClass",
            global_name,
            scoped=False,
            handler="runc",
            overhead={"podFixed": {"cpu": "10m", "memory": "64Mi" if ordinal == 0 else "1Gi"}},
        )
        add(
            "scheduling.k8s.io/v1",
            "PriorityClass",
            global_name,
            scoped=False,
            value=-10 if ordinal == 0 else 20,
            globalDefault=False,
            preemptionPolicy="Never",
        )
        add(
            "v1",
            "Secret",
            name,
            type="Opaque",
            data={"private": base64.b64encode(CANARY.encode()).decode()},
        )
        add(
            "v1",
            "ServiceAccount",
            name,
            automountServiceAccountToken=False,
            secrets=[{"name": "owned-a"}] + ([{"name": "owned-b"}] if ordinal else []),
            imagePullSecrets=[],
        )
        add(
            "v1",
            "Pod",
            name,
            spec={
                "serviceAccountName": name,
                "automountServiceAccountToken": False,
                "runtimeClassName": global_name,
                "priorityClassName": global_name,
                "nodeSelector": {"curated.kind/absent-node": "true"},
                "terminationGracePeriodSeconds": 0,
                "containers": [{"name": "app", "image": SHELL_IMAGE, "command": ["sleep", "3600"]}],
            },
        )
        result[-1]["metadata"]["labels"]["curated.kind/selected"] = suffix
        add(
            "apps/v1",
            "Deployment",
            "workload-" + suffix,
            spec={
                "replicas": 0,
                "selector": {"matchLabels": {"curated.kind/workload": suffix}},
                "template": {
                    "metadata": {"labels": {"curated.kind/workload": suffix}},
                    "spec": {"containers": [{"name": "app", "image": SHELL_IMAGE}]},
                },
            },
        )
        target = {"apiVersion": "apps/v1", "kind": "Deployment", "name": "workload-" + suffix}
        add(
            "autoscaling/v2",
            "HorizontalPodAutoscaler",
            name,
            spec={
                "scaleTargetRef": target,
                "minReplicas": 1,
                "maxReplicas": 5 if ordinal == 0 else 15,
                "metrics": [
                    {
                        "type": "Resource",
                        "resource": {
                            "name": "cpu",
                            "target": {
                                "type": "Utilization",
                                "averageUtilization": 70 if ordinal == 0 else 90,
                            },
                        },
                    }
                ],
            },
        )
        add(
            VPA_GROUP + "/v1",
            "VerticalPodAutoscaler",
            name,
            spec={
                "targetRef": target,
                "updatePolicy": {"updateMode": "Off" if ordinal == 0 else "Initial"},
            },
        )
        selector = {"matchLabels": {"curated.kind/selected": "a"}} if ordinal == 0 else {}
        add(
            "policy/v1",
            "PodDisruptionBudget",
            name,
            spec={"minAvailable": 1 if ordinal == 0 else "50%", "selector": selector},
        )
        add(
            "networking.k8s.io/v1",
            "NetworkPolicy",
            name,
            spec={
                **({"podSelector": selector} if ordinal == 0 else {}),
                "policyTypes": ["Ingress"],
                "ingress": [{"ports": [{"port": 8080, "protocol": "TCP"}]}] if ordinal == 0 else [],
            },
        )
        add(
            "networking.k8s.io/v1",
            "IngressClass",
            global_name,
            scoped=False,
            spec={
                "controller": "curated.kind/fixture",
                "parameters": {
                    "kind": "ConfigMap",
                    "name": "owned-parameters",
                    "scope": "Namespace",
                    "namespace": namespace,
                },
            },
        )
        result[-1]["metadata"]["annotations"]["ingressclass.kubernetes.io/is-default-class"] = (
            "true" if ordinal == 0 else "false"
        )
        add(
            "coordination.k8s.io/v1",
            "Lease",
            name,
            spec={
                "holderIdentity": "owned-holder",
                "leaseDurationSeconds": 15 if ordinal == 0 else 30,
                "leaseTransitions": ordinal,
            },
        )
        hard = {"pods": "100", "configmaps": "100"}
        if ordinal:
            hard["services"] = "100"
        add("v1", "ResourceQuota", name, spec={"hard": hard})
        limits = [
            {
                "type": "Container",
                "max": {"cpu": "2"},
                "default": {"cpu": "100m"},
                "defaultRequest": {"cpu": "10m"},
            }
        ]
        if ordinal == 0:
            limits.append({"type": "PersistentVolumeClaim", "max": {"storage": "2Gi"}})
        add("v1", "LimitRange", name, spec={"limits": limits})
        rules = [{"verbs": ["get", "list", "watch"], "apiGroups": [""], "resources": ["pods"]}]
        if ordinal:
            rules.append({"verbs": ["get"], "apiGroups": [""], "resources": ["configmaps"]})
        for kind, role_name, scoped in (("Role", name, True), ("ClusterRole", global_name, False)):
            add("rbac.authorization.k8s.io/v1", kind, role_name, scoped=scoped, rules=rules)
        subjects = [{"kind": "ServiceAccount", "name": name, "namespace": namespace}]
        if ordinal:
            subjects += [
                {
                    "kind": "User",
                    "apiGroup": "rbac.authorization.k8s.io",
                    "name": "owned-user-" + str(index),
                }
                for index in range(2)
            ]
        for kind, binding_name, role_name, scoped in (
            ("RoleBinding", name, name, True),
            ("ClusterRoleBinding", global_name, global_name, False),
        ):
            add(
                "rbac.authorization.k8s.io/v1",
                kind,
                binding_name,
                scoped=scoped,
                roleRef={
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "Role" if scoped else "ClusterRole",
                    "name": role_name,
                },
                subjects=subjects,
            )
        for kind in ("MutatingWebhookConfiguration", "ValidatingWebhookConfiguration"):
            webhooks = []
            for index in range(1 if ordinal == 0 else 2):
                webhooks.append(
                    {
                        "name": f"owned-{index}.curated.kind",
                        "admissionReviewVersions": ["v1"],
                        "failurePolicy": "Ignore",
                        "sideEffects": "None",
                        "timeoutSeconds": 7 if ordinal == 0 else 20,
                        "clientConfig": {
                            "service": {
                                "namespace": namespace,
                                "name": "owned-service",
                                "path": LINK_PATH,
                            }
                        }
                        if index == 0
                        else {"url": "https://127.0.0.1:9443" + LINK_PATH},
                        "namespaceSelector": {"matchLabels": {"curated.kind/never-admit": "true"}},
                        "rules": [
                            {
                                "operations": ["CREATE"],
                                "apiGroups": ["unserved.curated.kind"],
                                "apiVersions": ["v1"],
                                "resources": ["widgets"],
                                "scope": "Namespaced",
                            }
                        ],
                    }
                )
            add(
                "admissionregistration.k8s.io/v1",
                kind,
                global_name,
                scoped=False,
                webhooks=webhooks,
            )
    add("v1", "ConfigMap", "owned-parameters", data={"private": CANARY})
    add(
        "v1",
        "Service",
        "owned-service",
        spec={"ports": [{"port": 8080}], "selector": {"curated.kind/selected": "a"}},
    )
    add(
        "networking.k8s.io/v1",
        "Ingress",
        "owned-ingress",
        spec={
            "ingressClassName": namespace + "-a",
            "defaultBackend": {"service": {"name": "owned-service", "port": {"number": 8080}}},
        },
    )
    return tuple(result)


def endpoint_manifests(namespace: str, pod_uid: str) -> tuple[dict[str, Any], ...]:
    """Manual slice addresses are documentation ranges; only targetRef proves identity."""
    return tuple(
        {
            "apiVersion": "discovery.k8s.io/v1",
            "kind": "EndpointSlice",
            "metadata": {
                "name": "owned-" + suffix,
                "namespace": namespace,
                "labels": {
                    "kubernetes.io/service-name": "owned-service",
                    "endpointslice.kubernetes.io/managed-by": "curated.kind.fixture",
                    "curated.kind/owned": namespace,
                },
            },
            "addressType": "IPv4",
            "endpoints": [
                {
                    "addresses": ["192.0.2.1"],
                    "conditions": {"ready": True, "serving": True, "terminating": False},
                    "targetRef": {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "namespace": namespace,
                        "name": "owned-a",
                        "uid": pod_uid,
                    },
                },
                {
                    "addresses": ["192.0.2.2"],
                    "conditions": {"ready": False, "serving": False, "terminating": True},
                },
                {"addresses": ["192.0.2.3"]},
            ]
            if suffix == "a"
            else [],
            "ports": [{"name": "http", "port": 8080, "protocol": "TCP"}],
        }
        for suffix in ("a", "b")
    )


def event_manifests(namespace: str, pod_uid: str, at: datetime) -> tuple[dict[str, Any], ...]:
    """Two Warning members and one Normal event with actual regarding UID."""
    stamp = at.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return tuple(
        {
            "apiVersion": "events.k8s.io/v1",
            "kind": "Event",
            "metadata": {"name": "owned-event-" + suffix, "namespace": namespace},
            "regarding": {
                "apiVersion": "v1",
                "kind": "Pod",
                "namespace": namespace,
                "name": "owned-a",
                "uid": pod_uid,
            },
            "eventTime": stamp,
            "reportingController": "curated.kind/fixture",
            "reportingInstance": "owned-verifier",
            "action": "Observe",
            "reason": "OwnedWarning" if suffix != "normal" else "OwnedNormal",
            "type": "Warning" if suffix != "normal" else "Normal",
            "note": CANARY,
            **(
                {"series": {"count": 2 if suffix == "a" else 3, "lastObservedTime": stamp}}
                if suffix != "normal"
                else {}
            ),
        }
        for suffix in ("a", "b", "normal")
    )


async def until(predicate: Callable[[], bool], *, timeout: float = 30) -> None:
    """Wait on observable state under one finite deadline, never a settling sleep."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def observed[T](predicate: Callable[[], Awaitable[T | None]], *, timeout: float = 30) -> T:
    async with asyncio.timeout(timeout):
        while (value := await predicate()) is None:
            await asyncio.sleep(0.05)
        return value


async def wait_for_crd_established(client: KubernetesSession) -> None:
    async def established() -> bool | None:
        document = await client.get_json(
            "/apis/apiextensions.k8s.io/v1/customresourcedefinitions/"
            + VPA_PLURAL
            + "."
            + VPA_GROUP
        )
        status = document.get("status")
        if status is None:
            return None
        if not isinstance(status, dict):
            raise AssertionError("Owned CRD establishment status is malformed.")
        conditions = status.get("conditions")
        if conditions is None:
            return None
        if not isinstance(conditions, list) or any(
            not isinstance(item, dict) for item in conditions
        ):
            raise AssertionError("Owned CRD establishment conditions are malformed.")
        return (
            True
            if any(
                item.get("type") == "Established" and item.get("status") == "True"
                for item in conditions
            )
            else None
        )

    await observed(established, timeout=45)


async def write(
    client: KubernetesSession, path: str, method: str, body: dict[str, Any]
) -> dict[str, Any]:
    sdk = client.api
    if sdk is None:
        raise AppError("Owned session is not open.")
    value = await sdk.call_api(
        path,
        method,
        body=body,
        response_types_map={200: "object", 201: "object", 202: "object"},
        auth_settings=["BearerToken"],
        header_params={
            "Content-Type": "application/merge-patch+json"
            if method == "PATCH"
            else "application/json"
        },
        _return_http_data_only=True,
        _request_timeout=READ_SECONDS,
    )
    if not isinstance(value, dict):
        raise AssertionError("Owned write returned no Kubernetes object.")
    return cast(dict[str, Any], value)


def evidence_json(value: object) -> str:
    """Encode the declared evidence types without an arbitrary repr fallback."""

    def encode(item: object) -> object:
        if isinstance(item, frozenset) and all(isinstance(member, str) for member in item):
            return sorted(item)
        if isinstance(item, Decimal) and item.is_finite():
            return str(item)
        if isinstance(item, datetime) and item.utcoffset() is not None:
            return item.astimezone(UTC).isoformat()
        if isinstance(item, UUID):
            return str(item)
        raise TypeError("Unsupported evidence type: " + type(item).__name__)

    return json.dumps(value, default=encode, sort_keys=True, allow_nan=False, indent=2) + "\n"


def persist(directory: Path, name: str, value: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(evidence_json(value))


async def check_native_projection(
    reader: ResourceReader,
    case: FamilyCase,
    resource: ApiResource,
    selected: tuple[ResourceRecord, ...],
    directory: Path,
) -> dict[str, object]:
    """Retain actual observations before asserting; raw reads are fixture-only."""
    identities = [
        {
            "name": record.name,
            "uid": record.uid,
            "namespace": record.namespace,
            "resource_version": record.resource_version,
            "metadata_only": record.metadata_only,
        }
        for record in selected
    ]
    persist(
        directory,
        "native-current-family.json",
        {
            "stage": "capturing-projection",
            "resource": asdict(resource),
            "records": identities,
            "field": case.field,
            "expected": [case.first, case.second],
        },
    )
    if resource.name == "endpointslices" and resource.group == "discovery.k8s.io":
        if len(selected) != 2:
            raise AssertionError("Raw diagnostics require exactly the two controlled slices.")
        raw: list[dict[str, object]] = []
        for record in selected:
            path = object_path(resource, record)
            entry: dict[str, object] = {
                "path": path,
                "selected_uid": record.uid,
                "selected_resource_version": record.resource_version,
            }
            for representation in ("get", "table"):
                document = await reader.session.get_json(
                    path,
                    params={"includeObject": "Object"} if representation == "table" else None,
                    accept=TABLE_ACCEPT if representation == "table" else "application/json",
                    max_bytes=RAW_REPRESENTATION_BYTES,
                )
                entry[representation] = {
                    "observed_at": datetime.now(UTC).isoformat(),
                    "body": document,
                }
                persist(directory, "endpoint-raw-representations.json", [*raw, entry])
            raw.append(entry)
    projected = tuple(curated_cells(resource, record) for record in selected)
    values = tuple(dict(item.values)[case.field].text for item in projected)
    observation: dict[str, object] = {
        "stage": "observed-before-assert",
        "resource": asdict(resource),
        "source_path": resource.path(selected[0].namespace) if selected else None,
        "observed_at": datetime.now(UTC).isoformat(),
        "actual_table_full_objects": all(
            record.server is not None and not record.metadata_only for record in selected
        ),
        "uids": [record.uid for record in selected],
        "records": identities,
        "field": case.field,
        "expected": [case.first, case.second],
        "values": values,
        "source_notices": [item.notices for item in projected],
        "cells": [
            {key: {"text": value.text, "sort": value.sort} for key, value in item.values}
            for item in projected
        ],
    }
    persist(directory, "native-current-family.json", observation)
    persist(directory, "native-" + case.resource + "-observation.json", observation)
    assert len({required_uid(record) for record in selected}) == 2
    assert all(record.server is not None and not record.metadata_only for record in selected)
    assert values == (case.first, case.second)
    return observation


def require_owned(cluster: OwnedCluster, reader: ResourceReader, catalog: KubeCatalog) -> None:
    """The CLI's owned_cluster is the sole producer; no existing-config CLI exists."""
    if (
        not cluster.name.startswith("kuberich-test-")
        or cluster.context != "kind-" + cluster.name
        or len(cluster.node_ids) != 1
        or not cluster.node_ids[0]
        or not cluster.directory.is_absolute()
        or not cluster.path.is_absolute()
        or cluster.path.parent != cluster.directory
        or cluster.path.stat().st_mode & 0o777 != 0o600
        or catalog.names != (cluster.context,)
        or reader.session.context.name != cluster.context
        or reader.session.api is None
    ):
        raise ValueError("Refusing a session outside the verified owned cluster.")


def object_path(resource: ApiResource, record: ResourceRecord) -> str:
    return resource.path(record.namespace) + "/" + record.name


async def create_document(
    reader: ResourceReader, discovery: Discovery, document: dict[str, Any]
) -> dict[str, Any]:
    group_version = document["apiVersion"].split("/")
    group, version = ("", group_version[0]) if len(group_version) == 1 else group_version
    matches = [
        resource
        for resource in discovery.resources
        if resource.group == group
        and resource.version == version
        and resource.kind == document["kind"]
    ]
    if len(matches) != 1:
        raise AssertionError("Fixture type is not uniquely advertised by real discovery.")
    resource = matches[0]
    namespace = document["metadata"].get("namespace")
    if resource.namespaced != (namespace is not None):
        raise AssertionError("Fixture namespace contradicts actual discovered scope.")
    return await write(reader.session, resource.path(namespace), "POST", document)


async def open_details(app: KubeRichApp) -> InspectionScreen:
    app.action_inspect_details()
    await until(lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None)
    screen = app.screen
    assert isinstance(screen, InspectionScreen) and screen.result is not None
    assert screen.result.curated is not None and screen.result.curated.sections
    assert CANARY not in screen.viewer.text and LINK_PATH not in screen.viewer.text
    return screen


async def choose_link(screen: InspectionScreen, pilot: Any, key: str) -> None:
    assert screen.result is not None and screen.result.curated is not None
    index = next(index for index, link in enumerate(screen.result.curated.links) if link.key == key)
    link = screen.result.curated.links[index]
    assert link.destination is not None and link.unavailable_reason is None
    screen.action_page("links")
    screen.links.highlighted = index
    await pilot.press("enter")


def events_ready(app: KubeRichApp, resource: ApiResource, options: EventOptions) -> bool:
    source, observation = app.events_table.source, app.workspace.store.observation
    return bool(
        app.events_table.display
        and source is not None
        and observation.scope is not None
        and observation.scope.resource == resource
        and observation.status is ViewStatus.LIVE
        and source.scope == observation.scope
        and source.revision == observation.revision
        and source.status is observation.status
        and app.events_table.options == options
    )


def inspection_closed(app: KubeRichApp, inspection: InspectionScreen) -> bool:
    return (
        inspection not in app.screen_stack
        and not inspection.is_attached
        and inspection.operation_count == 0
        and app.operations.retained_general_inspection_count == 0
    )


def inspection_lifecycle(app: KubeRichApp, inspection: InspectionScreen) -> dict[str, object]:
    def widget(value: Any) -> dict[str, object] | None:
        return (
            None
            if value is None
            else {"type": type(value).__name__, "id": value.id, "object_identity": id(value)}
        )

    return {
        "captured_target": asdict(inspection.service.target),
        "resource": asdict(inspection.service.resource),
        "inspection_identity": id(inspection),
        "is_mounted": inspection.is_mounted,
        "is_attached": inspection.is_attached,
        "in_actual_stack": any(screen is inspection for screen in app.screen_stack),
        "operation_count": inspection.operation_count,
        "navigator_operation_count": inspection.navigator.operation_count
        if inspection.navigator
        else 0,
        "retained_general_inspections": app.operations.retained_general_inspection_count,
        "retained_container_inspections": app.operations.retained_inspection_count,
        "invalidated": inspection.invalidated,
        "result_present": inspection.result is not None,
        "root_stack": [widget(screen) for screen in app.screen_stack],
        "app_focus": widget(app.focused),
        "inspection_focus": widget(inspection.focused),
    }


async def wait_for_inspection_closed(
    app: KubeRichApp, inspection: InspectionScreen, directory: Path, label: str
) -> None:
    persist(
        directory, label + "-inspection-after-escape.json", inspection_lifecycle(app, inspection)
    )
    try:
        await until(lambda: inspection_closed(app, inspection))
    except BaseException as error:
        try:
            persist(
                directory,
                label + "-inspection-close-failure.json",
                inspection_lifecycle(app, inspection),
            )
        except BaseException as archive_error:
            error.add_note("Inspection lifecycle archive failed: " + type(archive_error).__name__)
        raise
    persist(directory, label + "-inspection-closed.json", inspection_lifecycle(app, inspection))


async def open_standard(
    app: KubeRichApp,
    resource: ApiResource,
    namespace: str,
    selected: tuple[ResourceRecord, ...],
) -> None:
    definition = RESOURCE_ALIASES[resource.name]
    await app.run_command(definition.aliases[0] + (" " + namespace if resource.namespaced else ""))
    await until(
        lambda: (
            app.state.scope is not None
            and app.state.scope.resource == resource
            and app.state.status is ViewStatus.LIVE
        )
    )
    app.filter_input.value = (
        ("re:(^| )owned-[ab]( |$)" if resource.namespaced else namespace)
        if definition.curated
        else ""
    )
    await until(
        lambda: (
            app.standard_table.display
            and set(rows(app.standard_table)) == {required_uid(record) for record in selected}
        )
    )


async def verify_links(
    app: KubeRichApp,
    pilot: Any,
    reader: ResourceReader,
    resources: dict[str, ApiResource],
    records: dict[str, tuple[ResourceRecord, ...]],
    namespace: str,
) -> dict[str, object]:
    """The actual inspector performs source revalidation and explicit destination I/O."""
    pods = resources["pods"]
    pod = records["pods"][0]
    await open_standard(app, resources["networkpolicies"], namespace, records["networkpolicies"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["networkpolicies"][0]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "selected-pods")
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.state.scope is not None
            and app.state.scope.resource == pods
            and app.resources.row_count == 1
        )
    )
    assert app.resources.selected_uid == pod.uid
    bookmark = app.navigator.capture()
    assert bookmark is not None and bookmark.curated is not None
    assert bookmark.curated.resource == pods and bookmark.curated.namespace == namespace
    # Re-enter through the actual command path; the omitted selector was admitted
    # as {} by Kubernetes and must deliberately include both namespace Pods.
    await open_standard(app, resources["networkpolicies"], namespace, records["networkpolicies"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["networkpolicies"][1]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "selected-pods")
    await until(
        lambda: (
            len(app.screen_stack) == 1 and app.resources.display and app.resources.row_count == 2
        )
    )
    assert {row.key.value for row in app.resources.ordered_rows} == {
        item.uid for item in records["pods"]
    }

    slices = resources["endpointslices"]
    await open_standard(app, slices, namespace, records["endpointslices"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["endpointslices"][0]))
    )
    screen = await open_details(app)
    assert screen.result is not None and screen.result.curated is not None
    target = next(link for link in screen.result.curated.links if link.key == "target-0")
    assert isinstance(target.destination, ReferenceDestination)
    assert target.destination.require_uid and target.destination.ref.uid == pod.uid
    await choose_link(screen, pilot, "target-0")
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.resources.display
            and rows(app.resources) == (required_uid(pod),)
        )
    )
    await open_standard(app, slices, namespace, records["endpointslices"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["endpointslices"][0]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "service")
    service = resources["services"]
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.state.scope is not None
            and app.state.scope.resource == service
            and app.standard_table.row_count == 1
        )
    )
    assert app.standard_table.selected_uid == records["services"][0].uid

    await open_standard(app, resources["runtimeclasses"], namespace, records["runtimeclasses"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["runtimeclasses"][0]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "pods")
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.resources.display
            and rows(app.resources) == (required_uid(pod),)
        )
    )
    await open_standard(app, resources["ingressclasses"], namespace, records["ingressclasses"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["ingressclasses"][0]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "ingresses")
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.state.scope is not None
            and app.state.scope.resource == resources["ingresses"]
            and rows(app.standard_table) == (required_uid(records["ingresses"][0]),)
        )
    )
    await open_standard(app, resources["ingressclasses"], namespace, records["ingressclasses"])
    app.standard_table.move_cursor(
        row=app.standard_table.get_row_index(required_uid(records["ingressclasses"][0]))
    )
    screen = await open_details(app)
    await choose_link(screen, pilot, "parameters")
    await until(
        lambda: (
            len(app.screen_stack) == 1
            and app.state.scope is not None
            and app.state.scope.resource == resources["configmaps"]
            and rows(app.standard_table) == (required_uid(records["configmaps"][0]),)
        )
    )

    # A role detail links into existing authorization intents; no policy evaluator
    # or guessed access decision is introduced by this verifier.
    role = await reader.get(resources["roles"], "owned-a", namespace)
    details = curated_details(resources["roles"], role)
    assert any(isinstance(link.destination, AuthorizationDestination) for link in details.links)
    return {
        "selected_pod_uid": pod.uid,
        "omitted_selector_admitted_as_all_namespace_pods": True,
        "endpoint_declared_service_uid": records["services"][0].uid,
        "endpoint_target_requires_actual_uid": True,
        "runtimeclass_selected_namespace_pod_uid": pod.uid,
        "ingressclass_selected_namespace_ingress_uid": records["ingresses"][0].uid,
        "group_kind_only_parameters_actual_uid": records["configmaps"][0].uid,
        "role_authorization_intent_present": True,
    }


async def verify_events(
    app: KubeRichApp,
    pilot: Any,
    reader: ResourceReader,
    resource: ApiResource,
    namespace: str,
    pod: ResourceRecord,
    original_pod: dict[str, Any],
    directory: Path,
) -> dict[str, object]:
    snapshot = await reader.list(resource, namespace)
    controlled = tuple(item for item in snapshot.items if item.name.startswith("owned-event-"))
    assert len(controlled) == 3
    facts = tuple(event_fact(resource, item) for item in controlled)
    assert all(fact.regarding is not None and fact.regarding.uid == pod.uid for fact in facts)
    groups = group_events(facts, EventOptions(grouped=True, warnings_only=True))
    assert len(groups) == 1
    group = groups[0]
    assert group.known_occurrences == 5 and len(group.member_uids) == 2
    assert group.unknown_count_members == 0 and group.unknown_time_members == 0
    legacy = (await reader.discover()).resolve("events", group="", version="v1")
    converted = tuple([await reader.get(legacy, item.name, namespace) for item in controlled])
    assert tuple(item.uid for item in converted) == tuple(item.uid for item in controlled)
    legacy_facts = tuple(event_fact(legacy, item) for item in converted)
    legacy_groups = group_events(legacy_facts, EventOptions(grouped=True, warnings_only=True))
    assert len(legacy_groups) == 1 and legacy_groups[0].known_occurrences == 5
    assert all(
        fact.regarding is not None and fact.regarding.uid == pod.uid for fact in legacy_facts
    )
    persist(
        directory,
        "native-event-observations.json",
        {
            "modern_facts": [asdict(fact) for fact in facts],
            "legacy_facts": [asdict(fact) for fact in legacy_facts],
            "warning_group": asdict(group),
        },
    )

    def stage(name: str) -> None:
        persist(
            directory,
            "event-current-stage.json",
            {
                "stage": name,
                "at": datetime.now(UTC).isoformat(),
                "resource": asdict(resource),
                "pod_uid": pod.uid,
            },
        )

    stage("opening-native-event-view")
    await app.run_command(f"resource events.events.k8s.io/v1 {namespace}")
    await until(lambda: events_ready(app, resource, EventOptions()))
    app.filter_input.value = ""
    app.navigator.events_options(EventOptions(grouped=True, warnings_only=True))
    await until(
        lambda: (
            events_ready(app, resource, EventOptions(grouped=True, warnings_only=True))
            and group.row_key in app.events_table.rows
        )
    )
    assert app.events_table.get_cell(group.row_key, "occurrences").text == "5"
    assert all(
        app.events_table.get_cell(row.key, "type").text == "Warning"
        for row in app.events_table.ordered_rows
    )
    stage("warning-group-accepted-opening-exact-members")
    app.events_table.move_cursor(row=app.events_table.get_row_index(group.row_key))
    await pilot.press("enter")
    await until(
        lambda: (
            events_ready(
                app,
                resource,
                EventOptions(warnings_only=True, members=EventGroupMembers(group.key)),
            )
            and app.events_table.options.members is not None
            and {row.key.value for row in app.events_table.ordered_rows} == set(group.member_uids)
        )
    )
    assert app.state.scope is not None and app.state.scope.resource == resource
    assert app.state.scope.namespace == namespace
    stage("exact-members-accepted-opening-event-details")
    selected = next(item for item in controlled if item.name == "owned-event-a")
    app.events_table.move_cursor(row=app.events_table.get_row_index(required_uid(selected)))
    await pilot.press("enter")
    await until(lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None)
    screen = cast(InspectionScreen, app.screen)
    await choose_link(screen, pilot, "regarding")
    await until(
        lambda: (
            len(app.screen_stack) == 1 and app.resources.display and app.resources.row_count == 1
        )
    )
    assert app.resources.selected_uid == pod.uid
    stage("actual-regarding-uid-followed-recreating-same-name-pod")
    # Delete/recreate the same name under a UID precondition; the old Event may
    # remain informative but must never silently retarget its regarding link.
    pods = app.state.scope.resource if app.state.scope is not None else None
    assert pods is not None and pods.name == "pods"
    await write(
        reader.session,
        object_path(pods, pod),
        "DELETE",
        {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "gracePeriodSeconds": 0,
            "preconditions": {"uid": pod.uid},
        },
    )

    async def deleted() -> bool | None:
        try:
            await reader.get(pods, pod.name, namespace)
        except HttpProblem as problem:
            if problem.status == 404:
                return True
            raise
        return None

    await observed(deleted)
    replacement = await create_document(reader, await reader.discover(), original_pod)
    replacement_uid = replacement["metadata"]["uid"]
    assert replacement_uid != pod.uid
    stage("pod-recreated-opening-old-event-reference")
    await app.run_command(f"resource events.events.k8s.io/v1 {namespace}")
    await until(
        lambda: (
            events_ready(app, resource, EventOptions()) and selected.uid in app.events_table.rows
        )
    )
    app.events_table.move_cursor(row=app.events_table.get_row_index(required_uid(selected)))
    await pilot.press("enter")
    await until(lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None)
    screen = cast(InspectionScreen, app.screen)
    await choose_link(screen, pilot, "regarding")
    await until(lambda: "replaced" in str(screen.status.content))
    assert app.screen is screen and screen.operation_count == 0
    stage("old-event-reference-rejected-new-pod-uid")
    await pilot.press("escape")
    await wait_for_inspection_closed(app, screen, directory, "events-regarding")
    assert app.check_action("edit", ()) is False and app.check_action("review_delete", ()) is False
    return {
        "resource": asdict(resource),
        "created_event_uids": [item.uid for item in controlled],
        "warning_member_uids": group.member_uids,
        "known_reported_occurrences": group.known_occurrences,
        "normal_event_excluded": True,
        "core_v1_same_actual_event_uids": [item.uid for item in converted],
        "actual_regarding_uid": pod.uid,
        "replacement_uid": replacement_uid,
        "replacement_link_rejected": True,
        "limits": "Authored Event API fixtures; no event-controller durability claim.",
    }


def required_uid(record: ResourceRecord) -> str:
    if not isinstance(record.uid, str) or not record.uid:
        raise AssertionError("The actual Kubernetes object has no UID.")
    return record.uid


def rows(table: Any) -> tuple[str, ...]:
    return tuple(row.key.value for row in table.ordered_rows)


async def verify_app(
    reader: ResourceReader,
    catalog: KubeCatalog,
    cluster: OwnedCluster,
    resources: dict[str, ApiResource],
    records: dict[str, tuple[ResourceRecord, ...]],
    namespace: str,
    other_namespace: str,
    directory: Path,
    original_pod: dict[str, Any],
) -> dict[str, object]:
    app = KubeRichApp(
        Settings(read_only=False),
        logging.Logger("owned-curated-kind", level=100),
        catalog=catalog,
        connection=ConnectionRequest(
            kubeconfig=str(cluster.path),
            context=cluster.context,
            namespace=namespace,
            timeout=READ_SECONDS,
        ),
    )
    evidence: list[dict[str, object]] = []
    async with app.run_test(size=(120, 36)) as pilot:
        await until(lambda: app.state.status is ViewStatus.LIVE)
        for case in CASES:
            resource, selected = resources[case.resource], records[case.resource]
            persist(
                directory,
                "ordinary-app-current-stage.json",
                {
                    "resource": asdict(resource),
                    "field": case.field,
                    "expected_uids": [required_uid(record) for record in selected],
                    "at": datetime.now(UTC).isoformat(),
                },
            )
            definition: ResourceDefinition = RESOURCE_ALIASES[case.resource]
            command = definition.aliases[0] + (" " + namespace if resource.namespaced else "")
            await app.run_command(command)

            def loaded(resource: ApiResource = resource) -> bool:
                return (
                    app.state.scope is not None
                    and app.state.scope.resource == resource
                    and app.state.status is ViewStatus.LIVE
                )

            await until(loaded)
            app.filter_input.value = "re:(^| )owned-[ab]( |$)" if resource.namespaced else namespace
            identities = tuple(required_uid(record) for record in selected)

            def visible(identities: tuple[str, ...] = identities) -> bool:
                return set(rows(app.standard_table)) == set(identities)

            await until(visible)
            await pilot.pause()
            table = app.standard_table
            assert table.row_count == 2 and definition.curated
            assert tuple(column.value for column in table.columns) == tuple(
                column.key for column in definition.columns
            )
            assert tuple(table.get_cell(identity, case.field).text for identity in identities) == (
                case.first,
                case.second,
            )
            table.restore_sort(case.field, False)
            await pilot.pause()
            ascending = tuple(identities[index] for index in case.ascending)
            assert rows(table) == ascending
            table.action_reverse_sort()
            await pilot.pause()
            assert rows(table) == tuple(reversed(ascending))
            table.move_cursor(row=table.get_row_index(identities[0]))
            await pilot.pause()
            marker = uuid4().hex
            await write(
                reader.session,
                object_path(resource, selected[0]),
                "PATCH",
                {"metadata": {"annotations": {"curated.kind/watched": marker}}},
            )

            def watched(identity: str = identities[0], marker: str = marker) -> bool:
                return app.workspace.store.observation.snapshot is not None and any(
                    item.uid == identity
                    and item.manifest["metadata"].get("annotations", {}).get("curated.kind/watched")
                    == marker
                    for item in app.workspace.store.observation.snapshot.items
                )

            await until(watched)
            assert table.selected_uid == identities[0] and table.row_count == 2
            assert (
                app.check_action("edit", ()) is False
                and app.check_action("review_delete", ()) is False
            )
            await pilot.press("E", "ctrl+d")
            await pilot.pause()
            assert len(app.screen_stack) == 1
            assert "Edit" not in str(app.header.shortcuts) and "Delete" not in str(
                app.header.shortcuts
            )
            text = "\n".join(
                str(cell) for index in range(table.row_count) for cell in table.get_row_at(index)
            )
            assert CANARY not in text and LINK_PATH not in text
            inspection = await open_details(app)
            assert inspection.result is not None and inspection.result.curated is not None
            inspected_version = inspection.result.resource_version
            assert inspected_version is not None
            await pilot.press("escape")

            await wait_for_inspection_closed(app, inspection, directory, case.resource)
            assert table.selected_uid == identities[0]
            evidence.append(
                {
                    "resource": asdict(resource),
                    "namespace": namespace if resource.namespaced else None,
                    "command": command,
                    "uids": identities,
                    "field": case.field,
                    "values": [case.first, case.second],
                    "ascending": ascending,
                    "descending": tuple(reversed(ascending)),
                    "actual_list_watch_get": True,
                    "fresh_inspection_resource_version": inspected_version,
                    "source_payload_hidden": True,
                    "family_read_only_with_settings_false": True,
                }
            )
            persist(directory, "ordinary-app-progress.json", evidence)

        # The same HPA object is read through both real served APIs, with the same
        # UID, not separate fixtures masquerading as version conversion.
        app.filter_input.value = ""
        hpa = resources["horizontalpodautoscalers"]
        v1 = (await reader.discover()).resolve(
            "horizontalpodautoscalers", group="autoscaling", version="v1"
        )
        await app.run_command(f"resource horizontalpodautoscalers.autoscaling/v1 {namespace}")
        await until(
            lambda: (
                app.state.scope is not None
                and app.state.scope.resource == v1
                and app.state.status is ViewStatus.LIVE
                and app.standard_table.row_count == 2
            )
        )
        hpa_uid = required_uid(records["horizontalpodautoscalers"][0])
        assert app.standard_table.get_cell(hpa_uid, "metrics").text == "70"
        await app.run_command(f"resource horizontalpodautoscalers.autoscaling/v2 {namespace}")
        await until(
            lambda: (
                app.state.scope is not None
                and app.state.scope.resource == hpa
                and app.state.status is ViewStatus.LIVE
                and app.standard_table.row_count == 2
            )
        )
        assert app.standard_table.get_cell(hpa_uid, "metrics").text == "1"

        await app.run_command("netpol " + namespace)
        await until(
            lambda: (
                app.standard_table.display
                and app.state.scope is not None
                and app.state.scope.resource == resources["networkpolicies"]
                and app.standard_table.row_count == 2
            )
        )
        await app.run_command("server compact")
        await until(
            lambda: (
                app.state.scope is not None
                and app.state.scope.query.compact
                and tuple(key.value for key in app.standard_table.columns)
                == ("namespace", "name", "info", "age")
                and app.standard_table.row_count == 2
            )
        )
        snapshot = app.workspace.store.observation.snapshot
        assert snapshot is not None and all(record.metadata_only for record in snapshot.items)
        await app.run_command("server full")
        await until(
            lambda: "selector" in app.standard_table.columns and app.standard_table.row_count == 2
        )

        await app.run_command("netpol " + other_namespace)
        await until(
            lambda: (
                app.state.scope is not None
                and app.state.scope.namespace == other_namespace
                and app.state.status is ViewStatus.LIVE
                and app.standard_table.row_count == 0
            )
        )
        assert app.workspace.store.observation.problem is None
        assert (
            app.workspace.store.observation.snapshot is not None
            and app.workspace.store.observation.snapshot.collection.complete
        )
        await app.run_command("netpol " + namespace)
        await until(
            lambda: (
                app.state.scope is not None
                and app.state.scope.namespace == namespace
                and app.state.status is ViewStatus.LIVE
                and app.standard_table.row_count == 2
            )
        )
        links = await verify_links(app, pilot, reader, resources, records, namespace)
        persist(directory, "curated-link-observations.json", links)
        events = await verify_events(
            app,
            pilot,
            reader,
            resources["events"],
            namespace,
            records["pods"][0],
            original_pod,
            directory,
        )
        persist(directory, "event-observations.json", events)
        image = app.save_screenshot(
            filename="curated-owned-kind.svg", path=str(directory.resolve())
        )
        assert Path(image).is_file()
    assert app.sessions.client is None
    assert app.views.renderer.active_count == 0
    assert (
        app.workspace.ownership.subscription_count == 0 and app.workspace.ownership.close_complete
    )
    return {
        "ordinary_families": evidence,
        "ordinary_count": len(evidence),
        "events": events,
        "events_count": 1,
        "hpa_same_uid_real_v1_v2": hpa_uid,
        "compact_real_metadata_fallback": True,
        "actual_other_namespace_empty": True,
        "links": links,
        "owned_app_closed": True,
    }


async def verify_curated_resources(
    reader: ResourceReader,
    catalog: KubeCatalog,
    cluster: OwnedCluster,
    *,
    evidence_dir: Path,
) -> dict[str, object]:
    require_owned(cluster, reader, catalog)
    namespace, other = (
        "kuberich-curated-" + uuid4().hex[:10],
        "kuberich-curated-empty-" + uuid4().hex[:10],
    )
    planned = fixture_manifests(namespace, other)
    records: dict[str, tuple[ResourceRecord, ...]] = {}
    resources: dict[str, ApiResource] = {}
    progress: list[dict[str, object]] = []

    def checkpoint(stage: str, **values: object) -> None:
        progress.append({"stage": stage, "at": datetime.now(UTC).isoformat(), **values})
        persist(evidence_dir, "api-progress.json", progress)

    async with asyncio.timeout(VERIFY_SECONDS):
        discovery = await reader.discover()
        assert not any(
            item.group == VPA_GROUP and item.name == VPA_PLURAL for item in discovery.resources
        )
        checkpoint("vpa-absent-before-owned-crd", native_vpa_available=False)
        crd = await create_document(reader, discovery, vpa_crd())

        await wait_for_crd_established(reader.session)
        discovery = await reader.discover()
        assert (
            discovery.resolve(VPA_PLURAL, group=VPA_GROUP, version="v1").kind
            == "VerticalPodAutoscaler"
        )
        checkpoint(
            "owned-vpa-crd-established", crd_uid=crd["metadata"]["uid"], controller_installed=False
        )
        for document in planned:
            checkpoint(
                "creating-native-object",
                api_version=document["apiVersion"],
                kind=document["kind"],
                name=document["metadata"]["name"],
                namespace=document["metadata"].get("namespace"),
            )
            await create_document(reader, discovery, document)
        pods = discovery.resolve("pods", group="", version="v1")
        pod = await reader.get(pods, "owned-a", namespace)
        pod_uid = required_uid(pod)
        for document in (
            *endpoint_manifests(namespace, pod_uid),
            *event_manifests(namespace, pod_uid, datetime.now(UTC)),
        ):
            await create_document(reader, discovery, document)
        checkpoint(
            "all-controlled-objects-created",
            namespace=namespace,
            other_namespace=other,
            pod_uid=pod_uid,
        )
        tables = ResourceReader(reader.session, tables=True)
        native: list[dict[str, object]] = []
        profiles = {family.resource: family for family in curated_families()}
        assert {case.resource for case in CASES} == set(profiles)
        for case in CASES:
            profile = profiles[case.resource]
            resource = discovery.resolve(
                profile.resource,
                group=profile.group,
                version="v2" if profile.resource == "horizontalpodautoscalers" else "v1",
            )
            resources[case.resource] = resource
            own_names = (
                ("owned-a", "owned-b")
                if resource.namespaced
                else (namespace + "-a", namespace + "-b")
            )
            persist(
                evidence_dir,
                "native-current-family.json",
                {
                    "stage": "reading-full-table",
                    "resource": asdict(resource),
                    "namespace": namespace if resource.namespaced else None,
                    "names": own_names,
                    "field": case.field,
                    "expected": [case.first, case.second],
                },
            )
            snapshot = await tables.list(resource, namespace if resource.namespaced else None)
            selected = tuple(
                next(record for record in snapshot.items if record.name == name)
                for name in own_names
            )
            observation = await check_native_projection(
                reader, case, resource, selected, evidence_dir
            )
            if case.resource == "resourcequotas":
                for name in own_names:

                    async def enforced(
                        name: str = name, resource: ApiResource = resource
                    ) -> ResourceRecord | None:
                        current = await reader.get(resource, name, namespace)
                        status = current.manifest.get("status", {})
                        return (
                            current
                            if status.get("hard") and isinstance(status.get("used"), dict)
                            else None
                        )

                    await observed(enforced)
            records[case.resource] = selected
            native.append(observation)
            persist(evidence_dir, "native-projection-observations.json", native)
        resources["pods"] = pods
        resources["services"] = discovery.resolve("services", group="", version="v1")
        resources["ingresses"] = discovery.resolve(
            "ingresses", group="networking.k8s.io", version="v1"
        )
        resources["configmaps"] = discovery.resolve("configmaps", group="", version="v1")
        resources["events"] = discovery.resolve("events", group="events.k8s.io", version="v1")
        records["pods"] = tuple(
            [await reader.get(pods, name, namespace) for name in ("owned-a", "owned-b")]
        )
        records["services"] = (await reader.get(resources["services"], "owned-service", namespace),)
        records["ingresses"] = (
            await reader.get(resources["ingresses"], "owned-ingress", namespace),
        )
        records["configmaps"] = (
            await reader.get(resources["configmaps"], "owned-parameters", namespace),
        )
        v1 = discovery.resolve("horizontalpodautoscalers", group="autoscaling", version="v1")
        assert (await reader.get(v1, "owned-a", namespace)).uid == records[
            "horizontalpodautoscalers"
        ][0].uid
        checkpoint(
            "all-eighteen-native-table-projections", count=len(native), hpa_v1_v2_same_uid=True
        )

        delegated = KubernetesSession(
            catalog.select(
                cluster.context,
                ConnectionOverrides(
                    as_user=f"system:serviceaccount:{namespace}:owned-a",
                    as_groups=("system:authenticated", f"system:serviceaccounts:{namespace}"),
                ),
            ),
            READ_SECONDS,
        )
        await delegated.open()
        try:
            restricted = ResourceReader(delegated)

            async def allowed() -> bool | None:
                try:
                    result = await restricted.list(pods, namespace)
                except HttpProblem as problem:
                    if problem.status == 403:
                        return None
                    raise
                return (
                    True
                    if {item.uid for item in result.items} == {item.uid for item in records["pods"]}
                    else None
                )

            await observed(allowed)
            try:
                await restricted.list(resources["networkpolicies"], namespace)
            except HttpProblem as problem:
                assert problem.status == 403
            else:
                raise AssertionError("Actual RBAC-denied policy list unexpectedly succeeded.")
        finally:
            await finish_owned(asyncio.create_task(delegated.close()))
        checkpoint("actual-rbac-pods-allowed-policy-list-forbidden", denial_status=403)
        original_pod = next(
            document
            for document in planned
            if document["kind"] == "Pod" and document["metadata"]["name"] == "owned-a"
        )
        result = await verify_app(
            reader,
            catalog,
            cluster,
            resources,
            records,
            namespace,
            other,
            evidence_dir,
            original_pod,
        )
        checkpoint("all-nineteen-real-app-contracts-complete", count=19)
        return {
            **result,
            "native_projections": native,
            "actual_policy_rbac_denial": 403,
            "minimal_owned_vpa_crd_only": True,
            "native_vpa_preinstallation_absent": True,
            "no_autoscaler_controller_or_network_health_claim": True,
        }
