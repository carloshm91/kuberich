"""Real keyboard bytes against the actual CLI and an owned HTTP log fixture."""

import threading

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_logs(command, directory, *, evidence, error_exit=False):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "log-viewer-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--readonly"], directory
        ) as terminal:
            terminal.wait_for(b"80 pods")
            if not error_exit:
                marker = terminal.send(b"\r")
                terminal.wait_for(b"Containers", since=marker)
                terminal.wait_for(b"Back to pods", since=marker)
                marker = terminal.send(b"\r")
            else:
                marker = terminal.send(b"l")
            terminal.wait_for(b"Logs", since=marker)
            terminal.wait_for(b"log-line-", since=marker)
            marker = terminal.send(b"p")
            terminal.wait_for(b"Paused", since=marker)
            terminal.send(b"gkj")
            marker = terminal.send(b"G")
            terminal.wait_for(b"Following", since=marker)
            marker = terminal.send(b"/log-line-00\r")
            terminal.wait_for(b"Matching line", since=marker)
            marker = terminal.send(b"\x19")
            terminal.wait_for(b"Retained redacted logs copied", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b"?")
            terminal.wait_for(b"Log controls", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(
                "Esc → Pods" if error_exit else "Esc → Containers",
                since=marker,
                absent=("Log controls",),
            )
            terminal.resize(100, 30)
            if error_exit:
                marker = terminal.send(b"v")
                terminal.wait_for(b"Previous container logs unavailable", since=marker)
                terminal.send(b"\x11")
            else:
                marker = terminal.send(b"\x1b")
                terminal.wait_for(b"Back to pods", since=marker)
                marker = terminal.send(b"\x1b")
                terminal.wait_for(b"80 pods", since=marker)
                terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"hidden-log-token" not in terminal.transcript
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
