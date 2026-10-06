"""Actual CLI container shell trials with an owned API and fake kubectl executable."""

import json
import os
import signal
import sys
import threading
from pathlib import Path

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession

FAKE = """
import curses, json, os, signal, stat, sys, termios, tty
from pathlib import Path
directory=Path(__file__).resolve().parent.parent
scenario=(directory/'scenario').read_text()
args=sys.argv[1:]
path=Path(args[0].split('=',1)[1])
assert stat.S_IMODE(path.stat().st_mode)==0o600
data=json.loads(path.read_text())
assert data['current-context']=='kubetrol-test-pty'
assert data['clusters'][0]['cluster']['server'].startswith('http://127.0.0.1:')
assert data['users'][0]['user']['token']=='synthetic-pty'
assert args[1:8]==['--context=kubetrol-test-pty','--namespace=default','exec','--stdin','--tty','--container=worker','owned-pty-pod-079']
assert args[8:]==['--','sh']
with (directory/'exec-arguments.jsonl').open('a') as output:
    output.write(json.dumps(args)+'\\n')
(directory/'caller-pid').write_text(str(os.getppid()))
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
    os.write(1,('SHELL CHILD SIZE '+str(size.columns)+' '+str(size.lines)+'\\n').encode())
signal.signal(signal.SIGWINCH,resize)
print('SHELL CHILD READY',flush=True)
line=sys.stdin.readline().strip()
print('SHELL INPUT '+line,flush=True)
tty.setraw(0)
raise SystemExit(127 if scenario=='shell_missing' else 1 if scenario=='failure' else 0)
"""


def terminal_shell(command: list[str], directory: Path, scenario: str, *, evidence: str) -> None:
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    server.shell_containers = ("worker",)
    if scenario == "deleted":
        server.pod_get_status = 404
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
    flags = ["--kubeconfig", str(path), "--context", "kubetrol-test-pty"]
    if scenario == "readonly":
        flags.append("--readonly")
    try:
        with TerminalSession(
            [sys.executable, str(wrapper), *command, *flags], directory
        ) as terminal:
            terminal.wait_for(b"80 pods")
            marker = terminal.send(b"\x1b[1;5F")
            terminal.wait_for(b"owned-pty-pod-079", since=marker)
            marker = terminal.send(b"\r")
            terminal.wait_for(b"Containers", since=marker)
            terminal.wait_for(b"worker", since=marker)
            terminal.send(b"\x1b[B")
            attempts = 2 if scenario in {"success", "failure"} else 1
            for _ in range(attempts):
                marker = terminal.send(b"s")
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
                            b"Kubetrol shell | exit to return" not in terminal.transcript[marker:]
                        )
                    break
                terminal.wait_for(b"SHELL CHILD START", since=marker)
                entering = terminal.transcript[marker:]
                heading = b"\x1b[H\x1b[2JKubetrol shell | exit to return"
                assert entering.index(heading) < entering.index(b"SHELL CHILD START")
                assert b"Context: kubetrol-test-pty" in entering
                assert b"Pod: default/owned-pty-pod-079" in entering
                assert b"Container: worker" in entering
                assert b"\x1b[3J" not in entering
                terminal.send(b"start\n")
                if scenario == "fullscreen":
                    terminal.wait_for(b"OWNED FULLSCREEN READY", since=marker)
                    marker = terminal.resize(80, 25)
                    terminal.wait_for(b"FULLSCREEN SIZE 80 25", since=marker)
                    terminal.send(b"q")
                    terminal.wait_for(b"Shell closed", since=marker)
                else:
                    terminal.wait_for(b"SHELL CHILD READY", since=marker)
                    marker = terminal.resize(80, 25)
                    terminal.wait_for(b"SHELL CHILD SIZE 80 25", since=marker)
                    if scenario == "terminate":
                        os.kill(int((directory / "caller-pid").read_text()), signal.SIGTERM)
                        terminal.finish(expected=143)
                        break
                    if scenario == "ctrl_c":
                        terminal.send(b"\x03")
                        terminal.wait_for(b"Shell interrupted", since=marker)
                    else:
                        terminal.send(b"owned selected worker\n")
                        terminal.wait_for(b"SHELL INPUT owned selected worker", since=marker)
                        terminal.wait_for(
                            b"preferences"
                            if scenario == "shell_missing"
                            else b"pods/exec"
                            if scenario == "failure"
                            else b"Shell closed",
                            since=marker,
                        )
                terminal.resize(100, 30)
                terminal.send(b"\x1b[1;5H\x1b[1;5F")
            if scenario != "terminate":
                marker = terminal.send(b"\x1b")
                terminal.wait_for(b"Sort NAME", since=marker)
                marker = terminal.send(b":shell\r" if scenario != "readonly" else b"\r")
                terminal.wait_for(b"Containers", since=marker)
                marker = terminal.send(b"\x1b")
                terminal.wait_for(b"Sort NAME", since=marker)
                terminal.send(b"\x11")
                terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
        captured = directory / "exec-arguments.jsonl"
        if scenario not in {"missing", "readonly", "deleted"}:
            values = [json.loads(line) for line in captured.read_text().splitlines()]
            assert len(values) == attempts and all(
                "--container=worker" in value for value in values
            )
            assert all(not Path(value[0].split("=", 1)[1]).exists() for value in values)
        else:
            assert not captured.exists()
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
