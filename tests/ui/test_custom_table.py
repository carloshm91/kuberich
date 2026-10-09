"""Generic column changes must preserve a stable current selection and typed sort."""

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.custom import CustomLayout
from kuberich.domain.resources import ServerColumn
from kuberich.ui.custom import CustomTable
from tests.support.tables import custom_resource
from tests.unit.test_custom_layout import captured


class TableApp(App):
    def __init__(self):
        super().__init__()
        self.table = CustomTable()

    def compose(self) -> ComposeResult:
        yield self.table


@pytest.mark.asyncio
async def test_generic_table_typed_sort_literal_headers_and_compatible_reconfiguration():
    app = TableApp()
    async with app.run_test(size=(80, 24)) as pilot:
        table = app.table
        assert "NAME" in table.sort_summary
        table.setup()
        assert not table.columns
        headers = (ServerColumn("[bold]Level", "integer"), ServerColumn("Enabled", "boolean"))
        layout = CustomLayout.build(custom_resource(), headers)
        table.configure_layout(layout, 1)
        table.configure_layout(layout, 1)
        assert table.columns["c1"].label.plain == "[bold]Level"
        rows = tuple(
            layout.row(captured(headers, (number, True), name=name))
            for name, number in (("ten", 10), ("two", 2))
        )
        assert await table.apply_rows(rows, 1, lambda: True)
        table.set_sort("c1")
        assert "[bold]Level" in table.sort_summary
        assert [row.key.value for row in table.ordered_rows] == ["owned-two", "owned-ten"]
        table.move_cursor(row=1)
        before = table.selected_uid
        changed = layout.configure(("c1",))
        table.configure_layout(changed, 1)
        await table.apply_rows(
            tuple(
                changed.row(captured(headers, (number, True), name=name))
                for name, number in (("ten", 10), ("two", 2))
            ),
            1,
            lambda: True,
        )
        await pilot.pause()
        assert table.selected_uid == before and table.sort_column == "c1"
        changed_headers = (ServerColumn("Different", "boolean"),)
        replacement = CustomLayout.build(custom_resource(), changed_headers)
        table.configure_layout(replacement, 1)
        await table.apply_rows(
            tuple(
                replacement.row(captured(changed_headers, (True,), name=name))
                for name in ("ten", "two")
            ),
            1,
            lambda: True,
        )
        await pilot.pause()
        assert table.selected_uid == before and table.sort_column == "name"
        stale = replace(replacement, resource=custom_resource(version="v1beta1"))
        table.configure_layout(stale, 2)
        assert table._pending_viewport is None
        assert not await table.apply_rows((), 2, lambda: False)
        await table.apply_rows((), 2, lambda: True)
        assert not table.row_count
