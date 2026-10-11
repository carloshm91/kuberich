"""Bounded immutable terminal rows and a deliberate frozen local review window."""

from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.errors import AppError

HISTORY_ROWS = 1000
COPY_BYTES = 65536
SEARCH_CHARACTERS = 256


class TerminalCell(NamedTuple):
    data: str
    fg: str
    bg: str
    bold: bool
    italics: bool
    underscore: bool
    strikethrough: bool
    reverse: bool


@dataclass(frozen=True, slots=True)
class TerminalRow:
    cells: tuple[TerminalCell, ...]
    text: str


class TerminalHistory:
    def __init__(self, limit: int = HISTORY_ROWS) -> None:
        if type(limit) is not int or not 1 <= limit <= HISTORY_ROWS:
            raise AppError("Terminal history limit must be between 1 and 1000 rows.")
        self.rows: deque[TerminalRow] = deque(maxlen=limit)
        self.dropped = 0

    def append(self, row: TerminalRow) -> None:
        if len(self.rows) == self.rows.maxlen:
            self.dropped += 1
        self.rows.append(row)

    def clear(self) -> None:
        self.rows.clear()
        self.dropped = 0


class TerminalReview:
    """Snapshot references stay bounded even while the live ring continues scrolling."""

    def __init__(self, rows: tuple[TerminalRow, ...]) -> None:
        if not rows:
            raise AppError("No terminal output is available to review.")
        self.rows = rows
        self.cursor = len(rows) - 1
        self.top = 0
        self.mark: int | None = None
        self.query = ""

    def fit(self, height: int) -> None:
        height = max(1, height)
        self.top = min(self.top, self.cursor)
        self.top = max(self.top, self.cursor - height + 1)
        self.top = min(self.top, max(0, len(self.rows) - height))

    def move(self, delta: int, height: int) -> None:
        self.cursor = min(len(self.rows) - 1, max(0, self.cursor + delta))
        self.fit(height)

    def edge(self, end: bool, height: int) -> None:
        self.cursor = len(self.rows) - 1 if end else 0
        self.fit(height)

    def toggle_mark(self) -> None:
        self.mark = self.cursor if self.mark is None else None

    def selected(self, index: int) -> bool:
        first, last = sorted((self.cursor, self.cursor if self.mark is None else self.mark))
        return first <= index <= last

    def find(self, query: str, *, backwards: bool = False, height: int) -> bool:
        if len(query) > SEARCH_CHARACTERS:
            raise AppError("Search accepts at most 256 characters.")
        self.query = query
        if not query:
            return False
        step = -1 if backwards else 1
        needle = query.casefold()
        for offset in range(1, len(self.rows) + 1):
            index = (self.cursor + step * offset) % len(self.rows)
            if needle in self.rows[index].text.casefold():
                self.cursor = index
                self.fit(height)
                return True
        return False

    def copy(self) -> str:
        first, last = sorted((self.cursor, self.cursor if self.mark is None else self.mark))
        rows = self.rows[first : last + 1]
        if sum(len(row.text.encode("utf-8")) for row in rows) + len(rows) - 1 > COPY_BYTES:
            raise AppError("Selection is too large; copy at most 64 KiB at a time.")
        text = sanitize_text("\n".join(row.text for row in rows), allow_newlines=True)
        if len(text.encode("utf-8")) > COPY_BYTES:
            raise AppError("Escaped selection is too large; select fewer rows.")
        return text
