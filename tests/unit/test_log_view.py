"""Retained identities, windows and export limits are independent of the terminal."""

from datetime import UTC, datetime

import pytest

from kubetrol.domain.log_view import (
    MAX_COPY_BYTES,
    WINDOWS,
    LogEntry,
    LogHistory,
    parse_start_time,
    window_options,
)
from kubetrol.domain.logs import LogLine
from kubetrol.errors import AppError


def test_timestamps_toggle_only_recognized_server_prefixes():
    line = LogEntry(1, LogLine("2026-10-05T12:00:00.000+02:00 plain"))
    assert line.text(True).startswith("2026")
    assert line.text(False) == "plain"
    assert LogEntry(2, LogLine("ordinary text")).text(False) == "ordinary text"


def test_all_windows_previous_head_and_aware_start_time():
    for name in WINDOWS:
        value = window_options(name, previous=False)
        assert value.timestamps
        assert value.follow == (name != "Head 1000")
        previous = window_options(name, previous=True)
        assert previous.previous and not previous.follow
    assert window_options("Tail 100", previous=False).tail_lines == 100
    assert window_options("Last 5m", previous=False).since_seconds == 300
    time = datetime(2026, 10, 5, tzinfo=UTC)
    assert window_options("Since time", previous=False, since=time).since_time == time
    for name in ("unknown", "Since time"):
        with pytest.raises(AppError):
            window_options(name, previous=False)
    assert parse_start_time("2026-10-05T00:00:00Z") == time
    for value in ("not-a-time", "2026-10-05T00:00:00"):
        with pytest.raises(AppError):
            parse_start_time(value)


def test_marks_eviction_clear_and_sequence_identity_do_not_refer_to_new_lines():
    history = LogHistory(max_lines=2, max_bytes=20)
    for value in ("one", "two"):
        history.append(LogLine(value))
    history.mark(1)
    history.mark(1)
    assert not history.marks
    history.mark(1)
    history.append(LogLine("three"))
    assert history.buffer.dropped_lines == 1 and not history.marks
    assert [entry.number for entry in history.entries] == [2, 3]
    assert history.export(clipboard=True) == "two\nthree"
    with pytest.raises(AppError):
        history.mark(1)
    assert history.clear() == 2 and not history.entries and not history.buffer.lines
    history.append(LogLine("x" * 21))
    assert not history.entries and history.next_number == 5


def test_clipboard_payload_bound_counts_utf8_bytes():
    history = LogHistory()
    for _ in range(130):
        history.append(LogLine("界" * 3000))
    assert len(history.export().encode()) > MAX_COPY_BYTES
    with pytest.raises(AppError, match="1 MiB"):
        history.export(clipboard=True)
