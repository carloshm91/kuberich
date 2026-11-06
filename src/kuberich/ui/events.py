"""Literal Event rows with separate object/group selection and stable viewports."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import ClassVar

from rich.text import Text
from textual import events, on
from textual.binding import Binding, BindingType
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from kuberich.domain.events import (
    EVENT_FIELDS,
    EventGroup,
    EventGroupRow,
    EventObjectRow,
    EventOptions,
    EventRow,
    EventSourceState,
)
from kuberich.domain.exports import TableSource
from kuberich.domain.navigation import Viewport
from kuberich.domain.resource_preferences import ColumnSpec
from kuberich.domain.table_values import Value
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.ui.keybindings import table_bindings
from kuberich.ui.presentation import FrameTable

EVENT_COLUMNS = ("namespace", *EVENT_FIELDS)
_WIDTHS = (16, 9, 22, 32, 30, 58, 32)


@dataclass(frozen=True, slots=True)
class EventCell:
    key: str
    text: str
    numeric: bool = False

    def __rich__(self) -> Text:
        value = safe_text(self.text)
        value.truncate(256, overflow="ellipsis")
        value.justify = "right" if self.numeric else "left"
        return value

    @property
    def plain(self) -> str:
        return self.__rich__().plain


def _key(row: EventRow) -> str:
    return row.uid if isinstance(row, EventObjectRow) else row.key


def _values(row: EventRow) -> tuple[Value, ...]:
    namespace = row.fact.namespace if isinstance(row, EventObjectRow) else row.group.key.namespace
    return (Value(namespace, namespace), *row.values)


def _tie(row: EventRow) -> tuple[str, str, str]:
    return (
        (row.fact.namespace, row.fact.name, row.uid)
        if isinstance(row, EventObjectRow)
        else (row.group.key.namespace, "", row.key)
    )


class EventsTable(FrameTable[EventCell]):
    _row_repaint_enabled = True
    BINDING_PROFILE = "events"
    BINDINGS: ClassVar[list[BindingType]] = [
        *table_bindings("events"),
        Binding("w", "toggle_warnings", "Warnings", show=False),
        Binding("t", "toggle_groups", "Groups", show=False),
    ]

    class SortChanged(Message):
        pass

    def __init__(
        self,
        *,
        id: str = "events",
        options_changed: Callable[[EventOptions], None] = lambda options: None,
    ) -> None:
        self._interaction_revision = 0
        super().__init__(id=id, cursor_type="row", zebra_stripes=True)
        self._rows: dict[str, EventRow] = {}
        self._revision = -1
        self._restoration = 0
        self._ordered_state: tuple[str, bool, int] | None = None
        self.sort_column = "last-seen"
        self.descending = True
        self.source: EventSourceState | None = None
        self.options = EventOptions()
        self.limited = False
        self.notices: tuple[str, ...] = ()
        self.options_changed = options_changed

    def setup(self) -> None:
        for key, width in zip(EVENT_COLUMNS, _WIDTHS, strict=True):
            self.add_column(key.upper(), key=key, width=width)

    def reset(self, revision: int) -> None:
        if revision != self._revision:
            self._revision = revision
            self._restoration += 1
            self._rows.clear()
            self.clear()
            self._ordered_state = None
            self.source, self.options = None, EventOptions()
            self.limited, self.notices = False, ()
            self.scroll_to(0, 0, animate=False, immediate=True)

    @property
    def visible_columns(self) -> tuple[ColumnSpec, ...]:
        return tuple(
            ColumnSpec(key, width=width) for key, width in zip(EVENT_COLUMNS, _WIDTHS, strict=True)
        )

    @property
    def sort_summary(self) -> str:
        return f"Sort {self.sort_column.upper()} {'↓' if self.descending else '↑'} · {self.navigation_hint('sort')} column · {self.navigation_hint('reverse_sort')} reverse"

    @property
    def selected_key(self) -> str | None:
        return (
            self.coordinate_to_cell_key(self.cursor_coordinate).row_key.value
            if self.row_count
            else None
        )

    @property
    def selected_uid(self) -> str | None:
        return self.selected_event_uid()

    def selected_event_uid(self) -> str | None:
        row = self._rows.get(self.selected_key or "")
        return row.uid if isinstance(row, EventObjectRow) else None

    def selected_group(self) -> EventGroup | None:
        row = self._rows.get(self.selected_key or "")
        return row.group if isinstance(row, EventGroupRow) else None

    def capture_viewport(self) -> Viewport:
        top = (
            self.coordinate_to_cell_key(
                Coordinate(min(int(self.scroll_y), self.row_count - 1), 0)
            ).row_key.value
            if self.row_count
            else None
        )
        return Viewport(self.selected_key, self.cursor_row, self.scroll_x, self.scroll_y, top)

    def restore_viewport(self, viewport: Viewport) -> None:
        destination = (
            self.get_row_index(viewport.selected)
            if viewport.selected in self._rows
            else min(viewport.index, max(0, self.row_count - 1))
        )
        self.move_cursor(row=destination, scroll=False)
        self._restoration += 1
        revision, restoration = self._revision, self._restoration
        selected, interaction = self.selected_key, self._interaction_revision
        layout = self._column_revision

        def restore_scroll() -> None:
            if (
                self._revision == revision
                and self._restoration == restoration
                and self.selected_key == selected
                and self._interaction_revision == interaction
                and self._column_revision == layout
            ):
                y = (
                    self.get_row_index(viewport.top) + viewport.y % 1
                    if viewport.top in self._rows
                    else viewport.y
                )
                self.scroll_to(viewport.x, y, animate=False, immediate=True, force=True)

        self.call_after_refresh(restore_scroll)

    def watch_cursor_coordinate(
        self, old_coordinate: Coordinate, new_coordinate: Coordinate
    ) -> None:
        self._interaction_revision += old_coordinate != new_coordinate
        super().watch_cursor_coordinate(old_coordinate, new_coordinate)

    def watch_scroll_x(self, old_value: float, new_value: float) -> None:
        self._interaction_revision += old_value != new_value
        super().watch_scroll_x(old_value, new_value)

    @on(events.MouseScrollDown)
    @on(events.MouseScrollUp)
    def vertical_scroll_input(self) -> None:
        # Native cursor placement can transiently scroll before layout clamps
        # it. Only actual wheel input revokes a pending viewport restoration.
        self._interaction_revision += 1

    def _sort(self) -> None:
        state = self.sort_column, self.descending, self._row_order_revision
        if state == self._ordered_state:
            return
        viewport = self.capture_viewport()
        index = EVENT_COLUMNS.index(self.sort_column)
        rows = sorted(self._rows.values(), key=_tie)
        known = [row for row in rows if _values(row)[index].sort is not None]
        unknown = [row for row in rows if _values(row)[index].sort is None]
        known.sort(
            key=lambda row: value if (value := _values(row)[index].sort) is not None else 0,
            reverse=self.descending,
        )
        wanted = tuple(_key(row) for row in (*known, *unknown))
        if wanted != tuple(row.key.value for row in self.ordered_rows):
            ranks = {key: index for index, key in enumerate(wanted)}
            self.sort("namespace", key=lambda cell: ranks[cell.key])
            self.restore_viewport(viewport)
        self._ordered_state = self.sort_column, self.descending, self._row_order_revision

    def restore_sort(self, column: str, descending: bool) -> None:
        self._interaction_revision += 1
        self.sort_column = column if column in EVENT_COLUMNS else "last-seen"
        self.descending = descending
        self._sort()
        self.post_message(self.SortChanged())

    def set_sort(self, column: str) -> None:
        self.restore_sort(column, not self.descending if column == self.sort_column else False)

    def action_next_sort(self) -> None:
        self.set_sort(
            EVENT_COLUMNS[(EVENT_COLUMNS.index(self.sort_column) + 1) % len(EVENT_COLUMNS)]
        )

    def action_reverse_sort(self) -> None:
        self.set_sort(self.sort_column)

    def action_scroll_home(self) -> None:
        self._interaction_revision += 1
        self.scroll_to(x=0, animate=False, immediate=True, force=True)

    def action_scroll_end(self) -> None:
        self._interaction_revision += 1
        self.scroll_to(x=self.max_scroll_x, animate=False, immediate=True, force=True)

    def action_toggle_warnings(self) -> None:
        self.options_changed(replace(self.options, warnings_only=not self.options.warnings_only))

    def action_toggle_groups(self) -> None:
        self.options_changed(replace(self.options, grouped=not self.options.grouped))

    @on(DataTable.HeaderSelected)
    def sort_header(self, event: DataTable.HeaderSelected) -> None:
        event.stop()
        if event.column_index >= 0:
            self.set_sort(event.column_key.value or "last-seen")

    async def apply_rows(
        self,
        rows: tuple[EventRow, ...],
        revision: int,
        current: Callable[[], bool],
        /,
        *,
        source: EventSourceState | None,
        options: EventOptions,
        limited: bool = False,
        notices: tuple[str, ...] = (),
    ) -> bool:
        if not current():
            return False
        self.reset(revision)
        layout = self._column_revision
        initial, interacted = not self.row_count, False
        incoming = {_key(row): row for row in rows}
        removals = [(key, None) for key in self._rows if key not in incoming]
        changes = [(key, row) for key, row in incoming.items() if self._rows.get(key) != row]
        patches = removals + changes
        for start in range(0, len(patches), 128):
            if not current() or layout != self._column_revision:
                return False
            viewport = self.capture_viewport()
            for key, row in patches[start : start + 128]:
                if row is None:
                    self.remove_row(key)
                    del self._rows[key]
                    continue
                cells = tuple(
                    EventCell(key, value.text, column == "occurrences")
                    for column, value in zip(EVENT_COLUMNS, _values(row), strict=True)
                )
                if key not in self._rows:
                    self.add_row(*cells, key=key, label=" ")
                else:
                    for column, cell, previous in zip(
                        EVENT_COLUMNS, cells, self.get_row(key), strict=True
                    ):
                        if cell != previous:
                            self.update_cell(key, column, cell)
                self._rows[key] = row
            self._ordered_state = None
            self.restore_viewport(viewport)
            interaction = self._interaction_revision
            await asyncio.sleep(0)
            interacted |= interaction != self._interaction_revision
        if not current() or layout != self._column_revision:
            return False
        self._sort()
        if initial and not interacted:
            self.restore_viewport(Viewport(None, 0, 0, 0, None))
        self.source, self.options = source, options
        self.limited, self.notices = limited, notices
        return True

    def capture_dump(
        self, *, columns: tuple[str, ...], concealed_columns: frozenset[int]
    ) -> TableSource:
        if (
            len(columns) != len(EVENT_COLUMNS)
            or tuple(column.value for column in self.columns) != EVENT_COLUMNS
            or any(
                type(index) is not int or not 0 <= index < len(columns)
                for index in concealed_columns
            )
            or self.row_count > 10000
        ):
            raise AppError("The Event table has no bounded consistent export projection.")
        keys = tuple(row.key.value or "" for row in self.ordered_rows)
        return TableSource(
            columns=columns,
            rows=tuple(
                tuple(
                    "[REDACTED COLUMN]" if index in concealed_columns else value.text
                    for index, value in enumerate(_values(self._rows[key]))
                )
                for key in keys
            ),
            row_keys=keys,
            concealed_columns=concealed_columns,
        )
