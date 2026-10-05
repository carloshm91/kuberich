"""One actual terminal trial reused for source and freshly installed entry points."""

import threading

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_navigation(command, directory, *, evidence, initial_scope=False):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "navigation-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    arguments = [
        *command,
        "--kubeconfig",
        str(path),
        "--readonly",
        "--command",
        "ns team" if initial_scope else "po",
    ]
    try:
        with TerminalSession(arguments, directory) as terminal:
            terminal.wait_for(b"owned-pty-pod-000")
            terminal.wait_for(b"80 pods")
            if initial_scope:
                terminal.wait_for(b"Namespace: team")
            marker = terminal.send(b":p")
            terminal.wait_for(b"Tab completes", since=marker)
            terminal.send(b"\t\r")
            marker = terminal.send(b"/pod-00\r")
            terminal.wait_for(b"10/80 pods", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"80 pods", since=marker)
            marker = terminal.send(b"/re:[\r")
            terminal.wait_for(b"Invalid regex", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"80 pods", since=marker)
            marker = terminal.send(b":ns de" if initial_scope else b":ns te")
            terminal.wait_for(b"Tab completes", since=marker)
            marker = terminal.send(b"\t\r")
            terminal.wait_for(
                b"Namespace: default" if initial_scope else b"Namespace: team", since=marker
            )
            terminal.wait_for(b"80 pods", since=marker)
            marker = terminal.send(b":back\r")
            terminal.wait_for(
                b"Namespace: team" if initial_scope else b"Namespace: default", since=marker
            )
            terminal.wait_for(b"Live", since=marker)
            marker = terminal.send(b":forward\r")
            terminal.wait_for(
                b"Namespace: default" if initial_scope else b"Namespace: team", since=marker
            )
            terminal.wait_for(b"Live", since=marker)
            marker = terminal.send(b":ctx kub")
            terminal.wait_for(b"kubetrol-test-pty", since=marker)
            marker = terminal.send(b"\t\r")
            terminal.wait_for(b"Live", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b":c")
            terminal.wait_for(b"Tab completes", since=marker)
            terminal.send(b"\x1b[B\x1b[B\t\x1b")
            terminal.resize(100, 30)
            terminal.send(b"\x11")
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
