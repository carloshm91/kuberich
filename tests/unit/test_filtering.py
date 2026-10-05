"""Text/regex behavior plus hostile-pattern and owned cancellation boundaries."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kubetrol.domain.pods import pod_row
from kubetrol.services import filtering
from tests.support.pods import pod, record


def sample():
    return tuple(
        pod_row(record(pod(name, restarts=i)))
        for i, name in enumerate(["API", "payroll", "api-worker"])
    )


def test_plain_filter_is_case_insensitive_literal_and_searches_supported_columns():
    rows = sample()
    assert filtering.filter_rows(rows, "").rows is rows
    assert [row.name for row in filtering.filter_rows(rows, "api").rows] == ["API", "api-worker"]
    assert filtering.filter_rows(rows, "Running").rows == rows
    assert filtering.filter_rows(rows, "team").rows == rows
    assert filtering.filter_rows(rows, "1/1").rows == rows
    assert filtering.filter_rows(rows, "2").rows == (rows[2],)
    assert filtering.filter_rows(rows, "[API]").rows == ()
    assert filtering.filter_rows((replace(rows[0], name="CAFÉ"),), "café").rows
    assert filtering.filter_rows(rows, "x" * 257).problem


def test_regex_syntax_error_and_empty_match_are_explicit_without_losing_rows():
    rows = sample()
    result = filtering.filter_rows(rows, r"re:\bapi(?:-worker)?\b")
    assert result.rows == (rows[0], rows[2]) and result.problem is None
    assert filtering.filter_rows(rows, "re:").rows == rows
    assert filtering.filter_rows(rows, "re:[").rows is rows
    assert "Invalid regex" in filtering.filter_rows(rows, "re:[").problem
    assert filtering.filter_rows(rows, "re:NOTHERE").rows == ()


def test_total_regex_budget_and_actual_adversarial_match_are_bounded(monkeypatch):
    rows = sample()
    clock = iter([0.0, 1.0])
    with monkeypatch.context() as patch:
        patch.setattr(filtering.time, "monotonic", lambda: next(clock))
        assert "time budget" in filtering.filter_rows(rows, "re:api").problem
    hostile = replace(rows[0], name="a" * 50_000 + "!")
    result = filtering.filter_rows((hostile,), r"re:(a|aa)+$")
    assert result.rows == (hostile,) and "time budget" in result.problem
    assert filtering.filter_rows((), "re:api").rows == ()


@pytest.mark.asyncio
async def test_thread_runs_off_loop_and_repeated_cancellation_drains_owned_job(monkeypatch):
    started, release, ended = (threading.Event() for _ in range(3))

    def controlled(rows, query):
        started.set()
        try:
            assert release.wait(3)
            return filtering.FilterResult(rows)
        finally:
            ended.set()

    monkeypatch.setattr(filtering, "filter_rows", controlled)
    rows = sample()
    assert (await filtering.apply_filter(rows, "")).rows is rows
    task = asyncio.create_task(filtering.apply_filter(rows, "api"))
    try:
        async with asyncio.timeout(3):
            while not started.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done() and not ended.is_set()
        task.cancel()
        await asyncio.sleep(0.01)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended.is_set()


@pytest.mark.asyncio
async def test_worker_failure_is_observed_even_during_cancellation(monkeypatch):
    release, started = threading.Event(), threading.Event()

    def broken(rows, query):
        started.set()
        assert release.wait(3)
        raise RuntimeError("owned-filter-failure")

    monkeypatch.setattr(filtering, "filter_rows", broken)
    task = asyncio.create_task(filtering.apply_filter(sample(), "api"))
    try:
        async with asyncio.timeout(3):
            while not started.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
