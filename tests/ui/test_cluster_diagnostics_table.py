"""Native diagnostic rows preserve limits, literal cells and precise viewports."""

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.cluster_diagnostics import (
    DiagnosticIdentity,
    DiagnosticSeverity,
    DiagnosticSourceKind,
)
from kuberich.domain.diagnostic_rows import diagnostic_rows
from kuberich.domain.navigation import Viewport
from kuberich.ui.cluster_diagnostics import ClusterDiagnosticsTable
from tests.support.diagnostic_ui import NOW, finding, snapshot


class Host(App):
    def __init__(self):
        super().__init__()
        self.table = ClusterDiagnosticsTable()

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()


@pytest.mark.asyncio
async def test_source_age_and_partial_status_survive_literal_updates_reorder_and_retirement():
    app = Host()
    data = snapshot()
    rows = diagnostic_rows(data, now=NOW)
    hostile = replace(rows[2], summary="[bold]literal\x1b[31m\nline", details=("one",))
    async with app.run_test(size=(35, 10)) as pilot:
        assert app.table.selected_key() is None and app.table.row_at(None) is None
        assert not await app.table.apply_rows(rows, data, lambda: False)
        assert await app.table.apply_rows((*rows[:2], hostile, rows[3]), data, lambda: True)
        cell = app.table.get_cell(hostile.key, "SUMMARY")
        assert "[bold]literal" in cell.plain and "\x1b" not in cell.plain and not cell.spans
        assert app.table.get_cell("source:pods", "AGE").plain == "70s (stale)"
        assert app.table.get_cell("source:pods", "SUMMARY").plain.startswith("partial")
        assert app.table.get_cell("source:events", "AGE").plain == "unknown"
        app.table.move_cursor(row=app.table.get_row_index(hostile.key))
        await pilot.pause()
        changed = replace(hostile, details=("one", "two", "three"))
        await app.table.apply_rows((changed, rows[0]), data, lambda: True)
        assert app.table.selected_key() == hostile.key
        assert app.table.row_at("source:events") is None
        assert app.table.get_row_height(hostile.key) == 4
        long = replace(changed, details=("x" * 3000, *("more" for _ in range(8))))
        await app.table.apply_rows((long,), data, lambda: True)
        assert app.table.get_cell(hostile.key, "SUMMARY").plain.endswith("[truncated]")
        updated_age = replace(long, age="71s (stale)")
        await app.table.apply_rows((updated_age,), data, lambda: True)
        assert app.table.get_cell(hostile.key, "AGE").plain == "71s (stale)"
        current = replace(data, request=replace(data.request, revision=2))
        await app.table.apply_rows((long,), current, lambda: True)
        assert not await app.table.apply_rows((), data, lambda: True)
        assert app.table.row_count == 1
        app.table.reset(3)
        await app.table.apply_rows((), None, lambda: True)
        assert app.table.row_count == 0 and app.table.request is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intervene", [None, "selection", "horizontal", "vertical"])
async def test_diagnostic_viewport_is_exact_after_coalesced_render_and_respects_manual_input(
    intervene,
):
    app = Host()
    data = snapshot(findings=tuple(finding(f"finding-{index:02}") for index in range(25)))
    rows = diagnostic_rows(data, now=NOW)
    async with app.run_test(size=(45, 12)) as pilot:
        await app.table.apply_rows(rows, data, lambda: True)
        app.table.move_cursor(row=8)
        await pilot.pause()
        expected = replace(app.table.capture_viewport(), x=9)
        app.table.restore_viewport(expected)
        if intervene == "selection":
            app.table.move_cursor(row=9, scroll=False)
            app.table.move_cursor(row=8, scroll=False)
        elif intervene == "horizontal":
            app.table.scroll_to(x=4, animate=False, immediate=True, force=True)
        elif intervene == "vertical":
            app.table.scroll_to(y=0, animate=False, immediate=True, force=True)
        manual = app.table.capture_viewport()
        await app.table.apply_rows(rows, data, lambda: True)
        await pilot.pause()
        if intervene is None:
            assert app.table.capture_viewport() == expected
        elif intervene != "selection":
            assert app.table.capture_viewport() == manual
        else:
            assert app.table.capture_viewport().x == 0
        app.table.restore_viewport(Viewport("missing", 99, 0, 0, "missing"))
        app.table.reset(4)
        await pilot.pause()
        assert app.table.selected_key() is None


@pytest.mark.asyncio
async def test_identical_external_messages_keep_occurrence_keys_and_severity_source_sort_selection():
    app = Host()
    first = replace(
        finding("external:0"),
        source=DiagnosticSourceKind.POPEYE,
        identity=DiagnosticIdentity.NAME_ONLY,
    )
    second = replace(first, key="external:1")
    third = replace(
        first,
        key="native:2",
        severity=DiagnosticSeverity.INFO,
        source=DiagnosticSourceKind.CONDITION,
        identity=DiagnosticIdentity.UID_BOUND,
    )
    data = snapshot(findings=(first, second, third))
    rows = diagnostic_rows(data, now=NOW)
    async with app.run_test(size=(120, 16)) as pilot:
        await app.table.apply_rows(rows, data, lambda: True)
        assert len({row.key.value for row in app.table.ordered_rows}) == len(rows)
        app.table.move_cursor(row=app.table.get_row_index(first.key))
        await pilot.pause()
        app.table.set_sort("source", False)
        await pilot.pause()
        assert app.table.selected_key() == first.key
        keys = [row.key.value for row in app.table.ordered_rows]
        assert keys[-3] == third.key
        app.table.set_sort("severity", False)
        assert [row.key.value for row in app.table.ordered_rows][-3] == third.key
        with pytest.raises(ValueError, match="severity or source"):
            app.table.set_sort("name", False)


@pytest.mark.asyncio
async def test_native_header_sort_and_keyboard_navigation_work_in_a_narrow_window():
    app = Host()
    data = snapshot(findings=(finding("first"), finding("second")))
    async with app.run_test(size=(40, 10)) as pilot:
        await app.table.apply_rows(diagnostic_rows(data, now=NOW), data, lambda: True)
        await pilot.pause()
        assert await pilot.click(app.table, offset=(3, 0))
        assert app.table.sort_column == "severity" and not app.table.descending
        assert await pilot.click(app.table, offset=(3, 0))
        assert app.table.descending
        assert await pilot.click(app.table, offset=(13, 0))
        assert app.table.sort_column == "severity"
        app.table.focus()
        before = app.table.cursor_row
        await pilot.press("down")
        assert app.table.cursor_row == before + 1
        await pilot.press("alt+l")
        assert app.table.scroll_target_x > 0
