"""Actual KubeRich App/Pilot historical metrics against owned synthetic HTTP."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiohttp import web
from textual.widgets import Button

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.exports import TableSource, read_artifact
from kuberich.services.appearance import PreferenceSource
from kuberich.ui.app import KubeRichApp
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.export_review import ExportReviewScreen
from kuberich.ui.history import HistoryScreen
from tests.support.connections import catalog_fixture
from tests.support.export_ui import save_review, service_for
from tests.support.history import history_http
from tests.support.history_explorer import NAMESPACE, POD_PATH, RAW_ERROR, HistoryApi
from tests.support.workspace import stable_watch, wait_for
from tests.ui.test_history_screen import text
from tests.ui.test_live_preferences import save


@asynccontextmanager
async def app_fixture(tmp_path, *, configured=True):
    api = HistoryApi()
    entered, release = asyncio.Event(), asyncio.Event()
    hold = False

    def hold_reads(value):
        nonlocal hold
        hold = value

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        status, value = api.response(request.path, request.query)
        if hold and request.path.endswith("query_range"):
            entered.set()
            await release.wait()
        return web.json_response(value, status=status)

    raw = {"read_only": True}
    if configured:
        raw["observability"] = {"history": {"namespace": NAMESPACE, "service": "metrics"}}
    path = tmp_path / "preferences.yaml"
    write_config(path, parse_document({"schema_version": 1, **raw}))
    document = read_config(path)
    preferences = PreferenceSource(ConfigLocation(path, True), document)
    async with history_http(handler) as url:
        app = KubeRichApp(
            preferences.settings(document),
            logging.Logger("history-owned", 100),
            preferences=preferences,
            catalog=catalog_fixture(tmp_path, url),
            export_service=service_for(tmp_path),
        )
        try:
            yield app, api, path, entered, release, hold_reads
        finally:
            release.set()


async def open_history(app, pilot, *, command=False):
    parent = app.screen
    if command:
        await app.run_command(":history")
    else:
        await pilot.press("M")
    await wait_for(lambda: isinstance(app.screen, HistoryScreen))
    screen = app.screen
    await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
    assert await screen.table.wait_for_refresh()
    return parent, screen


async def open_review(app, pilot):
    await app.run_command(":export")
    await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
    review = app.screen
    await wait_for(lambda: review.ready_to_save)
    return review


async def root_ready(app):
    await wait_for(lambda: app.views.table.row_count > 0)
    assert await app.views.table.wait_for_refresh()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,kind",
    [("pods", "pod"), ("nodes", "node"), ("deployments", "workload"), ("pulse", "cluster")],
)
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_actual_app_entry_scopes_ranges_metric_projection_and_parent_restore(
    tmp_path, route, kind, size
):
    async with app_fixture(tmp_path) as (app, api, *_), app.run_test(size=size) as pilot:
        await root_ready(app)
        await app.run_command(":" + route)
        await wait_for(lambda: app.state.view_kind == route)
        await root_ready(app)
        await pilot.pause()
        table = app.views.table
        if kind != "cluster":
            table.move_cursor(row=0, scroll=False)
        table.scroll_to(x=4, y=0, animate=False, immediate=True, force=True)
        await pilot.pause()
        viewport = table.capture_viewport()
        parent, screen = await open_history(app, pilot, command=kind == "workload")
        assert (
            screen.scope.kind == kind and screen.scope.session == app.sessions.observation.identity
        )
        assert app.focused is screen.table and "last N/A" in text(screen)
        assert "partial" in str(screen.status.content) and "nonfinite" in text(screen)
        for key, duration in zip(
            "1234567", (900, 1800, 3600, 10800, 21600, 43200, 86400), strict=True
        ):
            previous = screen.request
            await pilot.press(key)
            await wait_for(
                lambda previous=previous: (
                    screen.request is not previous and screen.operation_count == 0
                )
            )
            assert screen.snapshot.request_id == screen.request.id
            assert (screen.request.end - screen.request.start).total_seconds() == duration
            assert app.state.namespace == NAMESPACE  # range keys win over root namespace presets
        before = len([path for path, _ in api.requests if path.endswith("query_range")])
        await pilot.press("m", "n", "a", "f", "right_square_bracket")
        await pilot.pause()
        assert screen.device is not None and dict(screen.device)["device"] == "/dev/synthetic-b"
        assert len([path for path, _ in api.requests if path.endswith("query_range")]) == before
        assert ("size minus free" if kind == "node" else "not unique") in text(screen)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is parent and screen.operation_count == 0)
        assert await table.wait_for_refresh()
        assert table.capture_viewport().selected == viewport.selected
        assert (table.scroll_x, table.scroll_y) == (viewport.x, viewport.y)
        assert app.focused is table
    assert app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,field",
    [
        ("app", "containers"),
        ("init", "initContainers"),
        ("sidecar", "initContainers"),
        ("debug", "ephemeralContainers"),
    ],
)
async def test_actual_container_history_keeps_family_shared_network_and_parent_identity(
    tmp_path, name, field
):
    async with app_fixture(tmp_path) as (app, api, *_), app.run_test() as pilot:
        await root_ready(app)
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, ContainerScreen))
        parent = app.screen
        parent.table.move_cursor(row=parent.table.get_row_index(name))
        await pilot.pause()
        viewport = (parent.table.cursor_coordinate, parent.table.scroll_x, parent.table.scroll_y)
        _, screen = await open_history(app, pilot)
        assert screen.scope.kind == "container" and screen.scope.target.container == name
        assert screen.scope.container_field == field
        assert screen.scope.target.uid == api.records[POD_PATH]["metadata"]["uid"]
        await pilot.press("n")
        assert "Pod network shared with this container" in text(screen)
        await pilot.press("escape")
        await wait_for(lambda: app.screen is parent and screen.operation_count == 0)
        assert await parent.table.wait_for_refresh()
        assert (
            parent.table.cursor_coordinate,
            parent.table.scroll_x,
            parent.table.scroll_y,
        ) == viewport
        assert app.focused is parent.table


@pytest.mark.asyncio
async def test_actual_export_review_save_browser_view_copy_is_numeric_sanitized_and_origin_bound(
    tmp_path,
):
    async with app_fixture(tmp_path) as (app, _api, *_), app.run_test() as pilot:
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        await pilot.press("n")
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        assert isinstance(lease.capture.source, TableSource)
        review = await open_review(app, pilot)
        assert isinstance(review, ExportReviewScreen) and lease.current()
        destination = tmp_path / "exports" / "history.txt"
        await save_review(app, pilot, review, destination)
        assert app.screen is screen and lease.current()
        raw = destination.read_text()
        assert "2048" in raw and "nonfinite" in raw and "queried" in raw
        assert "Provider" in raw or "provider" in raw
        assert RAW_ERROR not in raw and "bearer_token_file" not in raw and "ca_file" not in raw
        prepared = read_artifact(destination.read_bytes(), artifact_id=uuid4())
        assert prepared.metadata.scope.uid == screen.scope.target.uid
        await app.run_command(":exports")
        await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
        browser = app.screen
        await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
        async with asyncio.timeout(5):
            assert await browser.wait_for_refresh()
            view_button = browser.query_one("#artifacts-view", Button)
            await wait_for(
                lambda: (
                    app.screen is browser
                    and browser.is_mounted
                    and view_button.is_mounted
                    and view_button.display
                    and view_button.visible
                    and not view_button.disabled
                    and not view_button.has_class("-active")
                    and view_button.region.area > 0
                    and app.get_widget_at(*view_button.region.offset)[0] is view_button
                )
            )
            assert await pilot.click(view_button)
        await wait_for(lambda: isinstance(app.screen, ArtifactViewerScreen))
        viewer = app.screen
        await wait_for(lambda: viewer.prepared is not None and viewer.operation_count == 0)
        await pilot.press("ctrl+y")
        await wait_for(lambda: bool(app.clipboard))
        assert "2048" in viewer.viewer.text and "2048" in app.clipboard
        assert RAW_ERROR not in app.clipboard
        await pilot.press("escape", "escape")
        await wait_for(lambda: app.screen is screen)
        await pilot.press("m")
        assert not lease.current()


@pytest.mark.asyncio
async def test_actual_theme_keeps_held_read_but_observability_reload_revokes_old_request(tmp_path):
    async with (
        app_fixture(tmp_path) as (app, _api, path, entered, release, hold),
        app.run_test() as pilot,
    ):
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        hold(True)
        await pilot.press("r")
        await asyncio.wait_for(entered.wait(), 5)
        request = screen.request
        try:
            save(
                path,
                {
                    "read_only": True,
                    "theme": "textual-light",
                    "observability": {"history": {"namespace": NAMESPACE, "service": "metrics"}},
                },
            )
            await app.live_preferences.check()
            assert screen.request is request and screen.operation_count > 0
            save(
                path,
                {
                    "read_only": True,
                    "observability": {"history": {"namespace": NAMESPACE, "service": "alternate"}},
                },
            )
            await app.live_preferences.check()
            assert screen.snapshot is None
            hold(False)
            release.set()
            await wait_for(
                lambda: (
                    screen.request is not request
                    and screen.snapshot is not None
                    and screen.operation_count == 0
                )
            )
            assert screen.options.endpoint.service == "alternate"
            assert screen.snapshot.request_id == screen.request.id
        finally:
            hold(False)
            release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_actual_denied_or_absent_backend_never_displays_raw_error(tmp_path, status):
    async with app_fixture(tmp_path) as (app, api, *_), app.run_test() as pilot:
        api.status = status
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        assert "forbidden" in text(screen) if status == 403 else "unavailable" in text(screen)
        assert RAW_ERROR not in text(screen)
        assert not any(
            point.value == 0 for series in screen.snapshot.series for point in series.points
        )


@pytest.mark.asyncio
async def test_actual_unconfigured_entry_performs_no_history_request(tmp_path):
    async with app_fixture(tmp_path, configured=False) as (app, api, *_), app.run_test() as pilot:
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        assert "not configured" in str(screen.status.content)
        assert not any(path.endswith("query_range") for path, _ in api.requests)


@pytest.mark.asyncio
async def test_actual_backend_detection_is_explicit_and_keyboard_selects_one_candidate(tmp_path):
    async with app_fixture(tmp_path) as (app, api, *_), app.run_test() as pilot:
        await root_ready(app)
        assert not any(path.endswith("query_range") for path, _ in api.requests)
        _, screen = await open_history(app, pilot)
        before = len([path for path, _ in api.requests if path.endswith("query_range")])
        await pilot.press("d")
        await wait_for(lambda: len(screen.candidates.items) == 2 and screen.operation_count == 0)
        assert len([path for path, _ in api.requests if path.endswith("query_range")]) == before
        assert "metrics-uid" in text(screen) and "alternate-uid" in text(screen)
        await pilot.press("b")
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        first = screen.options.endpoint.service
        await pilot.press("b")
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert {first, screen.options.endpoint.service} == {"metrics", "alternate"}
        request = screen.request
        selected = screen.family
        await pilot.press("colon", "7", "b", "n", "f")
        assert app.focused is screen.command_input
        assert screen.command_input.value == "7bnf"
        assert screen.request is request and screen.family == selected
        await pilot.press("escape")
        assert app.screen is screen and app.focused is screen.table


@pytest.mark.asyncio
async def test_actual_uid_replacement_during_finite_read_cannot_publish_or_export(tmp_path):
    async with (
        app_fixture(tmp_path) as (app, api, _path, entered, release, hold),
        app.run_test() as pilot,
    ):
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        hold(True)
        await pilot.press("r")
        await asyncio.wait_for(entered.wait(), 5)
        try:
            assert not screen.capture_export(datetime.now(UTC))
            api.records[POD_PATH]["metadata"]["uid"] = "replacement-pod-uid"
            hold(False)
            release.set()
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.invalidated and screen.snapshot is None
            assert not screen.capture_export(datetime.now(UTC))
        finally:
            hold(False)
            release.set()


@pytest.mark.asyncio
async def test_actual_namespace_transition_drains_held_detail_before_client_close(tmp_path):
    async with (
        app_fixture(tmp_path) as (app, _api, _path, entered, release, hold),
        app.run_test() as pilot,
    ):
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        hold(True)
        await pilot.press("r")
        await asyncio.wait_for(entered.wait(), 5)
        try:
            await app.run_command(":ctx kuberich-test-Two")
            await wait_for(lambda: app.state.context == "kuberich-test-Two")
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.invalidated and screen.snapshot is None
            assert not screen.capture_export(datetime.now(UTC))
        finally:
            hold(False)
            release.set()


@pytest.mark.asyncio
async def test_actual_export_overlay_keeps_claim_but_valid_reload_revokes_review_capture(tmp_path):
    async with app_fixture(tmp_path) as (app, _api, path, *_), app.run_test() as pilot:
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        review = await open_review(app, pilot)
        assert lease.current() and screen in app.screen_stack
        save(
            path,
            {
                "read_only": True,
                "observability": {"history": {"namespace": NAMESPACE, "service": "alternate"}},
            },
        )
        await app.live_preferences.check()
        assert not lease.current() and screen in app.screen_stack
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert screen.options.endpoint.service == "alternate"
        assert app.screen is review
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen and review.stopped)
        assert screen.capture_export(datetime.now(UTC))[0][1].current()


@pytest.mark.asyncio
async def test_node_detection_uses_captured_selected_namespace_without_narrowing_host_metrics(
    tmp_path,
):
    async with app_fixture(tmp_path) as (app, api, *_), app.run_test() as pilot:
        await root_ready(app)
        await app.run_command(":nodes")
        await wait_for(lambda: app.state.view_kind == "nodes")
        await root_ready(app)
        _, screen = await open_history(app, pilot)
        assert app.state.namespace == NAMESPACE and screen.scope.namespace is None
        before = len([path for path, _ in api.requests if path.endswith("query_range")])
        await pilot.press("d")
        await wait_for(lambda: screen.operation_count == 0)
        assert len(screen.candidates.items) == 2
        assert any(path == "/api/v1/namespaces/team/services" for path, _ in api.requests)
        assert len([path for path, _ in api.requests if path.endswith("query_range")]) == before
        assert screen.scope.namespace is None
        await pilot.press("b")
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert screen.request.scope.namespace is None
        assert any(
            "node_cpu_seconds_total" in parameters["query"]
            and 'namespace="team"' not in parameters["query"]
            for path, parameters in api.requests
            if path.endswith("query_range")
        )
