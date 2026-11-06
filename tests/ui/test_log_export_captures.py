"""Actual retained log captures keep their producing scope through reader transitions."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from textual.widgets import OptionList

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.config.schema import Settings
from kuberich.diagnostics.reports import report_payload
from kuberich.domain.exports import AggregateLogsSource, SingleLogsSource
from kuberich.domain.log_view import WINDOWS
from kuberich.services.aggregate_logs import AggregateLogs
from kuberich.services.exports import ExportService
from kuberich.services.logs import LogStream
from kuberich.ui.aggregate_logs import AggregateLogScreen, LogSourcesScreen
from kuberich.ui.app import KubeRichApp
from kuberich.ui.logs import LogScreen
from kuberich.ui.scopes import ScopeScreen
from tests.support.aggregate_logs import AggregateApi
from tests.support.connections import catalog_fixture, namespaces
from tests.support.workspace import wait_for, workspace_api

AT = datetime(2026, 11, 5, 12, 30, tzinfo=UTC)


class ReadGate:
    """Observe real public reads; hold the first cancelled producer's final return."""

    def __init__(self, *, hold=False, arrival=""):
        self.hold = hold
        self.arrival = arrival
        self.calls = []
        self.draining = asyncio.Event()
        self.release = asyncio.Event()
        self.drained = asyncio.Event()
        self.arrived = asyncio.Event()

    def wrap(self, operation):
        async def observed(owner, options, sink, *args, **kwargs):
            index = len(self.calls)
            task = asyncio.current_task()
            self.calls.append((owner.target, options, kwargs.get("head_lines"), task))

            async def retain(*values):
                if self.arrival and self.arrival in values[-1].text:
                    self.arrived.set()
                await sink(*values)

            try:
                return await operation(owner, options, retain, *args, **kwargs)
            except asyncio.CancelledError:
                if self.hold and index == 0:
                    self.draining.set()
                    try:
                        await self.release.wait()
                    finally:
                        self.drained.set()
                raise

        return observed


async def ns(request):
    return namespaces("team", "default")


def owned_app(tmp_path, url):
    service = ExportService(
        files=ArtifactFiles(),
        default_root=tmp_path / "exports",
        report_payload=lambda: report_payload(config_status="missing", log_path=None),
        clock=lambda: AT,
        new_id=uuid4,
    )
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("log-export-captures", level=100),
        catalog=catalog_fixture(tmp_path, url),
        export_service=service,
    )
    return app, service


async def press_until(pilot, key, effect):
    """Own one key until its effect, independently of global animation completion."""
    operation = asyncio.create_task(pilot.press(key))

    def applied():
        if operation.done():
            operation.result()
        return effect()

    try:
        await wait_for(applied)
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)
        if not operation.cancelled():
            operation.result()


async def choose_scope(app, pilot, index, *, effect=None):
    await wait_for(lambda: isinstance(app.screen, ScopeScreen))
    app.screen.query_one(OptionList).highlighted = index
    if effect is None:
        await pilot.press("enter")
    else:
        await press_until(pilot, "enter", effect)


async def open_viewer(app, pilot, *, aggregate=False, all_namespaces=False):
    await wait_for(lambda: app.resources.row_count > 0)
    if all_namespaces:
        await app.run_command(":pods *")
        await wait_for(
            lambda: app.sessions.observation.namespace is None and app.resources.row_count > 0
        )
    await pilot.press("L" if aggregate else "l")
    if not aggregate:
        await wait_for(lambda: any(isinstance(screen, LogScreen) for screen in app.screen_stack))
        if isinstance(app.screen, ScopeScreen):
            await choose_scope(app, pilot, 0)
    await wait_for(lambda: isinstance(app.screen, AggregateLogScreen if aggregate else LogScreen))
    screen = app.screen
    await wait_for(lambda: bool(screen.capture_export(AT)) and bool(screen.history.entries))
    return screen


def single_api(*, two_containers=False):
    api = AggregateApi(count=1)
    api.pods["pod-00"]["status"]["containerStatuses"][0]["lastState"] = {
        "terminated": {
            "containerID": "synthetic://previous-app",
            "startedAt": "2026-11-05T11:00:00Z",
            "finishedAt": "2026-11-05T11:30:00Z",
        }
    }
    if two_containers:
        api.pods["pod-00"]["spec"]["containers"].append({"name": "sidecar", "image": "synthetic"})
    api.initial["pod-00", "app"] = b"2026-11-05T12:00:00Z old-app-window\n"
    api.initial["pod-00", "sidecar"] = b"2026-11-05T12:01:00Z new-sidecar-window\n"
    return api


