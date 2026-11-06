"""Actual nested App/Pilot inspection over an owned, read-only HTTP fixture."""

import asyncio
import copy
import logging
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Button

from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.domain.exports import TableSource
from kuberich.domain.resources import resource_record
from kuberich.errors import AppError
from kuberich.services.commands import ScopedCommand
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.artifact_viewer import ArtifactViewerScreen
from kuberich.ui.container_inspection import ContainerInspectionScreen
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.export_review import ExportReviewScreen
from kuberich.ui.logs import LogScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.container_inspection import (
    CONFIG_PATH,
    NAMESPACE,
    POD_PATH,
    PRIVATE_VALUE,
    SECRET_PATH,
    InspectionApi,
)
from tests.support.container_inspection import (
    descriptor as inspection_descriptor,
)
from tests.support.export_ui import save_review, service_for
from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.workspace import stable_watch, wait_for, workspace_api

MARKERS = ("ordinary-literal-marker-你好", "ordinary-config-marker", "ordinary-label-marker")


def populated_api():
    api = InspectionApi()
    pod = api.records[POD_PATH]
    pod["metadata"]["labels"]["plain"] = MARKERS[2]
    env = [
        {"name": "LITERAL", "value": MARKERS[0]},
        {"name": "DERIVED", "value": "$(LITERAL)/$(CONFIG)"},
        {"name": "EMPTY", "value": ""},
        {"name": "LABEL", "valueFrom": {"fieldRef": {"fieldPath": "metadata.labels['plain']"}}},
        {"name": "RUNTIME", "valueFrom": {"fieldRef": {"fieldPath": "status.podIP"}}},
    ]
    app = pod["spec"]["containers"][0]
    app["env"] = env
    api.records[CONFIG_PATH]["data"]["CONFIG"] = MARKERS[1]
    for field in ("initContainers", "ephemeralContainers"):
        for declaration in pod["spec"][field]:
            declaration["env"] = copy.deepcopy(env)
            declaration["envFrom"] = copy.deepcopy(app["envFrom"])
    # Reverse observed names, including an unrelated name, so no position can identify status.
    for field, status in (
        ("containers", "containerStatuses"),
        ("initContainers", "initContainerStatuses"),
        ("ephemeralContainers", "ephemeralContainerStatuses"),
    ):
        pod["status"][status] = [
            {
                "name": declaration["name"],
                "image": "observed/" + declaration["name"],
                "imageID": "opaque://image/" + declaration["name"],
                "containerID": "opaque://runtime/" + declaration["name"],
            }
            for declaration in reversed(pod["spec"][field])
        ]
        pod["status"][status].insert(0, {"name": "unrelated", "imageID": "wrong-status-marker"})
    return api


@asynccontextmanager
async def app_fixture(tmp_path, api=None):
    from kuberich.ui.app import KubeRichApp

    api = populated_api() if api is None else api

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(api.records[POD_PATH]))
        if request.path.endswith("/log"):
            return web.Response(text="owned-container-log\n")
        return await api.handle(request)

    def roots():
        result = legacy_roots()
        result["/api/v1"]["resources"].extend(
            (descriptor("configmaps", kind="ConfigMap"), descriptor("secrets", kind="Secret"))
        )
        return result

    async with workspace_api(
        lambda request: _namespace_response(), handler, discovery_roots=roots
    ) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("container-inspection", level=100),
            catalog=catalog_fixture(tmp_path, url),
            initial_command=ScopedCommand(Command.PODS, NAMESPACE),
            export_service=service_for(tmp_path),
        )
        try:
            yield app, api
        finally:
            api.release.set()


async def _namespace_response():
    return namespaces(NAMESPACE, "default")


async def open_inspector(app, pilot, name="app"):
    await wait_for(lambda: app.resources.row_count == 1)
    await pilot.pause()
    assert await app.resources.wait_for_refresh()
    await pilot.press("enter")
    await wait_for(lambda: isinstance(app.screen, ContainerScreen))
    parent = app.screen
    parent.table.move_cursor(row=parent.table.get_row_index(name))
    await pilot.pause()
    await pilot.press("e")
    await wait_for(lambda: isinstance(app.screen, ContainerInspectionScreen))
    screen = app.screen
    await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
    await pilot.pause()
    assert app.focused is screen.table
    return parent, screen


def select_entry(screen, name):
    entry = next(entry for entry in screen.snapshot.entries if entry.name == name)
    screen.table.move_cursor(row=screen.table.get_row_index(str(entry.id)))


