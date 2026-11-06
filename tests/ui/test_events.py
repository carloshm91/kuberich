"""Real Event table/controller behavior without an additional collection owner."""

import asyncio
import threading
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult

from kuberich.domain.curated_navigation import LabelsMatch, ResolvedCollectionBookmark
from kuberich.domain.events import (
    EventGroupMembers,
    EventObjectRow,
    EventOptions,
    event_fact,
    event_rows,
    group_key,
)
from kuberich.domain.relationships import structured_selector
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState, metadata_record, resource_record
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ResourceSelection, ViewObservation, ViewStatus
from kuberich.errors import AppError
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from kuberich.ui.controllers.events import EventsController
from kuberich.ui.events import EVENT_COLUMNS, EventCell, EventsTable
from tests.support.events import (
    EVENT_CANARY,
    FIRST,
    event_record,
    event_resource,
    event_snapshot,
    event_source,
)


class EventHost(App[None]):
    CSS = "EventsTable { width: 1fr; height: 1fr; }"

    def __init__(self, *, options_changed=lambda options: None):
        super().__init__()
        self.table = EventsTable(options_changed=options_changed)

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()
        self.table.focus()


def rows(count=80, *, grouped=False):
    facts = tuple(
        event_fact(
            event_resource(),
            event_record(
                uid=f"event-{index:03}",
                reason=f"Reason{index:03}",
                series={"count": index, "lastObservedTime": FIRST},
            ),
        )
        for index in range(count)
    )
    return event_rows(facts, EventOptions(grouped=grouped))


def request(snapshot, *, current=lambda: True, expected_uid=None, query=""):
    source = event_source(snapshot)
    view = ViewObservation(
        revision=source.revision,
        context="owned-events",
        scope=source.scope,
        status=source.status,
        snapshot=snapshot,
    )
    # The controller is independent of the eventual Root EVENTS route enum.
    route = ViewRoute(ViewKind.STANDARD, ResourceSelection("events", snapshot.resource.group))
    return RenderRequest(view, query, current, route, expected_uid=expected_uid)


def rendered(table):
    return "\n".join(table.render_line(line).text for line in range(table.size.height))


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
@pytest.mark.parametrize("grouped", [False, True])
async def test_literal_rows_resize_stable_identity_and_parent_viewport(size, grouped):
    app = EventHost()
    data = rows(grouped=grouped)
    options = EventOptions(grouped=grouped)
    async with app.run_test(size=size) as pilot:
        table = app.table
        assert await table.apply_rows(data, 1, lambda: True, source=None, options=options)
        await table.wait_for_refresh()
        assert "NAMESPACE" in rendered(table) and "team" in rendered(table)
        assert table.has_focus
        await pilot.press("pagedown", "pagedown", "right", "right")
        await table.wait_for_refresh()
        before = table.capture_viewport()
        assert before.selected is not None and before.index > 0
        assert (table.selected_group() is not None) is grouped
        assert (table.selected_event_uid() is None) is grouped
        assert table.selected_uid == table.selected_event_uid()
        assert await table.apply_rows(data, 1, lambda: True, source=None, options=options)
        await table.wait_for_refresh()
        assert table.capture_viewport() == before
        # A real return to the parent restores its stable row and both scroll axes.
        table.move_cursor(row=0)
        table.scroll_to(0, 0, animate=False, immediate=True)
        table.restore_viewport(before)
        await table.wait_for_refresh()
        assert table.capture_viewport() == before
        await pilot.resize_terminal(100, 30)
        await table.wait_for_refresh()
        assert table.selected_key == before.selected
        assert "OCCURRENCES" in rendered(table)
        # Vanished selection selects a real nearest row, without a fake object UID.
        remaining = tuple(
            row
            for row in data
            if (row.uid if isinstance(row, EventObjectRow) else row.key) != before.selected
        )
        assert await table.apply_rows(remaining, 1, lambda: True, source=None, options=options)
        assert table.selected_key != before.selected
        assert (table.selected_event_uid() is None) is grouped
        assert await table.apply_rows((), 1, lambda: True, source=None, options=options)
        assert table.selected_key is table.selected_uid is table.selected_group() is None


