"""Owned source and installed-CLI generic resources in an actual native terminal."""

import json
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from tests.support.custom import GROUP, objects, roots, table


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        path = urlsplit(self.path)
        if "watch=true" in path.query:
            self.send_response(200)
            self.end_headers()
            with suppress(OSError):
                while not self.server.stopping.wait(0.03):
                    self.wfile.write(b"\n")
                    self.wfile.flush()
            return
        if path.path in roots():
            value = roots()[path.path]
        elif path.path == "/api/v1/namespaces":
            value = {
                "metadata": {"resourceVersion": "owned/ns"},
                "items": [{"metadata": {"name": name}} for name in ("team", "default")],
            }
        elif path.path.endswith("/events"):
            value = {"apiVersion": "v1", "kind": "EventList", "items": []}
        elif path.path.startswith("/apis/"):
            parts = path.path.split("/")
            namespaced = parts[4] == "namespaces"
            prefix = 7 if namespaced else 5
            values = objects(
                parts[2],
                parts[3],
                parts[6] if namespaced else parts[4],
                parts[5] if namespaced else "team",
            )
            if len(parts) > prefix:
                value = next(obj for obj in values if obj["metadata"]["name"] == parts[-1])
            elif "as=Table" in self.headers.get("Accept", ""):
                value = table(values, sensitive=True)
            else:
                value = {
                    "apiVersion": values[0]["apiVersion"],
                    "kind": values[0]["kind"] + "List",
                    "metadata": {"resourceVersion": "owned/list"},
                    "items": values,
                }
        else:
            value = {
                "apiVersion": "v1",
                "kind": "PodList",
                "metadata": {"resourceVersion": "owned/list"},
                "items": [],
            }
        body = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def log_message(self, *args):
        pass


def terminal_custom_views(command, directory, evidence):
    from tests.support.terminal_api import config
    from tests.terminal.pty_support import TerminalSession

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.stopping = threading.Event()
    owner = threading.Thread(target=server.serve_forever, daemon=True)
    owner.start()
    path = config(
        directory / "owned-custom-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [
                *command,
                "--kubeconfig",
                str(path),
                "--command",
                "resource widgets." + GROUP + "/v1beta1 team",
                "--readonly",
            ],
            directory,
        ) as terminal:
            terminal.wait_for_screen("widgets." + GROUP + "(team)[3]")
            terminal.wait_for_screen("Level")
            terminal.wait_for_screen("[REDACTED]")
            terminal.send(b"\r")
            terminal.wait_for_screen("Widget")
            terminal.send(b"y")
            terminal.wait_for_screen("raw-field")
            terminal.send(b"\x1b")
            terminal.wait_for_screen("widgets." + GROUP + "(team)[3]", absent=("kind: Widget",))
            marker = terminal.send(b":columns c2\r")
            terminal.wait_for_screen("columns updated", since=marker)
            marker = terminal.send(b":columns c99\r")
            terminal.wait_for_screen("view is retained", since=marker)
            marker = terminal.send(b":gdt\r")
            terminal.wait_for_screen("gadgets." + GROUP + "(cluster)[3]", since=marker)
            marker = terminal.send(b":wdg *\r")
            terminal.wait_for_screen("widgets." + GROUP + "(all)[3]", since=marker)
            terminal.resize(40, 12)
            terminal.wait_for_screen("NAME")
            terminal.resize(100, 30)
            marker = terminal.send(b":refresh\r")
            terminal.wait_for_screen("widgets." + GROUP + "(all)[3]", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
            assert b"synthetic-column-secret" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        owner.join(timeout=2)
        server.server_close()
        assert not owner.is_alive()
