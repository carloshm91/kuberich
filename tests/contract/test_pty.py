"""Real child controlling-terminal, input, resize, signals, bounds and lifecycle."""

import asyncio
import os
import signal
import sys

import pytest

from kubetrol.adapters.pty import PtyEndpoint
from kubetrol.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.processes import ProcessRunner
from tests.contract.test_processes import command


async def until(endpoint, marker):
    data = b""
    async with asyncio.timeout(5):
        while marker not in data:
            value = await endpoint.read()
            assert value, data
            data += value
    return data


@pytest.mark.asyncio
async def test_actual_child_pty_geometry_input_unicode_and_ctrl_c(tmp_path):
    # Signal handlers must not re-enter stdout while the initial print flushes.
    # Observe the signal in normal child execution before printing its geometry.
    code = """
import os, signal, time
resized = False
def resize(*_):
    global resized
    resized = True
signal.signal(signal.SIGWINCH, resize)
print('OWNER', os.getpgrp() == os.tcgetpgrp(0), os.environ['TERM'], os.get_terminal_size(0), flush=True)
while not resized:
    time.sleep(0.01)
print('RESIZE', os.get_terminal_size(0), flush=True)
print('INPUT', input(), flush=True)
print('WAIT', flush=True)
input()
"""
    script = tmp_path / "resize_child.py"
    script.write_text(code)
    captured = capture_command(
        [sys.executable, str(script)],
        environment=dict(os.environ),
        directory=tmp_path,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.PLUGIN,
    )
    async with ProcessRunner(AccessPolicy(False)) as runner:
        async with runner.terminal(
            captured,
            width=71,
            height=19,
            guard=lambda: None,
        ) as (endpoint, session):
            data = await until(endpoint, b"lines=19")
            assert b"OWNER True xterm-256color" in data
            endpoint.resize(80, 25)
            assert b"columns=80, lines=25" in await until(endpoint, b"lines=25")
            endpoint.write("unicode á\r".encode())
            assert "INPUT unicode á".encode() in await until(endpoint, b"WAIT")
            endpoint.write(b"\x03")
            result = await session.wait()
            assert result.status is ProcessStatus.SIGNALLED and result.returncode == -signal.SIGINT
        assert endpoint.closed and endpoint.slave == -1
        with pytest.raises(OSError):
            os.fstat(endpoint.master)
        assert runner.active_count == 0


@pytest.mark.asyncio
async def test_output_backpressure_and_exit_drain(tmp_path):
    async with (
        ProcessRunner(AccessPolicy(False)) as runner,
        runner.terminal(
            command(tmp_path, "import os; os.write(1,b'x'*400000)", mode=ProcessMode.FOREGROUND),
            width=20,
            height=4,
            guard=lambda: None,
        ) as (endpoint, session),
    ):
        await asyncio.sleep(0.1)
        assert endpoint.queue.qsize() <= 8
        data = bytearray()
        while chunk := await endpoint.read():
            data.extend(chunk)
        assert len(data) == 400000 and (await session.wait()).returncode == 0
        assert await endpoint.read() == b""


@pytest.mark.asyncio
async def test_cancelled_owner_reaps_ignoring_child_and_closes_descriptors(tmp_path):
    opened = asyncio.Future()
    async with ProcessRunner(AccessPolicy(False), terminate_grace=0.02) as runner:

        async def owner():
            async with runner.terminal(
                command(
                    tmp_path,
                    "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('READY',flush=True); time.sleep(60)",
                    mode=ProcessMode.FOREGROUND,
                ),
                width=20,
                height=4,
                guard=lambda: None,
            ) as (endpoint, session):
                await until(endpoint, b"READY")
                opened.set_result((endpoint, session))
                await endpoint.read()

        task = asyncio.create_task(owner())
        endpoint, session = await opened
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert endpoint.closed and session.task.done()
        with pytest.raises(ProcessLookupError):
            os.kill(session.pid, 0)
        assert runner.active_count == 0


@pytest.mark.asyncio
async def test_pty_input_bound_close_and_readonly_before_allocation(tmp_path, monkeypatch):
    endpoint = PtyEndpoint(20, 4)
    with pytest.raises(AppError, match="busy"):
        endpoint.write(b"x" * 65537)
    endpoint.close()
    endpoint.close()
    endpoint.resize(1, 1)
    endpoint.write(b"ignored")
    assert await endpoint.read() == b""
    value = command(tmp_path, mode=ProcessMode.FOREGROUND)
    async with ProcessRunner(AccessPolicy(True)) as runner:
        with pytest.raises(AppError, match="Read-only"):
            async with runner.terminal(value, width=20, height=4, guard=lambda: None):
                pytest.fail("read-only process started")
