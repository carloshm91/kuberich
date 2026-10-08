"""Real terminal review/confirmation against an owned API, including packaged launches."""

from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


def terminal_workload(command, directory, evidence, url, api, action="scale 3"):
    path = config(directory / "owned-workload-config", url, {"token": "synthetic-workload"})
    before = path.read_bytes()
    with TerminalSession(
        [*command, "--kubeconfig", str(path), "--command", "deploy team"], directory
    ) as terminal:
        terminal.wait_for_screen("deployments(team)[1]")
        terminal.send((":" + action + "\r").encode())
        terminal.wait_for_screen("captured workload")
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Review this exact target")
        assert not api.requests
        terminal.send(b"\r")
        terminal.wait_for_screen("deployments(team)[1]", absent=("captured workload",))
        assert not api.requests
        terminal.send((":" + action + "\r").encode())
        terminal.wait_for_screen("captured workload")
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Review this exact target")
        terminal.send(b"\x1b[Z\r")
        terminal.wait_for_screen("Controller has not observed")
        assert len(api.requests) == 1
        terminal.resize(40, 12)
        terminal.wait_for_screen("captured workload")
        terminal.resize(100, 30)
        terminal.send(b"\x1b")
        terminal.wait_for_screen("deployments(team)[1]", absent=("captured workload",))
        terminal.send(b":writes\r")
        terminal.wait_for_screen("API confirmed")
        assert "private-workload" not in "\n".join(terminal.screen.display)
        terminal.send(b"\x1b\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
        assert b"synthetic-workload" not in terminal.transcript
    assert path.read_bytes() == before
