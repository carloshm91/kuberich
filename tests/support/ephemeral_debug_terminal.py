"""Owned loopback debug API and audited helper for source and installed CLI PTYs."""

import copy
import json
import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.tables import server_table


def debug_pod():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "debug-workload",
            "namespace": "team",
            "uid": "owned-debug-pod-uid",
            "resourceVersion": "opaque/debug-v1",
        },
        "spec": {"containers": [{"name": "app", "image": "synthetic-workload"}]},
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "app",
                    "containerID": "containerd://owned-app-instance",
                    "restartCount": 0,
                    "state": {"running": {"startedAt": "2026-11-10T00:00:00Z"}},
                }
            ],
        },
    }


def debug_roots():
    values = legacy_roots()
    values["/api/v1"]["resources"] = [
        descriptor("pods", kind="Pod"),
        {
            "name": "pods/ephemeralcontainers",
            "kind": "Pod",
            "namespaced": True,
            "verbs": ["get", "patch"],
        },
        {"name": "pods/attach", "kind": "Pod", "namespaced": True, "verbs": ["get", "create"]},
    ]
    return values


class DebugHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, payload=None, *, status=200):
        body = json.dumps(payload or {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
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
        values = debug_roots()
        if parsed.path in values:
            self.respond(values[parsed.path])
        elif parsed.path.endswith("/namespaces"):
            self.respond(collection({"metadata": {"name": "team", "uid": "team-uid"}}))
        elif parsed.path.endswith("/pods"):
            pod = copy.deepcopy(self.server.pod)
            self.respond(
                server_table(pod)
                if "as=Table" in self.headers.get("Accept", "")
                else collection(pod)
            )
        elif parsed.path.endswith("/pods/debug-workload"):
            self.respond(copy.deepcopy(self.server.pod))
        else:
            self.respond(collection())

    def do_PATCH(self):
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(("PATCH", parsed.path, query, body))
        assert parsed.path == "/api/v1/namespaces/team/pods/debug-workload/ephemeralcontainers"
        assert self.headers["Content-Type"] == "application/json-patch+json"
        assert query.get("fieldValidation") == ["Strict"]
        if self.server.denied:
            self.respond({"kind": "Status", "code": 403}, status=403)
            return
        pod = self.server.pod
        assert body[:2] == [
            {"op": "test", "path": "/metadata/uid", "value": pod["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": pod["metadata"]["resourceVersion"],
            },
        ]
        assert len(body) == 3 and body[2]["op"] == "add"
        entry = body[2]["value"]
        if isinstance(entry, list):
            assert len(entry) == 1 and not pod["spec"].get("ephemeralContainers")
            entry = entry[0]
        value = copy.deepcopy(pod)
        value["spec"].setdefault("ephemeralContainers", []).append(entry)
        if query.get("dryRun") != ["All"]:
            value["metadata"]["resourceVersion"] += "x"
            value["status"].setdefault("ephemeralContainerStatuses", []).append(
                {
                    "name": entry["name"],
                    "containerID": "containerd://owned-debug-" + entry["name"],
                    "restartCount": 0,
                    "state": {"running": {"startedAt": "2026-11-10T00:01:00Z"}},
                }
            )
            self.server.pod = value
            self.server.appended.set()
            if self.server.drop_response:
                self.close_connection = True
                self.connection.close()
                return
        self.respond(value)


class DebugServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), DebugHandler)
        self.pod = debug_pod()
        self.requests = []
        self.stopping = threading.Event()
        self.appended = threading.Event()
        self.denied = False
        self.drop_response = False


@contextmanager
def debug_api():
    server = DebugServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