def capture(screen):
    choices = dict(screen.capture_export(AT))
    assert set(choices) == {"logs", "screen"}
    return choices["logs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["container", "window", "previous"])
async def test_single_log_transition_refuses_capture_while_old_reader_drains(
    tmp_path, monkeypatch, change
):
    gate = ReadGate(hold=True)
    monkeypatch.setattr(LogStream, "run", gate.wrap(LogStream.run))
    api = single_api(two_containers=True)
    queries = []

    async def handler(request):
        if request.path.endswith("/log"):
            queries.append(dict(request.query))
        return await api.handler(request)

    async with workspace_api(ns, handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            try:
                screen = await open_viewer(app, pilot, all_namespaces=True)
                old = capture(screen)
                source = old.capture.source
                assert isinstance(source, SingleLogsSource)
                assert old.capture.scope.header_namespace is None
                assert old.capture.scope.collection_namespace == "team"
                assert (
                    old.capture.scope.namespace_mode == "one"
                    and old.capture.scope.container == "app"
                )
                assert not source.options.previous and source.options.tail_lines == 1000
                assert source.head_lines is None and "old-app-window" in source.entries[0].line.text
                assert old.current() and old.session == screen.stream.target.session
                if change == "container":
                    await pilot.click("#log-container")
                    await choose_scope(
                        app,
                        pilot,
                        1,
                        effect=lambda: screen.container == "sidecar" and gate.draining.is_set(),
                    )
                elif change == "window":
                    await pilot.click("#log-window")
                    await choose_scope(
                        app,
                        pilot,
                        WINDOWS.index("Head 1000"),
                        effect=lambda: screen.window == "Head 1000" and gate.draining.is_set(),
                    )
                else:
                    await pilot.click("#log-previous")
                await wait_for(gate.draining.is_set)
                assert not old.current() and screen.capture_export(AT) == ()
                assert "old-app-window" in screen.history.entries[0].line.text
                assert len(gate.calls) == 1 and len(queries) == 1
                if change != "container":
                    api.initial["pod-00", "app"] = b"2026-11-05T12:02:00Z new-request-window\n"
                gate.release.set()
                await wait_for(gate.drained.is_set)
                await wait_for(
                    lambda: (
                        len(gate.calls) == 2
                        and bool(screen.capture_export(AT))
                        and bool(screen.history.entries)
                        and "old-app-window" not in screen.history.export()
                    )
                )
                new = capture(screen)
                assert isinstance(new.capture.source, SingleLogsSource)
                assert all(
                    "old-app-window" not in entry.line.text for entry in new.capture.source.entries
                )
                assert "old-app-window" in source.entries[0].line.text
                assert new.capture.scope.container == (
                    "sidecar" if change == "container" else "app"
                )
                assert new.capture.source.options == gate.calls[-1][1]
                assert new.capture.source.options.previous == (change == "previous")
                if change == "window":
                    assert new.capture.source.head_lines == 1000
                    assert (
                        new.capture.source.options.tail_lines == -1
                        and not new.capture.source.options.follow
                    )
                    assert "tailLines" not in queries[-1]
                if change == "previous":
                    assert queries[-1]["previous"] == "true" and queries[-1]["follow"] == "false"
                assert new.capture.scope.source_at is not None
                prepared = await service.prepare(new, "logs")
                assert (
                    str(screen.stream.target.session.connection_id).encode() not in prepared.payload
                )
                assert b"old-app-window" not in prepared.payload and b"new-" in prepared.payload
                service.discard(prepared)
            finally:
                gate.release.set()
        assert all(task.done() for _, _, _, task in gate.calls)
        assert service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)


@pytest.mark.asyncio
async def test_single_capture_is_immutable_on_append_pause_resize_scroll_and_clear(
    tmp_path, monkeypatch
):
    gate = ReadGate(arrival="held-while-paused")
    monkeypatch.setattr(LogStream, "run", gate.wrap(LogStream.run))
    api = single_api()
    async with workspace_api(ns, api.handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            screen = await open_viewer(app, pilot)
            original = capture(screen)
            original_entries = original.capture.source.entries
            baseline = api.requests.copy()
            await api.emit("pod-00", "app", b"2026-11-05T12:00:01Z appended-new-line\n")
            await wait_for(lambda: len(screen.history.entries) == 2)
            assert original.current() and len(original_entries) == 1
            assert all("appended" not in entry.line.text for entry in original_entries)
            await pilot.press("p")
            assert screen.paused
            paused = capture(screen)
            await api.emit("pod-00", "app", b"2026-11-05T12:00:02Z held-while-paused\n")
            await wait_for(gate.arrived.is_set)
            assert len(screen.history.entries) == 2 and paused.current()
            await pilot.resize_terminal(40, 12)
            screen.body.scroll_to(y=0, x=2, animate=False, immediate=True)
            await pilot.pause()
            assert paused.current() and original.current()
            await pilot.press("p")
            await wait_for(lambda: len(screen.history.entries) == 3)
            assert paused.current() and len(paused.capture.source.entries) == 2
            prepared = await service.prepare(original, "logs")
            assert b"appended-new-line" not in prepared.payload
            assert b"held-while-paused" not in prepared.payload
            assert api.requests == baseline
            service.discard(prepared)
            await pilot.press("C")
            assert not original.current() and not paused.current()
            assert not screen.history.entries
            cleared = capture(screen)
            assert cleared.capture.source.entries == () and cleared.capture.scope.source_at is None
            assert api.requests == baseline
        assert all(task.done() for _, _, _, task in gate.calls) and service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["timestamps", "search", "context"])
async def test_single_capture_guard_rejects_presentation_or_context_changes(tmp_path, control):
    api = single_api()
    async with workspace_api(ns, api.handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await open_viewer(app, pilot)
            original = capture(screen)
            if control == "timestamps":
                await pilot.press("t")
                assert not capture(screen).capture.source.show_timestamps
            elif control == "search":
                await pilot.press("slash", *"old", "enter")
                assert capture(screen).capture.presentation.query == "old"
            else:
                await app.workspace.connect("kuberich-test-two")
                assert screen.capture_export(AT) == ()
                assert screen.closed and screen.active_count == 0
            assert not original.current()
            assert service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["window", "previous"])
async def test_aggregate_transition_waits_for_old_owner_and_never_relabels_old_records(
    tmp_path, monkeypatch, change
):
    gate = ReadGate(hold=True)
    monkeypatch.setattr(AggregateLogs, "run", gate.wrap(AggregateLogs.run))
    api = single_api()
    async with workspace_api(ns, api.handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test() as pilot:
            try:
                screen = await open_viewer(app, pilot, aggregate=True, all_namespaces=True)
                old = capture(screen)
                assert isinstance(old.capture.source, AggregateLogsSource)
                records = old.capture.source.records
                assert records and "old-app-window" in records[0].payload
                assert old.capture.scope.header_namespace is None
                assert (
                    old.capture.scope.collection_namespace == "team"
                    and old.capture.scope.container is None
                )
                if change == "window":
                    await press_until(pilot, "o", lambda: isinstance(app.screen, ScopeScreen))
                    await choose_scope(
                        app,
                        pilot,
                        WINDOWS.index("Last 5m"),
                        effect=lambda: screen.window == "Last 5m" and gate.draining.is_set(),
                    )
                else:
                    await press_until(
                        pilot, "v", lambda: screen.previous and gate.draining.is_set()
                    )
                await wait_for(gate.draining.is_set)
                assert not old.current() and screen.capture_export(AT) == ()
                assert "old-app-window" in screen.aggregate.export()
                assert len(gate.calls) == 1
                api.initial["pod-00", "app"] = b"2026-11-05T12:03:00Z new-aggregate-window\n"
                gate.release.set()
                await wait_for(gate.drained.is_set)
                await wait_for(
                    lambda: (
                        len(gate.calls) == 2
                        and bool(screen.capture_export(AT))
                        and "new-aggregate-window" in screen.aggregate.export()
                    )
                )
                current = capture(screen)
                assert current.capture.source.options == gate.calls[-1][1]
                assert current.capture.source.options.previous == (change == "previous")
                assert current.capture.source.options.since_seconds == (
                    300 if change == "window" else None
                )
                assert all(
                    "old-app-window" not in record.payload
                    for record in current.capture.source.records
                )
                assert "old-app-window" in records[0].payload
                prepared = await service.prepare(current, "logs")
                assert (
                    b"new-aggregate-window" in prepared.payload
                    and b"old-app-window" not in prepared.payload
                )
                assert (
                    str(screen.owner.target.session.connection_id).encode() not in prepared.payload
                )
                assert (
                    b"start_token" not in prepared.payload and b"generation" not in prepared.payload
                )
                service.discard(prepared)
            finally:
                gate.release.set()
        assert all(task.done() for _, _, _, task in gate.calls)
        assert service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)


@pytest.mark.asyncio
async def test_aggregate_filter_selection_json_statuses_and_new_lines_keep_captured_provenance(
    tmp_path,
):
    api = single_api(two_containers=True)
    api.pods["pod-00"]["spec"]["initContainers"] = [{"name": "denied"}]
    api.denied.add(("pod-00", "denied"))
    async with workspace_api(ns, api.handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            screen = await open_viewer(app, pilot, aggregate=True)
            await wait_for(
                lambda: len(screen.aggregate.records) == 2 and len(screen.owner.states) == 3
            )
            await wait_for(
                lambda: any(
                    state.status == "failed" and "403" in state.message
                    for state in screen.owner.states.values()
                )
            )
            original = capture(screen)
            baseline = api.requests.copy()
            assert original.capture.source.selected_sources is None
            assert any("denied" in status for _, status in original.capture.source.source_statuses)
            await api.emit("pod-00", "app", b"2026-11-05T12:04:00Z new-after-capture\n")
            await wait_for(lambda: len(screen.aggregate.records) == 3)
            assert original.current() and len(original.capture.source.records) == 2
            await pilot.press("s")
            await wait_for(lambda: isinstance(app.screen, ScopeScreen))
            app_source = next(
                index for index, label in enumerate(app.screen.values) if ":app " in label
            )
            await choose_scope(app, pilot, app_source)
            assert not original.current()
            filtered = capture(screen)
            assert filtered.capture.source.source_filter is not None
            assert len(filtered.capture.source.records) == 3  # Filter is captured separately.
            assert api.requests == baseline
            await pilot.press("J")
            assert not filtered.current()
            json_capture = capture(screen)
            assert json_capture.capture.source.json_mode
            await pilot.press("c")
            await wait_for(lambda: isinstance(app.screen, LogSourcesScreen))
            picker = app.screen
            app_row = next(
                index
                for index in range(picker.table.row_count)
                if ":app " in str(picker.table.get_row_at(index)[1])
            )
            picker.table.move_cursor(row=app_row)
            await pilot.press("enter")
            await wait_for(lambda: screen.owner.selected is not None)
            assert not json_capture.current()
            selected = capture(screen)
            assert selected.capture.source.selected_sources == frozenset({("owned-pod-00", "app")})
            assert len(selected.capture.source.source_statuses) == 3
            prepared = await service.prepare(selected, "logs")
            metadata_line, descriptor_line, *retained = prepared.payload.decode().splitlines()
            descriptor = json.loads(descriptor_line.partition(": ")[2])
            assert descriptor["selected_sources"] == [
                list(key) for key in selected.capture.source.selected_sources
            ]
            assert descriptor["source_filter"] == list(selected.capture.source.source_filter)
            assert len(descriptor["source_statuses"]) == 3
            assert b"denied" in prepared.payload
            assert b"start_token" not in prepared.payload
            assert "kuberich-export" in metadata_line
            assert len(retained) == 2
            assert all(json.loads(line)["source"]["uid"] == "owned-pod-00" for line in retained)
            service.discard(prepared)
            await pilot.press("escape")
            await wait_for(lambda: app.screen is screen)
            await pilot.press("C")
            assert not selected.current() and not screen.aggregate.records
            assert capture(screen).capture.source.records == ()
            assert service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)


@pytest.mark.asyncio
async def test_aggregate_pause_resize_scroll_and_context_keep_or_invalidate_exact_capture(
    tmp_path, monkeypatch
):
    gate = ReadGate(arrival="aggregate-paused-line")
    monkeypatch.setattr(LogStream, "run", gate.wrap(LogStream.run))
    api = single_api()
    async with workspace_api(ns, api.handler) as url:
        app, service = owned_app(tmp_path, url)
        async with app.run_test(size=(120, 36)) as pilot:
            screen = await open_viewer(app, pilot, aggregate=True)
            original = capture(screen)
            assert isinstance(original.capture.source, AggregateLogsSource)
            old_records = original.capture.source.records
            baseline = api.requests.copy()
            await pilot.press("p")
            assert screen.paused
            await api.emit("pod-00", "app", b"2026-11-05T12:05:00Z aggregate-paused-line\n")
            await wait_for(gate.arrived.is_set)
            assert len(screen.aggregate.records) == len(old_records) == 1
            await pilot.resize_terminal(40, 12)
            screen.body.scroll_to(y=0, x=3, animate=False, immediate=True)
            await pilot.pause()
            assert original.current()
            await pilot.press("p")
            await wait_for(lambda: len(screen.aggregate.records) == 2)
            assert original.current() and len(old_records) == 1
            prepared = await service.prepare(original, "logs")
            assert b"aggregate-paused-line" not in prepared.payload
            assert api.requests == baseline
            service.discard(prepared)
            await app.workspace.connect("kuberich-test-two")
            assert not original.current() and screen.capture_export(AT) == ()
            assert screen.closed and screen.active_count == 0
            assert not screen.aggregate.records
        assert all(task.done() for _, _, _, task in gate.calls)
        assert service.operation_count == 0
        await wait_for(lambda: api.active == 0 and api.watch_active == 0)
