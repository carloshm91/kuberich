"""Reused projection rows avoid wide equality, while value changes remain visible."""

from dataclasses import replace

import pytest

from tests.ui.test_table_ordering import TableApp, identities


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
async def test_row_reuse_value_equivalence_and_changed_cells_preserve_the_actual_view(
    kind, monkeypatch
):
    app = TableApp(kind)
    rows = app.rows(256)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        assert await table.apply_rows(rows, 1, lambda: True)
        table.move_cursor(row=128)
        await pilot.pause()
        selected = table.selected_uid
        viewport = table.capture_viewport()
        ordered = identities(table)
        equality_calls = []
        row_type = type(rows[0])
        original = row_type.__eq__

        def observed(row, other):
            equality_calls.append(row.uid)
            return original(row, other)

        monkeypatch.setattr(row_type, "__eq__", observed)
        assert await table.apply_rows(rows, 1, lambda: True)
        assert equality_calls == []
        assert identities(table) == ordered
        assert table.selected_uid == selected
        assert table.capture_viewport().y == viewport.y

        equal_values = tuple(replace(row) for row in rows)
        assert await table.apply_rows(equal_values, 1, lambda: True)
        assert len(equality_calls) == len(rows)
        assert identities(table) == ordered and table.selected_uid == selected

        equality_calls.clear()
        key = "restarts" if kind == "pods" else "desired" if kind == "standard" else "c1"
        changed = app.changed(rows[128], key, 9876)
        edited = (*rows[:128], changed, *rows[129:])
        assert await table.apply_rows(edited, 1, lambda: True)
        await pilot.pause()
        assert equality_calls == [rows[128].uid]
        assert str(table.get_cell(changed.uid, key)) == "9876"
        assert identities(table) == ordered and table.selected_uid == selected
        assert table.capture_viewport().y == viewport.y
