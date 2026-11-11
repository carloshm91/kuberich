"""Native Helm routes with owned HTTP metadata and an actual fixture executable."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest, ConnectionState
from kuberich.domain.helm import HelmReleaseKey
from kuberich.domain.navigation import HelmBookmark
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService, ScopedCommand, suggestions
from kuberich.services.helm import HelmService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.helm_inspection import HelmInspectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.helm import HelmMetadataAPI, calls, fake_helm, storage_list
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


@asynccontextmanager
async def helm_app(
    tmp_path,
    *,
    read_only=False,
    initial=Command.EMPTY,
    connection=None,
    connection_status=200,
    **options,
):
    settings, environment, scenario, record = fake_helm(tmp_path, **options)
    api = HelmMetadataAPI()
    api.connection_status = connection_status
    marker = tmp_path / "rollback-effect"
    api.rollback_marker = marker
    environment["KUBERICH_HELM_FIXTURE_ROLLBACK_MARKER"] = str(marker)
    services = []

    async def namespace_response(request):
        if api.connection_status == "disconnect":
            request.transport.close()
            return web.Response()
        if api.connection_status != 200:
            return web.json_response({}, status=api.connection_status)
        return namespaces("team", "other", "default")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if "/secrets" in request.path or "/configmaps" in request.path:
            api.requests.append(
                (request.path, dict(request.query), request.headers.get("Accept", ""))
            )
            api.started.set()
            if api.block:
                await api.release.wait()
            if api.status != 200:
                return web.json_response({}, status=api.status)
            if marker.exists():
                from tests.support.helm import storage

                api.records[3]["metadata"]["labels"]["status"] = "superseded"
                api.records[4] = storage(4, status="deployed")
            if request.path.rsplit("/", 1)[-1].startswith("sh.helm.release"):
                item = next(
                    (
                        item
                        for item in api.records.values()
                        if item["metadata"]["name"] == request.path.rsplit("/", 1)[-1]
                    ),
                    None,
                )
                return (
                    web.json_response(item)
                    if item is not None
                    else web.json_response({}, status=404)
                )
            return web.json_response(storage_list(list(api.records.values())))
        return web.json_response(collection())

    async with workspace_api(namespace_response, resources) as url:

        def factory(client, current):
            service = HelmService(
                client,
                AccessPolicy(read_only),
                settings,
                environment,
                tmp_path,
                current,
                catalog_directory=tmp_path / "owned-catalog",
            )
            services.append(service)
            return service

        app = KubeRichApp(
            Settings(read_only=read_only),
            logging.Logger("helm-ui", level=100),
            catalog=catalog_fixture(tmp_path, url),
            connection=connection or ConnectionRequest(),
            initial_command=initial,
            environment=environment,
            directory=tmp_path,
            helm_factory=factory,
        )
        try:
            yield app, api, services, scenario, record
        finally:
            api.release.set()


async def helm_ready(app, *, row_count=None):
    await wait_for(
        lambda: (
            app.views.route.kind is ViewKind.HELM
            and app.workspace.store.observation.helm is not None
            and not app.workspace.store.observation.helm.collecting
            and (
                app.workspace.store.observation.helm.listing is not None
                or app.workspace.store.observation.helm.problem is not None
            )
            and app.helm_table.request == app.workspace.helm_request
            and (row_count is None or app.helm_table.row_count == row_count)
        )
    )
    assert await asyncio.wait_for(app.helm_table.wait_for_refresh(), 5)


async def open_inspector(app, pilot):
    await helm_ready(app)
    await pilot.pause()
    app.set_focus(app.helm_table)
    await pilot.press("enter")
    await wait_for(lambda: isinstance(app.screen, HelmInspectionScreen))
    await wait_for(lambda: app.screen.is_mounted and bool(app.screen.viewer.text))
    return app.screen


def test_helm_command_contract_and_bookmarks_keep_existing_history_rollback():
    commands = CommandService(AccessPolicy(True))
    assert commands.resolve(":helm") is Command.HELM
    assert commands.resolve(":helm team") == ScopedCommand(Command.HELM, "team")
    assert commands.resolve(":helm *") == ScopedCommand(Command.HELM, "*")
    for text in ("helm team extra", "helm -namespace", "helm ../team"):
        with pytest.raises(AppError):
            commands.resolve(text)
    assert commands.resolve("history") is Command.HISTORY
    with pytest.raises(AppError):
        commands.resolve("rollback 1")
    assert CommandService(AccessPolicy(False)).resolve("rollback 1") == ScopedCommand(
        Command.ROLLBACK, "1"
    )
    assert suggestions("helm ", (), ("*", "team")) == ("helm *", "helm team")
    assert ViewRoute.helm().selection is None
    assert ViewRoute.helm().display_key == "helm"
    with pytest.raises(AppError):
        HelmBookmark("../bad")
    assert HelmBookmark(None, HelmReleaseKey("team", "demo")).namespace is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial", [Command.HELM, ScopedCommand(Command.HELM, "team"), ScopedCommand(Command.HELM, "*")]
)
async def test_initial_helm_routes_probe_only_after_explicit_command(tmp_path, initial):
    async with helm_app(tmp_path, initial=initial) as (app, _api, services, _scenario, record):
        assert not record.exists()
        async with app.run_test(size=(100, 30)) as pilot:
            await helm_ready(app)
            await pilot.pause()
            assert app.helm_table.row_count == 1
            assert app.helm_table.selected_release().key == HelmReleaseKey("team", "demo")
            assert app.state.scope is None
            assert "helm" in app.header.binding_profile or app.header.binding_profile == "resources"
            assert all(
                not app.check_action(action, ())
                for action in (
                    "edit",
                    "inspect_yaml",
                    "review_delete",
                    "xray",
                    "logs",
                    "port_forward",
                    "views",
                )
            )
            probe = calls(record)[0]["argv"]
            assert probe[-2:] == ["version", "--template={{.Version}}"]
            assert "--kube-context=kuberich-test-one" in probe
            assert any(argument.startswith("--kubeconfig=") for argument in probe)
            assert any(argument.startswith("--namespace=") for argument in probe)
        assert services and all(service.operation_count == 0 for service in services)


@pytest.mark.asyncio
async def test_helm_picker_filter_sort_refresh_back_forward_and_inspect(tmp_path):
    async with (
        helm_app(tmp_path) as (app, _api, _services, _scenario, record),
        app.run_test(size=(80, 24)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        assert not record.exists()
        await app.run_command("helm")
        await helm_ready(app)
        await pilot.press("s", "S")
        column, descending = app.helm_table.sort_column, app.helm_table.descending
        app.filter_input.value = "demo"
        await pilot.pause()
        app.set_focus(app.helm_table)
        request = app.workspace.helm_request
        await pilot.press("f4")
        await helm_ready(app)
        assert app.workspace.helm_request != request
        assert app.filter_input.value == "demo"
        assert (app.helm_table.sort_column, app.helm_table.descending) == (column, descending)
        await app.run_command("ns")
        await wait_for(lambda: app.namespace_table.row_count == 3)
        await app.run_command("ns *")
        await helm_ready(app)
        assert app.state.namespace is None
        await app.run_command("pods")
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("back")
        await helm_ready(app)
        assert app.state.namespace is None
        screen = await open_inspector(app, pilot)
        assert "Revision: 3" in screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: app.screen is app.screen_stack[0])
        assert screen.viewer.text == "" and screen.operation_count == 0
        await app.run_command("forward")
        await wait_for(lambda: app.views.route.kind is ViewKind.PODS)


@pytest.mark.asyncio
async def test_unsupported_driver_is_feature_local_and_never_probes_at_startup(tmp_path):
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("unsupported-driver", level=100),
        environment={"HELM_DRIVER": "sql"},
    )
    async with app.run_test() as pilot:
        await app.run_command("helm")
        await pilot.pause()
        assert app.views.route.kind is ViewKind.PODS
        assert "driver" in str(app.status.content).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options, expected", [({"version": "v2.0.0"}, "supported"), ({"mode": "malformed"}, "output")]
)
async def test_helm_tool_errors_remain_local_and_actionable(tmp_path, options, expected):
    async with (
        helm_app(tmp_path, **options) as (app, _api, _services, _scenario, _record),
        app.run_test(),
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        await helm_ready(app)
        assert app.workspace.store.observation.helm.problem is not None
        assert expected in str(app.status.content).lower()
        assert app.helm_table.row_count == 0
        await app.run_command("pods")
        await wait_for(lambda: app.state.scope is not None)


@pytest.mark.asyncio
async def test_failed_refresh_retains_stale_rows_and_refuses_inspection(tmp_path):
    async with (
        helm_app(tmp_path) as (app, _api, _services, scenario, _record),
        app.run_test() as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        await helm_ready(app)
        scenario.write_text(json.dumps({"mode": "error"}))
        await pilot.press("f4")
        await helm_ready(app)
        assert app.helm_table.row_count == 1
        assert "STALE" in str(app.status.content)
        await app.helm_actions.inspect()
        assert len(app.screen_stack) == 1
        assert "current Helm release" in str(app.status.content)


@pytest.mark.asyncio
async def test_disconnected_helm_and_invalid_scope_do_not_create_target_authority(tmp_path):
    app = KubeRichApp(
        Settings(read_only=True), logging.Logger("helm-disconnected", level=100), environment={}
    )
    async with app.run_test():
        await app.run_command("helm")
        assert "Connect to a context" in str(app.status.content)
        await app.helm_actions.inspect()
        assert len(app.screen_stack) == 1
        assert app.workspace.helm_request is None


def listed(name, namespace="team", revision=3):
    return {
        "name": name,
        "namespace": namespace,
        "revision": str(revision),
        "status": "deployed",
        "chart": "[red]tiny[/red]-0.1.0",
        "app_version": "1.0",
        "updated": "2026-11-09 12:00:00 +0000 UTC",
    }


@pytest.mark.asyncio
async def test_duplicate_names_typed_sort_filter_and_viewport_survive_real_refresh(tmp_path):
    rows = [
        listed(f"release-{index:03}", namespace, index + 1)
        for namespace in ("team", "other")
        for index in range(35)
    ]
    async with (
        helm_app(tmp_path, releases=rows, initial=ScopedCommand(Command.HELM, "*")) as (
            app,
            _api,
            _services,
            scenario,
            _record,
        ),
        app.run_test(size=(80, 20)) as pilot,
    ):
        await helm_ready(app)
        assert app.helm_table.row_count == 70
        table = app.helm_table
        await pilot.click("#helm-releases", offset=(3, 0))
        assert table.sort_column == "namespace"
        await pilot.click("#helm-releases", offset=(3, 0))
        assert table.descending
        table.restore_sort("revision", True)
        await pilot.pause()
        assert table.selected_release().key.namespace in {"team", "other"}
        assert table.get_cell("team/release-000", "chart").plain == "[red]tiny[/red]-0.1.0"
        assert not table.get_cell("team/release-000", "chart").spans
        table.move_cursor(row=table.get_row_index("team/release-020"))
        await pilot.pause()
        table.scroll_to(8, 20, animate=False, immediate=True, force=True)
        await pilot.pause()
        before = table.capture_viewport()
        scenario.write_text(json.dumps({"releases": list(reversed(rows))}))
        await pilot.press("f4")
        await helm_ready(app)
        await pilot.pause()
        assert table.capture_viewport().selected == before.selected
        assert table.capture_viewport().x == before.x
        app.filter_input.value = "other"
        await wait_for(lambda: table.row_count == 35)
        assert all(
            table.get_cell(row.key, "namespace").plain == "other" for row in table.ordered_rows
        )
        app.filter_input.value = "no-matches"
        await wait_for(lambda: table.row_count == 0)
        assert table.selected_release() is None
        app.filter_input.value = ""
        await wait_for(lambda: table.row_count == 70)
        table.restore_sort("updated", False)
        assert table.sort_column == "name"
        request = app.workspace.helm_request
        snapshot = app.workspace.store.observation.helm
        driver = app.views.registry.resolve(app.views.route)
        viewport = driver.capture_viewport()
        driver.restore_viewport(viewport)
        assert "edit" not in driver.available_actions(app.presenter.capture())
        assert not await table.apply_rows((), snapshot, lambda: False)
        assert request.generation > 1
        assert not await table.apply_rows(
            (),
            replace(snapshot, request=replace(request, generation=request.generation - 1)),
            lambda: True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [listed(f"release-{index:03}") for index in range(501)]])
async def test_empty_and_incomplete_are_distinct_native_states(tmp_path, rows):
    async with (
        helm_app(tmp_path, releases=rows, initial=Command.HELM) as (
            app,
            _api,
            _services,
            _scenario,
            _record,
        ),
        app.run_test() as pilot,
    ):
        await helm_ready(app)
        await pilot.pause()
        if rows:
            assert app.helm_table.row_count == 500
            assert "INCOMPLETE" in str(app.status.content)
            assert app.workspace.store.observation.helm.listing.complete is False
        else:
            assert app.helm_table.row_count == 0
            assert app.workspace.store.observation.helm.problem is None
            assert "No Helm releases" in str(app.query_one("#empty-title").content)


@pytest.mark.asyncio
async def test_missing_tool_and_metadata_denial_do_not_escape_the_feature(tmp_path):
    async with (
        helm_app(tmp_path) as (app, api, _services, _scenario, record),
        app.run_test() as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        await helm_ready(app)
        api.status = 403
        await app.helm_actions.inspect()
        assert len(app.screen_stack) == 1
        assert "storage" in str(app.status.content).lower()
        (tmp_path / "helm-fixture").unlink()
        await pilot.press("f4")
        await helm_ready(app)
        assert app.workspace.store.observation.helm.problem.kind == "missing-tool"
        assert "helm" in str(app.status.content).lower()
        assert record.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_state",
    [("disconnect", ConnectionState.UNREACHABLE), (401, ConnectionState.AUTH_ERROR)],
)
@pytest.mark.parametrize("retry", ["f4", "refresh"])
@pytest.mark.parametrize(
    "initial, expected_namespace",
    [
        (Command.HELM, "team"),
        (ScopedCommand(Command.HELM, "team"), "team"),
        (ScopedCommand(Command.HELM, "*"), None),
    ],
)
async def test_initial_helm_connection_failure_is_visible_and_retry_preserves_namespace_intent(
    tmp_path, failure, expected_state, retry, initial, expected_namespace
):
    async with (
        helm_app(
            tmp_path,
            initial=initial,
            connection=ConnectionRequest(namespace="team"),
            connection_status=failure,
        ) as (app, api, services, _scenario, record),
        app.run_test(size=(100, 30)) as pilot,
    ):
        await wait_for(lambda: app.state.connection is expected_state)
        await pilot.pause()
        assert app.views.route.kind is ViewKind.HELM
        assert app.workspace.helm_request is None
        assert not record.exists()
        failure_identity = app.sessions.observation.identity
        assert "Connection unavailable" in str(app.query_one("#empty-title").content)
        assert app.sessions.observation.message in str(app.status.content)
        api.connection_status = 200
        if retry == "f4":
            await pilot.press("f4")
        else:
            await app.run_command("refresh")
        # The loading frame already has this request, before completed rows render.
        await helm_ready(app, row_count=1)
        assert app.workspace.store.observation.helm.problem is None
        assert app.workspace.helm_request.scope.namespace == expected_namespace
        assert app.sessions.observation.namespace == expected_namespace
        assert app.workspace.helm_request.scope.session != failure_identity
        assert app.helm_table.request == app.workspace.helm_request
        assert app.helm_table.row_count == 1
        assert app.helm_table.capture_viewport().selected == "team/demo"
        assert app.helm_table.selected_release().key == HelmReleaseKey("team", "demo")
        assert len(services) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("initial_catalog", [False, True])
async def test_root_catalog_route_is_cached_without_helm_probe_and_drains_on_departure(
    tmp_path, read_only, initial_catalog
):
    from pathlib import Path

    from textual.widgets import Button

    from kuberich.ui.helm_catalog import HelmCatalogScreen

    initial = Command.HELM_CATALOG if initial_catalog else Command.EMPTY
    async with (
        helm_app(tmp_path, read_only=read_only, initial=initial) as (app, _, services, _, record),
        app.run_test(size=(80, 24)) as pilot,
    ):
        if not initial_catalog:
            await wait_for(lambda: app.state.scope is not None)
            await app.run_command("helmcharts")
        await wait_for(lambda: isinstance(app.screen, HelmCatalogScreen))
        screen = app.screen
        await pilot.pause()
        await wait_for(lambda: screen.is_mounted)
        await wait_for(lambda: screen.operation_count == 0)
        assert screen.service is app.workspace.helm_service
        assert screen.service.current(screen.request)
        assert screen.service.catalog.snapshot.repositories == ()
        assert not record.exists()  # Cached catalog navigation never launches Helm.
        assert screen.query_one("#helm-catalog-add", Button).disabled is read_only
        assert not list(Path(screen.service.client.directory.name).glob("helm-*"))
        assert not (tmp_path / "owned-catalog").exists()
        app.action_navigation_help()
        await pilot.pause()
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen)
        assert not record.exists()
        await app.run_command("pods")
        await wait_for(lambda: app.state.scope is not None and app.screen is not screen)
        assert screen.invalidated and screen.operation_count == 0
        assert not screen.service.current(screen.request)
        assert not record.exists()
    assert all(service.operation_count == 0 for service in services)