def table_text(screen):
    return "\n".join(
        " ".join(cell.plain for cell in screen.table.get_row(key)) for key in screen.table.rows
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,kind,field",
    [
        ("app", "App", "containers"),
        ("init", "Init", "initContainers"),
        ("sidecar", "Sidecar", "initContainers"),
        ("debug", "Ephemeral", "ephemeralContainers"),
    ],
)
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_nested_family_identity_hidden_metadata_status_and_parent_viewport(
    tmp_path, name, kind, field, size
):
    async with app_fixture(tmp_path) as (app, api):
        async with app.run_test(size=size) as pilot:
            parent, screen = await open_inspector(app, pilot, name)
            assert (
                screen.snapshot.container.name,
                screen.snapshot.container.kind,
                screen.snapshot.container.field,
            ) == (name, kind, field)
            assert not screen.viewer.text and not app.clipboard
            assert screen.table.content_region.height >= 1
            assert screen.query_one("#container-inspection-back", Button).region.bottom <= size[1]
            parent_viewport = (
                parent.table.cursor_coordinate,
                parent.table.scroll_x,
                parent.table.scroll_y,
            )
            for marker in (*MARKERS, PRIVATE_VALUE):
                assert marker not in table_text(screen) and marker not in repr(screen.snapshot)
            assert "runtime-field" in table_text(screen)
            await pilot.press("i")
            await pilot.pause()
            text = table_text(screen)
            assert "observed/" + name in text and "opaque://runtime/" + name in text
            assert "wrong-status-marker" not in text
            await pilot.press("s")
            await pilot.pause()
            assert "inspection-config" in table_text(screen) and "available" in table_text(screen)
            assert not screen.viewer.text
            await pilot.press("escape")
            await wait_for(lambda: screen.operation_count == 0)
            assert app.screen is parent and app.focused is parent.table
            assert await parent.table.wait_for_refresh()
            assert (
                parent.table.cursor_coordinate,
                parent.table.scroll_x,
                parent.table.scroll_y,
            ) == parent_viewport
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, LogScreen) and bool(app.screen.body.rows))
            assert app.screen.container == name
            await pilot.press("escape", "escape")
            assert app.focused is app.resources
        assert app.sessions.client is None and api.active == 0


@pytest.mark.asyncio
async def test_reveal_and_copy_are_distinct_fresh_reads_and_screenshots_remain_blocked(tmp_path):
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        before = len(api.requests)
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert screen.viewer.text == MARKERS[0]
        assert len(api.requests) > before
        with pytest.raises(AppError, match="sensitive"):
            app.export_screenshot()
        assert app.deliver_screenshot("blocked.svg", str(tmp_path)) is None
        assert not (tmp_path / "blocked.svg").exists()
        before = len(api.requests)
        await pilot.press("ctrl+y")
        await wait_for(lambda: app.clipboard == MARKERS[0])
        assert len(api.requests) > before and not screen.viewer.text and not screen.revealed
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        select_entry(screen, "DERIVED")
        await pilot.pause()
        assert not screen.viewer.text
        assert "Values hidden" in str(screen.status.content)
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert screen.viewer.text == MARKERS[0] + "/" + MARKERS[1]
        await pilot.press("i")
        assert not screen.viewer.text
        await pilot.press("colon", "e", "i", "s", "r")
        assert screen.command_input.value == "eisr" and screen.section == "image"
        await pilot.press("escape", "escape")
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.snapshot is None and not screen.viewer.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "resourceVersion", "content"])
async def test_changed_source_requires_reload_before_fresh_copy(tmp_path, change):
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "CONFIG")
        await pilot.pause()
        source = api.records[CONFIG_PATH]
        if change == "content":
            source["data"]["CONFIG"] = "changed-current-source"
        else:
            source["metadata"][change] += "-changed"
        await pilot.press("r")
        await wait_for(lambda: "reload required" in str(screen.status.content))
        assert not screen.viewer.text and not app.clipboard
        assert screen.reload_required
        reads = len(api.requests)
        await pilot.press("down", "i", "s", "e")
        screen.hide_value()
        assert "reload required" in str(screen.status.content)
        assert not screen.check_action("copy", ())
        screen.action_copy()
        assert len(api.requests) == reads and "reload required" in str(screen.status.content)
        await pilot.press("R")
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert not screen.reload_required
        await pilot.pause()
        select_entry(screen, "CONFIG")
        await pilot.pause()
        await pilot.press("ctrl+y")
        await wait_for(lambda: bool(app.clipboard))
        assert app.clipboard == source["data"]["CONFIG"]


