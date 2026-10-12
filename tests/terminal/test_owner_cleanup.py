"""A failed terminal body must not abandon its direct child or diagnostic lock."""

import fcntl
import os
import signal
import sys
from contextlib import suppress

import pytest

from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("ignore_term", [False, True])
def test_failed_terminal_body_reaps_child_and_releases_lock(tmp_path, ignore_term):
    child = (
        "import fcntl,os,signal,time\n"
        "from pathlib import Path\n"
        "lock = open('owned-log.lock','w')\n"
        "fcntl.flock(lock,fcntl.LOCK_EX)\n"
        "Path('child.pid').write_text(str(os.getpid()))\n"
        "signal.signal(signal.SIGHUP,signal.SIG_IGN)\n"
        + (
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            if ignore_term
            else "signal.signal(signal.SIGTERM,lambda *_: time.sleep(0.5) or os._exit(0))\n"
        )
        + "os.write(1,b'owned-child-ready')\nwhile True: signal.pause()\n"
    )
    pid = None
    try:
        with (
            pytest.raises(RuntimeError, match="owned injected body failure"),
            TerminalSession([sys.executable, "-c", child], tmp_path) as terminal,
        ):
            terminal.wait_for(b"owned-child-ready")
            pid = int((tmp_path / "child.pid").read_text())
            raise RuntimeError("owned injected body failure")
        assert terminal.process.poll() == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        with (tmp_path / "owned-log.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for descriptor in (terminal.master, terminal.slave, terminal.completion_read):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        if pid is not None:
            with suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
