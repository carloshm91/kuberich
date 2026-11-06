"""Explicit synthetic resource semantics and an owned full discovery fixture."""

import copy
from contextlib import asynccontextmanager

from aiohttp import web

from kuberich.domain.curated import known_family
from kuberich.domain.curated_policy import FAMILIES as POLICY_FAMILIES
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.resources import api_resource, resource_record
from tests.support.connections import namespaces
from tests.support.curated_access import access_manifest, access_resource
from tests.support.curated_policy import policy_manifest, policy_resource
from tests.support.curated_scaling import SAMPLES as SCALING_SAMPLES
from tests.support.curated_scaling import api as scaling_api
from tests.support.curated_scaling import record as scaling_record
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
        "binaryData": {"binary": "cHJpdmF0ZS1iaW5hcnktcGF5bG9hZA=="},
    },
    {"type": "Opaque", "data": {"token": "cHJpdmF0ZS1zZWNyZXQtcGF5bG9hZA=="}},
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


def _curated_sample(definition):
    family = known_family(definition.group, definition.name)
    assert family is not None
    if family.kind in SCALING_SAMPLES:
        resource = scaling_api(family.kind)
        return resource, scaling_record(resource).manifest
    if family.resource in {item.resource for item in POLICY_FAMILIES}:
        return policy_resource(family.resource), policy_manifest(family.resource)
    return access_resource(family.kind), access_manifest(family.kind)


_CURATED = tuple(_curated_sample(item) for item in STANDARD_RESOURCES if item.curated)
_VERSIONS = (*("v1" for _ in KINDS), *(resource.version for resource, _ in _CURATED))
KINDS = (*KINDS, *(resource.kind for resource, _ in _CURATED))
FIXTURES = (*FIXTURES, *(fixture for _, fixture in _CURATED))


def api(definition):
    index = STANDARD_RESOURCES.index(definition)
    selected = _VERSIONS[index]
    version = f"{definition.group}/{selected}" if definition.group else selected
    return api_resource(
        version, descriptor(definition.name, kind=KINDS[index], namespaced=definition.namespaced)
    )


def manifest(definition, *, name="owned-one", namespace="team", uid=None, overrides=None):
    value = item(name, namespace=namespace if definition.namespaced else None, uid=uid)
    value.pop("spec")
    value.update(apiVersion=api(definition).api_version, kind=api(definition).kind)
    value["metadata"]["creationTimestamp"] = "2026-10-01T00:00:00Z"
    # Callers may edit the result, so never share nested fixture data between tests.
    fixture = copy.deepcopy(FIXTURES[STANDARD_RESOURCES.index(definition)])
    value.update({key: val for key, val in fixture.items() if key != "metadata"})
    value["metadata"].update(
        {
            key: val
            for key, val in fixture.get("metadata", {}).items()
            if key not in {"name", "uid", "namespace", "resourceVersion", "creationTimestamp"}
        }
    )
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
    resources = tuple(api(definition) for definition in STANDARD_RESOURCES)
    groups = sorted({resource.group for resource in resources if resource.group})
    result["/apis"]["groups"] = [
        {
            "name": group,
            "versions": [
                {"groupVersion": f"{group}/{version}", "version": version}
                for version in sorted(
                    {resource.version for resource in resources if resource.group == group}
                )
            ],
            "preferredVersion": {
                "groupVersion": f"{group}/{'v2' if group == 'autoscaling' else 'v1'}",
                "version": "v2" if group == "autoscaling" else "v1",
            },
        }
        for group in groups
    ]
    for group, version in sorted({(resource.group, resource.version) for resource in resources}):
        path = f"/apis/{group}/{version}" if group else "/api/v1"
        existing = result.get(path, {}).get("resources", [])
        result[path] = {
            "kind": "APIResourceList",
            "groupVersion": f"{group}/{version}" if group else version,
            "resources": [
                *existing,
                *(
                    descriptor(resource.name, namespaced=resource.namespaced, kind=resource.kind)
                    for resource in resources
                    if (resource.group, resource.version) == (group, version)
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
