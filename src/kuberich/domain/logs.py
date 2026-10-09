"""Validated log queries, bounded UTF-8 framing and retained sanitized output."""

import codecs
import re
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from kuberich.domain.log_json import sanitize_log_line
from kuberich.domain.resources import api_segment, resource_object
from kuberich.errors import AppError

MAX_CHUNK = 65536
MAX_LINE = 8192
MAX_LINES = 5000
MAX_BYTES = 4 * 1024 * 1024
_KEY_MARKER = re.compile(r"-----(BEGIN|END) [^-\n]{0,64}PRIVATE KEY-----", re.IGNORECASE)


@dataclass(frozen=True)
class LogOptions:
    follow: bool = True
    previous: bool = False
    timestamps: bool = True
    tail_lines: int = 1000
    since_seconds: int | None = None
    since_time: datetime | None = None

    def __post_init__(self) -> None:
        for value in (self.follow, self.previous, self.timestamps):
            if type(value) is not bool:
                raise AppError("Log switches must be true or false.")
        if type(self.tail_lines) is not int or not -1 <= self.tail_lines <= 1000000:
            raise AppError("Log tail must be -1 (all) or an integer up to 1000000.")
        if self.since_seconds is not None and (
            type(self.since_seconds) is not int or not 1 <= self.since_seconds <= 2147483647
        ):
            raise AppError("Log since-seconds must be a positive bounded integer.")
        if self.since_time is not None and (
            not isinstance(self.since_time, datetime) or self.since_time.utcoffset() is None
        ):
            raise AppError("Log since-time must be a timezone-aware datetime.")
        if self.since_seconds is not None and self.since_time is not None:
            raise AppError("Log since-seconds and since-time are mutually exclusive.")

    def parameters(self, container: str) -> dict[str, str]:
        api_segment(container)
        result = {
            "container": container,
            "follow": str(self.follow).lower(),
            "previous": str(self.previous).lower(),
            "timestamps": str(self.timestamps).lower(),
        }
        if self.tail_lines >= 0:
            result["tailLines"] = str(self.tail_lines)
        if self.since_seconds is not None:
            result["sinceSeconds"] = str(self.since_seconds)
        if self.since_time is not None:
            result["sinceTime"] = self.since_time.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return result


def log_containers(manifest: dict[str, Any]) -> tuple[str, ...]:
    spec = resource_object(manifest.get("spec"))
    names = []
    for field in ("containers", "initContainers", "ephemeralContainers"):
        values = spec.get(field) or []
        if not isinstance(values, list) or len(values) > 128:
            raise AppError("Invalid or excessive log container list.")
        for value in values:
            name = api_segment(resource_object(value).get("name"))
            if name in names:
                raise AppError("Duplicate container name in pod specification.")
            names.append(name)
    return tuple(names)


@dataclass(frozen=True)
class LogLine:
    text: str
    truncated: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.text, str)
            or len(self.text) > MAX_LINE * 6 + 32
            or type(self.truncated) is not bool
        ):
            raise AppError("Log line must contain bounded text and a boolean truncation flag.")

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8", errors="backslashreplace"))


class LogDecoder:
    """At most one bounded unfinished line; invalid UTF-8 is visibly replaced."""

    def __init__(self) -> None:
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.pending = ""
        self.truncated = False
        self.private_key = False
        self.key_end = False
        self.marker_tail = ""
        self.finished = False

    def _line(self) -> LogLine:
        raw = self.pending.removesuffix("\r")
        text = "[REDACTED KEY]" if self.private_key else sanitize_log_line(raw)
        if self.key_end:
            self.private_key = False
        self.key_end = False
        self.marker_tail = ""
        result = LogLine(text + (" [line truncated]" if self.truncated else ""), self.truncated)
        self.pending = ""
        self.truncated = False
        return result

    def feed(self, data: bytes, *, final: bool = False) -> tuple[LogLine, ...]:
        if self.finished or len(data) > MAX_CHUNK:
            raise AppError("Log decoder is closed or received an excessive chunk.")
        text = self.decoder.decode(data, final=final)
        lines = []
        parts = text.split("\n")
        for index, part in enumerate(parts):
            marker = self.marker_tail + part
            for match in _KEY_MARKER.finditer(marker):
                beginning = match.group(1).upper() == "BEGIN"
                self.private_key = self.private_key or beginning
                self.key_end = not beginning
            self.marker_tail = marker[-128:]
            available = MAX_LINE - len(self.pending)
            self.pending += part[:available]
            self.truncated = self.truncated or len(part) > available
            if index < len(parts) - 1:
                lines.append(self._line())
        if final:
            self.finished = True
            if self.pending or self.truncated:
                lines.append(self._line())
        return tuple(lines)


class LogBuffer:
    """Consumer-owned ring; no hidden transport queue or unbounded history."""

    def __init__(self, *, max_lines: int = MAX_LINES, max_bytes: int = MAX_BYTES) -> None:
        if (
            type(max_lines) is not int
            or not 1 <= max_lines <= MAX_LINES
            or type(max_bytes) is not int
            or not 1 <= max_bytes <= MAX_BYTES
        ):
            raise AppError("Log retention limits must be positive bounded integers.")
        self.max_lines, self.max_bytes = max_lines, max_bytes
        self.lines: deque[LogLine] = deque()
        self.size_bytes = 0
        self.dropped_lines = 0

    def append(self, line: LogLine) -> None:
        self.lines.append(line)
        self.size_bytes += line.size_bytes
        while len(self.lines) > self.max_lines or self.size_bytes > self.max_bytes:
            self.size_bytes -= self.lines.popleft().size_bytes
            self.dropped_lines += 1
