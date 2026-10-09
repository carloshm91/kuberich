"""Virtualized literal log rows, with scoped navigation and bounded layout cache."""

import asyncio
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import ClassVar

from rich.segment import Segment
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

from kuberich.domain.log_view import LogEntry

VISIBLE_CACHE = 128


@dataclass(frozen=True, slots=True)
class _RenderedLine:
    segments: tuple[Segment, ...]
    cell_length: int

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments)

    def __iter__(self) -> Iterator[Segment]:
        return iter(self.segments)


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
        self.rows: list[tuple[int, tuple[_RenderedLine, ...]]] = []
        self.starts: list[int] = []
        self.matches: list[int] = []
        self._cache: dict[int, tuple[tuple[object, ...], tuple[_RenderedLine, ...]]] = {}
        self._strips: OrderedDict[tuple[int, int], tuple[_RenderedLine, Strip]] = OrderedDict()
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
        entries: tuple[LogEntry, ...],
        *,
        wrap: bool,
        timestamps: bool,
        query: str,
        marks: frozenset[int],
        valid: Callable[[], bool],
    ) -> None:
        if not valid():
            return
        retained = {entry.number for entry in entries}
        self._cache = {number: value for number, value in self._cache.items() if number in retained}
        width = max(1, self.scrollable_content_region.width)
        style = self.rich_style
        rows, starts, matches = [], [], []
        height, maximum_width = 0, width
        for index, entry in enumerate(entries):
            value = entry.text(timestamps)
            key = (width if wrap else None, timestamps, query, entry.number in marks)
            cached = self._cache.get(entry.number)
            if cached is None or cached[0] != key:
                prefix = "* " if entry.number in marks else "  "
                text = Text(prefix + value, style=style)
                if query:
                    text.highlight_words([query], style="reverse bold", case_sensitive=True)
                parts = text.wrap(self.app.console, width, overflow="fold") if wrap else [text]
                rendered = []
                for part in parts:
                    segments = tuple(Segment.apply_style(part.render(self.app.console), style))
                    rendered.append(
                        _RenderedLine(segments, sum(segment.cell_length for segment in segments))
                    )
                strips = tuple(rendered)
                self._cache[entry.number] = key, strips
            else:
                strips = cached[1]
            rows.append((entry.number, strips))
            starts.append(height)
            height += len(strips)
            maximum_width = max(maximum_width, *(strip.cell_length for strip in strips))
            if query and query in value:
                matches.append(entry.number)
            if index % 16 == 0:
                await asyncio.sleep(0)
                if not valid():
                    return
        if not valid():
            return
        anchor, x = self.first_visible, self.scroll_x
        self.rows, self.starts, self.matches = rows, starts, matches
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

        self.call_after_refresh(restore)
        self.render_batches += 1
        self.refresh()

    def _restore_anchor(
        self,
        anchor: tuple[int, int],
        x: float,
        rows: list[tuple[int, tuple[_RenderedLine, ...]]],
        starts: list[int],
    ) -> None:
        numbers = [number for number, _ in rows]
        position = numbers.index(anchor[0]) if anchor[0] in numbers else 0
        offset = min(anchor[1], len(rows[position][1]) - 1) if rows else 0
        y = starts[position] + offset if starts else 0
        self.scroll_to(x=x, y=y, animate=False, immediate=True)

    def invalidate(self) -> None:
        self._cache.clear()
        self._strips.clear()

    def clear(self) -> None:
        self.rows.clear()
        self.starts.clear()
        self.matches.clear()
        self.invalidate()
        self.virtual_size = Size(0, 0)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        x, offset = self.scroll_offset
        position = offset + y
        index = bisect_right(self.starts, position) - 1
        if index < 0 or index >= len(self.rows):
            return Strip.blank(self.size.width, self.rich_style)
        strips = self.rows[index][1]
        line = position - self.starts[index]
        if line >= len(strips):
            return Strip.blank(self.size.width, self.rich_style)
        rendered = strips[line]
        key = self.rows[index][0], line
        cached = self._strips.get(key)
        if cached is None or cached[0] is not rendered:
            strip = Strip(rendered.segments, rendered.cell_length)
            self._strips[key] = rendered, strip
            if len(self._strips) > VISIBLE_CACHE:
                self._strips.popitem(last=False)
        else:
            strip = cached[1]
        self._strips.move_to_end(key)
        return strip.crop_extend(x, x + self.size.width, self.rich_style)

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
