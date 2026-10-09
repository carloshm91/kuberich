"""Actual inner/outer PTY attach endings, without live-cluster credentials."""

import json
import os
import signal
import sys

from tests.support.connections import catalog_fixture
from tests.terminal.pty_support import TerminalSession

CHILD = r"""
import json,os,stat,sys,time,tty
from pathlib import Path
root=Path(__file__).parent
(root/'pid').write_text(str(os.getpid()))
(root/'caller-pid').write_text(str(os.getppid()))
(root/'argv').write_text(json.dumps(sys.argv[1:]))
configuration=Path(sys.argv[1].split('=',1)[1])
assert stat.S_IMODE(configuration.stat().st_mode)==0o600
tty.setraw(0)
os.write(1,b'OWNED ATTACH READY\r\n')
mode=os.environ['ATTACH_CASE']
if mode in ('eof','failure'):
 time.sleep(.5);sys.exit(23 if mode=='failure' else 0)
data=b''
while True:
 data=(data+os.read(0,4096))[-4096:]
 if b'\x03' in data:sys.exit(130)
 if b'\x10\x11' in data:sys.exit(0)
"""


def terminal_attach(command, directory, url, scenario, evidence):
    catalog_fixture(directory, url)
    config = directory / "fixture-config"
    before = config.read_bytes()
    tools = directory / "tools"
    tools.mkdir()
    binary = tools / "kubectl"
    binary.write_text(f"#!{sys.executable}\n" + CHILD)
    binary.chmod(0o700)
    environment = {**os.environ, "PATH": str(tools), "ATTACH_CASE": scenario}
    with TerminalSession(
        [
            *command,
            "--kubeconfig",
            str(config),
            "--context",
            "kuberich-test-one",
            "--namespace",
            "team",
            "--write",
        ],
        directory,
        environment=environment,
    ) as terminal:
        terminal.wait_for_screen("pods(team)[1]")
        terminal.send(b":attach\r")
        terminal.wait_for_screen("containers(team/api)[1]")
        terminal.send(b"a")
        terminal.wait_for_screen("OWNED ATTACH READY")
        arguments = json.loads((tools / "argv").read_text())
        path = arguments[0].split("=", 1)[1]
        pid = int((tools / "pid").read_text())
        assert arguments[3:] == [
            "attach",
            "--stdin",
            "--tty",
            "--container=app",
            "--detach-keys=ctrl-p,ctrl-q",
            "--pod-running-timeout=1s",
            "api",
        ]
        if scenario == "interrupt":
            terminal.send(b"\x03")
        elif scenario == "detach":
            terminal.send(b"\x10\x11")
        elif scenario == "close":
            terminal.send(b"\x1d")
        elif scenario == "terminate":
            os.kill(int((tools / "caller-pid").read_text()), signal.SIGTERM)
        elif scenario == "quit":
            terminal.send(b"\x11")
        if scenario not in ("terminate", "quit"):
            terminal.wait_for_screen(
                "kubectl attach failed (exit 23)"
                if scenario == "failure"
                else "Attach interrupted"
                if scenario == "interrupt"
                else "containers(team/api)[1]"
            )
            if scenario == "eof":
                terminal.wait_for_screen("Attach closed")
            terminal.send(b"\x1b")
            terminal.wait_for_screen("pods(team)[1]")
            terminal.send(b"\x11")
        terminal.finish(expected=143 if scenario == "terminate" else 0)
        terminal.save_evidence(evidence)
    assert config.read_bytes() == before and not os.path.exists(path)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pass
    else:
        raise AssertionError("Owned attach child survived return/exit")
