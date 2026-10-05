"""Actual terminal inspection trial reused for installed artifacts."""

import threading

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_inspection(command, directory, *, evidence):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "inspection-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--readonly"], directory
        ) as terminal:
            terminal.wait_for(b"80 pods")
            marker = terminal.send(b"y")
            terminal.wait_for(b"kind: Pod", since=marker)
            terminal.wait_for(b"[REDACTED]", since=marker)
            marker = terminal.send(b"m")
            terminal.wait_for(b"managedFields", since=marker)
            marker = terminal.send(b"/containers\r")
            terminal.wait_for(b"Match 1/", since=marker)
            marker = terminal.send(b"\x19")
            terminal.wait_for(b"Redacted text copied", since=marker)
            marker = terminal.send(b"e")
            terminal.wait_for(b"OwnedWarning", since=marker)
            marker = terminal.send(b"d")
            terminal.wait_for(b"scheduling", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b"y")
            terminal.wait_for(b"YAML", since=marker)
            terminal.resize(100, 30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"80 pods", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"hidden-pty-env" not in terminal.transcript
            assert b"hidden-pty-token" not in terminal.transcript
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
