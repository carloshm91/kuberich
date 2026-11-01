"""Immutable rendering-cache diagnostics without exposing retained log contents."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

LayoutRecord = tuple[object, Sequence[object], object, object]
VisibleRecord = tuple[object, object]


@dataclass(frozen=True, slots=True)
class LogCacheInfo:
    """Stored source-line layouts, visible strips and their source-identity validity."""

    layout_count: int
    visible_strip_count: int
    current_sources: bool


def log_cache_info(
    layouts: Mapping[int, LayoutRecord],
    visible: Mapping[tuple[int, int], VisibleRecord],
) -> LogCacheInfo:
    """Report counts and whether each visible strip uses its current cached source."""
    current = True
    for (number, offset), (line, _) in visible.items():
        layout = layouts.get(number)
        if layout is None or not 0 <= offset < len(layout[1]) or line is not layout[1][offset]:
            current = False
            break
    return LogCacheInfo(len(layouts), len(visible), current)
