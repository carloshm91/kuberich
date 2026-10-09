"""Session controls and bounded visual work for the terminal workspace."""

from dataclasses import dataclass
from typing import TypeVar

from rich.style import Style
from textual.geometry import Region
from textual.strip import Strip
from textual.widgets import DataTable

Cell = TypeVar("Cell")


class FrameTable(DataTable[Cell]):
    """Resolve the inherited visual style once within a synchronous render frame."""

    _frame_style: Style | None = None

    @property
    def rich_style(self) -> Style:
        return self._frame_style if self._frame_style is not None else super().rich_style

    def render_lines(self, crop: Region) -> list[Strip]:
        previous = self._frame_style
        if previous is None:
            self._frame_style = super().rich_style
        try:
            return super().render_lines(crop)
        finally:
            # Nested rendering shares this frame, and failures must not keep a
            # style alive across a later theme, visibility or layout change.
            self._frame_style = previous


@dataclass(frozen=True)
class Presentation:
    headless: bool = False
    logoless: bool = False
    crumbsless: bool = False


DEFAULT_PRESENTATION = Presentation()
