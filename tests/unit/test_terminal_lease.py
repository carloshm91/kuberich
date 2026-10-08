"""The TTY lease restores attributes and the signal mask, including failures."""

import errno
import os
import pty
import signal
import termios
from contextlib import nullcontext

import pytest

from kuberich.adapters import terminal
from kuberich.errors import AppError
from tests.support.terminal_modes import restored_modes


@pytest.mark.parametrize("dimensions", [(90, 28), (0, 28), (90, 0)])
def test_live_native_size_requires_positive_geometry(monkeypatch, dimensions):
    monkeypatch.setattr(os, "get_terminal_size", lambda _: os.terminal_size(dimensions))
    assert terminal.current_terminal_size() == (
        dimensions if all(value > 0 for value in dimensions) else None
    )


def test_unavailable_native_size_is_not_reported_as_a_new_layout(monkeypatch):
    def lost(descriptor):
        raise OSError("owned revoked terminal")

    monkeypatch.setattr(os, "get_terminal_size", lost)
    assert terminal.current_terminal_size() is None


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
        assert restored_modes(original, termios.tcgetattr(slave))
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


def test_restoration_failure_on_a_live_terminal_is_not_suppressed(monkeypatch):
    master, slave = pty.openpty()
    monkeypatch.setattr(os, "tcgetpgrp", lambda _: os.getpgrp())
    monkeypatch.setattr(os, "tcsetpgrp", lambda *_: (_ for _ in ()).throw(OSError("fixture")))
    try:
        with pytest.raises(OSError, match="fixture"), terminal.TerminalLease(slave):
            pass
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("code", [errno.EIO, errno.ENXIO, errno.ENOTTY])
def test_a_revoked_terminal_does_not_replace_the_original_cancellation(monkeypatch, code):
    master, slave = pty.openpty()
    monkeypatch.setattr(os, "tcgetpgrp", lambda _: os.getpgrp())
    monkeypatch.setattr(
        os, "tcsetpgrp", lambda *_: (_ for _ in ()).throw(OSError(errno.EIO, "gone"))
    )
    captured = termios.tcgetattr

    def inspect(descriptor):
        if descriptor == slave and master is None:
            raise termios.error(code, "owned revoked terminal")
        return captured(descriptor)

    monkeypatch.setattr(termios, "tcgetattr", inspect)
    try:
        with pytest.raises(RuntimeError, match="cancelled"), terminal.TerminalLease(slave):
            os.close(master)
            master = None
            raise RuntimeError("cancelled")
    finally:
        if master is not None:
            os.close(master)
        os.close(slave)


@pytest.mark.parametrize("code", [errno.EIO, errno.ENXIO, errno.ENOTTY])
def test_only_a_captured_revoked_tty_is_redirected(tmp_path, monkeypatch, code):
    master, slave = pty.openpty()
    file = (tmp_path / "unrelated").open("wb")
    captured = termios.tcgetattr

    def inspect(descriptor):
        if descriptor == slave and master is None:
            raise termios.error(code, "owned revoked terminal")
        return captured(descriptor)

    monkeypatch.setattr(termios, "tcgetattr", inspect)
    try:
        owner = terminal.RevokedTerminalOutput((slave, file.fileno()))
        before = os.fstat(slave)
        owner.discard_revoked()
        assert os.fstat(slave) == before
        os.close(master)
        master = None
        owner.discard_revoked()
        assert not os.isatty(slave)
        assert os.write(slave, b"final buffered shutdown bytes") == 29
        os.write(file.fileno(), b"preserved")
        owner.discard_revoked()
        assert (tmp_path / "unrelated").read_bytes() == b"preserved"
    finally:
        if master is not None:
            os.close(master)
        os.close(slave)
        file.close()


def test_closing_a_real_master_is_classified_by_the_slave_driver():
    master, slave = pty.openpty()
    try:
        owner = terminal.RevokedTerminalOutput((slave,))
        identity = os.fstat(slave)
        os.close(master)
        master = None
        try:
            termios.tcgetattr(slave)
            os.write(slave, b"")
        except (termios.error, OSError) as error:
            assert error.args[0] in (errno.EIO, errno.ENXIO, errno.ENOTTY)
            unavailable = True
        else:
            # Darwin can retain readable attributes on this unclaimed PTY.
            unavailable = False
        owner.discard_revoked()
        assert (os.fstat(slave) != identity) is unavailable
    finally:
        if master is not None:
            os.close(master)
        os.close(slave)


