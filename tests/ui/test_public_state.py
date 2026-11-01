"""Public semantic application state, command routing and owned process environment."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionState
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from kuberich.ui.appearance import AboutScreen
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.context_admin import ContextEditScreen
from kuberich.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app


@pytest.mark.asyncio
async def test_public_state_tracks_empty_mounted_selection_scope_and_context_transitions(
    tmp_path: Path,
) -> None:
    empty_pods = False

    async def ns(request: web.Request) -> web.StreamResponse:
        return namespaces("team", "default")

    async def resources(request: web.Request) -> web.StreamResponse:
        if "watch" in request.query:
            return await stable_watch(request)
        if empty_pods:
            return web.json_response(collection())
        return web.json_response(
            collection(
                pod("alpha", namespace="team", uid="pod-alpha"),
                pod("bravo", namespace="team", uid="pod-bravo"),
            )
        )

    async with workspace_api(ns, resources) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        unmounted = app.state
        assert unmounted.view_kind == "pods"
        assert unmounted.context is None
        assert unmounted.namespace is None
        assert unmounted.scope is None
        assert unmounted.selected is None
        assert unmounted.connection is ConnectionState.DISCONNECTED
        assert unmounted.status is ViewStatus.DISCONNECTED

        async with app.run_test() as pilot:
            await wait_for(
                lambda: app.state.status is ViewStatus.LIVE and app.resources.row_count == 2
            )
            await pilot.pause()
            first_live = app.state
            assert first_live.view_kind == "pods"
            assert first_live.context == "kuberich-test-one"
            assert first_live.namespace == "team"
            assert first_live.scope is not None
            assert first_live.scope.resource.name == "pods"
            assert first_live.scope.namespace == "team"
            assert first_live.selected == "pod-alpha"
            assert first_live.connection is ConnectionState.CONNECTED
            assert unmounted.connection is ConnectionState.DISCONNECTED

            await pilot.press("j")
            await pilot.pause()
            moved = app.state
            assert moved.selected == "pod-bravo"
            assert first_live.selected == "pod-alpha"

            await app.run_command("ns")
            await wait_for(
                lambda: (
                    app.state.view_kind == "namespaces"
                    and app.state.status is ViewStatus.LIVE
                    and app.namespace_table.row_count == 2
                )
            )
            await pilot.pause()
            ns_state = app.state
            assert ns_state.view_kind == "namespaces"
            assert ns_state.scope is not None
            assert ns_state.scope.resource.name == "namespaces"
            assert ns_state.scope.namespace is None
            assert ns_state.selected == "namespace-default"

            empty_pods = True
            await app.run_command("ns default")
            await wait_for(
                lambda: (
                    app.state.view_kind == "pods"
                    and app.state.namespace == "default"
                    and app.state.status is ViewStatus.LIVE
                )
            )
            await pilot.pause()
            empty_state = app.state
            assert empty_state.view_kind == "pods"
            assert empty_state.namespace == "default"
            assert empty_state.selected is None

            await app.run_command("ctx kuberich-test-Two")
            await wait_for(
                lambda: (
                    app.state.context == "kuberich-test-Two"
                    and app.state.connection is ConnectionState.CONNECTED
                    and app.state.status is ViewStatus.LIVE
                )
            )
            switched = app.state
            assert switched.context == "kuberich-test-Two"
            assert switched.namespace == "default"
            assert first_live.context == "kuberich-test-one"


@pytest.mark.asyncio
async def test_run_command_matches_root_and_nested_command_bars_and_respects_modals(
    tmp_path: Path,
) -> None:
    def observation(application: KubeRichApp) -> tuple[object, ...]:
        state = application.state
        scope = state.scope
        if scope is not None:
            assert scope.session == application.sessions.observation.identity
        return (
            state.view_kind,
            state.context,
            state.namespace,
            None if scope is None else (scope.resource, scope.namespace, scope.session.generation),
            state.selected,
            state.connection,
            state.status,
            tuple(application.interactions.history.entries),
        )

    async def ns(request: web.Request) -> web.StreamResponse:
        return namespaces("team", "default")

    async def resources(request: web.Request) -> web.StreamResponse:
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(pod("api", namespace="team", uid="pod-api")))
        return web.json_response(pod("api", namespace="team", uid="pod-api"))

    async with workspace_api(ns, resources) as url:
        (tmp_path / "bar").mkdir()
        (tmp_path / "api").mkdir()
        bar_app = make_app(catalog_fixture(tmp_path / "bar", url))
        async with bar_app.run_test() as pilot:
            await wait_for(lambda: bar_app.resources.row_count == 1)
            await pilot.press("colon", *"ctx", "enter")
            await wait_for(
                lambda: (
                    bar_app.state.view_kind == "contexts" and bar_app.context_table.row_count == 2
                )
            )
            bar_after_ctx = observation(bar_app)

            await pilot.press("colon", *"po", "enter")
            await wait_for(
                lambda: bar_app.state.view_kind == "pods" and bar_app.resources.row_count == 1
            )
            await pilot.press("d")
            await wait_for(lambda: isinstance(bar_app.screen, InspectionScreen))
            await pilot.press("colon", *"back", "enter")
            await wait_for(lambda: len(bar_app.screen_stack) == 1)
            await pilot.pause()
            bar_after_back = observation(bar_app)

            await pilot.press("enter")
            await wait_for(lambda: isinstance(bar_app.screen, ContainerScreen))
            await pilot.press("colon", *"ns", "enter")
            await wait_for(
                lambda: (
                    len(bar_app.screen_stack) == 1
                    and bar_app.state.view_kind == "namespaces"
                    and bar_app.namespace_table.row_count == 2
                )
            )
            await pilot.pause()
            bar_after_nested_ns = observation(bar_app)

        app = make_app(catalog_fixture(tmp_path / "api", url))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)

            await pilot.press("colon", *"partial")
            assert app.focused is app.command_input
            assert app.command_input.value == "partial"

            await app.run_command("ctx")
            await wait_for(
                lambda: app.state.view_kind == "contexts" and app.context_table.row_count == 2
            )
            assert app.command_input.value == ""
            assert app.focused is app.context_table
            assert observation(app) == bar_after_ctx

            await app.run_command("po")
            await wait_for(lambda: app.state.view_kind == "pods" and app.resources.row_count == 1)

            await pilot.press("d")
            await wait_for(lambda: isinstance(app.screen, InspectionScreen))
            inspection = app.screen
            assert isinstance(inspection, InspectionScreen)
            await pilot.press("colon", *"draft")
            assert inspection.command_input is not None
            assert inspection.focused is inspection.command_input

            await app.run_command("back")
            await wait_for(lambda: len(app.screen_stack) == 1)
            await pilot.pause()
            assert observation(app) == bar_after_back

            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, ContainerScreen))
            await app.run_command("ns")
            await wait_for(
                lambda: (
                    len(app.screen_stack) == 1
                    and app.state.view_kind == "namespaces"
                    and app.namespace_table.row_count == 2
                )
            )
            await pilot.pause()
            assert observation(app) == bar_after_nested_ns

            await app.run_command("about")
            await wait_for(lambda: isinstance(app.screen, AboutScreen))
            await app.run_command("po")
            assert isinstance(app.screen, AboutScreen)
            assert app.state.view_kind == "namespaces"
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_run_command_enforces_read_only_policy_and_invalid_command_feedback(
    tmp_path: Path,
) -> None:
    writes: list[str] = []

    async def ns(request: web.Request) -> web.StreamResponse:
        return namespaces("team")

    async def resources(request: web.Request) -> web.StreamResponse:
        if request.method != "GET":
            writes.append(f"{request.method} {request.path}")
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("api", namespace="team", uid="pod-api")))

    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.getLogger("kuberich.test.readonly"),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.pause()

            await app.run_command("delete")
            assert (
                "Read-only mode blocks mutations, shell, attach, port-forward and external plugins."
                in str(app.status.content)
            )
            assert writes == []
            assert app.interactions.history.entries == []
            assert len(app.screen_stack) == 1

            await app.run_command("not-a-command?")
            assert "Command unavailable" in str(app.status.content)
            assert writes == []
            assert app.interactions.history.entries == []

            await app.run_command("not-a-valid-command")
            assert "Resource/version was not discovered" in str(app.status.content)
            assert app.interactions.history.entries == []
            assert writes == []


@pytest.mark.asyncio
async def test_explicit_environment_and_directory_injection_owns_copied_values(
    tmp_path: Path,
) -> None:
    kubeconfig = tmp_path / "owned-kubeconfig"
    work_dir = tmp_path / "owned-workdir"
    work_dir.mkdir()

    async def ns(request: web.Request) -> web.StreamResponse:
        return namespaces("team")

    async def resources(request: web.Request) -> web.StreamResponse:
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("api", namespace="team", uid="pod-api")))

    async with workspace_api(ns, resources) as url:
        catalog = catalog_fixture(tmp_path, url)
        kubeconfig.write_text((tmp_path / "fixture-config").read_text(), encoding="utf-8")
        caller_env = {
            "KUBECONFIG": str(kubeconfig),
            "KUBERICH_TEST_MARKER": "isolated",
        }
        app = KubeRichApp(
            Settings(),
            logging.getLogger("kuberich.test.env"),
            catalog=catalog,
            environment=caller_env,
            directory=work_dir,
        )
        caller_env["KUBECONFIG"] = str(tmp_path / "mutated-config")
        caller_env["KUBERICH_TEST_MARKER"] = "mutated"

        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, ContainerScreen))
            containers = app.screen
            assert isinstance(containers, ContainerScreen)
            assert containers.shell.environment["KUBERICH_TEST_MARKER"] == "isolated"
            assert containers.shell.environment["KUBECONFIG"] == str(kubeconfig)
            assert containers.shell.directory == work_dir.resolve()
            assert containers.attach.environment["KUBERICH_TEST_MARKER"] == "isolated"
            assert containers.attach.directory == work_dir.resolve()
            assert containers.transfers.environment["KUBERICH_TEST_MARKER"] == "isolated"
            assert containers.transfers.directory == work_dir.resolve()

            await app.run_command("ctx")
            await wait_for(
                lambda: (
                    len(app.screen_stack) == 1
                    and app.state.view_kind == "contexts"
                    and app.context_table.row_count == 2
                )
            )
            await app.run_command("rename renamed-context")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ContextEditScreen)
                    and bool(app.screen.query("#context-edit-cancel"))
                )
            )
            await pilot.pause()
            editor = app.screen
            assert isinstance(editor, ContextEditScreen)
            assert editor.paths == [kubeconfig]
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            await pilot.pause()
