"""Table frame reuse preserves visible styles, geometry and subsequent themes."""

import pytest
from textual.app import App, ComposeResult
from textual.geometry import Region
from textual.widgets import DataTable

from kuberich.ui.pods import PodCell
from kuberich.ui.presentation import FrameTable


class Tables(App):
    CSS = """
    DataTable { height: 1fr; border: solid blue; background: $surface; color: $text; }
    """

    def compose(self) -> ComposeResult:
        yield FrameTable(id="framed", cursor_type="row", zebra_stripes=True)

    def on_mount(self):
        for table in self.query(DataTable):
            table.add_columns("NAME", "MESSAGE", "COUNT")
            for number in range(80):
                table.add_row(
                    PodCell(str(number), f"resource-{number}"),
                    PodCell(str(number), f"literal [red] 界é {'x' * 40}"),
                    PodCell(str(number), str(number), numeric=True),
                    key=str(number),
                )
            table.fixed_columns = 1


def strips(table, *, reference=False):
    table._clear_caches()
    table._styles_cache.clear()
    crop = Region(0, 0, table.size.width, table.size.height)
    rows = DataTable.render_lines(table, crop) if reference else table.render_lines(crop)
    return tuple((tuple(line), line.cell_length) for line in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_frame_table_visible_rows_equal_reference_after_theme_scroll_and_visibility(size):
    app = Tables()
    async with app.run_test(size=size) as pilot:
        framed = app.query_one("#framed")
        for theme in ("textual-dark", "textual-light"):
            app.theme = theme
            for selected in (0, 37):
                framed.move_cursor(row=selected, column=1)
                await pilot.pause()
                before = strips(framed)
                assert before == strips(framed, reference=True)
                assert before and any(
                    "resource-" in segment.text for line, _ in before for segment in line
                )
                # A hidden frame must not retain its old inherited colors.
                framed.display = False
                framed.styles.color = "yellow"
                framed.styles.border = ("solid", "green")
                await pilot.pause()
                framed.display = True
                await pilot.pause()
                assert strips(framed) == strips(framed, reference=True)
                assert framed._frame_style is None
        await pilot.resize_terminal(49, 16)
        await pilot.pause()
        assert strips(framed) == strips(framed, reference=True)


@pytest.mark.asyncio
async def test_nested_frame_and_failed_render_do_not_retain_style(monkeypatch):
    app = Tables()
    async with app.run_test() as pilot:
        framed = app.query_one("#framed")
        original = DataTable.render_lines
        calls = []

        def nested(table, crop):
            calls.append(table.rich_style)
            if len(calls) == 1:
                table.render_lines(crop)
            return original(table, crop)

        with monkeypatch.context() as patch:
            patch.setattr(DataTable, "render_lines", nested)
            strips(framed)
        assert len(calls) == 2 and calls[0] is calls[1]
        assert framed._frame_style is None

        def failed(table, crop):
            assert table.rich_style is not None
            raise RuntimeError("owned failed render")

        with monkeypatch.context() as patch:
            patch.setattr(DataTable, "render_lines", failed)
            with pytest.raises(RuntimeError, match="owned failed render"):
                strips(framed)
        assert framed._frame_style is None
        app.theme = "textual-light"
        await pilot.pause()
        assert strips(framed) == strips(framed, reference=True)
