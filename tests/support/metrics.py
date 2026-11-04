"""Synthetic current samples; metrics objects deliberately omit UID/resourceVersion."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

from kuberich.domain.resources import ApiResource, ResourceSnapshot, resource_record
from tests.support.pods import pod, record
from tests.support.resources import descriptor, legacy_roots

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)


def metric_resource(name="pods", version="v1"):
    return ApiResource(
        "metrics.k8s.io",
        version,
        name,
        "PodMetrics" if name == "pods" else "NodeMetrics",
        name == "pods",
        frozenset({"get", "list"}),
    )


def sample(
    name="api",
    *,
    cpu="250m",
    memory="64Mi",
    now=NOW,
    containers=None,
    namespace="team",
    uid=None,
    version="v1",
):
    metadata = {"name": name}
    if namespace is not None:
        metadata["namespace"] = namespace
    if uid is not None:
        metadata["uid"] = uid
    value = {
        "apiVersion": f"metrics.k8s.io/{version}",
        "kind": "PodMetrics" if namespace is not None else "NodeMetrics",
        "metadata": metadata,
        "timestamp": now.isoformat(),
        "window": "30s",
    }
    if namespace is None:
        value["usage"] = {"cpu": cpu, "memory": memory}
    else:
        value["containers"] = (
            containers
            if containers is not None
            else [{"name": "app", "usage": {"cpu": cpu, "memory": memory}}]
        )
    return value


def sampled(value=None, **kwargs):
    value = sample(**kwargs) if value is None else value
    return resource_record(
        metric_resource(
            "pods" if "namespace" in value["metadata"] else "nodes",
            value["apiVersion"].split("/")[1],
        ),
        value,
    )


def budgeted(
    name="api", *, request="100m", limit="1", memory_request="32Mi", memory_limit="128Mi", **kwargs
):
    value = pod(name, **kwargs)
    resources = {"requests": {}, "limits": {}}
    for field, key, number in (
        ("requests", "cpu", request),
        ("limits", "cpu", limit),
        ("requests", "memory", memory_request),
        ("limits", "memory", memory_limit),
    ):
        if number is not None:
            resources[field][key] = number
    value["spec"]["containers"][0]["resources"] = resources
    return value


def budget_record(**kwargs):
    return record(budgeted(**kwargs))


def samples(*values, name="pods", version="v1"):
    return ResourceSnapshot(
        metric_resource(name, version),
        "team" if name == "pods" else None,
        None,
        tuple(sampled(value) for value in values),
    )


def metric_roots(version="v1"):
    roots = legacy_roots()
    roots["/apis"]["groups"] = [
        {
            "name": "metrics.k8s.io",
            "versions": [{"groupVersion": f"metrics.k8s.io/{version}", "version": version}],
            "preferredVersion": {"groupVersion": f"metrics.k8s.io/{version}", "version": version},
        }
    ]
    roots[f"/apis/metrics.k8s.io/{version}"] = {
        "kind": "APIResourceList",
        "groupVersion": f"metrics.k8s.io/{version}",
        "resources": [
            {
                **descriptor(
                    name,
                    kind="PodMetrics" if name == "pods" else "NodeMetrics",
                    namespaced=name == "pods",
                ),
                "verbs": ["get", "list"],
                "singularName": "",
                "shortNames": [],
            }
            for name in ("pods", "nodes")
        ],
    }
    roots["/api/v1"]["resources"].append(descriptor("nodes", kind="Node", namespaced=False))
    return roots


def sample_list(*values, version="v1", name="pods"):
    return {
        "apiVersion": f"metrics.k8s.io/{version}",
        "kind": "PodMetricsList" if name == "pods" else "NodeMetricsList",
        "metadata": {},
        "items": list(values),
    }


def admitted(name="api", **kwargs):
    """Ordinary admitted Pod with both normal kubelet allocation status fields."""
    kwargs.setdefault("created", NOW - timedelta(minutes=1))
    value = budgeted(name, **kwargs)
    declared = value["spec"]["containers"][0]["resources"]
    observed = value["status"]["containerStatuses"][0]
    observed["allocatedResources"] = deepcopy(declared["requests"])
    observed["resources"] = deepcopy(declared)
    return value
