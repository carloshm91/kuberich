"""Region repaint preserves native pixels, scroll and fallback behavior."""

import pytest
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable

from kuberich.ui.presentation import FrameTable, TableCell
from tests.ui.test_table_widths import WidthTables, widths


class OwnedTable(FrameTable):
    _row_repaint_enabled = True


class OwnedTables(WidthTables):
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield OwnedTable(id="framed", cursor_type="row")
            yield DataTable(id="native", cursor_type="row")


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [0, 199])
@pytest.mark.parametrize("fixed", ["none", "rows", "columns"])
async def test_visible_and_offscreen_updates_match_native_after_scroll_resize_and_frozen_cells(
    monkeypatch, target, fixed
):
    app = OwnedTables()
    async with app.run_test(size=(100, 24)) as pilot:
        framed = app.query_one("#framed", FrameTable)
        native = app.query_one("#native", DataTable)
        for table in (framed, native):
            table.add_column("NAMESPACE", key="namespace")
            table.add_column("RESTARTS", key="count")
            for index in range(200):
                uid = f"row-{index:03}"
                table.add_row(TableCell(uid, "team"), TableCell(uid, "0"), key=uid)
            table.fixed_rows = int(fixed == "rows")
            table.fixed_columns = int(fixed == "columns")
            table.move_cursor(row=120)
        app.set_focus(None)
        await pilot.pause()
        calls = []
        original = DataTable.refresh

        def observed(table, *regions, **kwargs):
            calls.append((table.id, regions, kwargs))
            return original(table, *regions, **kwargs)

        monkeypatch.setattr(DataTable, "refresh", observed)
        uid = f"row-{target:03}"
        for table in (framed, native):
            table.update_cell(uid, "count", TableCell(uid, "123"), update_width=True)
        framed_calls = [regions for identifier, regions, _ in calls if identifier == "framed"]
        assert not framed_calls if fixed == "none" else framed_calls == [()]
        assert [regions for identifier, regions, _ in calls if identifier == "native"] == [()]
        for table in (framed, native):
            table.move_cursor(row=target)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert framed.render_lines(framed.content_region.at_offset((0, 0))) == native.render_lines(
            native.content_region.at_offset((0, 0))
        )
        await pilot.resize_terminal(80, 18)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert framed.render_lines(framed.content_region.at_offset((0, 0))) == native.render_lines(
            native.content_region.at_offset((0, 0))
        )


@pytest.mark.asyncio
async def test_visible_header_bounded_edit_refreshes_one_native_row_and_growth_refreshes_the_table(
    monkeypatch,
):
    app = OwnedTables()
    async with app.run_test(size=(100, 24)) as pilot:
        table = app.query_one("#framed", FrameTable)
        table.add_column("RESTARTS", key="count")
        table.add_row(TableCell("row", "0"), key="row")
        await pilot.pause()
        calls = []
        original = DataTable.refresh

        def observed(widget, *regions, **kwargs):
            calls.append((widget.id, regions))
            return original(widget, *regions, **kwargs)

        monkeypatch.setattr(DataTable, "refresh", observed)
        table.update_cell("row", "count", TableCell("row", "123"), update_width=True)
        assert len(calls) == 1 and calls[0][0] == "framed" and len(calls[0][1]) == 1
        assert calls[0][1][0].height == 1
        calls.clear()
        table.update_cell("row", "count", TableCell("row", "1" * 30), update_width=True)
        assert calls == [("framed", ())]
        await pilot.pause()
        assert table.ordered_columns[0].content_width == 30


@pytest.mark.asyncio
async def test_native_update_failure_does_not_suppress_later_refresh(monkeypatch):
    app = OwnedTables()
    async with app.run_test() as pilot:
        table = app.query_one("#framed", FrameTable)
        table.add_column("RESTARTS", key="count")
        table.add_row(TableCell("row", "0"), key="row")
        await pilot.pause()
        update = DataTable.update_cell

        def broken(*args, **kwargs):
            raise RuntimeError("owned native failure")

        monkeypatch.setattr(DataTable, "update_cell", broken)
        with pytest.raises(RuntimeError, match="owned native failure"):
            table.update_cell("row", "count", TableCell("row", "123"), update_width=True)
        monkeypatch.setattr(DataTable, "update_cell", update)
        table.update_cell("row", "count", TableCell("row", "321"), update_width=True)
        table.refresh(layout=True)
        await pilot.pause()
        assert str(table.get_cell("row", "count")) == "321"
        assert not table._scoped_cell_refresh
