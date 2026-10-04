"""Actual CLI sessions in a PTY, including pending helper cancellation on quit."""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

from tests.terminal.pty_support import TerminalSession


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
        assert self.path.startswith("/api/v1/namespaces")
        assert self.headers.get("Authorization") == "Bearer synthetic-pty"
        body = json.dumps(
            {
                "items": [{"metadata": {"name": "default"}}, {"metadata": {"name": "team"}}],
                "metadata": {},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_connected_cli_context_namespace_retry_and_terminal_restoration(tmp_path: Path) -> None:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        tmp_path / "owned-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    original = path.read_bytes()
    try:
        with TerminalSession(
            [sys.executable, "-m", "kubetrol", "--kubeconfig", str(path)], tmp_path
        ) as terminal:
            terminal.wait_for(b"Session connected")
            assert b"synthetic-pty" not in terminal.transcript
            marker = terminal.send(b":ctx\r")
            terminal.wait_for(b"Choose context", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Cmd ", since=marker)
            marker = terminal.send(b":ns team\r")
            terminal.wait_for(b"Namespace: team", since=marker)
            terminal.send(b"q")
            terminal.finish()
            terminal.save_evidence("context-session")
        assert path.read_bytes() == original
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


def test_quitting_during_exec_helper_reaps_process_and_restores_tty(tmp_path: Path) -> None:
    script = tmp_path / "helper.py"
    pid_path = tmp_path / "helper-pid"
    script.write_text(
        "import os,time\nfrom pathlib import Path\nPath("
        + repr(str(pid_path))
        + ").write_text(str(os.getpid()))\ntime.sleep(30)"
    )
    path = config(
        tmp_path / "owned-config",
        "http://127.0.0.1:64321",
        {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1",
                "interactiveMode": "Never",
                "command": sys.executable,
                "args": [str(script)],
            }
        },
    )
    with TerminalSession(
        [sys.executable, "-m", "kubetrol", "--kubeconfig", str(path)], tmp_path
    ) as terminal:
        terminal.wait_for(b"Connecting")
        deadline = time.monotonic() + 3
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_path.exists()
        pid = int(pid_path.read_text())
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("context-helper-cancel")
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