@pytest.mark.asyncio
async def test_typed_count_sort_unknown_last_stable_ties_and_real_keyboard_toggles():
    changes = []
    app = EventHost(options_changed=changes.append)
    facts = tuple(
        event_fact(
            event_resource(),
            event_record(uid=uid, series={"count": count, "lastObservedTime": FIRST}),
        )
        for uid, count in (
            ("zero", 0),
            ("nine", 9),
            ("three", 3),
            ("unknown", True),
            ("three-b", 3),
        )
    )
    data = event_rows(facts, EventOptions())
    async with app.run_test() as pilot:
        table = app.table
        assert await table.apply_rows(data, 1, lambda: True, source=None, options=EventOptions())
        table.restore_sort("occurrences", False)
        assert tuple(row.key.value for row in table.ordered_rows) == (
            "zero",
            "three",
            "three-b",
            "nine",
            "unknown",
        )
        await pilot.press("S")
        assert table.descending
        assert tuple(row.key.value for row in table.ordered_rows) == (
            "nine",
            "three",
            "three-b",
            "zero",
            "unknown",
        )
        await pilot.press("s")
        assert table.sort_column == "last-seen"
        await pilot.press("G")
        assert table.cursor_row == 4
        await pilot.press("g")
        assert table.cursor_row == 0
        await pilot.press("w", "t")
        assert changes == [EventOptions(warnings_only=True), EventOptions(grouped=True)]
        assert table.options == EventOptions()  # Only Root commits the option change.
        table.restore_sort("not-a-column", False)
        assert table.sort_column == "last-seen"
        assert "LAST-SEEN" in table.sort_summary
        await table.wait_for_refresh()
        assert await pilot.click("#events", offset=(1, 0))
        assert table.sort_column == "last-seen"
        assert await pilot.click("#events", offset=(5, 0))
        assert table.sort_column == "namespace"
        assert tuple(spec.key for spec in table.visible_columns) == EVENT_COLUMNS


@pytest.mark.asyncio
async def test_patches_are_bounded_abort_obsolete_and_capture_only_immutable_safe_values(
    monkeypatch,
):
    app = EventHost()
    data = rows(300)
    async with app.run_test() as pilot:
        table = app.table
        assert not await table.apply_rows(
            data, 1, lambda: False, source=None, options=EventOptions()
        )
        alive = [True]
        insert = table.add_row

        def add(*args, **kwargs):
            result = insert(*args, **kwargs)
            if table.row_count == 128:
                asyncio.get_running_loop().call_soon(lambda: alive.__setitem__(0, False))
            return result

        monkeypatch.setattr(table, "add_row", add)
        assert not await table.apply_rows(
            data, 1, lambda: alive[0], source=None, options=EventOptions()
        )
        assert table.row_count == 128
        monkeypatch.setattr(table, "add_row", insert)
        snapshot = event_snapshot(event_record(reason="[bold]literal[/bold]"))
        source = event_source(snapshot)
        safe = event_rows((event_fact(snapshot.resource, snapshot.items[0]),), EventOptions())
        assert await table.apply_rows(
            safe,
            2,
            lambda: True,
            source=source,
            options=EventOptions(),
            limited=True,
            notices=("retained subset",),
        )
        assert table.source is source and table.limited and table.notices == ("retained subset",)
        assert table.get_cell("event-a", "reason").plain == "[bold]literal[/bold]"
        capture = table.capture_dump(columns=EVENT_COLUMNS, concealed_columns=frozenset({6}))
        assert capture.row_keys == ("event-a",)
        assert capture.rows[0][6] == "[REDACTED COLUMN]"
        assert EVENT_CANARY not in repr(capture) + repr(capture.rows)
        assert capture.rows[0][2] == "[bold]literal[/bold]"
        changed = replace(
            safe[0],
            values=(
                safe[0].values[0],
                replace(safe[0].values[1], text="changed"),
                *safe[0].values[2:],
            ),
        )
        assert await table.apply_rows(
            (changed,), 2, lambda: True, source=source, options=EventOptions()
        )
        assert table.get_cell("event-a", "reason").text == "changed"
        assert capture.rows[0][2] == "[bold]literal[/bold]"
        with pytest.raises(AppError, match="export projection"):
            table.capture_dump(columns=("one",), concealed_columns=frozenset())
        with pytest.raises(AppError, match="export projection"):
            table.capture_dump(columns=EVENT_COLUMNS, concealed_columns=frozenset({True}))
        await pilot.pause()


