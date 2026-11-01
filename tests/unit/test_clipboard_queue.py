"""Latest-selection writes keep their owner through failures and repeated teardown."""

import asyncio

import pytest

from kuberich.domain.clipboard import ClipboardBackend as B
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.clipboard import ClipboardQueue, NativeClipboard
from kuberich.services.processes import ProcessRunner
from tests.support.workers import CoroutineCalls


async def idle(queue):
    async with asyncio.timeout(5):
        while queue.active_count:
            await asyncio.sleep(0)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_fails", [False, True])
async def test_latest_pending_selection_replaces_intermediate_write_and_old_failures(
    tmp_path, monkeypatch, first_fails
):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        native = NativeClipboard(runner, {}, tmp_path)
        entered, release = asyncio.Event(), asyncio.Event()
        writes, callbacks, failures = [], [], []

        async def write(data, backend, *, failed):
            writes.append((data, backend))
            callbacks.append(failed)
            if data == b"first":
                entered.set()
                await release.wait()
                if first_fails:
                    raise AppError("First native write failed.")

        monkeypatch.setattr(native, "write", write)
        queue = ClipboardQueue(native, lambda data, error: failures.append((data, str(error))))
        try:
            queue.submit(b"first", B.X11)
            await asyncio.wait_for(entered.wait(), 5)
            queue.submit(b"intermediate", B.MACOS)
            queue.submit(b"last", B.X11)
            callbacks[0](AppError("Previous selection owner failed."))
            assert not failures
            release.set()
            await idle(queue)
            assert writes == [(b"first", B.X11), (b"last", B.X11)]
            assert not failures
            callbacks[-1](AppError("Current selection owner failed."))
            assert failures == [(b"last", "Current selection owner failed.")]
            queue.stop()
            callbacks[-1](AppError("Stopped selection owner failed."))
            queue.submit(b"ignored", B.MACOS)
            await asyncio.sleep(0)
            assert len(writes) == 2 and len(failures) == 1
        finally:
            release.set()
            await queue.close()
        assert queue.active_count == 0 and runner.active_count == 0


@pytest.mark.asyncio
async def test_completed_writer_can_restart_and_close_is_idempotent(tmp_path, monkeypatch):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        native = NativeClipboard(runner, {}, tmp_path)
        writes, closures = [], []
        original_close = native.close

        async def write(data, backend, *, failed):
            writes.append((data, backend))

        async def close():
            closures.append("closed")
            await original_close()

        monkeypatch.setattr(native, "write", write)
        monkeypatch.setattr(native, "close", close)
        queue = ClipboardQueue(native, lambda data, error: pytest.fail(str(error)))
        try:
            queue.submit(b"first", B.MACOS)
            await idle(queue)
            queue.submit(b"second", B.X11)
            await idle(queue)
            assert writes == [(b"first", B.MACOS), (b"second", B.X11)]
        finally:
            await queue.close()
        await queue.close()
        queue.submit(b"ignored", B.X11)
        assert closures == ["closed"] and queue.active_count == 0


@pytest.mark.asyncio
async def test_close_before_writer_starts_discards_pending_selection(tmp_path, monkeypatch):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        native = NativeClipboard(runner, {}, tmp_path)

        async def write(*args, **kwargs):
            pytest.fail("A stopped pending selection must not start a native writer.")

        monkeypatch.setattr(native, "write", write)
        queue = ClipboardQueue(native, lambda data, error: pytest.fail(str(error)))
        queue.submit(b"pending", B.X11)
        await queue.close()
        assert queue.active_count == 0


@pytest.mark.asyncio
async def test_close_without_copying_still_closes_the_native_owner(tmp_path, monkeypatch):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        native = NativeClipboard(runner, {}, tmp_path)
        closures = CoroutineCalls()
        monkeypatch.setattr(native, "close", closures.observe(native.close))
        queue = ClipboardQueue(native, lambda data, error: pytest.fail(str(error)))
        await queue.close()
        await queue.close()
        assert len(closures.tasks) == 1 and closures.latest.done()
        assert queue.active_count == 0


@pytest.mark.asyncio
async def test_repeated_caller_cancellation_drains_writer_and_native_cleanup(tmp_path, monkeypatch):
    async with ProcessRunner(AccessPolicy(True)) as runner:
        native = NativeClipboard(runner, {}, tmp_path)
        entered, cancel_seen, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        closing_entered, closing_release = asyncio.Event(), asyncio.Event()
        writes = CoroutineCalls()
        callbacks, failures, closures = [], [], []
        original_close = native.close

        async def write(data, backend, *, failed):
            callbacks.append(failed)
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancel_seen.set()
                await release.wait()
                raise

        async def close():
            closures.append("closing")
            closing_entered.set()
            await closing_release.wait()
            await original_close()

        monkeypatch.setattr(native, "write", writes.observe(write))
        monkeypatch.setattr(native, "close", close)
        queue = ClipboardQueue(native, lambda data, error: failures.append(str(error)))
        closing = None
        try:
            queue.submit(b"owned", B.X11)
            await asyncio.wait_for(entered.wait(), 5)
            closing = asyncio.create_task(queue.close())
            await asyncio.wait_for(cancel_seen.wait(), 5)
            for _ in range(2):
                closing.cancel()
                await asyncio.sleep(0)
                assert not closing.done() and not writes.latest.done()
                assert writes.latest.cancelling() == 1
            callbacks[0](AppError("Late writer failure."))
            queue.submit(b"ignored", B.X11)
            assert not failures and len(writes.tasks) == 1
            release.set()
            await asyncio.wait_for(closing_entered.wait(), 5)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done() and writes.latest.done()
        finally:
            release.set()
            closing_release.set()
            if closing is not None:
                await closing
            await queue.close()
        assert closures == ["closing"] and queue.active_count == 0
        assert runner.active_count == 0
