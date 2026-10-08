"""Actual CLI container shell trials with an owned API and fake kubectl executable."""

import json
import os
import signal
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

import pytest

from tests.support.terminal_api import Server, config
from tests.support.transports import TerminalTransport
from tests.terminal.pty_support import TerminalSession

FAKE = r"""
import curses, json, os, select, signal, stat, sys, termios, time, traceback, tty
from pathlib import Path
directory=Path(__file__).resolve().parent.parent
def record_failure(kind,value,trace):
    (directory/'child-error.json').write_text(json.dumps({
        'kind':kind.__name__,'message':str(value)[:512],
        'frames':[{'file':Path(frame.filename).name,'line':frame.lineno}
                  for frame in traceback.extract_tb(trace)]}))
    sys.__excepthook__(kind,value,trace)
sys.excepthook=record_failure
scenario=(directory/'scenario').read_text()
args=sys.argv[1:]
path=Path(args[0].split('=',1)[1])
assert stat.S_IMODE(path.stat().st_mode)==0o600
data=json.loads(path.read_text())
assert data['current-context']=='kuberich-test-pty'
assert data['clusters'][0]['cluster']['server'].startswith('http://127.0.0.1:')
assert data['users'][0]['user']['token']=='synthetic-pty'
assert args[1:8]==['--context=kuberich-test-pty','--namespace=default','exec','--stdin','--tty','--container=worker','owned-pty-pod-079']
assert args[8:]==['--','sh']
with (directory/'exec-arguments.jsonl').open('a') as output:
    output.write(json.dumps(args)+'\n')
(directory/'caller-pid').write_text(str(os.getppid()))
(directory/'child-pid').write_text(str(os.getpid()))
signal.signal(signal.SIGINT,signal.SIG_DFL)
print('SHELL CHILD START',flush=True)
assert sys.stdin.readline().strip()=='start'
assert os.tcgetpgrp(0)==os.getpgrp()
mode=termios.tcgetattr(0)
assert mode[3]&termios.ICANON and mode[3]&termios.ECHO
mode[3]&=~termios.ECHO
termios.tcsetattr(0,termios.TCSANOW,mode)
if scenario=='fullscreen':
    def screen(window):
        window.addstr(0,0,'OWNED FULLSCREEN READY')
        window.refresh()
        while True:
            key=window.getch()
            if key==curses.KEY_RESIZE:
                height,width=window.getmaxyx()
                window.erase()
                window.addstr(0,0,'FULLSCREEN SIZE '+str(width)+' '+str(height))
                window.refresh()
            if key==ord('q'):
                return
    curses.wrapper(screen)
    tty.setraw(0)
    raise SystemExit(0)
def resize(signum,frame):
    size=os.get_terminal_size(0)
    # A resize may interrupt stdout's buffered READY write; avoid reentrant IO.
    os.write(1,('SHELL CHILD SIZE '+str(size.columns)+' '+str(size.lines)+'\n').encode())
signal.signal(signal.SIGWINCH,resize)
if scenario=='protocol':
    tty.setraw(0)
    os.write(1,b'\x1b[H\x1b[1;2;3H\x1b[1;2;3r\x1b[?6n\x1b[?5nPROTOCOL RECOVERED\r\n')
    deadline=time.monotonic()+5
    reply=bytearray()
    while not reply.endswith(b'R'):
        assert time.monotonic()<deadline,'cursor query deadline'
        if select.select([0],[],[],.1)[0]:
            reply.extend(os.read(0,64))
    assert bytes(reply)==b'\x1b[?1;1R',bytes(reply)
    os.write(1,b'\x1b]52;c;cHJpdmF0ZS1jbGlwYm9hcmQ=\x07\x1b]0;protocol-private-title\x1b\\')
    os.write(1,'PROTOCOL NORMAL café 你好🙂\r\n'.encode())
    os.write(2,b'PROTOCOL STDERR [red]literal[/red]\r\n')
    def line():
        value=bytearray()
        while True:
            data=os.read(0,1)
            if data in (b'\r',b'\n'):
                return value.decode()
            assert data and len(value)<100
            value.extend(data)
    assert line()=='alternate'
    os.write(1,b'\x1b[?1049h\x1b[H\x1b[2JPROTOCOL ALTERNATE\r\n')
    assert line()=='normal'
    os.write(1,b'\x1b[?1049l\r\nPROTOCOL RETURNED\r\n')
    assert line()=='exit'
    (directory/'protocol-result.json').write_text(json.dumps({'cursor_reply':bytes(reply).hex(),'normal_alternate_return':True,'unicode':True,'stdout_stderr':True}))
    raise SystemExit(0)
print('SHELL CHILD READY',flush=True)
line=sys.stdin.readline().strip()
print('SHELL INPUT '+line,flush=True)
tty.setraw(0)
raise SystemExit(127 if scenario=='shell_missing' else 1 if scenario=='failure' else 0)
"""


