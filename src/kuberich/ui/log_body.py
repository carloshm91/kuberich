"""Virtualized literal log rows, with scoped navigation and bounded layout cache."""

import asyncio
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable
from itertools import pairwise
from typing import ClassVar

from rich.cells import cell_len
from rich.control import strip_control_codes
from rich.segment import Segment
from rich.style import Style
from rich.text import Span, Text
from textual.binding import Binding, BindingType
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from kuberich.domain.log_view import LogEntry

VISIBLE_CACHE = 128


type PreparedEntry = tuple[int, str]
type Subline = tuple[str, int, tuple[tuple[int, int, bool], ...]]
type CachedLayout = tuple[
    tuple[object, ...], tuple[Subline, ...], tuple[int, tuple[Subline, ...]], int
]


class LogBody(ScrollView, can_focus=True):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("pageup,ctrl+b", "page(-1,False)", "Page up", show=False),
        Binding("pagedown,ctrl+f", "page(1,False)", "Page down", show=False),
        Binding("ctrl+u", "page(-1,True)", "Half page up", show=False),
        Binding("ctrl+d", "page(1,True)", "Half page down", show=False),
        Binding("home,ctrl+home,g", "beginning", "First line", show=False),
        Binding("end,ctrl+end,G", "latest", "Last line", show=False),
        Binding("left,h", "horizontal(-1)", "Left", show=False),
        Binding("right,l", "horizontal(1)", "Right", show=False),
    ]

    class NavigationChanged(Message):
        pass

    DEFAULT_CSS = "LogBody { height: 1fr; min-height: 1; background: $surface; }"

    def __init__(self) -> None:
        super().__init__(id="log-body")
        self.follow = True
        self.column_lock = False
        self.programmatic = False
        self.rows: list[tuple[int, tuple[Subline, ...]]] = []
        self.starts: list[int] = []
        self.matches: list[int] = []
        self._cache: dict[int, CachedLayout] = {}
        self._alternates: dict[int, CachedLayout] = {}
        self._wrapped_context: tuple[int, bool, str] | None = None
        self._strips: OrderedDict[tuple[int, int], tuple[Subline, Strip]] = OrderedDict()
        self._layout_style = Style.null()
        self.render_batches = 0
        self.navigation_revision = 0

    @property
    def first_visible(self) -> tuple[int, int] | None:
        if not self.rows:
            return None
        index = min(len(self.rows) - 1, bisect_right(self.starts, int(self.scroll_y)) - 1)
        return self.rows[index][0], int(self.scroll_y) - self.starts[index]

    def watch_virtual_size(self, size: Size) -> None:
        # Textual 8's ScrollView may keep unchanged outer geometry when content
        # grows. Synchronize scrollbars/bounds explicitly before scroll_to,
        # whose permission check otherwise sees the old (hidden) scrollbars.
        self._scroll_update(size)

    async def load(
        self,
        entries: tuple[LogEntry | PreparedEntry, ...],
        *,
        wrap: bool,
        timestamps: bool,
        query: str,
        marks: frozenset[int],
        valid: Callable[[], bool],
    ) -> None:
        if not valid():
            return
        retained = {entry.number if isinstance(entry, LogEntry) else entry[0] for entry in entries}
        self._cache = {number: value for number, value in self._cache.items() if number in retained}
        self._alternates = {
            number: value for number, value in self._alternates.items() if number in retained
        }
        width = max(1, self.scrollable_content_region.width)
        style = self.rich_style
        keys = (
            (width if wrap else None, timestamps, query, False),
            (width if wrap else None, timestamps, query, True),
        )
        if wrap:
            self._wrapped_context = width, timestamps, query
        prime_wrap = not wrap and self._wrapped_context == (width, timestamps, query)
        wrapped_keys = ((width, timestamps, query, False), (width, timestamps, query, True))
        rows, starts, matches = [], [], []
        height, maximum_width = 0, width
        prepared = 0
        for index, entry in enumerate(entries):
            number = entry.number if isinstance(entry, LogEntry) else entry[0]
            value: str | None = None
            key = keys[number in marks]
            cached = self._cache.get(number)
            if cached is None or cached[0] != key:
                alternate = self._alternates.get(number)
                if alternate is not None and alternate[0] == key:
                    if cached is not None:
                        self._alternates[number] = cached
                    cached = alternate
                    self._cache[number] = cached
                    strips = alternate[1]
                else:
                    value = entry.text(timestamps) if isinstance(entry, LogEntry) else entry[1]
                    strips = self._prepare(value, number in marks, wrap, width, query, style)
                    prepared += 1
                    if cached is not None:
                        self._alternates[number] = cached
                    cached = key, strips, (number, strips), max(line[1] for line in strips)
                    self._cache[number] = cached
            else:
                strips = cached[1]
            if prime_wrap:
                wrapped_key = wrapped_keys[number in marks]
                alternate = self._alternates.get(number)
                if alternate is None or alternate[0] != wrapped_key:
                    if prepared == 16:
                        await asyncio.sleep(0)
                        prepared = 0
                        if not valid():
                            return
                    if value is None:
                        value = entry.text(timestamps) if isinstance(entry, LogEntry) else entry[1]
                    prepared_strips = self._prepare(
                        value, number in marks, True, width, query, style
                    )
                    self._alternates[number] = (
                        wrapped_key,
                        prepared_strips,
                        (number, prepared_strips),
                        max(line[1] for line in prepared_strips),
                    )
                    prepared += 1
            rows.append(cached[2])
            starts.append(height)
            height += len(strips)
            maximum_width = max(maximum_width, cached[3])
            if query:
                if value is None:
                    value = entry.text(timestamps) if isinstance(entry, LogEntry) else entry[1]
                if query in value:
                    matches.append(number)
            # New Rich layouts keep their existing sixteen-row turns. Reused
            # immutable layouts need fewer scheduler turns for the same history.
            if index % 128 == 0 or prepared == 16:
                await asyncio.sleep(0)
                prepared = 0
                if not valid():
                    return
        if not valid():
            return
        anchor, x = self.first_visible, self.scroll_x
        self.rows, self.starts, self.matches = rows, starts, matches
        if self._layout_style != style:
            self._strips.clear()
        self._layout_style = style
        for visible_key, (line, _) in tuple(self._strips.items()):
            cached_line = self._cache.get(visible_key[0])
            if (
                cached_line is None
                or visible_key[1] >= len(cached_line[1])
                or cached_line[1][visible_key[1]] is not line
            ):
                del self._strips[visible_key]
        self.programmatic = True
        try:
            self.virtual_size = Size(maximum_width, height)
        finally:
            self.programmatic = False
        revision = self.navigation_revision

        def restore() -> None:
            if not valid() or revision != self.navigation_revision:
                return
            self.programmatic = True
            try:
                if self.follow:
                    self.scroll_to(
                        x=x if self.column_lock else 0,
                        y=self.max_scroll_y,
                        animate=False,
                        immediate=True,
                    )
                elif anchor is not None:
                    self._restore_anchor(anchor, x, rows, starts)
            finally:
                self.programmatic = False

        # The current viewport bounds were synchronized by watch_virtual_size.
        # Follow its new tail before the first paint; recheck after layout in
        # case a scrollbar/resize changes the available viewport geometry.
        if self.follow:
            restore()
        self.call_after_refresh(restore)
        self.render_batches += 1
        self.refresh()

    def _prepare(
        self, value: str, marked: bool, wrap: bool, width: int, query: str, style: Style
    ) -> tuple[Subline, ...]:
        prefix = "* " if marked else "  "
        plain = prefix + value
        if not wrap and not query:
            plain = strip_control_codes(plain)
            strips: tuple[Subline, ...] = ((plain, cell_len(plain), ()),)
        else:
            text = Text(plain, style=style)
            if query:
                text.highlight_words([query], style="reverse bold", case_sensitive=True)
            parts = text.wrap(self.app.console, width, overflow="fold") if wrap else [text]
            rendered = []
            for part in parts:
                plain = part.plain
                ranges = tuple(
                    (span.start, span.end, span.style == "reverse bold") for span in part.spans
                )
                if ranges:
                    points = sorted(
                        {
                            0,
                            len(plain),
                            *(point for start, end, _ in ranges for point in (start, end)),
                        }
                    )
                    cells = sum(cell_len(plain[start:end]) for start, end in pairwise(points))
                else:
                    cells = cell_len(plain)
                rendered.append((plain, cells, ranges))
            strips = tuple(rendered)
        return strips

    def _restore_anchor(
        self,
        anchor: tuple[int, int],
        x: float,
        rows: list[tuple[int, tuple[Subline, ...]]],
        starts: list[int],
    ) -> None:
        numbers = [number for number, _ in rows]
        position = numbers.index(anchor[0]) if anchor[0] in numbers else 0
        offset = min(anchor[1], len(rows[position][1]) - 1) if rows else 0
        y = starts[position] + offset if starts else 0
        self.scroll_to(x=x, y=y, animate=False, immediate=True)

    def invalidate(self) -> None:
        self._cache.clear()
        self._alternates.clear()
        self._wrapped_context = None
        self._strips.clear()

    def clear(self) -> None:
        self.rows.clear()
        self.starts.clear()
        self.matches.clear()
        self.invalidate()
        self.virtual_size = Size(0, 0)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        style = self.rich_style
        if style != self._layout_style:
            self._strips.clear()
            self._layout_style = style
        x, offset = self.scroll_offset
        position = offset + y
        index = bisect_right(self.starts, position) - 1
        if index < 0 or index >= len(self.rows):
            return Strip.blank(self.size.width, style)
        strips = self.rows[index][1]
        line = position - self.starts[index]
        if line >= len(strips):
            return Strip.blank(self.size.width, style)
        rendered = strips[line]
        key = self.rows[index][0], line
        cached = self._strips.get(key)
        if cached is None or cached[0] is not rendered:
            plain, cells, ranges = rendered
            text = Text(
                plain,
                style=self._layout_style,
                spans=[
                    Span(start, end, "reverse bold" if highlighted else self._layout_style)
                    for start, end, highlighted in ranges
                ],
            )
            strip = Strip(
                Segment.apply_style(text.render(self.app.console), self._layout_style), cells
            )
            self._strips[key] = rendered, strip
            if len(self._strips) > VISIBLE_CACHE:
                self._strips.popitem(last=False)
        else:
            strip = cached[1]
        self._strips.move_to_end(key)
        return strip.crop_extend(x, x + self.size.width, style)

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if not self.programmatic and new_value < old_value <= self.max_scroll_y:
            self.follow = False
            self.navigation_revision += 1
            self.post_message(self.NavigationChanged())

    def action_move(self, direction: int) -> None:
        self.navigation_revision += 1
        if direction < 0:
            self.follow = False
        self.scroll_to(y=self.scroll_y + direction, animate=False, immediate=True)
        self.post_message(self.NavigationChanged())

    def action_page(self, direction: int, half: bool) -> None:
        self.navigation_revision += 1
        if direction < 0:
            self.follow = False
        amount = max(1, self.scrollable_content_region.height // (2 if half else 1))
        self.scroll_to(y=self.scroll_y + direction * amount, animate=False, immediate=True)
        self.post_message(self.NavigationChanged())

    def action_beginning(self) -> None:
        self.navigation_revision += 1
        self.follow = False
        self.scroll_to(y=0, animate=False, immediate=True)
        self.post_message(self.NavigationChanged())

    def action_latest(self) -> None:
        self.navigation_revision += 1
        self.follow = True
        self.scroll_to(y=self.max_scroll_y, animate=False, immediate=True)
        self.post_message(self.NavigationChanged())

    def action_horizontal(self, direction: int) -> None:
        self.navigation_revision += 1
        self.scroll_to(x=self.scroll_x + direction, animate=False, immediate=True)

    def jump(self, number: int) -> None:
        numbers = [number for number, _ in self.rows]
        if number in numbers:
            self.navigation_revision += 1
            self.follow = False
            self.scroll_to(y=self.starts[numbers.index(number)], animate=False, immediate=True)
            self.post_message(self.NavigationChanged())