@pytest.mark.asyncio
async def test_export_review_from_actual_reveal_contains_only_frozen_metadata(tmp_path):
    async with app_fixture(tmp_path) as (app, _), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "DERIVED")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        choices = screen.capture_export(datetime.now(UTC))
        assert tuple(kind for kind, _ in choices) == ("screen",)
        lease = choices[0][1]
        assert isinstance(lease.capture.source, TableSource) and lease.current()
        for marker in (*MARKERS, PRIVATE_VALUE, screen.snapshot.pod.payload_sha256):
            assert marker not in repr(lease.capture.source.rows)
        await pilot.press("colon", "e", "x", "p", "o", "r", "t", "enter")
        await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
        review = app.screen
        await wait_for(lambda: review.ready_to_save)
        assert isinstance(review, ExportReviewScreen) and not screen.viewer.text
        with pytest.raises(AppError, match="sensitive"):
            app.export_screenshot()
        assert lease.current()  # Legitimate export suspension preserves metadata capture.
        destination = tmp_path / "exports" / "inspection.txt"
        await save_review(app, pilot, review, destination)
        for marker in (*MARKERS, PRIVATE_VALUE, screen.snapshot.pod.payload_sha256):
            assert marker not in destination.read_text()
        assert app.screen is screen
        await pilot.press("colon", "e", "x", "p", "o", "r", "t", "s", "enter")
        await wait_for(lambda: isinstance(app.screen, ArtifactBrowserScreen))
        browser = app.screen
        await wait_for(lambda: browser.listing is not None and browser.operation_count == 0)
        assert browser.table.row_count == 1
        await pilot.click("#artifacts-view")
        await wait_for(lambda: isinstance(app.screen, ArtifactViewerScreen))
        viewer = app.screen
        await wait_for(lambda: viewer.prepared is not None and viewer.operation_count == 0)
        await pilot.press("ctrl+y")
        await wait_for(lambda: bool(app.clipboard))
        for marker in (*MARKERS, PRIVATE_VALUE, screen.snapshot.pod.payload_sha256):
            assert marker not in viewer.viewer.text and marker not in app.clipboard
        await pilot.press("escape", "escape")
        await wait_for(lambda: app.screen is screen)
        screen.action_section("image")
        assert not lease.current()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,state", [(403, "forbidden"), (404, "not-found")])
async def test_source_failures_remain_distinct_and_never_show_server_body(tmp_path, status, state):
    api = populated_api()
    api.statuses[SECRET_PATH] = status
    async with app_fixture(tmp_path, api) as (app, _), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        await pilot.press("s")
        await pilot.pause()
        assert state in table_text(screen)
        assert "inspection-private-server-body" not in table_text(screen)
        assert not screen.viewer.text


@pytest.mark.asyncio
async def test_held_disclosure_revoked_by_navigation_scope_change_and_repeated_close(tmp_path):
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        api.started.clear()
        api.held_paths.add(CONFIG_PATH)
        reads = len(api.requests)
        await pilot.press("r")
        await wait_for(
            lambda: (
                api.active > 0 and any(path == CONFIG_PATH for _, path, _ in api.requests[reads:])
            )
        )
        await pilot.press("down")
        api.release.set()
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.viewer.text and not app.clipboard
        api.release.clear()
        api.started.clear()
        await pilot.press("r")
        await wait_for(lambda: api.active > 0)
        closing = asyncio.create_task(screen.stop_owned())
        repeated = asyncio.create_task(screen.stop_owned())
        api.release.set()
        await asyncio.gather(closing, repeated)
        assert screen.operation_count == 0 and not screen.viewer.text and screen.snapshot is None
        await app.workspace.select_namespace("default")
        assert not app.clipboard


