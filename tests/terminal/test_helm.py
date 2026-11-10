"""Actual source CLI Helm navigation and terminal restoration over owned fixtures."""

import json
import os
import sys
import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.support.helm import PRIVATE_VALUE, calls, fake_helm, storage, storage_list
from tests.support.resources import collection, legacy_roots
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.headers.get("Authorization") == "Bearer synthetic-helm-pty"
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        self.server.paths.append(parsed.path)
        if "watch" in query:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.server.stopping.wait(30)
            return
        if parsed.path == "/api/v1/namespaces":
            payload = {
                "metadata": {"resourceVersion": "opaque-namespaces"},
                "items": [
                    {
                        "metadata": {
                            "name": name,
                            "uid": "owned-" + name,
                            "resourceVersion": "opaque-" + name,
                        },
                        "status": {"phase": "Active"},
                    }
                    for name in ("team", "default")
                ],
            }
        elif parsed.path in legacy_roots():
            payload = legacy_roots()[parsed.path]
        elif "/secrets" in parsed.path:
            identities = [storage(revision) for revision in (1, 2, 3)]
            assert "PartialObjectMetadata" in self.headers.get("Accept", "")
            payload = (
                next(
                    (
                        item
                        for item in identities
                        if item["metadata"]["name"] == parsed.path.rsplit("/", 1)[-1]
                    ),
                    None,
                )
                if "/sh.helm.release" in parsed.path
                else storage_list(identities)
            )
        else:
            payload = collection()
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def do_POST(self):
        self.send_error(405)

    def log_message(self, *args):
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.stopping = threading.Event()
        self.paths = []


@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
def test_native_helm_sections_resize_refresh_and_quit_restore_terminal(tmp_path, size):
    settings, environment, _scenario, record = fake_helm(tmp_path)
    executable = tmp_path / "helm"
    executable.symlink_to(settings.executable)
    environment["PATH"] = str(tmp_path) + os.pathsep + environment["PATH"]
    server = _Server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kubeconfig = config(
        tmp_path / "helm-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-helm-pty"},
    )
    kubeconfig.chmod(0o600)
    original = kubeconfig.read_bytes()
    try:
        with TerminalSession(
            [
                sys.executable,
                "-m",
                "kuberich",
                "--kubeconfig",
                str(kubeconfig),
                "--readonly",
                "-n",
                "team",
                "--command",
                "helm",
            ],
            tmp_path,
            environment=environment,
            size=size,
        ) as terminal:
            terminal.wait_for_screen("Helm(team)[1]")
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("revision 3", since=marker)
            terminal.wait_for_screen("Revision: 3", since=marker)
            # State is the fifth document line, below the compact viewport.
            marker = terminal.send(b"\x1b[B" * 4)
            terminal.wait_for_screen("State: deployed", since=marker)
            marker = terminal.send(b"2")
            terminal.wait_for_screen("withheld", since=marker)
            terminal.resize(100, 30)
            marker = terminal.send(b"6")
            terminal.wait_for_screen("superseded", since=marker)
            terminal.send(b"\x1b[B\x1b[B\r")
            terminal.wait_for_screen("Selected revision 1")
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("Helm(team)[1]", since=marker, absent=("Revision: 3",))
            marker = terminal.send(b"\x1bOS")  # xterm F4
            terminal.wait_for_screen("Helm(team)[1]", since=marker)
            terminal.resize(*size)
            assert PRIVATE_VALUE.encode() not in terminal.transcript
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(f"helm-native-{size[0]}")
        assert not any("rollback" in item["argv"] for item in calls(record))
        assert any("get" in item["argv"] for item in calls(record))
        assert kubeconfig.read_bytes() == original
        assert server.paths and all(not path.startswith("/apis/apps") for path in server.paths)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
