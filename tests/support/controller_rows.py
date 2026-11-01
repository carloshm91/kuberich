"""Owned snapshots for the real typed view-controller adapters."""

from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.resources import ResourceSnapshot, api_resource, resource_record
from kuberich.domain.view_routes import ViewRoute
from tests.support.pods import pod, snapshot
from tests.support.resources import descriptor, item


def observed(kind):
    if kind == "pods":
        return snapshot(pod("alpha"), pod("beta")), ViewRoute.pods()
    namespaced = kind != "namespaces"
    group, version = ("batch", "v1") if kind == "jobs" else ("", "v1")
    resource = api_resource(
        f"{group}/{version}" if group else version,
        descriptor(
            kind,
            kind={"jobs": "Job", "services": "Service", "namespaces": "Namespace"}[kind],
            namespaced=namespaced,
        ),
    )
    manifests = tuple(
        item(name, namespace="team" if namespaced else None) for name in ("alpha", "beta")
    )
    for manifest in manifests:
        manifest.update(apiVersion=resource.api_version, kind=resource.kind)
        manifest["status"] = {"phase": "Active", "succeeded": 1}
        if kind == "jobs":
            manifest["status"]["conditions"] = [{"type": "Complete", "status": "True"}]
    records = tuple(
        resource_record(resource, value, "team" if namespaced else None) for value in manifests
    )
    route = (
        ViewRoute.namespaces()
        if kind == "namespaces"
        else ViewRoute.standard(RESOURCE_ALIASES[kind])
    )
    return ResourceSnapshot(resource, "team" if namespaced else None, "owned", records), route
