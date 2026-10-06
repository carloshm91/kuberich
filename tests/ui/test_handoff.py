"""Cancellation/errors leave suspension normally before being propagated."""

import asyncio
import os
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
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected,presentation_failure", [(True, False), (True, True), (False, False)]
)
async def test_shell_screen_precedes_child_and_presentation_failure_restores_app(
    tmp_path, monkeypatch, selected, presentation_failure
):
    app = NativeApp()
    runner = ProcessRunner(AccessPolicy(False))
    target = ResourceTarget(
        SessionIdentity("owned-context", 1), "", "pods", "team", "api", "uid", "worker"
    )
    spec = capture_command(
        ["owned"],
        environment={},
        directory=tmp_path,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.EXEC,
        target=target if selected else None,
    )

    def guard():
        pass

    class Lease:
        descriptor = 27

        def __init__(self, fd):
            pass

        def __enter__(self):
            app.events.append("terminal leased")
            return self

        def __exit__(self, *args):
            app.events.append("terminal restored")

        def claim(self, group):
            pass

        def present(self, heading):
            assert "Context: owned-context" in heading
            assert "Pod: team/api" in heading and "Container: worker" in heading
            app.events.append("screen presented")
            if presentation_failure:
                raise AppError("owned screen failure")

    async def foreground(command, *, descriptor, claim, guard):
        assert command is spec and descriptor == 27
        app.events.append("child started")
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(handoff, "TerminalLease", Lease)
    monkeypatch.setattr(os, "get_terminal_size", lambda _: os.terminal_size((40, 12)))
    monkeypatch.setattr(runner, "foreground", foreground)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        if presentation_failure:
            with pytest.raises(AppError, match="screen failure"):
                await handoff.terminal_handoff(app, runner, spec, guard=guard)
        else:
            assert (await handoff.terminal_handoff(app, runner, spec, guard=guard)).returncode == 0
        assert app.events == [
            "suspended",
            "terminal leased",
            *(["screen presented"] if selected else []),
            *([] if presentation_failure else ["child started"]),
            "terminal restored",
            "resumed",
        ]
        assert signal.getsignal(signal.SIGTERM) == previous
    finally:
        await runner.close()