@pytest.mark.asyncio
async def test_nested_inspector_preserves_scrolled_parent_and_root_viewports(tmp_path):
    api = populated_api()
    declarations = api.records[POD_PATH]["spec"]["containers"]
    for ordinal in range(30):
        extra = copy.deepcopy(declarations[0])
        extra["name"] = f"worker-{ordinal:02}"
        declarations.append(extra)
    async with app_fixture(tmp_path, api) as (app, _), app.run_test(size=(40, 12)) as pilot:
        await wait_for(lambda: app.resources.row_count == 1)
        await pilot.pause()
        assert await app.resources.wait_for_refresh()
        await pilot.press("end")
        await pilot.pause()
        root_before = app.resources.capture_viewport()
        assert root_before.x > 0
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, ContainerScreen))
        parent = app.screen
        parent.table.move_cursor(row=parent.table.get_row_index("worker-26"))
        await pilot.press("end")
        await pilot.pause()
        assert await parent.table.wait_for_refresh()
        before = parent.table.cursor_coordinate, parent.table.scroll_x, parent.table.scroll_y
        assert before[1] > 0 and before[2] > 0
        await pilot.press("e")
        await wait_for(lambda: isinstance(app.screen, ContainerInspectionScreen))
        screen = app.screen
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert screen.snapshot.container.name == "worker-26"
        await pilot.press("escape")
        await wait_for(lambda: app.screen is parent and screen.operation_count == 0)
        assert await parent.table.wait_for_refresh()
        assert (
            parent.table.cursor_coordinate,
            parent.table.scroll_x,
            parent.table.scroll_y,
        ) == before
        await pilot.press("escape")
        assert await app.resources.wait_for_refresh()
        assert app.resources.capture_viewport() == root_before


@pytest.mark.asyncio
async def test_empty_unresolved_and_incomplete_values_remain_distinct(tmp_path):
    api = populated_api()
    api.records[POD_PATH]["spec"]["containers"][0]["env"].append(
        {"name": "INCOMPLETE", "value": "$(UNOBSERVED_SERVICE_VARIABLE)"}
    )
    async with app_fixture(tmp_path, api) as (app, _), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "EMPTY")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert screen.viewer.text == ""
        select_entry(screen, "RUNTIME")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: "unresolved" in str(screen.status.content))
        assert not screen.revealed and not screen.viewer.text
        select_entry(screen, "INCOMPLETE")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert "incomplete" in str(screen.status.content)
        await pilot.press("ctrl+y")
        await wait_for(lambda: "copying is unavailable" in str(screen.status.content))
        assert not screen.viewer.text and not app.clipboard


@pytest.mark.asyncio
async def test_bounded_preview_refused_oversize_copy_and_fixed_clipboard_error(
    tmp_path, monkeypatch
):
    api = populated_api()
    api.records[POD_PATH]["spec"]["containers"][0]["env"][0]["value"] = "ordinary-large-你好" * 7000
    async with app_fixture(tmp_path, api) as (app, _), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert screen.viewer.text.endswith("[Preview limited to 16384 characters]")
        assert len(screen.viewer.text) < 16500
        await pilot.press("ctrl+y")
        await wait_for(lambda: "64 KiB" in str(screen.status.content))
        assert not screen.viewer.text and not app.clipboard
        select_entry(screen, "CONFIG")
        await pilot.pause()

        def refused(value):
            raise RuntimeError(value)

        monkeypatch.setattr(app, "copy_to_clipboard", refused)
        await pilot.press("ctrl+y")
        await wait_for(lambda: "Clipboard write failed" in str(screen.status.content))
        assert MARKERS[1] not in str(screen.status.content) and not screen.viewer.text


@pytest.mark.asyncio
async def test_observed_pod_version_revokes_reveal_and_leases_reload_then_scope_drains(tmp_path):
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "LABEL")
        await pilot.pause()
        await pilot.press("r")
        await wait_for(lambda: screen.revealed)
        assert screen.viewer.text == MARKERS[2]
        lease = screen.capture_export(datetime.now(UTC))[0][1]
        api.records[POD_PATH]["metadata"]["resourceVersion"] = "new-observed-version"
        record = resource_record(inspection_descriptor("Pod"), api.records[POD_PATH])
        screen.observe_pod(record)
        assert not screen.viewer.text and not lease.current() and screen.snapshot is None
        assert "reload required" in str(screen.status.content)
        assert screen.reload_required
        screen.action_section("image")
        screen.action_section("environment")
        assert "reload required" in str(screen.status.content)
        await pilot.press("R")
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert screen.table.get_row_at(screen.table.cursor_row)[0].plain == "LABEL"
        fresh = screen.capture_export(datetime.now(UTC))[0][1]
        assert fresh.current()
        await app.workspace.select_namespace("default")
        await wait_for(lambda: screen.operation_count == 0 and screen.invalidated)
        assert not fresh.current() and not screen.viewer.text
        assert app.operations.retained_inspection_count == 0
        screen.action_reveal()
        assert "stopped" in str(screen.status.content)