def test_event_cell_literal_controls_and_group_identity_are_not_resource_uids():
    cell = EventCell("event-group:actual-digest", "[red]literal\x1b[31m\ntext", numeric=True)
    assert "\x1b" not in cell.plain and "[red]literal" in cell.plain
    assert cell.__rich__().justify == "right"
    assert len(EventCell("key", "x" * 1000).plain) <= 256


@pytest.mark.asyncio
async def test_reset_revokes_publication_and_pending_viewport_but_same_revision_preserves_it():
    app = EventHost()
    snapshot = event_snapshot(event_record())
    source = event_source(snapshot)
    options = EventOptions(grouped=True, warnings_only=True)
    async with app.run_test() as pilot:
        table = app.table
        assert await table.apply_rows(
            rows(grouped=True),
            4,
            lambda: True,
            source=source,
            options=options,
            limited=True,
            notices=("partial source",),
        )
        await pilot.press("pagedown", "right")
        await table.wait_for_refresh()
        viewport = table.capture_viewport()
        table.reset(4)
        assert table.capture_viewport() == viewport and table.source is source
        assert table.options == options and table.limited
        table.restore_viewport(viewport)
        table.reset(5)
        await table.wait_for_refresh()
        assert not table.row_count and table.selected_group() is table.selected_event_uid() is None
        assert table.source is None and table.options == EventOptions()
        assert not table.limited and not table.notices
        assert table.scroll_x == table.scroll_y == 0
        assert not await table.apply_rows(rows(), 4, lambda: False, source=source, options=options)
        assert not table.row_count and table.source is None
        assert await table.apply_rows(
            rows(1), 5, lambda: True, source=source, options=EventOptions()
        )
        await table.wait_for_refresh()
        assert table.selected_uid == "event-000"


@pytest.mark.asyncio
async def test_final_publication_guard_and_changed_native_column_layout_abort(monkeypatch):
    app = EventHost()
    async with app.run_test():
        table = app.table
        checks = 0

        def current():
            nonlocal checks
            checks += 1
            return checks < 3

        assert not await table.apply_rows(
            rows(2), 1, current, source=None, options=EventOptions(grouped=True)
        )
        assert table.options == EventOptions() and table.source is None
        insert = table.add_row

        def add(*args, **kwargs):
            result = insert(*args, **kwargs)
            if table.row_count == 128:
                asyncio.get_running_loop().call_soon(
                    lambda: table.add_column("UNEXPECTED", key="unexpected", width=10)
                )
            return result

        # An external schema change invalidates the next publication/capture.
        monkeypatch.setattr(table, "add_row", add)
        assert not await table.apply_rows(
            rows(140), 2, lambda: True, source=None, options=EventOptions()
        )
        assert table.row_count == 128
        with pytest.raises(AppError, match="export projection"):
            table.capture_dump(columns=EVENT_COLUMNS, concealed_columns=frozenset())


@pytest.mark.asyncio
async def test_controller_filters_exact_raw_uid_group_members_and_retires_real_projection():
    app, options = EventHost(), [EventOptions()]
    snapshot = event_snapshot(
        event_record(uid="first"), event_record(uid="second", reason="Scheduled", type="Normal")
    )
    controller = EventsController(
        app.table,
        lambda: options[0],
        lambda view: event_source(view.snapshot) if view.snapshot else None,
        lambda _: frozenset({"inspect"}),
    )
    driver = ViewDriver(controller)
    req = request(snapshot)
    async with app.run_test() as pilot:
        assert not await controller.apply((), req)
        result = await driver.render(req)
        assert result.applied and result.count == result.filtered == 2
        assert driver.available_actions(req) == frozenset({"inspect"})
        app.table.move_cursor(row=1)
        await app.table.wait_for_refresh()
        viewport = driver.capture_viewport()
        assert (await driver.render(replace(req, query="scheduled"))).filtered == 1
        driver.restore_viewport(viewport)
        assert app.table.selected_uid == "second"
        assert not (await driver.render(replace(req, current=lambda: False))).applied
        options[0] = EventOptions(grouped=True)
        assert (await driver.render(replace(req, expected_uid="first"))).count == 0
        assert app.table.row_count == 0  # A captured UID must never admit a group.
        assert (await driver.render(req)).count == 2
        group = app.table.selected_group()
        assert group is not None and app.table.selected_uid is None
        options[0] = EventOptions(members=EventGroupMembers(group.key))
        assert (await driver.render(req)).count == 1
        assert app.table.selected_uid in group.member_uids
        assert (await driver.render(replace(req, expected_uid="missing"))).filtered == 0
        result = await driver.render(replace(req, query="re:["))
        assert "Invalid regex" in result.problem and result.applied
        await controller.retire_projection()
        assert controller.projection.cached_count == controller.projection.operation_count == 0
        empty = replace(req, observation=replace(req.observation, snapshot=None))
        assert (await driver.render(empty)).count == 0
        await pilot.pause()


