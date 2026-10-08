"""Real terminal confirmation against an owned synchronous conditional PATCH server."""

import json
import threading
from contextlib import suppress
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from kubetrol.domain.registry import RESOURCE_ALIASES
from tests.support.standard import manifest, roots
from tests.support.standard_terminal import Handler
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


class MutationHandler(Handler):
    def reply(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(OSError):
            self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path)
        if path.path == "/api/v1" and not path.query:
            value = roots()[path.path]
            for resource in value["resources"]:
                if resource["name"] == "configmaps":
                    resource["verbs"].append("patch")
            self.reply(value)
        elif path.path == "/api/v1/namespaces/team/configmaps/owned-one":
            self.reply(self.server.value)
        elif path.path == "/api/v1/namespaces/team/configmaps" and not path.query:
            self.reply(
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMapList",
                    "metadata": {"resourceVersion": "opaque/list"},
                    "items": [self.server.value],
                }
            )
        else:
            super().do_GET()

    def do_PATCH(self):
        assert self.path == "/api/v1/namespaces/team/configmaps/owned-one"
        assert self.headers["Authorization"] == "Bearer synthetic-pty"
        assert self.headers["Content-Type"] == "application/json-patch+json"
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        for operation in body[:2]:
            if (
                operation["value"]
                != self.server.value["metadata"][operation["path"].split("/")[-1]]
            ):
                self.reply({}, 422)
                return
        self.server.value["metadata"]["annotations"] = body[2]["value"]
        self.server.value["metadata"]["resourceVersion"] = "opaque/version-8"
        self.reply(self.server.value)


def terminal_mutation(command, directory, evidence):
    server = ThreadingHTTPServer(("127.0.0.1", 0), MutationHandler)
    server.stopping = threading.Event()
    server.requests = []
    server.value = manifest(RESOURCE_ALIASES["cm"])
    server.value["metadata"]["resourceVersion"] = "opaque/version-7"
    server.value["metadata"]["annotations"] = {"preserved": "owned-original"}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "owned-write-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--command", "cm team"], directory
        ) as terminal:
            terminal.wait_for_screen("configmaps(team)[1]")
            terminal.send(b":annotate\r")
            terminal.wait_for_screen("Set annotation")
            terminal.send(b"example.io/review\towned-pty-value\r")
            terminal.wait_for_screen("Review the captured context")
            terminal.wait_for_screen("set example.io/review = owned-pty-value")
            assert not server.requests
            terminal.send(b"\r")  # Cancel has default focus; Enter sends no write.
            terminal.wait_for_screen("configmaps(team)[1]", absent=("Set annotation",))
            assert not server.requests
            terminal.send(b":annotate\r")
            terminal.wait_for_screen("Set annotation")
            terminal.send(b"example.io/review\towned-pty-value\r")
            terminal.wait_for_screen("Review the captured context")
            terminal.send(b"\x1b[Z\r")  # Shift+Tab from Cancel selects Confirm.
            terminal.wait_for_screen("Succeeded:")
            assert len(server.requests) == 1
            assert server.value["metadata"]["annotations"] == {
                "preserved": "owned-original",
                "example.io/review": "owned-pty-value",
            }, server.value["metadata"]["annotations"]
            assert server.value["data"]["config"] == "private-config-payload"
            terminal.send(b"\x1b")
            terminal.wait_for_screen("configmaps(team)[1]", absent=("Set annotation",))
            terminal.send(b":writes\r")
            terminal.wait_for_screen("last 32 operations")
            terminal.wait_for_screen("API confirmed")
            assert "owned-pty-value" not in "\n".join(terminal.screen.display)
            terminal.resize(40, 12)
            terminal.wait_for_screen("Writes")
            terminal.resize(100, 30)
            terminal.send(b"\x1b\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
