"""Log option semantics, bounded framing/retention and streaming credential policy."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from kuberich.domain.logs import (
    MAX_CHUNK,
    MAX_LINE,
    LogBuffer,
    LogDecoder,
    LogLine,
    LogOptions,
    log_containers,
)
from kuberich.errors import AppError


def test_log_query_parameters_selected_container_time_windows_and_exact_booleans():
    value = LogOptions(
        follow=False, previous=True, timestamps=False, tail_lines=-1, since_seconds=30
    )
    assert value.parameters("init") == {
        "container": "init",
        "follow": "false",
        "previous": "true",
        "timestamps": "false",
        "sinceSeconds": "30",
    }
    time = datetime(2026, 10, 5, 10, tzinfo=timezone(timedelta(hours=2)))
    assert LogOptions(since_time=time).parameters("app")["sinceTime"] == "2026-10-05T08:00:00Z"
    assert LogOptions().parameters("app")["tailLines"] == "1000"
    assert LogOptions(tail_lines=0).parameters("app")["tailLines"] == "0"
    with pytest.raises(AppError, match="segment"):
        value.parameters("bad/name")


@pytest.mark.parametrize(
    "values",
    [
        {"follow": 1},
        {"previous": "yes"},
        {"timestamps": None},
        {"tail_lines": True},
        {"tail_lines": -2},
        {"tail_lines": 1000001},
        {"since_seconds": True},
        {"since_seconds": 0},
        {"since_seconds": 2147483648},
        {"since_time": "today"},
        {"since_time": datetime(2026, 1, 1)},
        {"since_time": datetime(2026, 1, 1, tzinfo=UTC), "since_seconds": 10},
    ],
)
def test_invalid_log_options_fail_without_io(values):
    with pytest.raises(AppError):
        LogOptions(**values)


def test_regular_init_and_existing_ephemeral_containers_are_available_and_duplicates_rejected():
    raw = {
        "spec": {
            "containers": [{"name": "app"}],
            "initContainers": [{"name": "init"}],
            "ephemeralContainers": [{"name": "debug"}],
        }
    }
    assert log_containers(raw) == ("app", "init", "debug")
    assert log_containers({"spec": {"containers": None}}) == ()
    for field in ("containers", "initContainers", "ephemeralContainers"):
        for values in ("invalid", [{"name": "app"}] * 129):
            with pytest.raises(AppError, match="container list"):
                log_containers({"spec": {field: values}})
    raw["spec"]["ephemeralContainers"][0]["name"] = "app"
    with pytest.raises(AppError, match="Duplicate"):
        log_containers(raw)
    raw["spec"]["ephemeralContainers"][0]["name"] = "debug"
    raw["spec"]["initContainers"][0]["name"] = "app"
    with pytest.raises(AppError, match="Duplicate"):
        log_containers(raw)
    with pytest.raises(AppError):
        log_containers({"spec": {"containers": [{"name": "bad/name"}]}})


def test_partial_utf8_crlf_empty_lines_unfinished_tail_and_invalid_bytes_are_visible():
    decoder = LogDecoder()
    encoded = "你好\n".encode()
    assert decoder.feed(encoded[:2]) == ()
    assert decoder.feed(encoded[2:5]) == ()
    assert decoder.feed(encoded[5:]) == (LogLine("你好"),)
    assert decoder.feed(b"\r\n\nlast\xff") == (LogLine(""), LogLine(""))
    assert decoder.feed(b"", final=True) == (LogLine("last�"),)
    with pytest.raises(AppError, match="closed"):
        decoder.feed(b"late")
    assert LogDecoder().feed(b"", final=True) == ()
    assert LogDecoder().feed(b"\xe4", final=True) == (LogLine("�"),)


def test_long_line_chunks_remain_bounded_discard_suffix_and_resume_after_newline():
    decoder = LogDecoder()
    assert decoder.feed(b"x" * MAX_LINE) == ()
    for _ in range(20):
        assert decoder.feed(b"y" * MAX_CHUNK) == ()
        assert len(decoder.pending) == MAX_LINE and len(decoder.marker_tail) <= 128
    result = decoder.feed(b"\nnext\n")
    assert result[0] == LogLine("x" * MAX_LINE + " [line truncated]", True)
    assert result[1] == LogLine("next")
    with pytest.raises(AppError, match="excessive"):
        LogDecoder().feed(b"x" * (MAX_CHUNK + 1))
    assert LogDecoder().feed(b"x" * (MAX_LINE + 1), final=True)[0].truncated


def test_plaintext_markup_controls_and_credentials_are_not_terminal_instructions():
    lines = LogDecoder().feed(b"[red]literal[/red]\x1b[2J token=synthetic-value\nBearer abc\n")
    assert "[red]literal[/red]" in lines[0].text and "\x1b" not in lines[0].text
    assert "synthetic-value" not in lines[0].text and "abc" not in lines[1].text


def test_private_key_blocks_are_hidden_across_chunks_lines_and_discarded_long_prefix():
    decoder = LogDecoder()
    assert decoder.feed(b"x" * MAX_LINE + b"-----BEGIN RSA PRI") == ()
    assert decoder.feed(b"VATE KEY-----\n") == (LogLine("[REDACTED KEY] [line truncated]", True),)
    assert decoder.feed(b"synthetic-key-line\n-----END RSA PRIV") == (LogLine("[REDACTED KEY]"),)
    assert decoder.feed(b"ATE KEY-----\nordinary\n") == (
        LogLine("[REDACTED KEY]"),
        LogLine("ordinary"),
    )
    assert decoder.feed(b"-----BEGIN PRIVATE KEY-----\nunterminated", final=True) == (
        LogLine("[REDACTED KEY]"),
        LogLine("[REDACTED KEY]"),
    )


@pytest.mark.parametrize(
    "limits",
    [
        {"max_lines": 0},
        {"max_lines": 10001},
        {"max_lines": True},
        {"max_bytes": 0},
        {"max_bytes": 4194305},
        {"max_bytes": True},
    ],
)
def test_invalid_retention_limits_are_rejected(limits):
    with pytest.raises(AppError, match="retention"):
        LogBuffer(**limits)


def test_ring_keeps_latest_lines_and_measures_utf8_bytes_and_drops_oversize_lines():
    buffer = LogBuffer(max_lines=2, max_bytes=8)
    for text in ["one", "two", "你好"]:
        buffer.append(LogLine(text))
    assert tuple(buffer.lines) == (LogLine("你好"),)
    assert buffer.size_bytes == 6 and buffer.dropped_lines == 2
    buffer.append(LogLine("123456789"))
    assert not buffer.lines and buffer.size_bytes == 0 and buffer.dropped_lines == 4
    assert LogLine("你好").size_bytes == 6


def test_default_ring_retains_ten_thousand_ordered_lines_then_evicts_oldest():
    buffer = LogBuffer()
    for index in range(10000):
        buffer.append(LogLine(f"line-{index:05}"))
    assert len(buffer.lines) == 10000 and buffer.dropped_lines == 0
    assert buffer.lines[0].text == "line-00000" and buffer.lines[-1].text == "line-09999"
    buffer.append(LogLine("new arrival"))
    assert len(buffer.lines) == 10000 and buffer.dropped_lines == 1
    assert buffer.lines[0].text == "line-00001" and buffer.lines[-1].text == "new arrival"
    assert buffer.size_bytes == sum(line.size_bytes for line in buffer.lines)


def test_default_utf8_byte_limit_remains_four_mib_with_larger_line_capacity():
    buffer = LogBuffer()
    for _ in range(513):
        buffer.append(LogLine("é" * 4096))
    assert len(buffer.lines) == 512 and buffer.dropped_lines == 1
    assert buffer.size_bytes == buffer.max_bytes == 4 * 1024 * 1024


def test_key_markers_in_order_do_not_reveal_a_new_key_after_a_previous_end():
    decoder = LogDecoder()
    assert decoder.feed(b"-----BEGIN PRIVATE KEY-----\n") == (LogLine("[REDACTED KEY]"),)
    assert decoder.feed(
        b"-----END PRIVATE KEY----- -----BEGIN PRIVATE KEY-----\nnew-key-material\n"
    ) == (LogLine("[REDACTED KEY]"), LogLine("[REDACTED KEY]"))
    assert decoder.feed(b"-----END PRIVATE KEY-----\nordinary\n") == (
        LogLine("[REDACTED KEY]"),
        LogLine("ordinary"),
    )


@pytest.mark.parametrize(
    "text,truncated", [(None, False), ("x" * (MAX_LINE * 6 + 33), False), ("valid", 1)]
)
def test_line_contract_rejects_unbounded_or_invalid_values(text, truncated):
    with pytest.raises(AppError, match="bounded text"):
        LogLine(text, truncated)


def test_escaped_controls_and_malformed_unicode_keep_retention_byte_accounting_bounded():
    line = LogDecoder().feed(b"\x1b" * MAX_LINE + b"\n")[0]
    assert line.size_bytes == 6 * MAX_LINE and "\x1b" not in line.text
    assert LogLine("\ud800").size_bytes == 6
