"""Bounded retained log identities, literal search and read-window decisions."""

import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from kuberich.domain.logs import MAX_BYTES, MAX_LINES, LogBuffer, LogLine, LogOptions
from kuberich.errors import AppError

WINDOWS = (
    "Tail 1000",
    "Tail 100",
    "All",
    "Head 1000",
    "Last 1m",
    "Last 5m",
    "Last 15m",
    "Last 30m",
    "Last 1h",
)
MAX_COPY_BYTES = 1024 * 1024
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}) ")


@dataclass(frozen=True)
class LogEntry:
    number: int
    line: LogLine

    def text(self, timestamps: bool) -> str:
        return self.line.text if timestamps else _TIMESTAMP.sub("", self.line.text, count=1)


def window_options(window: str, *, previous: bool, since: datetime | None = None) -> LogOptions:
    if window == "Since time":
        if since is None:
            raise AppError("Choose a timezone-aware start time.")
        return LogOptions(previous=previous, follow=not previous, since_time=since)
    if window not in WINDOWS:
        raise AppError("Unknown log window.")
    return LogOptions(
        previous=previous,
        follow=not previous and window != "Head 1000",
        tail_lines={"Tail 1000": 1000, "Tail 100": 100}.get(window, -1),
        since_seconds={
            "Last 1m": 60,
            "Last 5m": 300,
            "Last 15m": 900,
            "Last 30m": 1800,
            "Last 1h": 3600,
        }.get(window),
    )


def parse_start_time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise AppError("Use an RFC3339 start time including Z or a timezone offset.") from None
    if result.utcoffset() is None:
        raise AppError("The log start time must include Z or a timezone offset.")
    return result


class LogHistory:
    def __init__(self, *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> None:
        self.buffer = LogBuffer(max_lines=max_lines, max_bytes=max_bytes)
        self.entries: deque[LogEntry] = deque()
        self.marks: set[int] = set()
        self.next_number = 1

    def append(self, line: LogLine) -> None:
        self.buffer.append(line)
        self.entries.append(LogEntry(self.next_number, line))
        self.next_number += 1
        while len(self.entries) > len(self.buffer.lines):
            self.marks.discard(self.entries.popleft().number)

    def clear(self) -> int:
        count = len(self.entries)
        self.entries.clear()
        self.marks.clear()
        self.buffer = LogBuffer(max_lines=self.buffer.max_lines, max_bytes=self.buffer.max_bytes)
        return count

    def mark(self, number: int) -> None:
        if not any(entry.number == number for entry in self.entries):
            raise AppError("That log line is no longer retained.")
        if number in self.marks:
            self.marks.remove(number)
        else:
            self.marks.add(number)

    def export(self, *, clipboard: bool = False) -> str:
        text = "\n".join(entry.line.text for entry in self.entries)
        if clipboard and len(text.encode("utf-8")) > MAX_COPY_BYTES:
            raise AppError("Copy exceeds 1 MiB; choose a smaller log window or save to a file.")
        return text
