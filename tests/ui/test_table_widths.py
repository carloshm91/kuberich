"""Width optimization preserves actual native sizing, repaint and key semantics."""

import pytest
from rich.measure import Measurement
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable
from textual.widgets.data_table import CellDoesNotExist

from kuberich.ui.pods import PodCell
from kuberich.ui.presentation import FrameTable


class WidthTables(App):
    CSS = "DataTable { width: 1fr; height: 1fr; }"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield FrameTable(id="framed", cursor_type="row")
            yield DataTable(id="native", cursor_type="row")


def widths(table):
    return (
        table.virtual_size,
        tuple(
            (column.content_width, column.get_render_width(table))
            for column in table.ordered_columns
        ),
    )


def cell(value):
    return PodCell("row", value)


class WideText(Text):
    def __rich_measure__(self, console, options):
        return Measurement(20, 20)


class CountingRenderable:
    def __init__(self, text="x" * 20):
        self.calls = 0
        self.text = text

    def __rich__(self):
        self.calls += 1
        return Text(self.text)


class WideCell(PodCell):
    def __rich__(self):
        return WideText(self.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,initial,replacement,other,height,fixed,resize",
    [
        ("RESTARTS", cell("0"), cell("12"), cell("7"), 1, None, True),
        ("RESTARTS", cell("12345678"), cell("1"), cell("7"), 1, None, True),
        ("NAME", cell("short"), cell("x" * 30), cell("tail"), 1, None, True),
        ("NAME", cell("x" * 30), cell("a"), cell("tail"), 1, None, True),
        ("NAME", cell("x" * 30), cell("a"), cell("y" * 30), 1, None, True),
        ("NAME", cell("a"), cell("b"), cell("y" * 30), 1, None, True),
        ("界é", cell("a"), cell("界"), cell(""), 1, None, True),
        ("VALUE", Text("old", style="red"), Text("new", style="blue"), Text(""), 1, None, True),
        ("VALUE", Text("old"), "[blue]new[/blue]", Text(""), 1, None, True),
        ("VALUE", Text("old"), Text("a\nb"), Text(""), 1, None, True),
        ("COUNT", cell("1"), cell("x" * 30), cell(""), 1, None, True),
        ("VALUE", Text("old"), WideText("new"), Text(""), 1, None, True),
        ("VALUE", cell("old"), WideCell("row", "new"), cell(""), 1, None, True),
        ("VALUE", "[red]x[/red]", "[blue]y[/blue]", "", 1, None, True),
        ("VALUE", 1.0, 100000.0, 0.0, 1, None, True),
        ("VALUE", Text("a\nb"), Text("界\nhello"), Text(""), 1, None, True),
        ("A\nLONG", cell("1"), cell("2"), cell(""), 1, None, True),
        ("A\u2028LONG", cell("12345"), cell("1"), cell(""), 1, None, True),
        ("VALUE", Text("a\nb"), Text("界\nhello"), Text(""), 2, None, True),
        ("VALUE", cell("1"), cell("2"), cell(""), 1, 12, True),
        ("VALUE", Text("a"), Text("\tx"), Text(""), None, None, True),
        ("VALUE", cell("1"), cell("x" * 30), cell(""), 1, None, False),
    ],
)
async def test_actual_widths_and_repaint_match_native_table(
    label, initial, replacement, other, height, fixed, resize
):
    app = WidthTables()
    async with app.run_test(size=(100, 30)) as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        for table in (framed, native):
            table.add_column(label, key="value", width=fixed)
            table.add_row(initial, key="first", height=height)
            table.add_row(other, key="second", height=height)
        await pilot.pause()
        assert widths(framed) == widths(native)
        for table in (framed, native):
            table.update_cell("first", "value", replacement, update_width=resize)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert framed.get_cell("first", "value") == replacement
        assert framed.render_line(1).text == native.render_line(1).text
        await pilot.resize_terminal(40, 12)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert framed.render_line(1).text == native.render_line(1).text


@pytest.mark.asyncio
@pytest.mark.parametrize("object_keys", [False, True])
async def test_header_bounded_edits_do_not_read_the_whole_column(monkeypatch, object_keys):
    app = WidthTables()
    async with app.run_test() as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        keys = {}
        for table in (framed, native):
            column = table.add_column("RESTARTS", key="count")
            for number in range(1000):
                row = table.add_row(cell("0"), key=str(number))
                if number == 0:
                    keys[table.id] = (row, column) if object_keys else ("0", "count")
        await pilot.pause()
        reads = []
        original = DataTable.get_column

        def observed(table, key):
            reads.append(table.id)
            return original(table, key)

        monkeypatch.setattr(DataTable, "get_column", observed)
        for number in range(20):
            value = cell(str(number))
            for table in (framed, native):
                table.update_cell(*keys[table.id], value, update_width=True)
            await pilot.pause()
            assert widths(framed) == widths(native)
            assert framed.get_cell("0", "count") == value
        assert "native" in reads and "framed" not in reads


