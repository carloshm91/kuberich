"""Owned synchronous HTTP fixture for real source/installed standard-view terminals."""

import json
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from kubetrol.domain.registry import STANDARD_RESOURCES
from tests.support.standard import api, manifest, roots


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        path = urlsplit(self.path)
        if "watch=true" in path.query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            with suppress(OSError):
                while not self.server.stopping.wait(0.03):
                    # Empty lines are ignored, keeping the fixture connection observable.
                    self.wfile.write(b"\n")
                    self.wfile.flush()
            return
        if path.path == "/api/v1/namespaces":
            value = {
                "metadata": {"resourceVersion": "opaque/ns"},
                "items": [{"metadata": {"name": name}} for name in ("team", "default")],
            }
        elif path.path in roots():
            value = roots()[path.path]
        elif path.path.endswith("/events"):
            value = {"apiVersion": "v1", "kind": "EventList", "metadata": {}, "items": []}
        else:
            value = None
            for definition in STANDARD_RESOURCES:
                resource = api(definition)
                namespace = (
                    path.path.split("/namespaces/")[1].split("/")[0]
                    if "/namespaces/" in path.path
                    else None
                )
                prefix = resource.path(namespace if resource.namespaced else None)
                if path.path == prefix:
                    value = {
                        "apiVersion": resource.api_version,
                        "kind": resource.kind + "List",
                        "metadata": {"resourceVersion": "opaque/list"},
                        "items": [manifest(definition, namespace=namespace or "team")],
                    }
                    break
                if path.path == prefix + "/owned-one":
                    value = manifest(definition, namespace=namespace or "team")
                    break
            if value is None:
                self.send_error(404)
                return
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def log_message(self, *args):
        pass


def terminal_standard_views(command, directory, evidence):
    from tests.support.terminal_api import config
    from tests.terminal.pty_support import TerminalSession

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.stopping = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "owned-standard-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--command", "deploy team", "--readonly"],
            directory,
        ) as terminal:
            terminal.wait_for_screen("deployments(team)[1]")
            terminal.wait_for_screen("UPDATED")
            terminal.wait_for_screen("10")
            marker = terminal.send(b":svc\r")
            terminal.wait_for_screen("services(team)[1]", since=marker)
            terminal.wait_for_screen("CLUSTER-IP")
            terminal.send(b"\r")
            terminal.wait_for_screen("Service")
            terminal.send(b"\x1b")
            terminal.wait_for_screen("services(team)[1]", absent=("kind: Service",))
            marker = terminal.send(b":pv\r")
            terminal.wait_for_screen("persistentvolumes(cluster)[1]", since=marker)
            terminal.wait_for_screen("2Gi")
            terminal.resize(40, 12)
            marker = terminal.send(b":sec team\r")
            terminal.wait_for_screen("secrets(team)[1]", since=marker)
            terminal.wait_for_screen("Opaque")
            terminal.send(b"y")
            terminal.wait_for_screen("kind: Secret")
            terminal.resize(100, 30)
            terminal.wait_for_screen("[REDACTED]")
            terminal.send(b"\x1b")
            terminal.resize(100, 30)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
            assert b"private-secret-payload" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