def terminal_shell(
    command: list[str],
    directory: Path,
    scenario: str,
    *,
    evidence: str,
    transport: TerminalTransport | None = None,
) -> None:
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    server.shell_containers = ("worker",)
    if scenario == "deleted":
        server.pod_get_status = 404
    if scenario == "early_close":
        server.pod_gate.clear()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "shell-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = path.read_bytes()
    binary = directory / "bin"
    binary.mkdir(exist_ok=True)
    if scenario != "missing":
        executable = binary / "kubectl"
        executable.write_text(f"#!{sys.executable}\n" + FAKE)
        executable.chmod(0o700)
    (directory / "scenario").write_text(scenario)
    wrapper = directory / "shell-launch.py"
    wrapper.write_text(
        "import os,sys\nfrom pathlib import Path\nos.environ['PATH']=str(Path.cwd()/'bin')\nos.execv(sys.argv[1],sys.argv[1:])\n"
    )
    flags = ["--kubeconfig", str(path), "--context", "kuberich-test-pty"]
    if scenario == "readonly":
        flags.append("--readonly")
    invocation = [sys.executable, str(wrapper), *command, *flags]
    try:
        with ExitStack() as stack:
            terminal = stack.enter_context(
                TerminalSession(invocation, directory, transport=transport)
            )
            terminal.wait_for(b"80 pods")
            marker = terminal.send(b"\x1b[1;5F")
            terminal.wait_for(b"owned-pty-pod-079", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for_screen("Containers", since=marker)
            terminal.wait_for_screen("worker", since=marker)
            terminal.send(b"\x1b[B")
            attempts = 2 if scenario in {"success", "failure", "early_close"} else 1
            for attempt in range(attempts):
                marker = terminal.send(b"s")
                if scenario == "early_close" and attempt == 0:
                    # Keep draining the PTY before waiting on the API gate;
                    # otherwise SSH output backpressure can stall the fixture.
                    terminal.wait_for_screen("KubeRich · Container shell")
                    assert server.pod_requested.wait(5), "Shell preflight did not reach its gate"
                    terminal.send(b"pending input\x1d")
                    terminal.wait_for_screen("Shell closed")
                    terminal.wait_for_screen("Containers")
                    assert not (directory / "exec-arguments.jsonl").exists()
                    server.pod_gate.set()
                    continue
                if scenario in {"missing", "readonly", "deleted"}:
                    expected = {
                        "missing": b"Install kubectl",
                        "readonly": b"Read-only mode",
                        "deleted": b"Pod unavailable",
                    }[scenario]
                    terminal.wait_for(expected, since=marker)
                    assert b"SHELL CHILD START" not in terminal.transcript[marker:]
                    if scenario in {"readonly", "deleted"}:
                        assert (
                            b"KubeRich shell | exit to return" not in terminal.transcript[marker:]
                        )
                    break
                terminal.wait_for_screen("SHELL CHILD START")
                entering = terminal.transcript[marker:]
                terminal.wait_for_screen("KubeRich · Container shell")
                terminal.wait_for_screen("Context: kuberich-test-pty")
                terminal.wait_for_screen("Pod: default/owned-pty-pod-079")
                terminal.wait_for_screen("Container: worker")
                terminal.wait_for_screen("SHELL CHILD START")
                assert b"\x1b[?1049l" not in entering
                assert b"\x1b[3J" not in entering
                terminal.send(b"start\n")
                if scenario == "protocol":
                    terminal.wait_for_screen("PROTOCOL RECOVERED")
                    terminal.wait_for_screen("PROTOCOL NORMAL café 你好🙂")
                    terminal.wait_for_screen("PROTOCOL STDERR [red]literal[/red]")
                    terminal.send(b"alternate\n")
                    terminal.wait_for_screen("PROTOCOL ALTERNATE")
                    for width, height in ((40, 12), (140, 44), (60, 18), (90, 28)):
                        terminal.resize(width, height)
                    terminal.wait_for_screen("SHELL CHILD SIZE 88 22")
                    terminal.resize(100, 30)
                    terminal.wait_for_screen("SHELL CHILD SIZE 98 24")
                    terminal.wait_for_screen("KubeRich · Container shell")
                    terminal.send(b"normal\n")
                    terminal.wait_for_screen("PROTOCOL RETURNED")
                    terminal.wait_for_screen("PROTOCOL NORMAL café 你好🙂")
                    terminal.send(b"exit\n")
                    terminal.wait_for_screen("Shell closed")
                    assert b"\x1b]52" not in terminal.transcript
                    assert b"protocol-private-title" not in terminal.transcript
                    result = json.loads((directory / "protocol-result.json").read_text())
                    assert result["cursor_reply"] == b"\x1b[?1;1R".hex()
                elif scenario == "fullscreen":
                    terminal.wait_for_screen("OWNED FULLSCREEN READY")
                    terminal.resize(80, 25)
                    terminal.wait_for_screen("FULLSCREEN SIZE 78 19")
                    terminal.wait_for_screen("Container: worker")
                    terminal.send(b"q")
                    terminal.wait_for(b"Shell closed", since=marker)
                else:
                    terminal.wait_for_screen("SHELL CHILD READY")
                    marker = terminal.resize(80, 25)
                    terminal.wait_for_screen("SHELL CHILD SIZE 78 19")
                    if scenario == "lost_ssh_tmux":
                        assert transport is not None and transport.tmux is not None
                        child = int((directory / "child-pid").read_text())
                        transport.disconnect()
                        terminal.finish()
                        terminal.save_evidence(evidence + "-detached")
                        terminal = stack.enter_context(
                            TerminalSession(invocation, directory, transport=transport)
                        )
                        terminal.wait_for_screen("SHELL CHILD READY")
                        assert int((directory / "child-pid").read_text()) == child
                        os.kill(child, 0)
                    if scenario in {"terminate", "hangup", "lost_ssh"}:
                        if scenario == "lost_ssh":
                            assert transport is not None
                            transport.disconnect()
                        else:
                            os.kill(
                                int((directory / "caller-pid").read_text()),
                                signal.SIGHUP if scenario == "hangup" else signal.SIGTERM,
                            )
                        terminal.finish(expected=143 if scenario == "terminate" else 129)
                        break
                    if scenario == "quit":
                        terminal.send(b"\x11")
                        terminal.finish()
                        break
                    if scenario == "close":
                        terminal.send(b"\x1d")
                        terminal.wait_for(b"Shell closed", since=marker)
                    elif scenario == "ctrl_c":
                        terminal.send(b"\x03")
                        terminal.wait_for(b"Shell interrupted", since=marker)
                    else:
                        terminal.send(b"owned selected worker\n")
                        terminal.wait_for(
                            b"Shell closed"
                            if scenario in {"success", "early_close", "lost_ssh_tmux"}
                            else b"preferences"
                            if scenario == "shell_missing"
                            else b"pods/exec",
                            since=marker,
                        )
                        terminal.wait_for(
                            b"preferences"
                            if scenario == "shell_missing"
                            else b"pods/exec"
                            if scenario == "failure"
                            else b"Shell closed",
                            since=marker,
                        )
                marker = terminal.resize(100, 30)
                terminal.wait_for_screen(
                    "Esc → Pods", row=28, since=marker, absent=("Container shell",)
                )
                terminal.send(b"\x1b[1;5H\x1b[1;5F")
            if scenario not in {"terminate", "quit", "hangup", "lost_ssh"}:
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen("Sort NAME", since=marker)
                marker = terminal.send(b":shell\r" if scenario != "readonly" else b"\r")
                terminal.wait_for_screen("Containers", since=marker)
                marker = terminal.send(b"\x1b")
                terminal.wait_for_screen("Sort NAME", since=marker)
                terminal.send(b"\x11")
                terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
        captured = directory / "exec-arguments.jsonl"
        if scenario not in {"missing", "readonly", "deleted"}:
            values = [json.loads(line) for line in captured.read_text().splitlines()]
            assert len(values) == (1 if scenario == "early_close" else attempts) and all(
                "--container=worker" in value for value in values
            )
            assert all(not Path(value[0].split("=", 1)[1]).exists() for value in values)
            with pytest.raises(ProcessLookupError):
                os.kill(int((directory / "child-pid").read_text()), 0)
        else:
            assert not captured.exists()
    finally:
        child_error = directory / "child-error.json"
        if child_error.exists():
            # Retain the owned fixture's actual failure even when repainting the
            # restored workspace has removed its traceback from the screen.
            retained = Path("artifacts/terminal")
            retained.mkdir(parents=True, exist_ok=True)
            (retained / f"{evidence}-child-error.json").write_bytes(child_error.read_bytes())
        server.pod_gate.set()
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
