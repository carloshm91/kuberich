"""Cancellation/errors leave suspension normally before being propagated."""

import asyncio
import signal
from contextlib import contextmanager

import pytest

from kubetrol.domain.processes import (
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.processes import ProcessRunner
from kubetrol.ui import handoff


class NativeApp:
    is_headless = False
    is_web = False

    def __init__(self):
        self.events = []
        self.exit_code = None

    @contextmanager
    def suspend(self):
        self.events.append("suspended")
        yield
        self.events.append("resumed")

    def exit(self, *, return_code):
        self.exit_code = return_code


def command(tmp_path):
    return capture_command(
        ["owned"],
        environment={},
        directory=tmp_path,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.PLUGIN,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [None, AppError("owned failure"), RuntimeError("owned failure"), asyncio.CancelledError()],
)
async def test_suspension_resumes_before_success_exception_or_cancel(
    tmp_path, monkeypatch, failure
):
    app = NativeApp()
    runner = ProcessRunner(AccessPolicy(False))
    events = app.events

    class Lease:
        descriptor = 0

        def claim(self, pid):
            pass

        def __init__(self, fd):
            pass

        def __enter__(self):
            events.append("terminal leased")
            return self

        def __exit__(self, *args):
            events.append("terminal restored")

    async def foreground(*args, **kwargs):
        if failure is not None:
            raise failure
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(handoff, "TerminalLease", Lease)
    monkeypatch.setattr(runner, "foreground", foreground)
    before = signal.getsignal(signal.SIGTERM)
    if failure is None:
        assert (await handoff.terminal_handoff(app, runner, command(tmp_path))).returncode == 0
    else:
        with pytest.raises(type(failure)):
            await handoff.terminal_handoff(app, runner, command(tmp_path))
    assert events == ["suspended", "terminal leased", "terminal restored", "resumed"]
    assert signal.getsignal(signal.SIGTERM) == before
    await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["is_headless", "is_web", "stdin"])
async def test_non_native_surfaces_refuse_handoff_before_suspending(
    tmp_path, monkeypatch, condition
):
    app = NativeApp()
    if condition == "stdin":
        monkeypatch.setattr(handoff.sys, "__stdin__", None)
    else:
        setattr(app, condition, True)
    async with ProcessRunner(AccessPolicy(False)) as runner:
        with pytest.raises(AppError, match="native"):
            await handoff.terminal_handoff(app, runner, command(tmp_path))
    assert not app.events


@pytest.mark.asyncio
async def test_parent_termination_requests_owned_cancel_and_application_exit(tmp_path, monkeypatch):
    app = NativeApp()
    runner = ProcessRunner(AccessPolicy(False))

    class Lease:
        descriptor = 0

        def claim(self, pid):
            pass

        def __init__(self, fd):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    async def foreground(*args, **kwargs):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        await asyncio.sleep(1)

    monkeypatch.setattr(handoff, "TerminalLease", Lease)
    monkeypatch.setattr(runner, "foreground", foreground)
    task = asyncio.create_task(handoff.terminal_handoff(app, runner, command(tmp_path)))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert app.events == ["suspended", "resumed"] and app.exit_code == 143
    await runner.close()


@pytest.mark.asyncio
async def test_concurrent_handoff_is_refused_before_changing_driver_or_signals(tmp_path):
    app = NativeApp()
    async with ProcessRunner(AccessPolicy(False)) as runner:
        before = signal.getsignal(signal.SIGTERM)
        with runner.reserve_terminal(), pytest.raises(AppError, match="already active"):
            await handoff.terminal_handoff(app, runner, command(tmp_path))
        assert not app.events and signal.getsignal(signal.SIGTERM) == before
