"""Real owned local children exercise output, startup races and process-group cleanup."""

import asyncio
import os
import pty
import signal
import sys
from dataclasses import replace

import pytest

from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.errors import AppError
from kuberich.services import processes
from kuberich.services.access import AccessPolicy
from kuberich.services.processes import ProcessRunner
from tests.unit.test_processes import target


def command(tmp_path, code="print('owned')", mode=ProcessMode.CAPTURE, **changes):
    value = capture_command(
        [sys.executable, "-c", code],
        environment=dict(os.environ),
        directory=tmp_path,
        mode=mode,
        purpose=ProcessPurpose.PLUGIN,
    )
    return replace(value, **changes)


@pytest.mark.asyncio
async def test_capture_preserves_literal_argv_cwd_and_snapshot_environment(tmp_path):
    argv = [
        sys.executable,
        "-c",
        "import os,sys; print(sys.argv[1]); print(os.getcwd()); print(os.environ['FIXTURE']); print('err',file=sys.stderr)",
        "$(touch sentinel); 'quoted' [markup]",
    ]
    env = {**os.environ, "FIXTURE": "before"}
    captured = capture_command(
        argv,
        environment=env,
        directory=tmp_path,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.PLUGIN,
    )
    env["FIXTURE"] = "after"
    async with ProcessRunner(AccessPolicy(False)) as runner:
        result = await runner.capture(captured)
        assert result.status is ProcessStatus.SUCCEEDED and result.returncode == 0
        assert result.stdout.decode().splitlines() == [argv[-1], str(tmp_path), "before"]
        assert result.stderr == b"err\n" and not (tmp_path / "sentinel").exists()
        await asyncio.sleep(0)
        assert runner.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status,exitcode",
    [
        ("raise SystemExit(7)", ProcessStatus.FAILED, 7),
        ("import os,signal; os.kill(os.getpid(),signal.SIGTERM)", ProcessStatus.SIGNALLED, -15),
    ],
)
async def test_failure_and_signal_are_typed_without_losing_actual_codes(
    tmp_path, code, status, exitcode
):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        result = await runner.capture(command(tmp_path, code))
        assert result.status is status and result.returncode == exitcode


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,status", [(64, ProcessStatus.SUCCEEDED), (100000, ProcessStatus.OUTPUT_LIMIT)]
)
async def test_output_is_bounded_across_both_streams(tmp_path, amount, status):
    async with ProcessRunner(AccessPolicy(False), output_limit=64) as runner:
        result = await runner.capture(
            command(
                tmp_path,
                f"import os; os.write(1,b'x'*{amount}); os.write(2,b'y'*{max(0, amount - 64)})",
            )
        )
        assert result.status is status
        assert len(result.stdout) + len(result.stderr) <= 64


@pytest.mark.asyncio
async def test_timeout_kills_a_child_ignoring_termination(tmp_path):
    async with ProcessRunner(AccessPolicy(False), terminate_grace=0.03) as runner:
        result = await runner.capture(
            command(
                tmp_path,
                "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)",
            ),
            timeout=0.3,
        )
        assert result.status is ProcessStatus.TIMED_OUT and result.returncode == -signal.SIGKILL


