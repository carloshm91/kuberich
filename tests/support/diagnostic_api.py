"""Owned loopback API for actual diagnostic App navigation and UID-checked logs."""

from datetime import UTC, datetime

from aiohttp import web

from tests.support.authorization_ui import AuthorizationAPI
from tests.support.diagnostic_native import DEPLOYMENTS, EVENTS, REPLICASETS
from tests.support.relationships import manifest, owner
from tests.support.resources import descriptor


class DiagnosticAPI(AuthorizationAPI):
    def __init__(self):
        super().__init__()
        self.log_reads = []
        self.log_status = 200
        self.get_status = {}
        for namespace in ("team", "other"):
            value = self.objects[("", "pods", namespace, "example")]
            value["metadata"]["uid"] = "pod-" + namespace
            value["status"] = {
                "phase": "Running",
                "conditions": [{"type": "Ready", "status": "False"}],
                "containerStatuses": [
                    {
                        "name": "app",
                        "ready": False,
                        "restartCount": 2,
                        "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                        "lastState": {"terminated": {"exitCode": 1, "reason": "Error"}},
                    }
                ],
            }
            self.add(
                EVENTS,
                "backoff",
                namespace=namespace,
                involvedObject={
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "namespace": namespace,
                    "name": "example",
                    "uid": value["metadata"]["uid"],
                },
                reason="BackOff",
                message="Synthetic restart backoff; no cause is established.",
                lastTimestamp=datetime.now(UTC).isoformat(),
            )
        self.objects[("apps", "deployments", "other", "root")] = manifest(
            DEPLOYMENTS,
            name="root",
            uid="deployment-other",
            namespace="other",
            spec={
                "replicas": 1,
                "selector": {"matchLabels": {"diagnostic": "owned"}},
                "template": {
                    "metadata": {"labels": {"diagnostic": "owned"}},
                    "spec": {"containers": [{"name": "app", "image": "synthetic"}]},
                },
            },
        )
        self.objects[("apps", "replicasets", "other", "intermediate")] = manifest(
            REPLICASETS,
            name="intermediate",
            uid="replicaset-other",
            namespace="other",
            spec={
                "replicas": 1,
                "selector": {"matchLabels": {"diagnostic": "owned"}},
                "template": {
                    "metadata": {"labels": {"diagnostic": "owned"}},
                    "spec": {"containers": [{"name": "app", "image": "synthetic"}]},
                },
            },
            metadata={"ownerReferences": [owner(DEPLOYMENTS, name="root", uid="deployment-other")]},
        )
        self.objects[("", "pods", "other", "example")]["metadata"]["ownerReferences"] = [
            owner(REPLICASETS, name="intermediate", uid="replicaset-other")
        ]
        self.objects[("", "pods", "other", "example")]["metadata"]["labels"] = {
            "diagnostic": "owned"
        }

    def roots(self):
        result = super().roots()
        result["/api/v1"]["resources"].append(descriptor("events", kind="Event"))
        result["/apis"]["groups"].append(
            {
                "name": "apps",
                "versions": [{"groupVersion": "apps/v1", "version": "v1"}],
                "preferredVersion": {"groupVersion": "apps/v1", "version": "v1"},
            }
        )
        result["/apis/apps/v1"] = {
            "apiVersion": "v1",
            "kind": "APIResourceList",
            "groupVersion": "apps/v1",
            "resources": [
                descriptor(item.name, kind=item.kind) for item in (DEPLOYMENTS, REPLICASETS)
            ],
        }
        return result

    async def handler(self, request):
        if request.method == "GET" and request.path in self.get_status:
            self.reads.append((request.path, dict(request.query)))
            return web.Response(status=self.get_status[request.path])
        if request.path.endswith("/log"):
            self.log_reads.append((request.path, dict(request.query)))
            return web.Response(
                text="synthetic previous log\n"
                if request.query.get("previous") == "true"
                else "synthetic current log\n",
                status=self.log_status,
            )
        return await super().handler(request)
