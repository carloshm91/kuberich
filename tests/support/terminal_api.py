"""Shared owned HTTP API and kubeconfig fixtures for actual CLI/install PTYs."""

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

from tests.support.pods import NOW, pod
from tests.support.resources import collection, item, legacy_roots
from tests.support.watches import bookmark, frame


def config(path: Path, server: str, user: dict) -> Path:
    data = {
        "current-context": "kubetrol-test-pty",
        "contexts": [
            {"name": "kubetrol-test-pty", "context": {"cluster": "owned", "user": "owned"}}
        ],
        "clusters": [{"name": "owned", "cluster": {"server": server}}],
        "users": [{"name": "owned", "user": user}],
    }
    path.write_text(yaml.safe_dump(data))
    return path


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
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
            payload = {
                "items": [{"metadata": {"name": "default"}}, {"metadata": {"name": "team"}}],
                "metadata": {},
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
        else:
            self.send_error(404)
            return
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
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
