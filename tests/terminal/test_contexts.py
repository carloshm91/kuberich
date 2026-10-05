"""Actual CLI sessions in a PTY, including pending helper cancellation on quit."""

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("authentication", ["token", "exec-null-env"])
def test_connected_cli_context_namespace_retry_and_terminal_restoration(
    tmp_path: Path, authentication: str
) -> None:
    server = Server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    user = {"token": "synthetic-pty"}
    if authentication == "exec-null-env":
        script = tmp_path / "provider.py"
        script.write_text(
            "import json\nprint("
            + repr(
                json.dumps(
                    {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "kind": "ExecCredential",
                        "status": {"token": "synthetic-pty"},
                    }
                )
            )
            + ")"
        )
        user = {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1beta1",
                "interactiveMode": "IfAvailable",
                "command": sys.executable,
                "args": [str(script)],
                "env": None,
            }
        }
    path = config(
        tmp_path / "owned-config",
        f"http://127.0.0.1:{server.server_port}",
        user,
    )
    original = path.read_bytes()
    try:
        with TerminalSession(
            [sys.executable, "-m", "kubetrol", "--kubeconfig", str(path)], tmp_path
        ) as terminal:
            terminal.wait_for(b"Live")
            terminal.wait_for(b"1 pods")
            assert b"synthetic-pty" not in terminal.transcript
            marker = terminal.send(b":ctx\r")
            terminal.wait_for(b"Choose context", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Cmd ", since=marker)
            for key in (b"n", b"\x1bOR", b"\x1b[13~"):
                marker = terminal.send(key)
                terminal.wait_for(b"Choose namespace", since=marker)
                marker = terminal.send(b"\x1b")
                terminal.wait_for(b"Cmd ", since=marker)
            marker = terminal.send(b":ns team\r")
            terminal.wait_for(b"Namespace: team", since=marker)
            marker = terminal.send(b":status\r")
            terminal.wait_for(b"Connection status", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Cmd ", since=marker)
            terminal.send(b"q")
            terminal.finish()
            terminal.save_evidence(f"context-session-{authentication}")
        assert path.read_bytes() == original
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()


def test_stale_live_recovery_scope_switch_and_quit_restore_real_terminal(tmp_path):
    server = Server()
    server.fail_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        tmp_path / "owned-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [sys.executable, "-m", "kubetrol", "--kubeconfig", str(path)], tmp_path
        ) as terminal:
            terminal.wait_for(b"Stale resource data")
            assert b"synthetic-pty" not in terminal.transcript
            server.fail_watches.clear()
            terminal.wait_for(b"Live")
            marker = terminal.send(b":ns team\r")
            terminal.wait_for(b"Namespace: team", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b":status\r")
            terminal.wait_for(b"Connection status", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Cmd ", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("workspace-stale-live-scope")
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
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
