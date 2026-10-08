"""Deterministic PTY syscall failure/backpressure boundaries and child startup."""

import errno
import os
import runpy
from pathlib import Path

import pytest

from kuberich.adapters import pty as module
from kuberich.adapters import pty_child
from kuberich.errors import AppError


@pytest.mark.asyncio
async def test_partial_writes_backpressure_io_failures_and_eof(monkeypatch):
    endpoint = module.PtyEndpoint(10, 4)
    original_write = os.write
    calls = 0

    def write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return 2
        if calls == 2:
            raise BlockingIOError()
        return len(data)

    monkeypatch.setattr(module.os, "write", write)
    endpoint.write(b"abcde")
    assert bytes(endpoint.pending) == b"cde"
    endpoint._writable()
    assert not endpoint.pending
    monkeypatch.setattr(module.os, "write", lambda *_: 0)
    endpoint.write(b"x")
    with pytest.raises(AppError, match="write"):
        await endpoint.read()
    endpoint.close()
    monkeypatch.setattr(module.os, "write", original_write)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error", [BlockingIOError(), OSError(errno.EIO, "eof"), OSError(errno.EBADF, "failure"), None]
)
async def test_reader_eof_blocking_and_safe_failure(error, monkeypatch):
    endpoint = module.PtyEndpoint(10, 4)

    def read(*_):
        if error is not None:
            raise error
        return b""

    monkeypatch.setattr(module.os, "read", read)
    endpoint._readable()
    if isinstance(error, BlockingIOError):
        assert not endpoint.eof
    elif isinstance(error, OSError) and error.errno != errno.EIO:
        with pytest.raises(AppError, match="read"):
            await endpoint.read()
        with pytest.raises(AppError, match="read"):
            await endpoint.read()
    else:
        assert await endpoint.read() == b""
    endpoint.close()


@pytest.mark.asyncio
async def test_allocation_setup_failure_closes_both_fds(monkeypatch):
    captured = []
    original = module.pty.openpty

    def allocate():
        pair = original()
        captured.extend(pair)
        return pair

    monkeypatch.setattr(module.pty, "openpty", allocate)

    def fail(*_):
        raise OSError("owned initialization failure")

    monkeypatch.setattr(module.os, "set_blocking", fail)
    with pytest.raises(OSError):
        module.PtyEndpoint(10, 4)
    for descriptor in captured:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_isolated_child_acquires_own_terminal_before_literal_exec(monkeypatch):
    calls = []
    monkeypatch.setattr(pty_child.fcntl, "ioctl", lambda *args: calls.append(("claim", args)))
    monkeypatch.setattr(pty_child.os, "tcsetpgrp", lambda *args: calls.append(("foreground", args)))
    monkeypatch.setattr(pty_child.sys, "argv", ["launcher", "/owned/program", "literal;argv"])

    def execv(path, args):
        calls.append(("exec", path, args))
        raise SystemExit(7)

    monkeypatch.setattr(pty_child.os, "execv", execv)
    with pytest.raises(SystemExit) as error:
        pty_child.main()
    assert error.value.code == 7 and calls[-1] == (
        "exec",
        "/owned/program",
        ["/owned/program", "literal;argv"],
    )
    assert [c[0] for c in calls] == ["claim", "foreground", "exec"]


def test_child_failure_is_safe_and_main_preserves_exit(monkeypatch):
    def fail(*_):
        raise OSError("sensitive startup error")

    monkeypatch.setattr(pty_child.fcntl, "ioctl", fail)
    output = []
    monkeypatch.setattr(pty_child.os, "write", lambda fd, data: output.append((fd, data)))
    assert pty_child.main() == 126
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(Path(pty_child.__file__)), run_name="__main__")
    assert error.value.code == 126
    assert all(data == b"Cannot start the interactive executable.\n" for _, data in output)
