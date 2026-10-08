"""Kubernetes-shaped pod fixtures with only owned synthetic values."""

from datetime import UTC, datetime

from kuberich.domain.resources import ResourceSnapshot, resource_record
from tests.support.resources import item, pod_resource

NOW = datetime(2026, 10, 5, 5, tzinfo=UTC)


def pod(name="pod", *, uid=None, namespace="team", restarts=0, ready=True, created=None):
    manifest = item(name, uid=uid, namespace=namespace)
    if created is not None:
        manifest["metadata"]["creationTimestamp"] = created.isoformat()
    manifest["status"] = {
        "phase": "Running",
        "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        "containerStatuses": [
            {"name": "app", "ready": ready, "restartCount": restarts, "state": {"running": {}}}
        ],
    }
    return manifest


def record(manifest):
    return resource_record(pod_resource(), manifest, manifest["metadata"].get("namespace"))


def snapshot(*manifests):
    return ResourceSnapshot(
        pod_resource(), "team", "snapshot", tuple(record(value) for value in manifests)
    )
