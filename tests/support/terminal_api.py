"""Shared owned HTTP API and kubeconfig fixtures for actual CLI/install PTYs."""

import json
import queue
import threading
import time
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from tests.support.pods import NOW, pod
from tests.support.resources import collection, item, legacy_roots
from tests.support.watches import bookmark, frame


def config(path: Path, server: str, user: dict) -> Path:
    data = {
        "current-context": "kuberich-test-pty",
        "contexts": [
            {"name": "kuberich-test-pty", "context": {"cluster": "owned", "user": "owned"}}
        ],
        "clusters": [{"name": "owned", "cluster": {"server": server}}],
        "users": [{"name": "owned", "user": user}],
    }
    path.write_text(yaml.safe_dump(data))
    return path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        if self.server.impersonation is not None:
            subject, groups = self.server.impersonation
            assert self.headers.get("Impersonate-User") == subject
            assert self.headers.get_all("Impersonate-Group") == list(groups)
            self.server.identity_verified.set()
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path.endswith("/log"):
            if query.get("previous") == ["true"]:
                self.send_error(400, "Owned previous instance unavailable")
                return
            body = "".join(
                f"2026-10-05T12:00:00Z log-line-{i:03} 你好 [red]literal[/red] token=hidden-log-token\n"
                for i in range(80)
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            if query.get("follow") != ["true"]:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                while query.get("follow") == ["true"] and not self.server.stopping.wait(0.1):
                    self.wfile.write(b"2026-10-05T12:00:01Z owned quiet follow\n")
                    self.wfile.flush()
            except OSError:
                pass
            return
        if "watch" in query:
            if self.server.fail_watches.is_set():
                self.send_error(503, "Owned fixture outage")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with self.server.watch_lock:
                self.server.watch_versions.append(query["resourceVersion"][0])
                if len(self.server.watch_versions) >= 3:
                    self.server.renewed.set()
            deadline = time.monotonic() + int(query["timeoutSeconds"][0])
            try:
                while time.monotonic() < deadline and not self.server.stopping.wait(0.03):
                    try:
                        update = self.server.pod_events.get_nowait()
                    except queue.Empty:
                        update = None
                    if update is not None:
                        self.wfile.write(frame(update))
                        self.wfile.flush()
                    if not self.server.quiet_watches.is_set():
                        self.wfile.write(frame(bookmark("owned-pty-version")))
                        self.wfile.flush()
            except OSError:
                pass
            return
        if parsed.path == "/api/v1/namespaces":
            self.server.namespace_requested.set()
            if not self.server.namespace_gate.wait(10):
                self.send_error(503, "Owned namespace gate timed out")
                return
            payload = {
                "items": [
                    {
                        "metadata": {
                            "name": name,
                            "uid": f"namespace-{name}",
                            "resourceVersion": "owned-ns-object",
                        },
                        "status": {"phase": "Active"},
                    }
                    for name in ("default", "team")
                ],
                "metadata": {"resourceVersion": "owned-ns-list"},
            }
        elif parsed.path in legacy_roots():
            payload = legacy_roots()[parsed.path]
        elif parsed.path.endswith("/pods"):
            namespace = parsed.path.split("/")[4] if "/namespaces/" in parsed.path else "default"
            payload = collection(item("owned-pty-pod", namespace=namespace))
            if self.server.pod_table.is_set():
                payload = collection(
                    *(
                        pod(
                            f"owned-pty-pod-{index:03}",
                            namespace=namespace,
                            uid=f"owned-{namespace}-{index:03}",
                            restarts=index,
                            created=NOW,
                        )
                        for index in range(80)
                    )
                )
        elif "/pods/" in parsed.path:
            self.server.pod_requested.set()
            if not self.server.pod_gate.wait(10):
                self.send_error(503, "Owned pod gate timed out")
                return
            if self.server.pod_get_status != 200:
                self.send_error(self.server.pod_get_status, "Owned pod preflight failure")
                return
            namespace = parsed.path.split("/")[4]
            name = parsed.path.rsplit("/", 1)[1]
            uid = (
                f"owned-{namespace}-{name.rsplit('-', 1)[1]}"
                if self.server.pod_table.is_set()
                else f"owned-{name}"
            )
            payload = pod(name, namespace=namespace, uid=uid)
            payload["metadata"]["managedFields"] = [{"manager": "owned-manager", "fieldsV1": {}}]
            payload["spec"]["containers"][0]["env"] = [{"name": "VALUE", "value": "hidden-pty-env"}]
        elif parsed.path.endswith("/events"):
            namespace = parsed.path.split("/")[4]
            payload = {
                "apiVersion": "v1",
                "kind": "EventList",
                "metadata": {},
                "items": [
                    {
                        "apiVersion": "v1",
                        "kind": "Event",
                        "metadata": {
                            "name": "owned-event",
                            "namespace": namespace,
                            "uid": "owned-event-uid",
                        },
                        "involvedObject": {"uid": f"owned-{namespace}-000", "namespace": namespace},
                        "type": "Warning",
                        "reason": "OwnedWarning",
                        "message": "token=hidden-pty-token",
                    }
                ],
            }
        else:
            self.send_error(404)
            return
        if self.server.shell_containers and (
            parsed.path.endswith("/pods") or "/pods/" in parsed.path
        ):
            values = payload["items"] if payload.get("kind") == "PodList" else [payload]
            for value in values:
                value["spec"]["containers"].extend(
                    {"name": name, "image": "synthetic"} for name in self.server.shell_containers
                )
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, *args):
        pass


class Server(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.fail_watches = threading.Event()
        self.stopping = threading.Event()
        self.quiet_watches = threading.Event()
        self.renewed = threading.Event()
        self.watch_versions = []
        self.watch_lock = threading.Lock()
        self.pod_events = queue.Queue()
        self.pod_table = threading.Event()
        self.shell_containers: tuple[str, ...] = ()
        self.pod_get_status = 200
        self.pod_requested = threading.Event()
        self.pod_gate = threading.Event()
        self.pod_gate.set()
        self.namespace_requested = threading.Event()
        self.namespace_gate = threading.Event()
        self.namespace_gate.set()
        self.impersonation = None
        self.identity_verified = threading.Event()
