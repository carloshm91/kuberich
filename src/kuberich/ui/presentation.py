"""Session controls and bounded visual work for the terminal workspace."""

from dataclasses import dataclass
from typing import Self, TypeVar, cast

from rich.style import Style
from rich.text import Text
from textual.geometry import Region
from textual.strip import Strip
from textual.widgets import DataTable
from textual.widgets.data_table import ColumnKey, RowKey

from kuberich.security.presentation import safe_text

Cell = TypeVar("Cell")


@dataclass(frozen=True)
class TableCell:
    uid: str
    text: str
    numeric: bool = False

    def __rich__(self) -> Text:
        value = safe_text(self.text)
        value.truncate(256, overflow="ellipsis")
        value.justify = "right" if self.numeric else "left"
        return value

    def __str__(self) -> str:
        return self.__rich__().plain


class FrameTable(DataTable[Cell]):
    """Keep native cell sizing and reuse inherited style within one render frame."""

    _frame_style: Style | None = None
    _width_metadata_trusted = True

    def add_row(
        self,
        *cells: Cell,
        height: int | None = 1,
        key: str | None = None,
        label: str | Text | None = None,
    ) -> RowKey:
        result = super().add_row(*cells, height=height, key=key, label=label)
        if any(type(cell) is not TableCell for cell in cells):
            self._width_metadata_trusted = False
        return result

    def add_column(
        self,
        label: str | Text,
        *,
        width: int | None = None,
        key: str | None = None,
        default: Cell | None = None,
    ) -> ColumnKey:
        result = super().add_column(label, width=width, key=key, default=default)
        if default is not None and type(default) is not TableCell:
            self._width_metadata_trusted = False
        return result

    def clear(self, columns: bool = False) -> Self:
        result = super().clear(columns)
        self._width_metadata_trusted = True
        return result

    def update_cell(
        self,
        row_key: RowKey | str,
        column_key: ColumnKey | str,
        value: Cell,
        *,
        update_width: bool = False,
    ) -> None:
        requested_width = update_width
        if update_width and self._width_metadata_trusted:
            row_id = RowKey(row_key) if isinstance(row_key, str) else row_key
            column_id = ColumnKey(column_key) if isinstance(column_key, str) else column_key
            row, column = self.rows.get(row_id), self.columns.get(column_id)
            if (
                row is not None
                and column is not None
                and row.height == 1
                and column.auto_width
                and type(column.label) is Text
                and len(column.label.plain.splitlines()) <= 1
                and column.content_width == column.label.cell_len
            ):
                previous = self.get_cell(row_id, column_id)
                # Only evaluate our own immutable cells. Unknown renderables
                # retain native evaluation order and measurement behavior.
                previous_text = (
                    cast(TableCell, previous).__rich__()
                    if type(previous) is TableCell
                    else previous
                )
                replacement = (
                    cast(TableCell, value).__rich__() if type(value) is TableCell else value
                )
                if (
                    type(previous_text) is Text
                    and type(replacement) is Text
                    and "\n" not in previous_text.plain
                    and "\n" not in replacement.plain
                    and previous_text.cell_len <= column.content_width
                    and replacement.cell_len <= column.content_width
                ):
                    # The header determines this column's width before and after
                    # the edit. Native resizing would rescan every retained row;
                    # its ordinary repaint still runs through the public method.
                    update_width = False
        super().update_cell(row_key, column_key, value, update_width=update_width)
        if not requested_width or type(value) is not TableCell:
            # Unsized edits and mutable/custom renderables can invalidate widths
            # in other cells. Keep native rescans until all rows are cleared.
            self._width_metadata_trusted = False

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
