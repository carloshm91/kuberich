"""Authorization rows retain literal fields, stable geometry and guarded requests."""

from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.authorization_rows import AuthorizationRow
from kuberich.domain.navigation import Viewport
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.ui.authorization import AuthorizationTable
from kuberich.ui.controllers.authorization import AuthorizationController
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from tests.unit.test_authorization_rows import observed


class Host(App):
    def __init__(self):
        super().__init__()
        self.table = AuthorizationTable()

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()


def row(key, label="Evidence", details=()):
    return AuthorizationRow(key, label, "namespace team", "ready", details, None, None)


@pytest.mark.asyncio
async def test_literal_fields_and_variable_geometry_survive_reorder_updates_and_retirement():
    app = Host()
    data = observed()
    rows = (row("first"), row("second"), row("hostile", "[bold]literal\x1b[31m\nline", ("one",)))
    async with app.run_test(size=(35, 10)) as pilot:
        assert app.table.selected_key() is None and app.table.row_at(None) is None
        assert not await app.table.apply_rows(rows, data, lambda: False)
        assert await app.table.apply_rows(rows, data, lambda: True)
        assert app.table.row_at("hostile") == rows[2]
        cell = app.table.get_cell("hostile", "EVIDENCE")
        assert "[bold]literal" in cell.plain and "\x1b" not in cell.plain and not cell.spans
        assert len(cell.plain.splitlines()) == 1
        app.table.move_cursor(row=1)
        changed = (replace(rows[2], details=("line", "two", "three")), rows[1])
        await app.table.apply_rows(changed, data, lambda: True)
        assert [item.key.value for item in app.table.ordered_rows] == ["hostile", "second"]
        assert app.table.selected_key() == "second"
        assert app.table.get_row_height("hostile") == 3
        long = replace(changed[0], details=("x" * 3000, *("more" for _ in range(10))))
        await app.table.apply_rows((long,), data, lambda: True)
        assert app.table.get_cell("hostile", "DETAIL / OBSERVATION").plain.endswith("[truncated]")
        await pilot.pause()
        assert not await app.table.apply_rows(
            (), replace(data, request=replace(data.request, revision=0)), lambda: True
        )
        assert app.table.row_count == 1
        app.table.reset(2)
        assert app.table.row_count == 0 and app.table.request is None
        await app.table.apply_rows((), None, lambda: True)
        assert app.table.selected_key() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("intervene", [None, "selection", "horizontal", "vertical"])
async def test_pending_history_viewport_survives_coalesced_rows_but_yields_to_intervention(
    intervene,
):
    app = Host()
    data = observed()
    rows = tuple(row(str(index), details=("x" * 120, "two", "three")) for index in range(25))
    async with app.run_test(size=(45, 12)) as pilot:
        await app.table.apply_rows(rows, data, lambda: True)
        app.table.move_cursor(row=8)
        await pilot.pause()
        original = app.table.capture_viewport()
        expected = replace(original, x=9)
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
        app.table.reset(3)
        await pilot.pause()
        assert app.table.selected_key() is None


@pytest.mark.asyncio
async def test_real_controller_keeps_warning_source_and_review_provenance_under_filter():
    app = Host()
    data = observed()
    request = RenderRequest(
        ViewObservation(authorization=data),
        "not-a-subject",
        lambda: True,
        ViewRoute.authorization(),
        expected_uid="not-an-aggregate-filter",
    )
    driver = ViewDriver(
        AuthorizationController(app.table, lambda _: frozenset({"open_relationship"}))
    )
    async with app.run_test() as pilot:
        outcome = await driver.render(request)
        assert outcome.applied
        assert all(
            item.key.value.startswith(("summary:", "source:", "warning:", "identity:", "review:"))
            for item in app.table.ordered_rows
        )
        assert app.table.row_at("summary:request") is not None
        assert driver.available_actions(request) == frozenset({"open_relationship"})
        before = driver.capture_viewport()
        assert not (await driver.render(replace(request, current=lambda: False))).applied
        driver.restore_viewport(before)
        await pilot.pause()
        assert driver.capture_viewport() == before
