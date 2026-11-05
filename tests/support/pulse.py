"""Synthetic resource families for current overview and exact drill-down trials."""

from kuberich.domain.pulse import FAMILIES
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    ResourceSnapshot,
    resource_record,
)
from tests.support.metrics import budgeted, metric_roots
from tests.support.resources import descriptor, item

KINDS = {
    "nodes": "Node",
    "pods": "Pod",
    "deployments": "Deployment",
    "replicasets": "ReplicaSet",
    "statefulsets": "StatefulSet",
    "daemonsets": "DaemonSet",
    "jobs": "Job",
    "cronjobs": "CronJob",
}


def pulse_resource(name="pods"):
    group = next(group for group, candidate in FAMILIES if candidate == name)
    return ApiResource(
        group, "v1", name, KINDS[name], name != "nodes", frozenset({"list", "watch"})
    )


def pulse_object(name="pods", identity="api", *, namespace="team", **fields):
    resource = pulse_resource(name)
    value = (
        budgeted(identity)
        if name == "pods"
        else item(identity, namespace=namespace if resource.namespaced else None)
    )
    value.update({"apiVersion": resource.api_version, "kind": resource.kind})
    value["metadata"]["generation"] = 1
    if resource.namespaced:
        value["metadata"]["namespace"] = namespace
    if name == "nodes":
        value["spec"] = {}
        value["status"] = {
            "conditions": [{"type": "Ready", "status": "True"}],
            "capacity": {"cpu": "4", "memory": "8Gi"},
            "allocatable": {"cpu": "3500m", "memory": "7Gi"},
        }
    elif name == "pods":
        value["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    elif name in {"deployments", "replicasets", "statefulsets"}:
        value["spec"] = {"replicas": 1}
        value["status"] = {
            "observedGeneration": 1,
            "readyReplicas": 1,
            "availableReplicas": 1,
            "updatedReplicas": 1,
        }
    elif name == "daemonsets":
        value["spec"] = {}
        value["status"] = {
            "observedGeneration": 1,
            "desiredNumberScheduled": 1,
            "numberReady": 1,
            "numberAvailable": 1,
            "updatedNumberScheduled": 1,
        }
    elif name == "jobs":
        value["spec"] = {}
        value["status"] = {"active": 1}
    else:
        value["spec"] = {"schedule": "* * * * *"}
        value["status"] = {
            "lastScheduleTime": "2026-11-04T12:00:00Z",
            "lastSuccessfulTime": "2026-11-04T12:00:00Z",
        }
    value.update(fields)
    return value


def pulse_record(name="pods", identity="api", **fields):
    return resource_record(pulse_resource(name), pulse_object(name, identity, **fields))


def pulse_snapshot(name="pods", *values, complete=True, version="snapshot"):
    resource = pulse_resource(name)
    records = tuple(resource_record(resource, value) for value in values)
    return ResourceSnapshot(
        resource,
        "team" if resource.namespaced else None,
        version,
        records,
        collection=CollectionState(
            complete, not complete, 1, sum(record.size_bytes for record in records)
        ),
    )


def pulse_roots():
    roots = metric_roots()
    roots["/api/v1"]["resources"] = [
        descriptor("namespaces", kind="Namespace", namespaced=False),
        descriptor("nodes", kind="Node", namespaced=False),
        descriptor(),
    ]
    for group in ("apps", "batch"):
        roots["/apis"]["groups"].append(
            {
                "name": group,
                "versions": [{"groupVersion": f"{group}/v1", "version": "v1"}],
                "preferredVersion": {"groupVersion": f"{group}/v1", "version": "v1"},
            }
        )
        roots[f"/apis/{group}/v1"] = {
            "kind": "APIResourceList",
            "groupVersion": f"{group}/v1",
            "resources": [
                descriptor(name, kind=KINDS[name])
                for candidate, name in FAMILIES
                if candidate == group
            ],
        }
    return roots
