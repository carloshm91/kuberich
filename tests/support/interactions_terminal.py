"""Actual capital-G, filtering and bounded OSC52 receipts through owned terminals."""

import base64
import threading

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_interactions(command, directory, *, evidence, transport=None):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "interaction-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(path), "--readonly"], directory, transport=transport
        ) as terminal:
            terminal.wait_for_screen("80 pods")
            marker = terminal.send(b"G")
            terminal.wait_for_screen("owned-pty-pod-079", since=marker)
            marker = terminal.send(b":copy\r")
            # Receipt proves the exact framed payload reached the owned outer
            # terminal; it does not claim that a user's terminal accepted a paste.
            receipt = b"\x1b]52;c;" + base64.b64encode(b"owned-pty-pod-079") + b"\x07"
            terminal.wait_for(receipt, since=marker)
            marker = terminal.send(b"g:copy\r")
            terminal.wait_for(
                b"\x1b]52;c;" + base64.b64encode(b"owned-pty-pod-000") + b"\x07", since=marker
            )
            marker = terminal.send(b"/!re:pod-00\r")
            terminal.wait_for_screen("70/80 pods", since=marker)
            marker = terminal.send(b"\x1b/" + "fuzzy:你好".encode() + b"\r")
            terminal.wait_for_screen("0/80 pods", since=marker)
            terminal.resize(40, 12)
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen("pods(default)[80]", since=marker)
            terminal.resize(100, 30)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(2)
        server.server_close()
        assert not thread.is_alive()