@pytest.mark.asyncio
async def test_unmounted_inspector_closes_once_and_export_has_no_underlying_resource(tmp_path):
    from kuberich.domain.exports import SupportSource

    async with app_fixture(tmp_path) as (app, _), app.run_test() as pilot:
        parent, screen = await open_inspector(app, pilot)
        choices = dict(app.export_sources.capture(datetime.now(UTC)))
        assert set(choices) == {"screen", "support"}
        support = choices["support"].capture.source
        assert (
            isinstance(support, SupportSource) and support.resource is None and support.logs is None
        )
        assert "Resource YAML is unavailable for this origin." in support.omissions
        lease = choices["screen"]
        await pilot.click("#container-inspection-back")
        await wait_for(lambda: app.screen is parent and screen.operation_count == 0)
        await asyncio.gather(screen.stop_owned(), screen.stop_owned())
        assert not lease.current() and not screen.capture_export(datetime.now(UTC))
        assert app.operations.retained_inspection_count == 0


@pytest.mark.asyncio
async def test_buttons_enter_reveal_hide_copy_sections_reload_and_back(tmp_path):
    async with app_fixture(tmp_path) as (app, _), app.run_test() as pilot:
        parent, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        await pilot.press("enter")
        await wait_for(lambda: screen.revealed)
        await pilot.click("#container-inspection-reveal")
        assert not screen.viewer.text and not screen.revealed
        await wait_for(
            lambda: (
                not screen.query_one("#container-inspection-reveal", Button).has_class("-active")
            )
        )
        await pilot.click("#container-inspection-reveal")
        await wait_for(lambda: screen.revealed)
        await pilot.click("#container-inspection-copy")
        await wait_for(lambda: app.clipboard == MARKERS[0])
        await pilot.click("#container-inspection-image")
        assert screen.section == "image" and not screen.viewer.text
        await pilot.click("#container-inspection-sources")
        assert screen.section == "sources"
        await pilot.click("#container-inspection-environment")
        assert screen.section == "environment"
        old = screen.snapshot
        await pilot.click("#container-inspection-reload")
        await wait_for(lambda: screen.snapshot is not None and screen.snapshot is not old)
        await pilot.click("#container-inspection-back")
        await wait_for(lambda: app.screen is parent and screen.operation_count == 0)


@pytest.mark.asyncio
async def test_initial_read_failure_is_fixed_reload_recovers_without_stealing_command_focus(
    tmp_path,
):
    api = populated_api()
    api.statuses[POD_PATH] = 403
    async with app_fixture(tmp_path, api) as (app, _), app.run_test() as pilot:
        await wait_for(lambda: app.resources.row_count == 1)
        await pilot.pause()
        await pilot.press("enter", "e")
        await wait_for(lambda: isinstance(app.screen, ContainerInspectionScreen))
        screen = app.screen
        await wait_for(lambda: screen.operation_count == 0)
        assert "read failed" in str(screen.status.content) and screen.snapshot is None
        assert not screen.capture_export(datetime.now(UTC))
        screen.action_section("image")
        screen.action_copy()
        assert "Select a current environment" in str(screen.status.content)
        api.statuses.clear()
        api.held_paths.add(CONFIG_PATH)
        api.started.clear()
        screen.action_section("environment")
        screen.action_reload()
        await wait_for(lambda: api.active > 0)
        screen.focus_command()
        await pilot.press("r")
        assert not screen.check_action("reveal", ())
        api.release.set()
        await wait_for(lambda: screen.snapshot is not None and screen.operation_count == 0)
        assert app.focused is screen.command_input and screen.command_input.value == "r"


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["selection", "section", "export"])
async def test_ui_rechecks_delayed_real_service_result_before_publication(
    tmp_path, monkeypatch, transition
):
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        started, release = asyncio.Event(), asyncio.Event()
        original = screen.service.disclose

        async def delayed(intent):
            result = await original(intent)
            started.set()
            await release.wait()
            return result

        monkeypatch.setattr(screen.service, "disclose", delayed)
        await pilot.press("r")
        await asyncio.wait_for(started.wait(), 5)
        if transition == "selection":
            screen.action_copy()
            assert "in progress" in str(screen.status.content)
            await pilot.press("down")
        elif transition == "section":
            await pilot.press("i")
        else:
            await pilot.press("colon", "e", "x", "p", "o", "r", "t", "enter")
            await wait_for(lambda: isinstance(app.screen, ExportReviewScreen))
            before = len(api.requests)
            screen.action_copy()
            assert len(api.requests) == before
        release.set()
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.viewer.text and not app.clipboard


