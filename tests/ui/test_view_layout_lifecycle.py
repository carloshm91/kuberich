"""A changed column layout invalidates yielded row batches and queued restores."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from textual.app import App

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable
from tests.ui.test_pods import rows as pod_rows
from tests.ui.test_standard_table import rows as standard_rows


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "namespaces", "standard"])
async def test_old_batches_cannot_repopulate_a_new_layout_or_restore_an_old_cursor(
    kind, monkeypatch
):
    if kind == "pods":
        table, rows = PodTable(), pod_rows(300)
        module = "kuberich.ui.pods.asyncio"
    elif kind == "namespaces":
        table = NamespaceTable()
        rows = tuple(
            NamespaceRow(f"ns-{n:03}", f"name-{n:03}", "Active", datetime(2026, 1, 1, tzinfo=UTC))
            for n in range(300)
        )
        module = "kuberich.ui.namespaces.asyncio"
    else:
        table, rows = StandardTable(), standard_rows(300)
        module = "kuberich.ui.standard.asyncio"

    class TableApp(App):
        def compose(self):
            yield table

        def on_mount(self):
            table.setup()
            table.focus()

    entered, release = asyncio.Event(), asyncio.Event()

    async def held_yield(delay):
        if not entered.is_set():
            entered.set()
            await release.wait()
        await asyncio.sleep(delay)

    monkeypatch.setattr(module, SimpleNamespace(sleep=held_yield))
    app = TableApp()
    async with app.run_test(size=(40, 12)) as pilot:
        task = asyncio.create_task(table.apply_rows(rows, 1, lambda: True))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            assert table.row_count == 128
            table.move_cursor(row=3)
            old_uid = table.selected_uid
            table.configure_view(ViewSpec((ColumnSpec("name", 16, "right"),), "age", True))
            release.set()
            assert not await task and table.row_count == 0
            assert await table.apply_rows(rows, 1, lambda: True)
            await pilot.pause()
            assert tuple(key.value for key in table.columns) == (
                ("NAME",) if kind == "namespaces" else ("name",)
            )
            assert table.selected_uid == old_uid and table.row_count == 300
            table.refresh_ages()  # The age field is hidden; sorting still uses its typed model.
            await pilot.press("G", "g", "j")
            assert table.cursor_row == 1
        finally:
            release.set()
            await task
