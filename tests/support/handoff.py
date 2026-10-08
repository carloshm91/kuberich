"""Real native Textual/child handoff trials, also runnable from a fresh wheel."""

import json
import os
import signal
from pathlib import Path

import pytest

from tests.support.transports import TerminalTransport
from tests.terminal.pty_support import TerminalSession

CHILD = """
import os, signal, sys, termios, tty
from pathlib import Path
Path('handoff-child.pid').write_text(str(os.getpid()))
print('HANDOFF START', flush=True)
# An actual terminal read waits for the parent to give this group foreground
# ownership (SIGTTIN/SIGCONT). Starting the interpreter alone is not that boundary.
assert sys.stdin.readline().strip() == 'start'
assert os.tcgetpgrp(0) == os.getpgrp()
mode = termios.tcgetattr(0)
assert mode[3] & termios.ICANON and mode[3] & termios.ECHO
mode[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, mode)
signal.signal(signal.SIGINT, signal.SIG_DFL)
def resize(signum, frame):
    size = os.get_terminal_size(0)
    # A signal can interrupt buffered stdout while its lock is held.
    os.write(1, ('CHILD RESIZED ' + str(size.columns) + ' ' + str(size.lines) + '\\n').encode())
signal.signal(signal.SIGWINCH, resize)
def terminate(signum, frame):
    tty.setraw(0)
    raise SystemExit(0)
signal.signal(signal.SIGTERM, terminate)
print('HANDOFF READY', flush=True)
print('HANDOFF STDERR READY', file=sys.stderr, flush=True)
line = sys.stdin.readline().strip()
print('CHILD INPUT ' + line, flush=True)
tty.setraw(0)
raise SystemExit(7 if sys.argv[1] == 'failure' else 0)
"""

APP = """
import asyncio, logging, os, signal, sys
from pathlib import Path
from textual.binding import Binding
from kubetrol.config.schema import Settings
from kubetrol.domain.processes import capture_command, ProcessMode, ProcessPurpose
from kubetrol.errors import AppError
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.handoff import terminal_handoff

scenario = sys.argv[1]
directory = Path.cwd()
class HandoffApp(KubetrolApp):
    BINDINGS = [Binding('h', 'handoff', 'Handoff'), Binding('f12', 'probe', 'Probe', priority=True)]
    def __init__(self):
        super().__init__(Settings(read_only=scenario == 'read_only'), logging.getLogger('owned-handoff'))
        self.attempt = 0
        self.probes = 0
        self.owner = None
    def action_handoff(self):
        self.run_worker(self.handoff(), group='owned-handoff', exclusive=True)
    def action_probe(self):
        self.probes += 1
        # The resource renderer owns the status row and may repaint it after a
        # resize. Keep the input witness in a stable, otherwise unused title.
        # A distinct counter proves each probe was actually handled again.
        self.call_after_refresh(lambda: setattr(self.query_one('#command-bar'),
            'border_title', 'READY ' + str(self.size.width) + ' ' + str(self.size.height)
            + ' #' + str(self.probes)))
    async def handoff(self):
        self.owner = asyncio.current_task()
        self.attempt += 1
        argv = [sys.executable, str(directory/'owned-child.py'), scenario]
        if scenario == 'spawn_error' and self.attempt == 1:
            argv = [str(directory/'missing-executable')]
        spec = capture_command(argv, environment=dict(os.environ), directory=directory,
            mode=ProcessMode.FOREGROUND, purpose=ProcessPurpose.PLUGIN)
        try:
            result = await terminal_handoff(self, self.processes, spec)
        except asyncio.CancelledError:
            self._set_status('RETURN CANCELLED')
        except AppError:
            self._set_status('RETURN ERROR')
        else:
            self._set_status('RETURN ' + result.status.name)

app = HandoffApp()
(directory/'owned-parent.pid').write_text(str(os.getpid()))
def cancel(signum, frame):
    asyncio.get_running_loop().call_soon(app.owner.cancel)
signal.signal(signal.SIGUSR1, cancel)
app.run()
assert app.processes.active_count == 0
raise SystemExit(app.return_code or 0)
"""


def terminal_handoff_trial(
    python: str,
    directory: Path,
    scenario: str,
    *,
    name: str,
    transport: TerminalTransport | None = None,
) -> None:
    (directory / "owned-child.py").write_text(CHILD)
    script = directory / "owned-handoff.py"
    script.write_text(APP)
    attempts = 2 if scenario in {"success", "failure", "spawn_error"} else 1
    with TerminalSession(
        [python, str(script), scenario], directory, transport=transport
    ) as terminal:
        terminal.wait_for(b"Disconnected")
        probes = 0
        for attempt in range(attempts):
            marker = terminal.send(b"h")
            if scenario == "read_only" or (scenario == "spawn_error" and attempt == 0):
                terminal.wait_for(b"RETURN ERROR", since=marker)
                assert b"HANDOFF READY" not in terminal.transcript[marker:]
                continue
            terminal.wait_for(b"HANDOFF START", since=marker)
            terminal.send(b"start\n")
            terminal.wait_for(b"HANDOFF READY", since=marker)
            terminal.wait_for(b"HANDOFF STDERR READY", since=marker)
            if scenario in {"parent_shutdown", "hangup", "lost_ssh"}:
                parent = int((directory / "owned-parent.pid").read_text())
                if scenario == "lost_ssh":
                    assert transport is not None
                    transport.disconnect()
                else:
                    os.kill(parent, signal.SIGHUP if scenario == "hangup" else signal.SIGTERM)
                terminal.finish(expected=143 if scenario == "parent_shutdown" else 129)
                terminal.save_evidence(name)
                with pytest.raises(ProcessLookupError):
                    os.kill(int((directory / "handoff-child.pid").read_text()), 0)
                return
            if scenario == "cancel":
                parent = int((directory / "owned-parent.pid").read_text())
                os.kill(parent, signal.SIGUSR1)
                terminal.wait_for(b"RETURN CANCELLED", since=marker)
                continue
            if scenario == "ctrl_c":
                terminal.send(b"\x03")
                terminal.wait_for(b"RETURN SIGNALLED", since=marker)
                continue
            marker = terminal.resize(80, 25)
            terminal.wait_for(b"CHILD RESIZED 80 25", since=marker)
            marker = terminal.send(b"owned keyboard input\n")
            terminal.wait_for(b"CHILD INPUT owned keyboard input", since=marker)
            status = b"FAILED" if scenario == "failure" else b"SUCCEEDED"
            terminal.wait_for(b"RETURN " + status, since=marker)
            marker = terminal.resize(100, 30)
            terminal.wait_for_screen("Stay in pods", row=28, since=marker)
            terminal.send(b"\x1b[24~")
            probes += 1
            terminal.wait_for_screen(f"READY 100 30 #{probes}", since=marker)
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(name)
    evidence = Path(__file__).resolve().parents[2] / "artifacts/terminal" / f"{name}.json"
    assert json.loads(evidence.read_text())["terminal_mode_restored"]
    if scenario not in {"read_only"}:
        with pytest.raises(ProcessLookupError):
            os.kill(int((directory / "handoff-child.pid").read_text()), 0)
