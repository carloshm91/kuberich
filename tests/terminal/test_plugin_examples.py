"""Actual keyboard input and restoration for the original interactive definition."""

import json
import os
import shlex
import sys
import threading
from pathlib import Path

import yaml

from tests.support.plugin_examples import EXAMPLES, executable
from tests.support.plugins_terminal import close_plugin_view
from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def test_original_shell_example_uses_literal_container_and_restores_terminal(tmp_path):
    executable(tmp_path)
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "plugins": {"schema_version": 1, "locations": [str(EXAMPLES)]},
            }
        )
    )
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        kubeconfig = config(
            tmp_path / "kubeconfig",
            f"http://127.0.0.1:{server.server_port}",
            {"token": "synthetic-pty"},
        )
        original = kubeconfig.read_bytes()
        with TerminalSession(
            [
                sys.executable,
                "-m",
                "kuberich",
                "--config",
                str(preferences),
                "--kubeconfig",
                str(kubeconfig),
                "--context",
                "kuberich-test-pty",
            ],
            tmp_path,
            environment={
                "PATH": str(tmp_path) + os.pathsep + os.defpath,
                "EXAMPLE_RECEIPT": str(tmp_path / "receipt"),
            },
        ) as terminal:
            terminal.wait_for_screen("80 pods")
            hostile = f"app ; $(touch {shlex.quote(str(tmp_path / 'NEVER'))})"
            for _ in range(2):
                marker = terminal.send(b":plugin pod-shell\r")
                terminal.wait_for_screen("Exact container name", since=marker)
                # Cancel -> Review (Run is disabled) -> the required input.
                review = terminal.send(b"\x1b[Z\x1b[Z" + hostile.encode() + b"\t\r")
                terminal.wait_for_screen("Review complete", since=review)
                run = terminal.send(b"\x1b[Z\r")
                terminal.wait_for(b"EXAMPLE_SHELL_READY", since=run)
                reply = terminal.send(b"owned-example\n")
                terminal.wait_for(b"EXAMPLE_INPUT owned-example", since=reply)
                terminal.wait_for_screen("Succeeded", since=run)
                close_plugin_view(terminal)
                receipt = json.loads((tmp_path / "receipt-shell").read_text())
                assert "--container=" + hostile in receipt["argv"]
                assert not (tmp_path / "NEVER").exists()
                assert not Path(receipt["private"]).exists()
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("original-plugin-example")
            assert b"synthetic-pty" not in terminal.transcript
        assert kubeconfig.read_bytes() == original
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        assert not thread.is_alive()
