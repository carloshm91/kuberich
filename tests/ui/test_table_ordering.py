"""Actual table ordering, typed values and viewport behavior under live edits."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.custom import CustomLayout
from kuberich.domain.pods import PodColumn, order, pod_row
from kuberich.domain.registry import RESOURCE_ALIASES, Value, order_resources, resource_row
from kuberich.domain.resources import ServerColumn
from kuberich.ui.custom import CustomTable
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable
from tests.support.pods import NOW, pod, record
from tests.support.standard import row_record
from tests.support.tables import custom_resource
from tests.unit.test_custom_layout import captured


class TableApp(App):
    CSS = "DataTable { width: 1fr; height: 1fr; }"

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.table = (
            PodTable() if kind == "pods" else CustomTable() if kind == "custom" else StandardTable()
        )
        self.layout = CustomLayout.build(custom_resource(), (ServerColumn("Level", "integer"),))

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        if self.kind == "custom":
            self.table.configure_layout(self.layout, 1)
        else:
            self.table.setup()

    def rows(self, count):
        result = []
        for index in range(count):
            name = f"item-{index:04}"
            if self.kind == "pods":
                result.append(
                    pod_row(
                        record(pod(name, restarts=index, created=NOW - timedelta(seconds=index)))
                    )
                )
            elif self.kind == "standard":
                result.append(
                    resource_row(
                        row_record(
                            RESOURCE_ALIASES["deploy"],
                            name=name,
                            overrides={
                                "spec": {"replicas": index},
                                "status": {"readyReplicas": index},
                            },
                        ),
                        RESOURCE_ALIASES["deploy"],
                    )
                )
            else:
                value = replace(
                    captured(self.layout.headers, (index,), name=name),
                    created_at=NOW - timedelta(seconds=index),
                )
                result.append(self.layout.row(value))
        return tuple(result)

    @property
    def numeric(self):
        return (
            PodColumn.RESTARTS
            if self.kind == "pods"
            else "desired"
            if self.kind == "standard"
            else "c1"
        )

    def changed(self, row, key, value):
        if self.kind == "pods":
            return replace(row, **{"created_at" if key == "age" else key: value})
        index = next(i for i, col in enumerate(self.table.definition.columns) if col.key == key)
        values = list(row.values)
        sort = (
            -value.timestamp()
            if key == "age" and value is not None
            else value.casefold()
            if isinstance(value, str)
            else value
        )
        values[index] = Value(str(value), sort)
        metadata = (
            {"created_at": value}
            if key == "age"
            else {key: value}
            if key in {"namespace", "name"}
            else {}
        )
        return replace(row, values=tuple(values), **metadata)

    def expected(self, rows):
        return (
            order(rows, self.table.sort_column, self.table.descending)
            if self.kind == "pods"
            else order_resources(rows, self.table._column_index(), self.table.descending)
        )


def identities(table):
    return tuple(row.key.value for row in table.ordered_rows)


def observe_order(app, monkeypatch):
    path = (
        "kuberich.ui.pods.order" if app.kind == "pods" else "kuberich.ui.standard.order_resources"
    )
    calls = []
    original = order if app.kind == "pods" else order_resources

    def measured(*args):
        calls.append(len(args[0]))
        return original(*args)

    monkeypatch.setattr(path, measured)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
async def test_large_unrelated_updates_keep_order_viewport_without_global_ordering(
    kind, monkeypatch
):
    app = TableApp(kind)
    rows = app.rows(1000)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        assert await table.apply_rows(rows, 1, lambda: True)
        table.move_cursor(row=750)
        await pilot.pause()
        before, wanted = table.capture_viewport(), identities(table)
        calls = observe_order(app, monkeypatch)
        for number in range(10):
            changed = app.changed(rows[0], app.numeric, 1000 + number)
            assert await table.apply_rows((changed, *rows[1:]), 1, lambda: True)
        await pilot.pause()
        assert identities(table) == wanted
        assert table.capture_viewport() == before
        assert str(table.get_cell(rows[0].uid, app.numeric)) == "1009"
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
@pytest.mark.parametrize("descending", [False, True])
async def test_active_typed_values_and_stable_ties_reorder_and_retain_selection(kind, descending):
    app = TableApp(kind)
    rows = app.rows(10)
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        table.restore_sort(app.numeric, descending)
        table.move_cursor(row=5)
        await pilot.pause()
        selected = table.selected_uid
        changed = (
            app.changed(rows[0], app.numeric, 20),
            app.changed(rows[1], app.numeric, 2),
            *rows[2:],
        )
        assert await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert identities(table) == tuple(row.uid for row in app.expected(changed))
        assert table.selected_uid == selected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
@pytest.mark.parametrize("key,value", [("namespace", "aaa"), ("name", "ITEM-9999"), ("age", None)])
async def test_identity_ties_and_unknown_ages_follow_canonical_order(kind, key, value):
    app = TableApp(kind)
    rows = app.rows(10)
    async with app.run_test() as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        table.restore_sort(
            PodColumn.AGE
            if key == "age" and kind == "pods"
            else "age"
            if key == "age"
            else app.numeric,
            True,
        )
        tied = tuple(app.changed(row, app.numeric, 2) for row in rows)
        await table.apply_rows(tied, 1, lambda: True)
        changed = (app.changed(tied[0], key, value), *tied[1:])
        assert await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert identities(table) == tuple(row.uid for row in app.expected(changed))
        if key == "age":
            assert identities(table)[-1] == rows[0].uid


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
async def test_native_reorder_membership_and_revisions_invalidate_previous_order(kind):
    app = TableApp(kind)
    rows = app.rows(10)
    async with app.run_test() as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        expected = tuple(row.uid for row in app.expected(rows))
        assert table.sort("name", key=lambda value: value.text, reverse=True) is table
        assert identities(table) == tuple(reversed(expected))
        assert await table.apply_rows(rows, 1, lambda: True)
        assert identities(table) == expected
        inserted = replace(rows[0], uid="new-identity", name="000-new")
        changed = (inserted, *rows[1:-1])
        assert await table.apply_rows(changed, 1, lambda: True)
        assert identities(table) == tuple(row.uid for row in app.expected(changed))
        assert await table.apply_rows((), 1, lambda: True)
        assert table.row_count == 0
        assert await table.apply_rows(rows, 2, lambda: True)
        await pilot.pause()
        assert identities(table) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
async def test_sort_input_during_yielding_updates_uses_current_column(kind, monkeypatch):
    app = TableApp(kind)
    rows = app.rows(260)
    async with app.run_test() as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        changed = tuple(app.changed(row, app.numeric, 1000 - i) for i, row in enumerate(rows))
        update = table.update_cell
        switched = False

        def observed(uid, column, *args, **kwargs):
            nonlocal switched
            result = update(uid, column, *args, **kwargs)
            if uid == rows[127].uid and column == app.numeric and not switched:
                switched = True
                asyncio.get_running_loop().call_soon(table.set_sort, app.numeric)
            return result

        monkeypatch.setattr(table, "update_cell", observed)
        assert await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert switched and table.sort_column == app.numeric
        assert identities(table) == tuple(row.uid for row in app.expected(changed))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pods", "standard", "custom"])
async def test_aborted_order_changing_batch_recovers_on_next_accepted_view(kind, monkeypatch):
    app = TableApp(kind)
    rows = app.rows(260)
    async with app.run_test() as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        table.restore_sort(app.numeric, False)
        changed = tuple(app.changed(row, app.numeric, 1000 - i) for i, row in enumerate(rows))
        update, current = table.update_cell, [True]

        def observed(uid, column, *args, **kwargs):
            result = update(uid, column, *args, **kwargs)
            if uid == rows[127].uid and column == app.numeric:
                asyncio.get_running_loop().call_soon(current.__setitem__, 0, False)
            return result

        monkeypatch.setattr(table, "update_cell", observed)
        assert not await table.apply_rows(changed, 1, lambda: current[0])
        monkeypatch.setattr(table, "update_cell", update)
        assert await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert identities(table) == tuple(row.uid for row in app.expected(changed))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "column,change",
    [
        (PodColumn.READY, {"ready": 2, "containers": 2}),
        (PodColumn.STATUS, {"status": "RUNNING"}),
    ],
)
async def test_equivalent_readiness_ratios_and_status_casing_keep_typed_order(
    column, change, monkeypatch
):
    app = TableApp("pods")
    rows = app.rows(10)
    async with app.run_test() as pilot:
        table = app.table
        await table.apply_rows(rows, 1, lambda: True)
        table.restore_sort(column, False)
        expected = identities(table)
        calls = observe_order(app, monkeypatch)
        changed = (replace(rows[0], **change), *rows[1:])
        assert await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert identities(table) == expected and not calls
        assert str(table.get_cell(rows[0].uid, column)) == (
            "2/2" if column is PodColumn.READY else "RUNNING"
        )


@pytest.mark.asyncio
async def test_epoch_timestamp_and_unknown_age_have_distinct_order_membership():
    app = TableApp("pods")
    rows = app.rows(3)
    async with app.run_test() as pilot:
        table = app.table
        epoch = NOW.replace(year=1970, month=1, day=1, hour=0)
        epoch = epoch.replace(minute=0, second=0, microsecond=0)
        original = (replace(rows[0], created_at=epoch), *rows[1:])
        await table.apply_rows(original, 1, lambda: True)
        table.restore_sort(PodColumn.AGE, True)
        assert identities(table)[0] == rows[0].uid
        changed = (replace(rows[0], created_at=None), *rows[1:])
        await table.apply_rows(changed, 1, lambda: True)
        await pilot.pause()
        assert identities(table)[-1] == rows[0].uid
