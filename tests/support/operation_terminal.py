"""Native keyboard-only resource review, explicit count and terminal restoration."""

from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


def terminal_operation(command, directory, evidence, url, api, action="trigger", alias="cj"):
    path = config(directory / "owned-operation-config", url, {"token": "synthetic-operation"})
    before = path.read_bytes()
    table = "cronjobs" if alias == "cj" else "configmaps"
    with TerminalSession(
        [*command, "--kubeconfig", str(path), "--command", alias + " team"], directory
    ) as terminal:
        terminal.wait_for_screen(table + "(team)[1]")
        terminal.send((":" + action + "\r").encode())
        terminal.wait_for_screen("captured resources")
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Review this exact operation")
        assert not api.requests
        terminal.send(b"\r")
        terminal.wait_for_screen(table + "(team)[1]", absent=("captured resources",))
        assert not api.requests
        terminal.send((":" + action + "\r").encode())
        terminal.wait_for_screen("captured resources")
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Review this exact operation")
        if action == "delete":
            terminal.send(b"\x1b[Z\x1b[Z\x1b[ZDELETE 1\t\t\r")
            terminal.wait_for_screen("Captured resource is absent")
        else:
            terminal.send(b"\x1b[Z\r")
            terminal.wait_for_screen("created-job-uid")
        assert len(api.requests) == 1
        terminal.resize(40, 12)
        terminal.wait_for_screen("captured resources")
        terminal.resize(100, 30)
        terminal.send(b"\x1b")
        terminal.wait_for_screen(table + "(team)[1]", absent=("captured resources",))
        terminal.send(b":writes\r")
        terminal.wait_for_screen("Writes · last 32")
        terminal.wait_for_screen("Captured resource" if action == "delete" else "created-job-uid")
        assert "private-template" not in "\n".join(terminal.screen.display)
        terminal.send(b"\x1b\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
        assert b"synthetic-operation" not in terminal.transcript
    assert path.read_bytes() == before
