"""Explicit synthetic resource semantics and an owned full discovery fixture."""

from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.resources import api_resource, resource_record
from tests.support.connections import namespaces
from tests.support.resources import descriptor, item, legacy_roots, reader_fixture
from tests.support.workspace import stable_watch

KINDS = (
    "Deployment",
    "ReplicaSet",
    "StatefulSet",
    "DaemonSet",
    "Job",
    "CronJob",
    "Service",
    "Endpoints",
    "Ingress",
    "ConfigMap",
    "Secret",
    "Node",
    "PersistentVolumeClaim",
    "PersistentVolume",
    "StorageClass",
)
FIXTURES = (
    {
        "spec": {"replicas": 12},
        "status": {"readyReplicas": 10, "updatedReplicas": 11, "availableReplicas": 9},
    },
    {"spec": {"replicas": 12}, "status": {"replicas": 11, "readyReplicas": 10}},
    {
        "spec": {"replicas": 12},
        "status": {"currentReplicas": 11, "updatedReplicas": 9, "readyReplicas": 10},
    },
    {
        "status": {
            "desiredNumberScheduled": 12,
            "currentNumberScheduled": 11,
            "numberReady": 10,
            "numberAvailable": 9,
        }
    },
    {"spec": {"completions": 12}, "status": {"succeeded": 10, "active": 1, "failed": 2}},
    {
        "spec": {"schedule": "*/5 * * * *", "suspend": False},
        "status": {"active": [{"name": "owned-job"}], "lastScheduleTime": "2026-10-01T12:00:00Z"},
    },
    {
        "spec": {"type": "ClusterIP", "clusterIP": "10.0.0.2", "ports": [{"port": 8080}]},
        "status": {"loadBalancer": {"ingress": [{"ip": "192.0.2.1"}]}},
    },
    {
        "subsets": [
            {
                "addresses": [{"ip": "192.0.2.1"}],
                "notReadyAddresses": [{"ip": "192.0.2.2"}],
                "ports": [{"port": 8080}],
            }
        ]
    },
    {
        "spec": {"ingressClassName": "owned", "rules": [{"host": "owned.example"}]},
        "status": {"loadBalancer": {"ingress": [{"hostname": "ingress.example"}]}},
    },
    {
        "data": {"config": "private-config-payload"},
        "binaryData": {"binary": "private-binary-payload"},
    },
    {"type": "Opaque", "data": {"token": "private-secret-payload"}},
    {
        "metadata": {"labels": {"node-role.kubernetes.io/control-plane": ""}},
        "status": {
            "conditions": [{"type": "Ready", "status": "True"}],
            "nodeInfo": {"kubeletVersion": "v1.36.4"},
        },
    },
    {
        "spec": {
            "volumeName": "owned-volume",
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "owned",
        },
        "status": {"phase": "Bound", "capacity": {"storage": "2Gi"}},
    },
    {
        "spec": {
            "capacity": {"storage": "2Gi"},
            "accessModes": ["ReadWriteOnce"],
            "persistentVolumeReclaimPolicy": "Retain",
            "claimRef": {"namespace": "team", "name": "owned-claim"},
            "storageClassName": "owned",
        },
        "status": {"phase": "Bound"},
    },
    {
        "provisioner": "kubernetes.io/no-provisioner",
        "reclaimPolicy": "Retain",
        "volumeBindingMode": "Immediate",
        "allowVolumeExpansion": False,
    },
)


def api(definition):
    index = STANDARD_RESOURCES.index(definition)
    version = f"{definition.group}/v1" if definition.group else "v1"
    return api_resource(
        version, descriptor(definition.name, kind=KINDS[index], namespaced=definition.namespaced)
    )


def manifest(definition, *, name="owned-one", namespace="team", uid=None, overrides=None):
    value = item(name, namespace=namespace if definition.namespaced else None, uid=uid)
    value.pop("spec")
    value.update(apiVersion=api(definition).api_version, kind=api(definition).kind)
    value["metadata"]["creationTimestamp"] = "2026-10-01T00:00:00Z"
    fixture = FIXTURES[STANDARD_RESOURCES.index(definition)]
    value.update({key: val for key, val in fixture.items() if key != "metadata"})
    value["metadata"].update(fixture.get("metadata", {}))
    if overrides:
        value.update(overrides)
    return value


def row_record(definition, **kwargs):
    return resource_record(
        api(definition),
        manifest(definition, **kwargs),
        kwargs.get("namespace", "team") if definition.namespaced else None,
    )


def roots():
    result = legacy_roots()
    groups = sorted({definition.group for definition in STANDARD_RESOURCES if definition.group})
    result["/apis"]["groups"] = [
        {
            "name": group,
            "versions": [{"groupVersion": f"{group}/v1", "version": "v1"}],
            "preferredVersion": {"groupVersion": f"{group}/v1", "version": "v1"},
        }
        for group in groups
    ]
    for group in ("", *groups):
        path = f"/apis/{group}/v1" if group else "/api/v1"
        existing = result.get(path, {}).get("resources", [])
        result[path] = {
            "kind": "APIResourceList",
            "groupVersion": f"{group}/v1" if group else "v1",
            "resources": [
                *existing,
                *(
                    descriptor(d.name, namespaced=d.namespaced, kind=api(d).kind)
                    for d in STANDARD_RESOURCES
                    if d.group == group
                ),
            ],
        }
    return result


@asynccontextmanager
async def standard_api(directory, handler=None, *, absent=None, denied=None):
    reads = []

    async def response(request):
        reads.append((request.path, dict(request.query)))
        if request.path == "/api/v1/namespaces" and "watch" not in request.query:
            return namespaces("team", "other", "default")
        discovery = roots()
        if absent:
            for entry in discovery.values():
                if "resources" in entry:
                    entry["resources"] = [
                        value for value in entry["resources"] if value["name"] != absent
                    ]
        if request.path in discovery:
            return web.json_response(discovery[request.path])
        if request.path.endswith("/events"):
            return web.json_response(
                {"apiVersion": "v1", "kind": "EventList", "metadata": {}, "items": []}
            )
        for definition in STANDARD_RESOURCES:
            resource = api(definition)
            namespace = (
                request.path.split("/namespaces/")[1].split("/")[0]
                if "/namespaces/" in request.path
                else None
            )
            prefix = resource.path(namespace if resource.namespaced else None)
            if request.path not in {prefix, prefix + "/owned-one"}:
                continue
            if denied == definition.name:
                return web.Response(status=403)
            if handler:
                overridden = await handler(request, definition)
                if overridden is not None:
                    return overridden
            if "watch" in request.query:
                return await stable_watch(request)
            value = manifest(definition, namespace=namespace or "team")
            if request.path == prefix + "/owned-one":
                return web.json_response(value)
            return web.json_response(
                {
                    "apiVersion": resource.api_version,
                    "kind": resource.kind + "List",
                    "metadata": {"resourceVersion": "opaque/list"},
                    "items": [value],
                }
            )
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            {
                "apiVersion": "v1",
                "kind": "PodList",
                "metadata": {"resourceVersion": "opaque/pods"},
                "items": [],
            }
        )

    async with reader_fixture(directory, response) as reader:
        yield reader.session.context.cluster.data["server"], reads