@pytest.mark.asyncio
async def test_pending_growth_shrink_removal_and_new_header_match_native():
    app = WidthTables()
    async with app.run_test() as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        for table in (framed, native):
            table.add_column("COUNT", key="count")
            table.add_row(cell("1"), key="first")
            table.add_row(cell("1"), key="second")
        await pilot.pause()
        for table in (framed, native):
            table.update_cell("first", "count", cell("x" * 20), update_width=True)
            table.update_cell("second", "count", cell("2"), update_width=True)
            table.update_cell("first", "count", cell("3"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        for table in (framed, native):
            table.update_cell("first", "count", cell("x" * 20), update_width=True)
        await pilot.pause()
        for table in (framed, native):
            table.remove_row("first")
            table.update_cell("second", "count", cell("4"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        for table in (framed, native):
            table.clear(columns=True)
            table.add_column("界 NEW HEADER", key="new")
            table.add_row(cell("1"), key="new")
            table.update_cell("new", "new", cell("2"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)


@pytest.mark.asyncio
@pytest.mark.parametrize("row,column", [("missing", "count"), ("first", "missing")])
async def test_invalid_keys_preserve_native_cell_error(row, column):
    app = WidthTables()
    async with app.run_test() as pilot:
        for table in app.query(DataTable):
            table.add_column("COUNT", key="count")
            table.add_row(cell("1"), key="first")
        await pilot.pause()
        for table in app.query(DataTable):
            with pytest.raises(CellDoesNotExist):
                table.update_cell(row, column, cell("2"), update_width=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown_previous", [False, True])
async def test_unknown_renderables_retain_native_deferred_evaluation(unknown_previous):
    app = WidthTables()
    async with app.run_test() as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        originals = []
        for table in (framed, native):
            table.add_column("VALUE", key="value")
            initial = CountingRenderable("old") if unknown_previous else Text("old")
            originals.append(initial)
            table.add_row(initial, key="first")
        await pilot.pause()
        renderables = []
        for table, initial in zip((framed, native), originals, strict=True):
            replacement = Text("new") if unknown_previous else CountingRenderable()
            observed = initial if unknown_previous else replacement
            before = observed.calls
            table.update_cell("first", "value", replacement, update_width=True)
            assert observed.calls == before
            renderables.append(observed)
        await pilot.pause()
        assert all(value.calls > 0 for value in renderables)
        assert widths(framed) == widths(native)
        assert framed.render_line(1).text == native.render_line(1).text


@pytest.mark.asyncio
async def test_unsized_edits_keep_native_growth_and_clear_recovery(monkeypatch):
    app = WidthTables()
    async with app.run_test() as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        for table in (framed, native):
            table.add_column("COUNT", key="count")
            table.add_row(cell("1"), key="first")
            table.add_row(cell("1"), key="second")
        await pilot.pause()
        for table in (framed, native):
            table.update_cell("first", "count", cell("x" * 30), update_width=False)
            table.update_cell("second", "count", cell("2"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        for table in (framed, native):
            table.clear()
            table.add_row(cell("1"), key="fresh")
        await pilot.pause()
        for table in (framed, native):
            table.update_cell("fresh", "count", cell("2"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        reads = []
        original = DataTable.get_column

        def observed(table, key):
            reads.append(table.id)
            return original(table, key)

        monkeypatch.setattr(DataTable, "get_column", observed)
        for table in (framed, native):
            table.update_cell("fresh", "count", cell("3"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert "native" in reads and "framed" not in reads


@pytest.mark.asyncio
async def test_mutable_column_defaults_keep_native_neighbor_measurement():
    app = WidthTables()
    async with app.run_test() as pilot:
        framed, native = app.query_one("#framed"), app.query_one("#native")
        defaults = []
        for table in (framed, native):
            table.add_column("COUNT", key="count")
            table.add_row(cell("1"), key="first")
            table.add_row(cell("1"), key="second")
            value = CountingRenderable("1")
            defaults.append(value)
            table.add_column("EXTRA", key="extra", default=value)
        await pilot.pause()
        for table, value in zip((framed, native), defaults, strict=True):
            value.text = "x" * 30
            table.update_cell("first", "extra", cell("2"), update_width=True)
        await pilot.pause()
        assert widths(framed) == widths(native)
        assert framed.render_line(2).text == native.render_line(2).text