@pytest.mark.asyncio
async def test_controller_rejects_options_changed_during_owned_decoder_and_preserves_source_stamp(
    monkeypatch,
):
    entered, release = threading.Event(), threading.Event()
    options = [EventOptions()]
    snapshot = event_snapshot(event_record())
    source = event_source(snapshot)

    def held(resource, record):
        entered.set()
        assert release.wait(5)
        return event_fact(resource, record)

    monkeypatch.setattr("kuberich.services.events.event_fact", held)
    app = EventHost()
    controller = EventsController(
        app.table, lambda: options[0], lambda _: source, lambda _: frozenset()
    )
    driver = ViewDriver(controller)
    req = request(snapshot)
    async with app.run_test():
        task = asyncio.create_task(driver.render(req))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            options[0] = EventOptions(grouped=True)
        finally:
            release.set()
            result = await asyncio.wait_for(task, 5)
        assert not result.applied and not app.table.row_count
        assert (await driver.render(req)).applied
        assert app.table.options.grouped and app.table.source is source
        assert (await driver.render(replace(req, query="backoff"))).applied
        assert app.table.source.snapshot_seen_at == source.snapshot_seen_at
        projected = await controller.project(req)
        await controller.retire_projection()
        assert not projected.current()


@pytest.mark.asyncio
async def test_metadata_only_warning_filter_and_incomplete_status_remain_visible():
    resource = event_resource()
    record = metadata_record(
        resource,
        {
            "apiVersion": "meta.k8s.io/v1",
            "kind": "PartialObjectMetadata",
            "metadata": event_record().manifest["metadata"],
        },
    )
    snapshot = replace(event_snapshot(record), collection=CollectionState(complete=False, pages=2))
    source = event_source(snapshot, status=ViewStatus.STALE)
    app, options = EventHost(), [EventOptions()]
    controller = EventsController(
        app.table, lambda: options[0], lambda _: source, lambda _: frozenset()
    )
    async with app.run_test():
        assert (await ViewDriver(controller).render(request(snapshot))).applied
        assert app.table.selected_uid == record.uid
        assert all(
            app.table.get_cell(record.uid, field).text == "unknown" for field in EVENT_COLUMNS[1:]
        )
        assert app.table.limited and app.table.source.status is ViewStatus.STALE
        assert "Metadata-only" in " ".join(app.table.notices)
        options[0] = EventOptions(warnings_only=True)
        assert (await ViewDriver(controller).render(request(snapshot))).filtered == 0
        assert "unknown type" in " ".join(app.table.notices)
        await controller.retire_projection()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["members", "labels"])
async def test_controller_preserves_captured_event_collection_predicate(kind):
    raw = event_record(uid="wanted").manifest
    raw["metadata"]["labels"] = {"app": "owned"}
    selected = resource_record(event_resource(), raw)
    snapshot = event_snapshot(selected, event_record(uid="other", reason="Scheduled"))
    predicate = (
        EventGroupMembers(group_key(event_fact(snapshot.resource, selected)))
        if kind == "members"
        else LabelsMatch(structured_selector({"matchLabels": {"app": "owned"}}))
    )
    bookmark = ResolvedCollectionBookmark(
        snapshot.resource, snapshot.namespace, predicate, ResourceQuery()
    )
    app = EventHost()
    controller = EventsController(
        app.table,
        lambda: EventOptions(),
        lambda view: event_source(view.snapshot),
        lambda _: frozenset(),
    )
    async with app.run_test():
        result = await ViewDriver(controller).render(replace(request(snapshot), curated=bookmark))
        assert result.applied and result.count == result.filtered == app.table.row_count == 1
        assert app.table.selected_uid == "wanted"
        await controller.retire_projection()
