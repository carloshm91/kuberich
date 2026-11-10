"""Owned loopback maintenance API for public Pilot and actual CLI PTY trials."""

import copy
import json
import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import yaml

from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.tables import server_table
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


def node_manifest():
    return {
        "apiVersion": "v1",
        "kind": "Node",
        "metadata": {
            "name": "owned-maintenance-node",
            "uid": "node-uid",
            "resourceVersion": "node-v1",
        },
        "spec": {"unschedulable": False},
    }


def pod_manifest(name="workload", *, managed=True, emptydir=False, daemonset=False):
    metadata = {
        "name": name,
        "namespace": "team",
        "uid": name + "-uid",
        "resourceVersion": "pod-v1",
    }
    if managed:
        metadata["ownerReferences"] = [
            {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet" if daemonset else "ReplicaSet",
                "name": "controller",
                "uid": "controller-uid",
                "controller": True,
            }
        ]
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": metadata,
        "spec": {
            "nodeName": "owned-maintenance-node",
            "containers": [{"name": "app", "image": "synthetic"}],
            "volumes": [{"name": "cache", "emptyDir": {}}] if emptydir else [],
        },
        "status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]},
    }


def pdb_collection(*items):
    return {**collection(*items), "apiVersion": "policy/v1", "kind": "PodDisruptionBudgetList"}


def roots():
    values = legacy_roots()
    values["/api/v1"]["resources"].extend(
        [
            {
                **descriptor("nodes", kind="Node", namespaced=False),
                "verbs": ["get", "list", "watch", "patch"],
            },
            {
                "name": "pods/eviction",
                "kind": "Eviction",
                "namespaced": True,
                "group": "policy",
                "version": "v1",
                "verbs": ["create"],
            },
        ]
    )
    groups = []
    for group, plural, kind in (
        ("policy", "poddisruptionbudgets", "PodDisruptionBudget"),
        ("apps", "replicasets", "ReplicaSet"),
    ):
        version = {"groupVersion": group + "/v1", "version": "v1"}
        groups.append({"name": group, "versions": [version], "preferredVersion": version})
        resources = [descriptor(plural, kind=kind)]
        if group == "apps":
            resources.append(descriptor("daemonsets", kind="DaemonSet"))
        values[f"/apis/{group}/v1"] = {
            "kind": "APIResourceList",
            "groupVersion": group + "/v1",
            "resources": resources,
        }
    values["/apis"]["groups"] = groups
    return values


class MaintenanceHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, payload=None, *, status=200, retry=False):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if retry:
            self.send_header("Retry-After", "30")
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def do_GET(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        self.server.requests.append(("GET", parsed.path, query))
        if "watch" in query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        values = roots()
        if parsed.path in values:
            self.respond(values[parsed.path])
        elif parsed.path == "/api/v1/namespaces":
            self.respond(
                collection(
                    {
                        "metadata": {
                            "name": "team",
                            "uid": "namespace-uid",
                            "resourceVersion": "ns-v1",
                        }
                    }
                )
            )
        elif parsed.path == "/api/v1/nodes":
            self.respond(
                server_table(copy.deepcopy(self.server.node))
                if "as=Table" in self.headers.get("Accept", "")
                else {**collection(copy.deepcopy(self.server.node)), "kind": "NodeList"}
            )
        elif parsed.path == "/api/v1/nodes/owned-maintenance-node":
            self.server.node_requested.set()
            self.server.node_gate.wait(10)
            self.respond(copy.deepcopy(self.server.node), status=self.server.node_status)
        elif parsed.path == "/api/v1/pods":
            if "fieldSelector" in query:
                assert query["fieldSelector"] == ["spec.nodeName=owned-maintenance-node"]
            self.respond(collection(*copy.deepcopy(list(self.server.pods.values()))))
        elif "/pods/" in parsed.path:
            pod = self.server.pods.get(parsed.path.rsplit("/", 1)[1])
            self.respond(copy.deepcopy(pod), status=200 if pod else 404)
        elif parsed.path.endswith("/poddisruptionbudgets"):
            self.respond(
                pdb_collection(
                    {
                        "apiVersion": "policy/v1",
                        "kind": "PodDisruptionBudget",
                        "metadata": {
                            "name": "budget",
                            "namespace": "team",
                            "uid": "pdb-uid",
                            "resourceVersion": "pdb-v1",
                            "generation": 1,
                        },
                        "spec": {"selector": {}, "minAvailable": 1},
                        "status": {
                            "disruptionsAllowed": 0 if self.server.blocked else 1,
                            "currentHealthy": 1,
                            "desiredHealthy": 1,
                            "observedGeneration": 1,
                        },
                    },
                    *self.server.extra_pdbs,
                )
            )
        elif parsed.path.endswith("/controller"):
            self.respond(
                {
                    "apiVersion": "apps/v1",
                    "kind": "DaemonSet" if "/daemonsets/" in parsed.path else "ReplicaSet",
                    "metadata": {
                        "name": "controller",
                        "namespace": "team",
                        "uid": "controller-uid",
                        "resourceVersion": "owner-v1",
                    },
                }
            )
        else:
            self.respond(collection())

    def do_PATCH(self):
        path = urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("PATCH", path, body))
        assert path == "/api/v1/nodes/owned-maintenance-node"
        assert body[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": "node-uid"},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": self.server.node["metadata"]["resourceVersion"],
            },
        ]
        self.server.node["spec"]["unschedulable"] = body[-1]["value"]
        self.server.node["metadata"]["resourceVersion"] += "x"
        self.respond(copy.deepcopy(self.server.node))

    def do_POST(self):
        path = urlsplit(self.path).path
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("POST", path, body))
        assert path.endswith("/eviction") and body["kind"] == "Eviction"
        name = path.split("/")[-2]
        pod = self.server.pods[name]
        assert body["deleteOptions"]["preconditions"] == {
            "uid": pod["metadata"]["uid"],
            "resourceVersion": pod["metadata"]["resourceVersion"],
        }
        self.server.attempted.set()
        if self.server.blocked:
            self.respond(
                {
                    "apiVersion": "v1",
                    "kind": "Status",
                    "status": "Failure",
                    "code": 429,
                    "reason": "TooManyRequests",
                },
                status=429,
                retry=True,
            )
        else:
            if self.server.terminating:
                pod["metadata"]["deletionTimestamp"] = "2026-11-10T00:00:00Z"
            else:
                del self.server.pods[name]
            self.respond(
                {"apiVersion": "v1", "kind": "Status", "status": "Success", "code": 201},
                status=201,
            )


class MaintenanceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), MaintenanceHandler)
        self.stopping = threading.Event()
        self.attempted = threading.Event()
        self.node_requested = threading.Event()
        self.node_gate = threading.Event()
        self.node_gate.set()
        self.node = node_manifest()
        self.pods = {"workload": pod_manifest()}
        self.requests = []
        self.blocked = True
        self.terminating = False
        self.node_status = 200
        self.extra_pdbs = []


@contextmanager
def maintenance_api():
    server = MaintenanceServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.node_gate.set()
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


def terminal_node_maintenance(command, directory, scenario, *, evidence):
    directory = directory.resolve()
    with maintenance_api() as api:
        api.blocked = scenario != "success"
        kubeconfig = config(
            directory / "maintenance-kubeconfig",
            f"http://127.0.0.1:{api.server_port}",
            {"token": "synthetic-maintenance"},
        )
        document = yaml.safe_load(kubeconfig.read_text())
        document["contexts"].append(
            {"name": "kuberich-maintenance-other", "context": {"cluster": "owned", "user": "owned"}}
        )
        kubeconfig.write_text(yaml.safe_dump(document))
        original = kubeconfig.read_bytes()
        invocation = [
            *command,
            "--kubeconfig",
            str(kubeconfig),
            "--context",
            "kuberich-test-pty",
            "--command",
            "nodes",
        ]
        with TerminalSession(invocation, directory, size=(120, 36)) as terminal:
            terminal.wait_for_screen("owned-maintenance-node")
            terminal.wait_for_screen("Live ·")
            terminal.send(b":drain\r")
            terminal.wait_for_screen("Review complete.")
            assert not any(method in {"PATCH", "POST"} for method, *_ in api.requests)
            terminal.send(b"\x1b[Z\r")
            terminal.wait_for_screen(
                "Original UID absent" if scenario == "success" else "Refused; waiting to retry"
            )
            assert api.attempted.is_set() and api.node["spec"]["unschedulable"]
            sent = sum(method == "POST" for method, *_ in api.requests)
            if scenario == "success":
                terminal.send(b"\x1b")
                terminal.wait_for_screen("Sort NAME", absent=("Node maintenance ·",))
                terminal.send(b":uncordon\r")
                terminal.wait_for_screen("Review complete.")
                assert api.node["spec"]["unschedulable"]
                terminal.send(b"\x1b[Z\r")
                terminal.wait_for_screen("Observed schedulable")
                terminal.send(b"\x11")
                terminal.finish()
            elif scenario == "quit":
                terminal.send(b"\x11")
                terminal.finish()
            else:
                terminal.send(b"\r")
                terminal.wait_for_screen("Maintenance stopped")
                terminal.wait_for_screen("Observed cordoned")
                terminal.resize(50, 15)
                terminal.send(b"\x1b")
                terminal.wait_for_screen("Sort NAME", absent=("Node maintenance ·",))
                if scenario == "context":
                    terminal.resize(120, 36)
                    terminal.send(b":ctx kuberich-maintenance-other\r")
                    terminal.wait_for_screen("kuberich-maintenance-other")
                terminal.send(b"\x11")
                terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-maintenance" not in terminal.transcript
        assert sent == sum(method == "POST" for method, *_ in api.requests)
        assert api.node["spec"]["unschedulable"] is (scenario != "success")
        assert kubeconfig.read_bytes() == original
