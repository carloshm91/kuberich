"""Artifact rows repaint when native idle measurement grows their columns."""

import asyncio

import pytest
from rich.text import Text
from textual.app import App

from kuberich.ui.artifact_browser import ArtifactTable
from tests.support.export_browser_geometry import seed_browser_artifact
from tests.support.export_ui import service_for
from tests.support.workspace import wait_for
from tests.ui.test_export_lifecycle_regressions import BrowserHost


class TableHost(App):
    def __init__(self, table):
        super().__init__()
        self.table = table

    def compose(self):
        yield self.table


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_artifact_table_repaints_row_measured_after_its_first_paint(size):
    table = ArtifactTable(cursor_type="row", show_cursor=False)
    table.styles.height = "1fr"
    async with TableHost(table).run_test(size=size) as pilot:
        table.add_columns("Filename", "Format")
        await pilot.pause()
        assert await table.wait_for_refresh()
        original_size = table.size
        table.add_row(Text("owned-export.txt"), Text("text"), key="owned")
        assert table.ordered_columns[0].content_width == len("Filename")
        assert "owned-ex " in table.render_line(1).text
        assert await table.wait_for_refresh()
        await pilot.pause()
        assert table.size == original_size
        assert table.ordered_columns[0].content_width == len("owned-export.txt")
        assert "owned-export.txt" in table.render_line(1).text


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_browser_scan_and_filter_rebuild_repaint_early_measured_row(
    tmp_path, monkeypatch, size
):
    directory = tmp_path / "exports"
    artifact = seed_browser_artifact(directory)
    service = service_for(tmp_path)
    scan_ready = asyncio.Event()
    first_paints = []
    scan = service.scan
    add_row = ArtifactTable.add_row

    async def held_scan(path):
        await scan_ready.wait()
        return await scan(path)

    def early_paint(table, *cells, **kwargs):
        key = add_row(table, *cells, **kwargs)
        first_paints.append(table.render_line(1).text)
        return key

    monkeypatch.setattr(service, "scan", held_scan)
    monkeypatch.setattr(ArtifactTable, "add_row", early_paint)
    app = BrowserHost(service, directory)
    async with app.run_test(size=size) as pilot:
        try:
            browser = app.browser
            await wait_for(lambda: bool(browser.table.columns) and browser.table.size.height > 1)
            await pilot.pause()
            scan_ready.set()
            await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
            for value in ("", "no-match", ""):
                browser.filter.value = value
                await pilot.pause()
                assert await browser.table.wait_for_refresh()
                if value != "no-match":
                    assert browser.table.row_count == 1
                    assert browser.table.get_row_at(0)[0].plain == artifact.name
                    assert browser.table.ordered_columns[0].content_width >= len(artifact.name)
                    assert artifact.name in browser.table.render_line(1).text
                else:
                    assert browser.table.row_count == 0
                    assert artifact.name not in browser.table.render_line(1).text
            assert first_paints and "owned-ex " in first_paints[0]
        finally:
            scan_ready.set()
