"""Public aggregate viewer keys in actual source and fresh-installed terminal sessions."""

import base64
import json
import re
import threading

from kuberich.domain.clipboard import MAX_OSC52_BYTES
from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_aggregate_logs(command, directory, evidence):
    server = Server()
    # Three live readers retain exactly 80 initial records each. Hold further
    # owned follow output so copy success never races the OSC52 backend bound.
    # Existing server.stopping still interrupts every handler's wait on exit.
    server.log_follow_gate.clear()
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
            marker = terminal.resize(220, 30)
            terminal.wait_for_screen("240 retained", since=marker)
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
            copied = re.search(rb"\x1b\]52;c;([^\x07]+)\x07", terminal.transcript[marker:])
            assert copied is not None, "Copy notice requires an actual OSC52 clipboard frame"
            payload = base64.b64decode(copied[1], validate=True)
            assert len(payload) <= MAX_OSC52_BYTES
            records = [json.loads(line) for line in payload.splitlines()]
            assert len(records) == 240
            assert {record["source"]["container"] for record in records} == {
                "app",
                "sidecar",
                "debug",
            }
            assert all(
                record["source"]["uid"] == "owned-default-000"
                and record["source"]["namespace"] == "default"
                and "[REDACTED]" in record["payload"]
                for record in records
            )
            assert b"log-line-000" in payload and b"hidden-log-token" not in payload
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