@pytest.mark.asyncio
async def test_background_waiter_cancellation_does_not_abandon_or_stop_owner(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        session = await runner.background(
            command(tmp_path, "import time; time.sleep(60)", mode=ProcessMode.BACKGROUND)
        )
        waiter = asyncio.create_task(session.wait())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert runner.active_count == 1
        result = await session.close()
        assert result.status is ProcessStatus.CANCELLED
        assert await session.close() == result
        with pytest.raises(ProcessLookupError):
            os.kill(session.pid, 0)


@pytest.mark.asyncio
async def test_capture_cancellation_awaits_child_cleanup(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        task = asyncio.create_task(runner.capture(command(tmp_path, "import time; time.sleep(60)")))
        while not runner._sessions:
            await asyncio.sleep(0.01)
        pid = next(iter(runner._sessions)).pid
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.active_count == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.asyncio
async def test_natural_parent_exit_cleans_descendants_holding_output_pipes(tmp_path):
    code = "import os,time; child=os.fork(); print('leader' if child else 'descendant',flush=True); time.sleep(60) if child == 0 else None"
    async with ProcessRunner(AccessPolicy(False), terminate_grace=0.03) as runner:
        result = await asyncio.wait_for(runner.capture(command(tmp_path, code)), 3)
        assert result.status is ProcessStatus.SUCCEEDED and b"leader" in result.stdout


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", list(ProcessMode))
@pytest.mark.parametrize(
    "purpose", [value for value in ProcessPurpose if value is not ProcessPurpose.AUTHENTICATE]
)
async def test_read_only_blocks_every_process_before_executable_resolution(
    tmp_path, monkeypatch, mode, purpose
):
    def forbidden(*args):
        raise AssertionError("Policy must run before executable lookup")

    monkeypatch.setattr(processes, "_executable", forbidden)
    runner = ProcessRunner(AccessPolicy(True))
    with pytest.raises(AppError, match="Read-only"):
        runner.require(command(tmp_path, mode=mode, purpose=purpose), mode, None)
    await runner.close()


@pytest.mark.asyncio
async def test_authentication_is_allowed_in_read_only_and_output_is_captured(tmp_path):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        result = await runner.capture(
            command(tmp_path, "print('synthetic-credential')", purpose=ProcessPurpose.AUTHENTICATE)
        )
        assert (
            result.status is ProcessStatus.SUCCEEDED
            and result.stdout.strip() == b"synthetic-credential"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "timeout", "overflow"])
async def test_authentication_foreground_keeps_stdout_private_and_bounded(tmp_path, scenario):
    import pty

    master, slave = pty.openpty()
    try:
        async with ProcessRunner(AccessPolicy(True), output_limit=1024) as runner:
            code = "import sys; print('provider-prompt',file=sys.stderr,flush=True); " + (
                "print('synthetic-credential')"
                if scenario == "success"
                else "import time;time.sleep(30)"
                if scenario == "timeout"
                else "print('x'*2048)"
            )
            spec = command(
                tmp_path,
                code,
                mode=ProcessMode.FOREGROUND,
                purpose=ProcessPurpose.AUTHENTICATE,
                terminal_input=False,
            )
            result = await runner.foreground(
                spec,
                descriptor=slave,
                claim=lambda group: None,
                timeout=0.5 if scenario == "timeout" else 5,
            )
            assert (
                result.status
                is {
                    "success": ProcessStatus.SUCCEEDED,
                    "timeout": ProcessStatus.TIMED_OUT,
                    "overflow": ProcessStatus.OUTPUT_LIMIT,
                }[scenario]
            )
            assert os.read(master, 1024) == b"provider-prompt\r\n"
            if scenario == "success":
                assert result.stdout.strip() == b"synthetic-credential"
            assert runner.active_count == 0
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.asyncio
async def test_missing_executable_and_bad_modes_fail_cleanly(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        missing = command(tmp_path, argv=(str(tmp_path / "missing-sensitive"),))
        with pytest.raises(AppError, match="Executable") as error:
            await runner.capture(missing)
        assert "missing-sensitive" not in str(error.value)
        with pytest.raises(AppError, match="mode"):
            await runner.background(command(tmp_path))
        with pytest.raises(AppError, match="guard"):
            await runner.capture(command(tmp_path, target=target()))
    with pytest.raises(AppError, match="closed"):
        await runner.capture(command(tmp_path))
    await runner.close()


@pytest.mark.asyncio
async def test_guard_invalidation_immediately_after_spawn_cleans_unstarted_monitor(tmp_path):
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise AppError("stale")

    async with ProcessRunner(AccessPolicy(False)) as runner:
        with pytest.raises(AppError, match="stale"):
            await runner.capture(
                command(tmp_path, "import time; time.sleep(60)", target=target()), guard=guard
            )
        assert runner.active_count == 0 and calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("close_runner", [False, True])
async def test_cancel_during_real_startup_retains_and_cleans_child(
    tmp_path, monkeypatch, close_runner
):
    entered, released = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    original = loop.subprocess_exec
    pids = []

    async def delayed(*args, **kwargs):
        value = await original(*args, **kwargs)
        pids.append(value[0].get_pid())
        entered.set()
        await released.wait()
        return value

    monkeypatch.setattr(loop, "subprocess_exec", delayed)
    runner = ProcessRunner(AccessPolicy(False))
    task = asyncio.create_task(runner.capture(command(tmp_path, "import time; time.sleep(60)")))
    await entered.wait()
    task.cancel()
    closing = asyncio.create_task(runner.close()) if close_runner else None
    task.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    if closing is not None:
        await closing
    await runner.close()
    assert runner.active_count == 0
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)


@pytest.mark.asyncio
async def test_spawn_os_error_is_sanitized(tmp_path, monkeypatch):
    async def failed(*args, **kwargs):
        raise OSError("fixture-sensitive-value")

    monkeypatch.setattr(asyncio.get_running_loop(), "subprocess_exec", failed)
    async with ProcessRunner(AccessPolicy(False)) as runner:
        with pytest.raises(AppError) as error:
            await runner.capture(command(tmp_path))
        assert "fixture-sensitive-value" not in str(error.value)


@pytest.mark.asyncio
async def test_explicit_relative_path_lookup_uses_captured_working_directory(tmp_path):
    (tmp_path / "bin").mkdir()
    helper = tmp_path / "bin/tool"
    helper.write_text("#!/bin/sh\nprintf owned")
    helper.chmod(0o700)
    async with ProcessRunner(AccessPolicy(False)) as runner:
        for executable, path in [("bin/tool", "/bin"), ("tool", "bin")]:
            value = command(tmp_path, argv=(executable,), environment=(("PATH", path),))
            assert (await runner.capture(value)).stdout == b"owned"


@pytest.mark.parametrize("value", [0, True, 8 * 1024 * 1024 + 1])
def test_invalid_output_budget(value):
    with pytest.raises(AppError):
        ProcessRunner(AccessPolicy(False), output_limit=value)


@pytest.mark.parametrize("value", [None, True, 0, 6, float("nan")])
def test_invalid_shutdown_grace_is_refused_before_any_process(value):
    with pytest.raises(AppError, match="termination grace"):
        ProcessRunner(AccessPolicy(False), terminate_grace=value)


@pytest.mark.asyncio
async def test_foreground_refuses_a_pipe_before_launch(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        with (
            (tmp_path / "file").open("w") as stream,
            pytest.raises(AppError, match="real interactive"),
        ):
            await runner.foreground(
                command(tmp_path, mode=ProcessMode.FOREGROUND),
                descriptor=stream.fileno(),
                claim=lambda pid: None,
            )
        assert runner.active_count == 0


@pytest.mark.asyncio
async def test_repeated_cancellation_cannot_cancel_owned_cleanup():
    released = asyncio.Event()
    pending = asyncio.create_task(released.wait())
    owner = asyncio.create_task(processes._finish_owned(pending))
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    owner.cancel()
    await asyncio.sleep(0)
    released.set()
    await owner
    assert pending.result() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ["success", "claim_error", "cancel"])
async def test_foreground_service_uses_terminal_descriptors_and_owns_failure_cleanup(
    tmp_path, scenario
):
    master, slave = pty.openpty()
    claimed = asyncio.Event()
    pid = None

    def claim(value):
        nonlocal pid
        pid = value
        claimed.set()
        if scenario == "claim_error":
            raise AppError("terminal claim failed")

    code = "print('owned foreground')" if scenario == "success" else "import time; time.sleep(60)"
    try:
        async with ProcessRunner(AccessPolicy(False)) as runner:
            task = asyncio.create_task(
                runner.foreground(
                    command(tmp_path, code, mode=ProcessMode.FOREGROUND),
                    descriptor=slave,
                    claim=claim,
                )
            )
            await claimed.wait()
            if scenario == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            elif scenario == "claim_error":
                with pytest.raises(AppError, match="claim failed"):
                    await task
            else:
                result = await task
                assert result.status is ProcessStatus.SUCCEEDED and result.stdout == b""
                assert b"owned foreground" in os.read(master, 1024)
            assert runner.active_count == 0
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.asyncio
async def test_pipe_failure_is_typed_without_exposing_exception_values(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        session = await runner.background(
            command(tmp_path, "import time; time.sleep(60)", mode=ProcessMode.BACKGROUND)
        )
        session.output.pipe_connection_lost(1, RuntimeError("fixture-sensitive-value"))
        result = await session.wait()
        assert result.status is ProcessStatus.IO_ERROR
        assert "fixture-sensitive-value" not in repr(result)


@pytest.mark.asyncio
async def test_delayed_transport_disconnect_falls_back_to_closing_owned_descriptors(
    tmp_path, monkeypatch
):
    original = processes._Output.connection_lost

    def delayed(self, exc):
        asyncio.get_running_loop().call_later(1.05, original, self, exc)

    monkeypatch.setattr(processes._Output, "connection_lost", delayed)
    async with ProcessRunner(AccessPolicy(False)) as runner:
        result = await runner.capture(command(tmp_path))
        assert result.status is ProcessStatus.SUCCEEDED


@pytest.mark.asyncio
@pytest.mark.parametrize("cause", ["overflow", "io_error"])
async def test_final_pipe_failures_after_process_exit_cannot_be_reported_as_success(
    tmp_path, monkeypatch, cause
):
    original = processes._Output.connection_lost

    def final_pipe(self, exc):
        if cause == "overflow":
            self.pipe_data_received(1, b"x" * 100)
        else:
            self.pipe_connection_lost(1, OSError("owned failure"))
        original(self, exc)

    monkeypatch.setattr(processes._Output, "connection_lost", final_pipe)
    async with ProcessRunner(AccessPolicy(False), output_limit=64) as runner:
        result = await runner.capture(command(tmp_path))
        expected = ProcessStatus.OUTPUT_LIMIT if cause == "overflow" else ProcessStatus.IO_ERROR
        assert result.status is expected and result.returncode == 0
        assert len(result.stdout) + len(result.stderr) <= 64


@pytest.mark.asyncio
async def test_cancelled_shutdown_still_drains_all_owned_children(tmp_path):
    runner = ProcessRunner(AccessPolicy(False), terminate_grace=0.2)
    session = await runner.background(
        command(tmp_path, "import time; time.sleep(60)", mode=ProcessMode.BACKGROUND)
    )
    closing = asyncio.create_task(runner.close())
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    await runner.close()
    assert runner.active_count == 0
    with pytest.raises(ProcessLookupError):
        os.kill(session.pid, 0)


@pytest.mark.asyncio
async def test_cancelled_monitor_keeps_its_cleanup_owner(tmp_path):
    async with ProcessRunner(AccessPolicy(False)) as runner:
        session = await runner.background(
            command(tmp_path, "import time; time.sleep(60)", mode=ProcessMode.BACKGROUND)
        )
        await asyncio.sleep(0)
        session.task.cancel()
        result = await session.wait()
        assert result.status is ProcessStatus.CANCELLED


@pytest.mark.asyncio
async def test_background_stream_drain_replenishes_only_consumed_capacity(tmp_path):
    code = """
import os,time
from pathlib import Path
for index in range(3):
    os.write(1,b'12345678'); os.write(2,b'abcdefgh')
    Path(f'mark-{index}').write_text('ready')
    while not Path(f'ack-{index}').exists(): time.sleep(.005)
"""
    script = tmp_path / "owned-stream.py"
    script.write_text(code)
    async with ProcessRunner(AccessPolicy(False), output_limit=16) as runner:
        session = await runner.background(
            replace(
                command(tmp_path, mode=ProcessMode.BACKGROUND), argv=(sys.executable, str(script))
            )
        )
        for index in range(3):
            async with asyncio.timeout(3):
                while not (tmp_path / f"mark-{index}").exists() or session.output.remaining:
                    await asyncio.sleep(0.005)
            assert session.running
            assert session.drain_output() == (b"12345678", b"abcdefgh")
            assert session.drain_output() == (b"", b"")
            (tmp_path / f"ack-{index}").write_text("continue")
        result = await session.wait()
        assert not session.running and result.status is ProcessStatus.SUCCEEDED
        assert result.stdout == result.stderr == b""


@pytest.mark.asyncio
async def test_output_drain_cannot_undo_an_existing_overflow(tmp_path):
    async with ProcessRunner(AccessPolicy(False), output_limit=16) as runner:
        session = await runner.background(
            command(
                tmp_path,
                "import os,time; os.write(1,b'x'*100); time.sleep(60)",
                mode=ProcessMode.BACKGROUND,
            )
        )
        async with asyncio.timeout(3):
            while not session.output.overflow.done():
                await asyncio.sleep(0.005)
        assert not session.running
        assert session.drain_output() == (b"x" * 16, b"")
        assert not session.running
        assert (await session.wait()).status is ProcessStatus.OUTPUT_LIMIT
