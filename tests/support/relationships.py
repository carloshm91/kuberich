"""Synthetic relationship resources; no cluster context or configuration contents."""

from kuberich.domain.relationships import RelationshipRef
from kuberich.domain.resources import ApiResource, resource_record


def descriptor(
    name="pods", kind="Pod", group="", *, namespaced=True, version="v1", verbs=("get", "list")
):
    return ApiResource(group, version, name, kind, namespaced, frozenset(verbs))


PODS = descriptor()
DEPLOYMENTS = descriptor("deployments", "Deployment", "apps")
SERVICES = descriptor("services", "Service")
SLICES = descriptor("endpointslices", "EndpointSlice", "discovery.k8s.io")
ENDPOINTS = descriptor("endpoints", "Endpoints")
CONFIGMAPS = descriptor("configmaps", "ConfigMap")
SECRETS = descriptor("secrets", "Secret")
ACCOUNTS = descriptor("serviceaccounts", "ServiceAccount")
CLAIMS = descriptor("persistentvolumeclaims", "PersistentVolumeClaim")
VOLUMES = descriptor("persistentvolumes", "PersistentVolume", namespaced=False)
NODES = descriptor("nodes", "Node", namespaced=False)
PRIORITIES = descriptor("priorityclasses", "PriorityClass", "scheduling.k8s.io", namespaced=False)


def manifest(
    resource=PODS,
    *,
    name="example",
    uid="example-uid",
    namespace="team",
    spec=None,
    metadata=None,
    **fields,
):
    meta = {"name": name, "uid": uid, "resourceVersion": "1"}
    if resource.namespaced:
        meta["namespace"] = namespace
    meta.update(metadata or {})
    return {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "metadata": meta,
        "spec": {"containers": [{"name": "app", "image": "synthetic"}]} if spec is None else spec,
        **fields,
    }


def record(resource=PODS, **options):
    return resource_record(resource, manifest(resource, **options))


def ref(resource=PODS, *, name="example", uid="example-uid", namespace="team"):
    return RelationshipRef(
        resource.api_version,
        resource.kind,
        namespace if resource.namespaced else None,
        name,
        uid,
        resource,
    )


def owner(resource=DEPLOYMENTS, *, name="example", uid="example-uid", **fields):
    return {
        "apiVersion": resource.api_version,
        "kind": resource.kind,
        "name": name,
        "uid": uid,
        "controller": True,
        **fields,
    }
