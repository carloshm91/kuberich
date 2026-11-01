"""Foreground waiting wakes on actual resume or close and owns no background tasks."""

import asyncio

import pytest

from kuberich.ui.foreground import ForegroundGate


@pytest.mark.asyncio
async def test_foreground_gate_repeated_suspend_resume_and_close_are_owned():
    requests = []
    gate = ForegroundGate(lambda: requests.append("paint"))
    assert not gate.active and not gate.closed
    first = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    assert not first.done()
    gate.resume()
    assert await first and gate.active and requests == ["paint"]
    gate.suspend()
    assert not gate.active
    second = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    assert not second.done()
    gate.resume()
    assert await second and requests == ["paint", "paint"]
    gate.suspend()
    waiting_at_exit = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    gate.close()
    assert not await waiting_at_exit and gate.closed and not gate.active
    gate.resume()
    gate.suspend()
    gate.close()
    assert not await gate.wait() and requests == ["paint", "paint"]


@pytest.mark.asyncio
async def test_cancelled_foreground_wait_does_not_steal_the_next_resume():
    requests = []
    gate = ForegroundGate(lambda: requests.append("paint"))
    waiting = asyncio.create_task(gate.wait())
    await asyncio.sleep(0)
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    gate.resume()
    assert await gate.wait() and requests == ["paint"]
    gate.close()
