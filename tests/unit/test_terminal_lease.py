"""The TTY lease restores attributes and the signal mask, including failures."""

import os
import pty
import signal
import termios
from contextlib import nullcontext

import pytest

from kubetrol.adapters import terminal
from kubetrol.errors import AppError


def test_non_terminal_refused(tmp_path):
    with (
        (tmp_path / "file").open("w") as stream,
        pytest.raises(AppError, match="real"),
        terminal.TerminalLease(stream.fileno()),
    ):
        pass


def test_foreground_ownership_is_required(monkeypatch):
    monkeypatch.setattr(os, "isatty", lambda _: True)
    monkeypatch.setattr(os, "tcgetpgrp", lambda _: os.getpgrp() + 1)
    with pytest.raises(AppError, match="own"), terminal.TerminalLease(0):
        pass


@pytest.mark.parametrize("failure", [False, True])
def test_lease_restores_real_terminal_attributes_after_child_changes(monkeypatch, failure):
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    groups = []
    monkeypatch.setattr(os, "tcgetpgrp", lambda _: os.getpgrp())
    monkeypatch.setattr(os, "tcsetpgrp", lambda fd, group: groups.append(group))

    def gone(*args):
        raise ProcessLookupError

    monkeypatch.setattr(os, "killpg", gone)
    try:
        expectation = pytest.raises(RuntimeError) if failure else nullcontext()
        with expectation, terminal.TerminalLease(slave) as lease:
            lease.claim(123)
            changed = termios.tcgetattr(slave)
            changed[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(slave, termios.TCSANOW, changed)
            if failure:
                raise RuntimeError("fixture")
        assert termios.tcgetattr(slave) == original
        assert groups == [123, os.getpgrp()]
    finally:
        os.close(master)
        os.close(slave)


def test_job_control_failure_restores_the_signal_mask(monkeypatch):
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, set())

    def failed(*args):
        raise OSError("fixture")

    monkeypatch.setattr(os, "tcsetpgrp", failed)
    with pytest.raises(OSError):
        terminal._foreground(0, os.getpgrp())
    assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == previous
