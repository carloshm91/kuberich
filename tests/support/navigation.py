"""One actual terminal trial reused for source and freshly installed entry points."""

import threading
import time

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
            marker = terminal.send(b":ctx\r")
            terminal.wait_for_screen("contexts[1]", since=marker)
            terminal.wait_for_screen("AUTHINFO", since=marker)
            assert any("NAME" in line and "CLUSTER" in line for line in terminal.screen.display)
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("pods(", since=marker, absent=("contexts[",))
            terminal.wait_for(b"80 pods", since=marker)
            if initial_scope:
                terminal.wait_for_screen("Namespace: team")
            marker = terminal.send(b":p")
            terminal.wait_for_screen("po", since=marker)
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
            terminal.wait_for_screen("ns default" if initial_scope else "ns team", since=marker)
            marker = terminal.send(b"\t\r")
            terminal.wait_for_screen("Namespace: default" if initial_scope else "Namespace: team")
            terminal.wait_for(b"80 pods", since=marker)
            marker = terminal.send(b":back\r")
            terminal.wait_for_screen("Namespace: team" if initial_scope else "Namespace: default")
            terminal.wait_for(b"Live", since=marker)
            marker = terminal.send(b":forward\r")
            terminal.wait_for_screen("Namespace: default" if initial_scope else "Namespace: team")
            terminal.wait_for(b"Live", since=marker)
            marker = terminal.send(b":ns ")
            terminal.wait_for_screen("ns *", since=marker)
            marker = terminal.send(b"\x1b[A\r" if initial_scope else b"\x1b[B\r")
            terminal.wait_for_screen("Namespace: team" if initial_scope else "Namespace: default")
            terminal.wait_for(b"80 pods", since=marker)
            marker = terminal.send(b":ctx kub")
            terminal.wait_for_screen("kubetrol-test-pty", since=marker)
            server.namespace_requested.clear()
            server.namespace_gate.clear()
            marker = terminal.send(b"\t\r")
            deadline = time.monotonic() + 10
            while not server.namespace_requested.is_set():
                terminal._read()
                assert time.monotonic() < deadline, "Context command did not reach owned API"
            terminal.wait_for_screen("State: Connecting", since=marker)
            marker = terminal.send(b":ns\r")
            terminal.wait_for_screen("Connect to a context before selecting", since=marker)
            marker = len(terminal.transcript)
            server.namespace_gate.set()
            terminal.wait_for_screen("State: Connected", since=marker, absent=("Connecting",))
            scope = "team" if initial_scope else "default"
            terminal.wait_for_screen(f"pods({scope})[80] · live", since=marker)
            marker = terminal.send(b":ns\r")
            terminal.wait_for_screen("namespaces(all)[2]", since=marker)
            assert any(
                "NAME" in line and "STATUS" in line and "AGE" in line
                for line in terminal.screen.display
            )
            marker = terminal.send(b"/te\r")
            terminal.wait_for_screen("Filter active · 1/2 namespaces", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("Namespace: team", since=marker)
            terminal.wait_for_screen("Esc → Namespaces")
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("namespaces(all)[1]", since=marker)
            terminal.wait_for_screen("/ te")
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("namespaces(all)[2]", since=marker)
            marker = terminal.send(b"0")
            terminal.wait_for_screen("Namespace: All", since=marker)
            terminal.wait_for(b"80 pods", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b":c")
            terminal.wait_for_screen("context", since=marker)
            terminal.send(b"\x1b[B\x1b[B\t\x1b")
            terminal.resize(100, 30)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.namespace_gate.set()
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
