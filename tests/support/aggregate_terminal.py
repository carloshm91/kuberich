"""Public aggregate viewer keys in actual source and fresh-installed terminal sessions."""

import threading

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_aggregate_logs(command, directory, evidence):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    server.shell_containers = ("sidecar", "debug")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "aggregate-kubeconfig",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--readonly"], directory
        ) as terminal:
            terminal.wait_for(b"80 pods")
            marker = terminal.send(b"L")
            terminal.wait_for(b"Aggregated logs", since=marker)
            terminal.wait_for(b"3/8 readers", since=marker)
            terminal.wait_for(b"uid=owned-default-000", since=marker)
            terminal.resize(220, 30)
            marker = terminal.send(b"J")
            terminal.wait_for(b'"source":', since=marker)
            marker = terminal.send(b"t")
            terminal.wait_for(b'"timestamp":null', since=marker)
            marker = terminal.send(b"p")
            terminal.wait_for(b"Paused", since=marker)
            marker = terminal.send(b"/log-line-000\r")
            terminal.wait_for(b"Matching line", since=marker)
            marker = terminal.send(b"\x19")
            terminal.wait_for(b"Retained redacted logs copied", since=marker)
            marker = terminal.send(b"c")
            terminal.wait_for(b"Log sources", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for(b"excluded", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Aggregated logs", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b"?")
            terminal.wait_for(b"Log controls", since=marker)
            terminal.resize(100, 30)
            marker = terminal.send(b"\x1b")
            terminal.wait_for(b"Aggregated logs", since=marker)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("80 pods", since=marker, absent=("Aggregated logs",))
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert (
                b"hidden-log-token" not in terminal.transcript
                and b"synthetic-pty" not in terminal.transcript
            )
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
