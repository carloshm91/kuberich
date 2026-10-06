"""A real CLI displays and navigates live pod rows and restores its terminal."""

import sys
import threading

from tests.support.pods import pod
from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def test_live_pod_navigation_update_sort_scope_and_resize_restore_terminal(tmp_path):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
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
            terminal.wait_for(b"owned-pty-pod-000")
            terminal.wait_for(b"80 pods")
            terminal.send(b"\x1b[6~")
            terminal.send(b"sss")
            terminal.wait_for(b"Sort RESTARTS")
            update = pod(
                "owned-pty-pod-000",
                namespace="default",
                uid="owned-default-000",
                restarts=1000,
                ready=False,
            )
            update["metadata"]["resourceVersion"] = "owned/modified"
            update["status"]["containerStatuses"][0]["state"] = {
                "waiting": {"reason": "CrashLoopBackOff"}
            }
            server.pod_events.put({"type": "MODIFIED", "object": update})
            marker = terminal.send(b"S\x1b[1;5H")
            terminal.wait_for(b"CrashLoopBackOff", since=marker)
            terminal.wait_for(b"1000", since=marker)
            marker = terminal.send(b":ns team\r")
            terminal.wait_for_screen("Namespace: team")
            terminal.wait_for(b"team      ", since=marker)
            # Scope changes preserve the fallback cursor; explicitly request the top.
            terminal.send(b"\x1b[1;5H")
            terminal.wait_for(b"owned-pty-pod-079", since=marker)
            terminal.resize(40, 12)
            terminal.send(b"\x1b[F")
            terminal.wait_for(b"AGE")
            terminal.resize(100, 30)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("live-pod-table")
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
