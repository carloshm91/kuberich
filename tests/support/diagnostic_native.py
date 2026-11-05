"""Synthetic native diagnostics fixtures; never read ambient cluster configuration."""

from datetime import UTC, datetime

from kuberich.domain.cluster_diagnostics import (
    DiagnosticRequest,
    DiagnosticScope,
    DiagnosticSnapshot,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
)
from kuberich.domain.relationships import reference_for
from kuberich.domain.resources import ApiResource, CollectionState, resource_record
from kuberich.domain.targets import SessionIdentity
from tests.support.resources import collection, item

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
PODS = ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list", "watch"}))
EVENTS = ApiResource("", "v1", "events", "Event", True, PODS.verbs)
NEW_EVENTS = ApiResource("events.k8s.io", "v1", "events", "Event", True, PODS.verbs)
DEPLOYMENTS = ApiResource("apps", "v1", "deployments", "Deployment", True, PODS.verbs)
REPLICASETS = ApiResource("apps", "v1", "replicasets", "ReplicaSet", True, PODS.verbs)
PVC = ApiResource("", "v1", "persistentvolumeclaims", "PersistentVolumeClaim", True, PODS.verbs)


def manifest(resource=PODS, name="one", *, uid=None, namespace="team", **fields):
    value = item(name, namespace=namespace, uid=uid)
    value.update(apiVersion=resource.api_version, kind=resource.kind)
    if resource is not PODS:
        value["spec"] = {"template": {"spec": value["spec"]}}
    value.update(fields)
    return value


def record(resource=PODS, name="one", **fields):
    return resource_record(resource, manifest(resource, name, **fields))


def ref(resource=PODS, name="one", **fields):
    return reference_for(resource, record(resource, name, **fields))


def request(root=None, namespace="team", *, revision=1, session=None):
    return DiagnosticRequest(
        DiagnosticScope(session or SessionIdentity("synthetic", 1), namespace, root), revision
    )


def source(
    kind=DiagnosticSourceKind.CONDITION,
    *,
    status=DiagnosticStatus.READY,
    detail="Observed",
    key="native",
):
    return DiagnosticSource(
        key, kind, PODS, "team", status, CollectionState(), "opaque/version", NOW, detail
    )


def snapshot(req=None, *, findings=(), sources=None, collecting=False):
    return DiagnosticSnapshot(
        req or request(),
        tuple(findings),
        tuple(sources if sources is not None else (source(),)),
        collecting,
        2,
        NOW,
    )


def list_body(resource=PODS, *values, token=""):
    return {
        **collection(*values, token=token),
        "apiVersion": resource.api_version,
        "kind": resource.kind + "List",
    }


def owner(value, resource, name="one", uid=None, **fields):
    value["metadata"]["ownerReferences"] = [
        {
            "apiVersion": resource.api_version,
            "kind": resource.kind,
            "name": name,
            "uid": uid or "owned-" + name,
            "controller": True,
            **fields,
        }
    ]
    return value
