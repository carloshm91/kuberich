"""Typed shared table under patches, large batches, sorting and identity replacement."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from kubetrol.config.schema import Settings
from kubetrol.domain.registry import RESOURCE_ALIASES, resource_row
from kubetrol.ui.app import KubetrolApp
from tests.support.standard import row_record


def rows(count=80):
    definition = RESOURCE_ALIASES["deploy"]
    return tuple(
        resource_row(
            row_record(
                definition,
                name=f"owned-{i:03}",
                overrides={"spec": {"replicas": i}, "status": {"readyReplicas": i}},
            ),
            definition,
        )
        for i in range(count)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_uid_scroll_sort_changes_deletion_and_replacement(size, monkeypatch):
    app = KubetrolApp(Settings(), logging.Logger("shared-table", level=100))
    async with app.run_test(size=size) as pilot:
        table = app.standard_table
        app._display_resource("deployments")
        app.query_one("#empty-state").display = False
        table.set_class(True, "populated")
        original = rows()
        assert await table.apply_rows(original, 1, lambda: True)
        await pilot.pause()
        await pilot.press("pagedown", "pagedown")
        await pilot.pause()
        before = table.capture_viewport()
        changed = resource_row(
            row_record(
                RESOURCE_ALIASES["deploy"],
                name=original[0].name,
                overrides={"spec": {"replicas": 1000}, "status": {"readyReplicas": 900}},
            ),
            RESOURCE_ALIASES["deploy"],
        )
        assert await table.apply_rows((changed, *original[1:]), 1, lambda: True)
        await pilot.pause()
        assert table.capture_viewport() == before
        assert str(table.get_cell(changed.uid, "ready")) == "900"
        assert await table.apply_rows((changed, *original[1:]), 1, lambda: True)
        await pilot.press("s", "S")
        assert table.sort_column == "ready" and table.descending
        assert [table._rows[r.key.value].values[2].sort for r in table.ordered_rows] == sorted(
            [row.values[2].sort for row in (changed, *original[1:])], reverse=True
        )
        assert table.selected_uid == before.selected
        remaining = tuple(row for row in (changed, *original[1:]) if row.uid != before.selected)
        assert await table.apply_rows(remaining, 1, lambda: True)
        assert table.selected_uid != before.selected
        recreated = replace(original[0], uid="replacement", name="owned-000")
        assert await table.apply_rows((recreated, *remaining[1:]), 1, lambda: True)
        assert "replacement" in table._rows
        table.restore_sort("invalid-column", True)
        assert table.sort_column == "name"
        table.restore_sort("name", False)
        await pilot.pause()
        assert await pilot.click("#standard-resources", offset=(2, 0))
        assert table.sort_column == "namespace"
        assert await table.apply_rows((), 1, lambda: True)
        assert table.row_count == 0 and table.selected_uid is None
        table.refresh_ages()
        assert not await table.apply_rows(original, 1, lambda: False)
        table.configure(RESOURCE_ALIASES["pv"])
        assert not table.row_count and "namespace" not in [column.value for column in table.columns]


@pytest.mark.asyncio
async def test_bounded_batch_aborts_previous_generation_and_age_refresh(monkeypatch):
    app = KubetrolApp(Settings(), logging.Logger("shared-table", level=100))
    async with app.run_test() as pilot:
        table = app.standard_table
        app._display_resource("deployments")
        alive = [True]
        add = table.add_row

        def insert(*args, **kwargs):
            value = add(*args, **kwargs)
            if table.row_count == 128:
                asyncio.get_running_loop().call_soon(lambda: alive.__setitem__(0, False))
            return value

        monkeypatch.setattr(table, "add_row", insert)
        assert not await table.apply_rows(rows(300), 1, lambda: alive[0])
        assert table.row_count == 128
        assert await table.apply_rows(rows(2), 2, lambda: True)
        assert table.row_count == 2 and table.selected_uid == rows(2)[0].uid
        clock = datetime(2026, 10, 1, tzinfo=UTC)
        monkeypatch.setattr("kubetrol.ui.standard.utc_now", lambda: clock)
        table.refresh_ages()
        assert str(table.get_cell(table.selected_uid, "age")) == "0s"
        clock += timedelta(seconds=61)
        table.refresh_ages()
        assert str(table.get_cell(table.selected_uid, "age")) == "1m"
        table.refresh_ages()
        calls = 0

        def current():
            nonlocal calls
            calls += 1
            return calls < 3

        assert not await table.apply_rows(rows(3), 2, current)
        table.configure(table.definition)
        await pilot.pause()