@pytest.mark.parametrize("code", [errno.EIO, errno.ENXIO, errno.ENOTTY])
def test_output_failure_with_readable_attributes_discards_only_the_captured_tty(monkeypatch, code):
    master, slave = pty.openpty()
    write = os.write
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    probes = []

    def unavailable(descriptor, data):
        if descriptor == slave and os.isatty(slave):
            probes.append(data)
            assert signal.SIGTTOU in signal.pthread_sigmask(signal.SIG_BLOCK, set())
            raise OSError(code, "owned hung-up output")
        return write(descriptor, data)

    try:
        original = termios.tcgetattr(slave)
        owner = terminal.RevokedTerminalOutput((slave,))
        monkeypatch.setattr(os, "write", unavailable)
        assert termios.tcgetattr(slave) == original
        owner.discard_revoked()
        assert probes == [b""]
        assert not os.isatty(slave)
        assert os.write(slave, b"buffered shutdown output") == 24
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == previous
    finally:
        os.close(master)
        os.close(slave)


def test_unexpected_output_probe_errors_restore_the_mask_and_preserve_the_descriptor(monkeypatch):
    master, slave = pty.openpty()
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    try:
        owner = terminal.RevokedTerminalOutput((slave,))
        original = os.fstat(slave)
        monkeypatch.setattr(
            os, "write", lambda *_: (_ for _ in ()).throw(OSError(errno.EPERM, "owned failure"))
        )
        with pytest.raises(OSError, match="owned failure"):
            owner.discard_revoked()
        assert os.fstat(slave) == original
        assert signal.pthread_sigmask(signal.SIG_BLOCK, set()) == previous
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.parametrize("closed", [False, True])
def test_output_descriptor_closed_or_replaced_after_capture_is_left_alone(tmp_path, closed):
    master, slave = pty.openpty()
    try:
        owner = terminal.RevokedTerminalOutput((slave,))
        if not closed:
            with (tmp_path / "replacement").open("wb") as replacement:
                os.dup2(replacement.fileno(), slave)
                owner.discard_revoked()
                os.write(slave, b"kept")
            assert (tmp_path / "replacement").read_bytes() == b"kept"
        else:
            os.close(slave)
            owner.discard_revoked()
    finally:
        os.close(master)
        if not closed:
            os.close(slave)


def test_unexpected_tty_inspection_errors_are_not_hidden(monkeypatch):
    def unavailable(descriptor):
        raise termios.error(errno.EINVAL, "unexpected")

    monkeypatch.setattr(termios, "tcgetattr", unavailable)
    with pytest.raises(termios.error, match="unexpected"):
        terminal._revoked(27)


def test_unexpected_output_descriptor_errors_are_not_hidden(monkeypatch):
    master, slave = pty.openpty()
    try:
        owner = terminal.RevokedTerminalOutput((slave,))
        monkeypatch.setattr(
            os, "fstat", lambda _: (_ for _ in ()).throw(OSError(errno.EPERM, "denied"))
        )
        with pytest.raises(OSError, match="denied"):
            owner.discard_revoked()
    finally:
        os.close(master)
        os.close(slave)


def test_screen_presentation_drains_partial_writes_without_erasing_scrollback(monkeypatch):
    received = bytearray()

    def partial(descriptor, data):
        assert descriptor == 27
        chunk = data[:3]
        received.extend(chunk)
        return len(chunk)

    monkeypatch.setattr(os, "write", partial)
    terminal.TerminalLease(27).present("Owned heading\n\n")
    assert received == b"\x1b[H\x1b[2JOwned heading\n\n"
    assert b"\x1b[3J" not in received


@pytest.mark.parametrize("no_progress", [False, True])
def test_screen_write_failures_are_actionable_without_raw_error_values(monkeypatch, no_progress):
    def failed(descriptor, data):
        if no_progress:
            return 0
        raise OSError("opaque-sensitive-terminal-value")

    monkeypatch.setattr(os, "write", failed)
    with pytest.raises(AppError, match="Check the terminal") as error:
        terminal.TerminalLease(27).present("Owned heading\n")
    assert "opaque-sensitive-terminal-value" not in str(error.value)
