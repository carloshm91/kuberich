"""Synthetic explorer API shared by actual App and source/installed CLI trials."""

import copy
import re
from dataclasses import dataclass, field

from tests.support.container_inspection import pod_fixture
from tests.support.history import matrix, service
from tests.support.pulse import pulse_object, pulse_roots
from tests.support.resources import collection, descriptor

NAMESPACE = "team"
POD_NAME = "history-pod"
POD_PATH = f"/api/v1/namespaces/{NAMESPACE}/pods/{POD_NAME}"
RAW_ERROR = "token=never-display-owned-backend-marker /private/history-auth-file"


@dataclass
class HistoryApi:
    """Finite Prometheus-compatible response vectors, explicitly synthetic."""

    requests: list = field(default_factory=list)
    status: int = 200
    gaps: bool = True
    records: dict = field(default_factory=dict)

    def __post_init__(self):
        pod = pod_fixture()
        pod["metadata"].update(name=POD_NAME, namespace=NAMESPACE, uid="history-pod-uid")
        pod["metadata"]["ownerReferences"] = [
            {
                "apiVersion": "apps/v1",
                "kind": "ReplicaSet",
                "name": "history-rs",
                "uid": "history-rs-uid",
                "controller": True,
            }
        ]
        self.records[POD_PATH] = pod
        for family, name in (
            ("nodes", "history-node"),
            ("deployments", "history-workload"),
            ("replicasets", "history-rs"),
        ):
            obj = pulse_object(family, name)
            obj["metadata"]["uid"] = name + "-uid"
            if family == "replicasets":
                obj["metadata"]["ownerReferences"] = [
                    {
                        "apiVersion": "apps/v1",
                        "kind": "Deployment",
                        "name": "history-workload",
                        "uid": "history-workload-uid",
                        "controller": True,
                    }
                ]
            path = (
                ("/api/v1/" if family == "nodes" else f"/apis/apps/v1/namespaces/{NAMESPACE}/")
                + family
                + "/"
                + name
            )
            self.records[path] = obj
        for name in ("metrics", "alternate"):
            self.records[f"/api/v1/namespaces/{NAMESPACE}/services/{name}"] = service(
                name, name + "-uid"
            )

    def roots(self):
        roots = pulse_roots()
        roots["/api/v1"]["resources"].append(descriptor("services", kind="Service"))
        return roots

    def response(self, path, parameters):
        """Return status/payload for GET; watches are owned by the caller."""
        self.requests.append((path, dict(parameters)))
        if path.endswith("query_range"):
            if self.status != 200:
                return self.status, {"message": RAW_ERROR}
            query = parameters["query"]
            group = re.match(r"sum by\(([^)]*)\)", query)
            labels = {}
            if group:
                values = {
                    "device": "/dev/synthetic-a",
                    "mountpoint": "/",
                    "fstype": "syntheticfs",
                    "interface": "eth0",
                    "namespace": NAMESPACE,
                    "pod": POD_NAME,
                    "container": "app",
                }
                labels = {key: values[key] for key in group[1].split(",") if key}
            is_value = query.startswith("sum")
            value = (
                "1"
                if not is_value
                else "0.5"
                if "cpu" in query
                else "1048576"
                if "memory" in query
                else "2048"
                if "network" in query
                else "3145728"
            )
            result = matrix(parameters, value=value, labels=labels)
            if self.gaps and is_value:
                values = result["data"]["result"][0]["values"]
                del values[1]
                values[-1][1] = "NaN"
            if is_value and ("fs_usage" in query or "node_filesystem_size_bytes" in query):
                other = copy.deepcopy(result["data"]["result"][0])
                other["metric"]["device"] = "/dev/synthetic-b"
                result["data"]["result"].append(other)
            return 200, result
        if path.endswith("status/buildinfo"):
            return 200, {"status": "success", "data": {"version": "synthetic-compatibility-only"}}
        if path.endswith("/query"):
            return 200, {
                "status": "success",
                "data": {"resultType": "vector", "result": [{"metric": {}, "value": [1, "1"]}]},
            }
        if path in self.roots():
            return 200, self.roots()[path]
        if path == "/api/v1/namespaces":
            return 200, collection(
                {
                    "metadata": {
                        "name": NAMESPACE,
                        "uid": "namespace-team",
                        "resourceVersion": "namespace-v1",
                    }
                }
            )
        if path in self.records:
            return 200, self.records[path]
        if "/metrics.k8s.io/" in path:
            return 404, {"message": "Current metrics are outside this historical fixture."}
        family = path.rsplit("/", 1)[-1]
        if family in {"pods", "nodes", "deployments", "replicasets", "services"}:
            payload = collection(
                *(obj for key, obj in self.records.items() if key.rsplit("/", 2)[-2] == family)
            )
            if payload["items"]:
                first = payload["items"][0]
                payload.update(apiVersion=first["apiVersion"], kind=first["kind"] + "List")
            return 200, payload
        if (
            family in {"statefulsets", "daemonsets", "jobs", "cronjobs"}
            or "/metrics.k8s.io/" in path
        ):
            return 200, collection()
        return 404, {"message": "Owned synthetic endpoint unavailable"}
