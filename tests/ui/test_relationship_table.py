"""Native relationship identity, expansion, source coverage and guarded rendering."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from kuberich.domain.navigation import Viewport
from kuberich.domain.relationships import (
    RelationDirection,
    RelationKind,
    RelationshipEvidence,
    RelationshipMode,
    RelationshipRef,
    RelationshipRequest,
    RelationshipRow,
    RelationshipScope,
    RelationshipSnapshot,
    RelationshipSource,
    RelationshipStatus,
    relationship_path_key,
)
from kuberich.domain.resources import CollectionState
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.view_routes import ViewRoute
from kuberich.domain.views import ViewObservation
from kuberich.ui.controllers import relationships as relationship_controller
from kuberich.ui.controllers.base import RenderRequest, ViewDriver
from kuberich.ui.controllers.relationships import RelationshipController
from kuberich.ui.relationships import RelationshipTable
from tests.support.resources import pod_resource


def row(path=(), *, name="root", status=RelationshipStatus.READY, expandable=False, details=()):
    resource = pod_resource()
    return RelationshipRow(
        path,
        RelationshipRef("v1", "Pod", "team", name, "uid-" + name, resource),
        RelationKind.OWNER if path else None,
        RelationDirection.OUTGOING if path else None,
        RelationshipEvidence.OBSERVED if path else None,
        status,
        "uid-" + name if status is RelationshipStatus.READY else None,
        details,
        expandable,
    )


def snapshot(*rows, expanded=frozenset(), revision=1, sources=()):
    resource = pod_resource()
    root = ResourceTarget(SessionIdentity("owned", 0), "", "pods", "team", "root", "uid-root")
    scope = RelationshipScope(root, resource, "team", RelationshipMode.XRAY)
    request = RelationshipRequest(scope, revision, expanded)
    return RelationshipSnapshot(request, rows, sources, 3, datetime(2026, 11, 5, tzinfo=UTC))


class TableApp(App):
    def __init__(self):
        super().__init__()
        self.table = RelationshipTable()
        self.expansions = []
        self.selections = []

    def compose(self) -> ComposeResult:
        yield self.table

    def on_mount(self):
        self.table.setup()

    def on_relationship_table_expansion_requested(self, event):
        assert event.control is self.table
        self.expansions.append((event.path, event.expanded))

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        self.selections.append(self.table.selected_path())


@pytest.mark.asyncio
async def test_relationship_statuses_keep_exact_descriptor_expected_and_observed_identity():
    app = TableApp()
    rows = tuple(
        replace(
            row((str(index),), status=status),
            relation=tuple(RelationKind)[index % len(RelationKind)],
            direction=tuple(RelationDirection)[index % len(RelationDirection)],
            evidence=tuple(RelationshipEvidence)[index % len(RelationshipEvidence)],
        )
        for index, status in enumerate(RelationshipStatus)
    )
    replacement = replace(rows[4], observed_uid="replacement-uid")
    rows = (*rows[:4], replacement, *rows[5:])
    async with app.run_test() as pilot:
        assert app.table.selected_path() is None
        data = snapshot(*rows)
        assert await app.table.apply_rows(rows, data, lambda: True)
        await pilot.pause()
        for item in rows:
            key = relationship_path_key(item.path)
            assert app.table.get_cell(key, "STATUS").plain == str(item.status)
            assert "Pod/root\n" in app.table.get_cell(key, "RESOURCE").plain
            assert "ns: team · v1" in app.table.get_cell(key, "RESOURCE").plain
            detail = app.table.get_cell(key, "DETAIL / OBSERVATION").plain
            assert "expected UID: uid-root" in detail
            assert "API resource: pods · v1" in detail
            assert f"observed UID: {item.observed_uid or 'unverified'}" in detail
            app.table.move_cursor(row=app.table.get_row_index(key))
            assert app.table.selected_path() == item.path
            assert app.table.row_at(item.path) == item
        assert app.table.row_at(("absent",)) is None
        assert app.table.request == data.request


@pytest.mark.asyncio
async def test_hostile_fields_are_literal_and_bounded_without_extra_remote_lines():
    app = TableApp()
    hostile = "[bold]hostile\x1b[31m\n\x1b]0;title\x07"
    item = replace(
        row(details=(hostile, "x" * 5000, *("extra" for _ in range(12)))),
        ref=RelationshipRef("v1", "Secret", None, hostile, None, None),
        observed_uid=None,
    )
    async with app.run_test(size=(30, 8)) as pilot:
        await app.table.apply_rows((item,), snapshot(item), lambda: True)
        await pilot.pause()
        key = relationship_path_key(())
        target = app.table.get_cell(key, "RESOURCE")
        detail = app.table.get_cell(key, "DETAIL / OBSERVATION")
        assert "[bold]hostile" in target.plain and not target.spans
        assert "cluster scope · v1" in target.plain
        assert len(target.plain.splitlines()) == 2
        assert "\x1b" not in target.plain + detail.plain
        assert "expected UID: unspecified\nobserved UID: unverified" in detail.plain
        assert "API resource: unresolved GVK" in detail.plain
        assert len(detail.plain) <= 2062 and detail.plain.endswith("[truncated]")
        assert app.table.region.width == 30


@pytest.mark.asyncio
async def test_arrow_expansion_and_enter_selection_never_open_or_change_the_graph_locally():
    app = TableApp()
    root = row(expandable=True)
    parent = row(("owner",), name="owner", expandable=True)
    child = row(("owner", "node"), name="node")
    data = snapshot(root, parent, expanded=frozenset({()}))
    async with app.run_test() as pilot:
        await app.table.apply_rows(data.rows, data, lambda: True)
        app.table.focus()
        await pilot.press("right")
        assert app.table.selected_path() == parent.path
        await pilot.press("right", "enter")
        assert app.expansions == [(parent.path, True)]
        assert app.selections == [parent.path]
        assert app.table.request == data.request and app.table.row_count == 2
        expanded = replace(
            data,
            request=replace(data.request, revision=2, expanded=frozenset({(), parent.path})),
            rows=(root, parent, child),
        )
        await app.table.apply_rows(expanded.rows, expanded, lambda: True)
        assert "▾" in app.table.get_cell(relationship_path_key(parent.path), "RESOURCE").plain
        await pilot.press("right")
        assert app.table.selected_path() == child.path
        await pilot.press("right", "left")
        assert app.table.selected_path() == parent.path
        await pilot.press("left")
        assert app.expansions[-1] == (parent.path, False)
        app.table.move_cursor(row=0)
        await pilot.press("left")
        assert app.expansions[-1] == ((), False)
        await app.table.apply_rows((root,), replace(expanded, rows=(root,)), lambda: True)
        await pilot.press("right")
        assert app.table.selected_path() == ()
        collapsed = replace(
            expanded, request=replace(expanded.request, revision=3, expanded=frozenset())
        )
        await app.table.apply_rows((root,), collapsed, lambda: True)
        before = tuple(app.expansions)
        await pilot.press("left")
        assert tuple(app.expansions) == before


@pytest.mark.asyncio
async def test_sources_stay_inspectable_when_filtered_or_no_supported_declarations_match():
    app = TableApp()
    sources = (
        RelationshipSource("pods", "team", RelationshipStatus.READY, CollectionState(), "7", ""),
        RelationshipSource("deployments", None, RelationshipStatus.FORBIDDEN, None, None, "Denied"),
        RelationshipSource(
            "jobs",
            "team",
            RelationshipStatus.TRUNCATED,
            CollectionState(complete=False, limited=True),
            "9",
            "Shared read budget exhausted",
        ),
    )
    async with app.run_test() as pilot:
        data = snapshot(sources=sources)
        await app.table.apply_rows((), data, lambda: True, filtered=True)
        assert app.table.row_count == 3
        for index, source in enumerate(sources):
            app.table.move_cursor(row=index)
            assert app.table.selected_path() is None
            cells = app.table.get_row_at(index)
            assert source.family in cells[0].plain
            assert cells[1].plain == str(source.status)
            assert ("INCOMPLETE" if index else "complete") in cells[2].plain
            assert "observed: unavailable · requests: 3" in cells[3].plain
        await pilot.press("right", "left", "enter")
        assert not app.expansions and app.selections == [None]
        await app.table.apply_rows((), replace(data, observed_at=None), lambda: True)
        assert "observed: unavailable" in app.table.get_row_at(0)[3].plain
        app.table.reset(2)
        assert not app.table.row_count and app.table.request is None
        await app.table.apply_rows((), None, lambda: True)
        assert app.table.get_row_at(0)[1].plain == "loading"
        await pilot.press("right", "left")
        await app.table.apply_rows((), snapshot(), lambda: True)
        assert app.table.get_row_at(0)[1].plain == "empty"
        await app.table.apply_rows((), None, lambda: True, filtered=True)
        assert app.table.row_count == 0


@pytest.mark.asyncio
async def test_source_observation_times_survive_expansion_without_inheriting_graph_time():
    app = TableApp()
    t0 = datetime(2026, 11, 5, tzinfo=UTC)
    t1, t2 = t0 + timedelta(minutes=1), t0 + timedelta(minutes=2)
    sources = (
        RelationshipSource(
            "pods", "team", RelationshipStatus.READY, CollectionState(), "7", "", t0
        ),
        RelationshipSource(
            "deployments", "team", RelationshipStatus.READY, CollectionState(), "8", "", t1
        ),
        RelationshipSource("jobs", "team", RelationshipStatus.FORBIDDEN, None, None, "Denied"),
    )
    root = row(expandable=True)
    data = replace(snapshot(root, sources=sources), observed_at=t1)
    async with app.run_test() as pilot:
        for observed, revision in ((t1, 1), (t2, 2)):
            expanded = replace(
                data,
                request=replace(data.request, revision=revision, expanded=frozenset({()})),
                observed_at=observed,
            )
            assert await app.table.apply_rows(expanded.rows, expanded, lambda: True)
            await pilot.pause()
            for source, expected in zip(sources, (t0, t1, None), strict=True):
                key = "source:" + relationship_path_key((source.family, source.namespace or ""))
                detail = app.table.get_cell(key, "DETAIL / OBSERVATION").plain
                timestamp = expected.isoformat(timespec="seconds") if expected else "unavailable"
                assert f"observed: {timestamp} · requests: 3" in detail
                assert t2.isoformat(timespec="seconds") not in detail
            root_detail = app.table.get_cell(
                relationship_path_key(()), "DETAIL / OBSERVATION"
            ).plain
            assert f"observed: {observed.isoformat(timespec='seconds')}" in root_detail


@pytest.mark.asyncio
async def test_exact_get_sources_do_not_claim_family_scan_completeness():
    app = TableApp()
    sources = (
        *(
            RelationshipSource(f"get:pods/team/{status}", "team", status, None, "7", "Exact GET")
            for status in (
                RelationshipStatus.READY,
                RelationshipStatus.LOADING,
                RelationshipStatus.FORBIDDEN,
            )
        ),
        RelationshipSource("pods", "team", RelationshipStatus.READY, CollectionState(), "8", ""),
        RelationshipSource(
            "jobs",
            "team",
            RelationshipStatus.READY,
            CollectionState(complete=False, limited=True),
            "9",
            "Partial scan",
        ),
    )
    async with app.run_test() as pilot:
        await app.table.apply_rows((), snapshot(sources=sources), lambda: True)
        await pilot.pause()
        for index in range(3):
            evidence = app.table.get_row_at(index)[2].plain
            assert "scan" not in evidence and "complete" not in evidence
            if index == 0:
                assert evidence == "observed exact resource · collection N/A"
                assert "INCOMPLETE" not in evidence
            else:
                assert "INCOMPLETE" in evidence
            app.table.move_cursor(row=index)
            assert app.table.selected_path() is None
        assert app.table.get_row_at(3)[2].plain == "scan source · complete"
        assert app.table.get_row_at(4)[2].plain == "scan source · INCOMPLETE"


@pytest.mark.asyncio
async def test_identical_shared_nodes_keep_distinct_path_keys_and_collector_order():
    app = TableApp()
    rows = (
        row(("a",), name="shared"),
        row(("a", "child"), name="nested"),
        row(("b",), name="shared"),
    )
    data = snapshot(*rows)
    async with app.run_test():
        await app.table.apply_rows(rows, data, lambda: True)
        assert [item.key.value for item in app.table.ordered_rows] == [
            relationship_path_key(item.path) for item in rows
        ]
        app.table.move_cursor(row=2)
        changed = (replace(rows[2], details=("New evidence",)), rows[0], rows[1])
        await app.table.apply_rows(changed, replace(data, rows=changed), lambda: True)
        assert app.table.selected_path() == ("b",)
        assert [item.key.value for item in app.table.ordered_rows] == [
            relationship_path_key(item.path) for item in changed
        ]


@pytest.mark.asyncio
async def test_variable_height_updates_preserve_exact_small_viewport_and_stable_selection():
    app = TableApp()
    rows = tuple(row((str(index),), name=f"pod-{index}") for index in range(30))
    data = snapshot(*rows)
    async with app.run_test(size=(40, 12)) as pilot:
        await app.table.apply_rows(rows, data, lambda: True)
        app.table.move_cursor(row=15)
        await pilot.pause()
        app.table.scroll_to(x=10, y=7, animate=False, immediate=True, force=True)
        await pilot.pause()
        before = app.table.capture_viewport()
        assert before.x == 10 and before.y == 7 and before.top_offset == 1
        changed = (replace(rows[0], details=("one", "two", "three")), *rows[1:])
        await app.table.apply_rows(changed, replace(data, rows=changed), lambda: True)
        await pilot.pause()
        after = app.table.capture_viewport()
        assert after.selected == before.selected and after.top == before.top
        assert after.x == before.x and after.top_offset == before.top_offset
        assert after.y == before.y + 3
        app.table.move_cursor(row=0)
        app.table.restore_viewport(after)
        await pilot.pause()
        assert app.table.capture_viewport() == after
        await app.table.apply_rows(rows, data, lambda: True)
        await pilot.pause()
        assert app.table.capture_viewport() == before
        app.table.focus()
        await pilot.press("shift+right")
        await pilot.pause()
        assert app.table.capture_viewport().x > before.x
        assert app.table.selected_path() == rows[15].path
        await pilot.press("alt+left", "alt+right")
        assert not app.expansions


@pytest.mark.asyncio
async def test_stale_request_and_scope_guard_cannot_replace_current_rows():
    app = TableApp()
    item = row(expandable=True)
    data = snapshot(item, revision=2)
    async with app.run_test() as pilot:
        assert not await app.table.apply_rows((item,), data, lambda: False)
        assert not app.table.row_count
        assert await app.table.apply_rows((item,), data, lambda: True)
        stale = replace(data, request=replace(data.request, revision=1), rows=())
        assert not await app.table.apply_rows((), stale, lambda: True)
        switched = replace(
            data,
            request=replace(data.request, scope=replace(data.request.scope, namespace="other")),
            rows=(),
        )
        assert not await app.table.apply_rows((), switched, lambda: False)
        assert app.table.row_count == 1 and app.table.request == data.request
        await app.table.apply_rows((item,), None, lambda: True)
        await pilot.press("right", "left")
        assert not app.expansions


@pytest.mark.asyncio
async def test_retired_viewport_callback_does_not_scroll_a_new_selection_or_reset():
    app = TableApp()
    rows = tuple(row((str(index),), name=f"pod-{index}") for index in range(20))
    async with app.run_test(size=(40, 10)) as pilot:
        await app.table.apply_rows(rows, snapshot(*rows), lambda: True)
        await pilot.pause()
        app.table.restore_viewport(Viewport(relationship_path_key(rows[5].path), 5, 10, 5, None))
        app.table.restore_viewport(Viewport(relationship_path_key(rows[6].path), 6, 0, 7, "gone"))
        await pilot.pause()
        assert app.table.capture_viewport().y == 7
        app.table.restore_viewport(Viewport(relationship_path_key(rows[5].path), 5, 10, 5, None))
        app.table.move_cursor(row=6, scroll=False)
        await pilot.pause()
        assert app.table.capture_viewport().x == 0
        assert app.table.selected_path() == rows[6].path
        app.table.restore_viewport(Viewport(None, 99, 10, 5, None))
        app.table.reset(3)
        await pilot.pause()
        assert app.table.selected_path() is None and app.table.capture_viewport().selected is None


@pytest.mark.asyncio
async def test_controller_shared_pipeline_filters_with_ancestors_and_rejects_retired_results():
    app = TableApp()
    root = row(expandable=True)
    parent = row(("owner",), name="deployment", expandable=True)
    child = row(("owner", "target"), name="needle")
    unrelated = row(("other",), name="unrelated")
    data = snapshot(root, parent, child, unrelated)
    request = RenderRequest(
        ViewObservation(relationships=data), "", lambda: True, ViewRoute.relationships()
    )
    controller = RelationshipController(app.table, lambda _: frozenset({"open_relationship"}))
    driver = ViewDriver(controller)
    async with app.run_test() as pilot:
        outcome = await driver.render(request)
        assert outcome.applied and outcome.count == outcome.filtered == 4
        assert (
            await driver.render(replace(request, expected_uid="unrelated-resource-uid"))
        ).filtered == 4
        app.table.move_cursor(row=2)
        before = driver.capture_viewport()
        outcome = await driver.render(replace(request, query="needle"))
        assert outcome.applied and outcome.count == 4 and outcome.filtered == 3
        assert [item.key.value for item in app.table.ordered_rows] == [
            relationship_path_key(item.path) for item in (root, parent, child)
        ]
        assert app.table.selected_path() == child.path
        assert driver.available_actions(request) == frozenset({"open_relationship"})
        assert not (await driver.render(replace(request, current=lambda: False))).applied
        outcome = await driver.render(replace(request, query="re:["))
        assert outcome.applied and "Invalid regex" in outcome.problem
        assert app.table.row_count == 4
        driver.restore_viewport(before)
        await pilot.pause()
        assert driver.capture_viewport().selected == before.selected
        outcome = await driver.render(replace(request, query="absent"))
        assert outcome.applied and outcome.filtered == app.table.row_count == 0
        outcome = await driver.render(replace(request, observation=ViewObservation()))
        assert outcome.applied and outcome.count == 0


@pytest.mark.asyncio
async def test_controller_discards_a_filter_result_retired_during_its_owned_await(monkeypatch):
    app = TableApp()
    data = snapshot(row(), row(("child",), name="needle"))
    current = True
    request = RenderRequest(
        ViewObservation(relationships=data), "", lambda: current, ViewRoute.relationships()
    )
    driver = ViewDriver(RelationshipController(app.table, lambda _: frozenset()))
    started, release = asyncio.Event(), asyncio.Event()
    actual = relationship_controller.apply_filter

    async def delayed(*args, **kwargs):
        started.set()
        await release.wait()
        return await actual(*args, **kwargs)

    async with app.run_test():
        assert (await driver.render(request)).applied
        before = tuple(item.key.value for item in app.table.ordered_rows)
        monkeypatch.setattr(relationship_controller, "apply_filter", delayed)
        pending = asyncio.create_task(driver.render(replace(request, query="needle")))
        await started.wait()
        current = False
        release.set()
        assert not (await pending).applied
        assert tuple(item.key.value for item in app.table.ordered_rows) == before
