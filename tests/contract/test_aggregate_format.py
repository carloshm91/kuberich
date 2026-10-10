"""Captured formatting stays ordered, bounded and owned through cancellation."""

import asyncio
import threading

import pytest

from kuberich.domain.aggregate_logs import AggregateHistory, AggregateLine, LogSource
from kuberich.domain.logs import LogDecoder, LogLine
from kuberich.services import aggregate_logs


def retained_history():
    history = AggregateHistory()
    line = LogDecoder().feed(
        '2026-10-09T12:00:00Z {"message":"你好","token":"private-value"}\n'.encode()
    )[0]
    for source in range(10):
        for _ in range(100):
            history.retain(LogSource("team", "same-name", f"uid-{source}", "app"), source, line)
    return history


@pytest.mark.asyncio
@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("timestamps", [False, True])
@pytest.mark.parametrize("source_filter", [None, ("uid-3", "app"), ("expired-uid", "app")])
async def test_captured_format_preserves_order_redaction_and_filters_between_owned_turns(
    monkeypatch, json_mode, timestamps, source_filter
):
    history = retained_history()
    history.json_mode, history.filter = json_mode, source_filter
    expected = tuple(
        (entry.number, entry.line.text) for entry in history.display_entries(timestamps)
    )
    records = tuple(history.records.values())
    original, turns = aggregate_logs.parse_owned, []

    async def observed(operation):
        values = await original(operation)
        assert 1 <= len(values) <= 32
        size = sum(len(text.encode()) for _, text in values)
        assert size <= 8192 or len(values) == 1
        turns.append((len(values), size))
        return values

    monkeypatch.setattr(aggregate_logs, "parse_owned", observed)
    result = await aggregate_logs.format_records(
        records, json_mode=json_mode, timestamps=timestamps, source_filter=source_filter
    )
    assert result == expected
    assert all("private-value" not in text and "你好" in text for _, text in result)
    assert len(turns) > 1 if result else not turns
    assert len(history.records) == 1000 and not history.buffer.dropped_lines


@pytest.mark.asyncio
async def test_one_large_retained_record_is_not_split_or_discarded():
    history = AggregateHistory()
    history.retain(LogSource("team", "same-name", "uid", "app"), 1, LogLine("é" * 4096))
    record = next(iter(history.records.values()))
    assert record.size_bytes > 8192
    result = await aggregate_logs.format_records((record,), json_mode=True)
    assert result == ((1, record.text(json_mode=True)),)


@pytest.mark.asyncio
@pytest.mark.parametrize("held_at", [1, 45])
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancellation_drains_format_worker_without_starting_another_turn(
    monkeypatch, held_at, fail
):
    history = retained_history()
    original = AggregateLine.text
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    errors, submitted = [], []
    loop.set_exception_handler(lambda owner, context: errors.append(context))

    def held(record, **options):
        submitted.append(record.number)
        if record.number != held_at:
            return original(record, **options)
        entered.set()
        try:
            assert release.wait(5)
            if fail:
                raise ValueError("owned-private-format-failure")
            return original(record, **options)
        finally:
            finished.set()

    monkeypatch.setattr(AggregateLine, "text", held)
    task = asyncio.create_task(
        aggregate_logs.format_records(tuple(history.records.values()), json_mode=True)
    )
    try:
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.02)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert finished.is_set() and submitted[-1] <= 64
        count = len(submitted)
        await asyncio.sleep(0.02)
        assert len(submitted) == count and not errors
    finally:
        loop.set_exception_handler(previous)