@pytest.mark.asyncio
async def test_unexpected_disclosure_failure_never_displays_exception_payload(
    tmp_path, monkeypatch
):
    async with app_fixture(tmp_path) as (app, _), app.run_test() as pilot:
        _, screen = await open_inspector(app, pilot)

        async def failed(intent):
            raise RuntimeError("ordinary-unexpected-error-value-marker")

        monkeypatch.setattr(screen.service, "disclose", failed)
        await pilot.press("r")
        await wait_for(lambda: "inspection failed" in str(screen.status.content))
        assert "ordinary-unexpected" not in str(screen.status.content) and not screen.viewer.text
        assert app.is_running


@pytest.mark.asyncio
async def test_detached_inspector_retains_held_resolution_until_real_workspace_client_close(
    tmp_path, monkeypatch
):
    import kuberich.services.container_inspection as implementation

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    resolve = implementation.resolve_selected

    def held_resolution(snapshot, entry, pod, sources):
        started.set()
        try:
            assert release.wait(5), "The owned resolution worker was not released."
            return resolve(snapshot, entry, pod, sources)
        finally:
            finished.set()

    monkeypatch.setattr(implementation, "resolve_selected", held_resolution)
    async with app_fixture(tmp_path) as (app, api), app.run_test() as pilot:
        parent, screen = await open_inspector(app, pilot)
        select_entry(screen, "LITERAL")
        await pilot.pause()
        client = app.sessions.client
        assert client is screen.service.client and client.api is not None
        client_api = client.api
        directory = Path(client.directory.name)
        assert directory.is_dir()
        before_close_started, client_close_started = asyncio.Event(), asyncio.Event()
        before_close = app.sessions.before_close
        close_client = client.close
        assert before_close is not None

        async def observe_before_close(selected):
            assert selected is client
            before_close_started.set()
            await before_close(selected)

        async def observe_client_close():
            client_close_started.set()
            await close_client()

        monkeypatch.setattr(app.sessions, "before_close", observe_before_close)
        monkeypatch.setattr(client, "close", observe_client_close)
        back = closing = None
        reads = len(api.requests)
        outcomes = []
        try:
            await pilot.press("r")
            assert await asyncio.to_thread(started.wait, 5)
            assert [path for _, path, _ in api.requests[reads:]] == [
                POD_PATH,
                CONFIG_PATH,
                SECRET_PATH,
                POD_PATH,
            ]
            back = asyncio.create_task(pilot.press("escape"))
            await wait_for(lambda: screen not in app.screen_stack)
            await wait_for(lambda: screen.invalidated)
            assert app.screen is parent
            assert app.operations.retained_inspection_count == 1
            assert screen.service.operation_count == 1 and screen.operation_count > 0
            assert not finished.is_set() and not screen.viewer.text

            closing = asyncio.create_task(app.workspace.close())
            await asyncio.wait_for(before_close_started.wait(), 5)
            assert not closing.done() and not client_close_started.is_set()
            assert app.sessions.client is client and client.api is client_api
            assert directory.is_dir() and not finished.is_set()
            # The public transport still performs a real owned API read while
            # before_close waits for the detached inspector's parser drainage.
            live = await asyncio.wait_for(client.get_json(POD_PATH), 5)
            assert live["metadata"]["uid"] == screen.service.target.uid
            assert not closing.done() and not client_close_started.is_set()
            assert app.operations.retained_inspection_count == 1
        finally:
            release.set()
            outcomes = await asyncio.wait_for(
                asyncio.gather(
                    *(task for task in (back, closing) if task is not None),
                    return_exceptions=True,
                ),
                5,
            )
        assert not any(isinstance(outcome, BaseException) for outcome in outcomes)
        assert finished.is_set() and client_close_started.is_set()
        assert app.sessions.client is None and client.api is None and not directory.exists()
        assert screen.operation_count == 0 and screen.service.operation_count == 0
        assert app.operations.retained_inspection_count == 0
        assert screen.snapshot is None and not screen.viewer.text and not app.clipboard
        assert api.active == 0
