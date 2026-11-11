"""Actual repository HTTP/storage and public cached chart/catalog controls."""

import asyncio
import base64
import logging
from contextlib import asynccontextmanager

import pytest
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select

from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.errors import AppError
from kuberich.services.commands import Command
from kuberich.services.helm import HelmService
from kuberich.services.processes import ProcessRunner
from kuberich.ui.app import KubeRichApp
from kuberich.ui.helm_catalog import HelmCatalogScreen, HelmRepositoryScreen
from kuberich.ui.helm_lifecycle import HelmLifecycleScreen
from kuberich.ui.keybindings import NavigationHelpScreen
from tests.support.connections import catalog_fixture, certificate
from tests.support.helm_catalog import chart_package
from tests.support.helm_lifecycle import ADDRESS, lifecycle_source
from tests.support.helm_lifecycle_ui import LifecycleTestApp
from tests.support.helm_oci import oci_artifact, oci_handler
from tests.support.history import history_http
from tests.support.workspace import wait_for


@asynccontextmanager
async def catalog_app(
    tmp_path, *, existing=False, namespace=ADDRESS.namespace, operation=HelmLifecycleKind.INSTALL
):
    async with lifecycle_source(tmp_path, existing=existing, namespace=namespace) as fixture:
        runner = ProcessRunner(fixture.service.policy)
        screen = HelmCatalogScreen(
            service=fixture.service,
            request=fixture.request,
            runner=runner,
            address=ADDRESS if operation is HelmLifecycleKind.UPGRADE else None,
            operation=operation,
        )
        try:
            yield LifecycleTestApp(screen), screen, fixture
        finally:
            await screen.stop_owned()
            await runner.close()


async def catalog_ready(screen, *, rows=None):
    await wait_for(
        lambda: (
            screen.is_mounted
            and screen.operation_count == 0
            and (rows is None or screen.table.row_count == rows)
        )
    )


async def add_form(app, screen, fixture, pilot):
    screen.add_repository()
    await wait_for(lambda: isinstance(app.screen, HelmRepositoryScreen))
    form = app.screen
    await pilot.pause()
    form.query_one("#helm-repository-name", Input).value = "owned"
    form.query_one("#helm-repository-url", Input).value = fixture.origin + "/charts"
    form.query_one("#helm-repository-loopback", Checkbox).value = True
    return form


@asynccontextmanager
async def held_owner_completion(owner, monkeypatch):
    """Delay a screen's task-completion callback without changing its operation."""
    loop = asyncio.get_running_loop()
    schedule = loop.call_soon
    entered = asyncio.Event()
    held = []

    def hold(callback, *args, context=None):
        if (
            getattr(callback, "__self__", None) is owner
            and len(args) == 1
            and isinstance(args[0], asyncio.Task)
        ):
            held.append((callback, args, context))
            entered.set()
            return schedule(lambda: None)
        return schedule(callback, *args, context=context)

    with monkeypatch.context() as patch:
        patch.setattr(loop, "call_soon", hold)
        try:
            yield entered, held
        finally:
            patch.undo()
            for callback, args, context in held:
                schedule(callback, *args, context=context)
            drained = asyncio.Event()
            schedule(drained.set)
            await drained.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 36), (80, 24), (40, 12)])
async def test_catalog_load_and_search_are_offline_and_controls_fit_small_windows(tmp_path, size):
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test(size=size) as pilot:
        await catalog_ready(screen, rows=0)
        assert fixture.calls() == [] and fixture.api.requests == []
        assert "cached" in str(screen.query_one(".helm-catalog-status").content)
        for name in ("add", "update", "remove", "select", "refresh", "back"):
            button = screen.query_one("#helm-catalog-" + name, Button)
            assert button.region.area > 0 and button.region.height == 1
            assert button.region.bottom <= size[1]
        screen.query_one("#helm-catalog-search", Input).value = "owned"
        await pilot.pause()
        await catalog_ready(screen, rows=0)
        assert fixture.calls() == [] and fixture.api.requests == []
        await pilot.press("escape")
        await wait_for(lambda: not screen.is_attached)
        assert screen.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", ["none", "basic", "bearer"])
async def test_registration_private_credentials_real_index_and_exact_version_lifecycle_preview(
    tmp_path, auth
):
    async with (
        catalog_app(tmp_path) as (app, screen, fixture),
        app.run_test(size=(100, 30)) as pilot,
    ):
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        for name in ("username", "password", "token"):
            assert form.query_one("#helm-repository-" + name, Input).password
        form.query_one("#helm-repository-auth", Select).value = auth
        await pilot.pause()
        if auth == "basic":
            form.query_one("#helm-repository-username", Input).value = "owned-user"
            form.query_one("#helm-repository-password", Input).value = "owned-private-ui-password"
        elif auth == "bearer":
            form.query_one("#helm-repository-token", Input).value = "owned-private-ui-token"
        form.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=1)
        assert fixture.calls() == []
        expected = (
            None
            if auth == "none"
            else "Basic " + base64.b64encode(b"owned-user:owned-private-ui-password").decode()
            if auth == "basic"
            else "Bearer owned-private-ui-token"
        )
        assert fixture.api.authorizations == [expected]
        assert "owned-private-ui" not in repr(screen.snapshot)
        assert screen.selected_chart().version == "1.0.0"
        before = len(fixture.api.requests)
        screen.query_one("#helm-catalog-search", Input).value = "missing"
        await pilot.pause()
        await catalog_ready(screen, rows=0)
        screen.query_one("#helm-catalog-search", Input).value = "owned-chart"
        await pilot.pause()
        await catalog_ready(screen, rows=1)
        assert len(fixture.api.requests) == before
        screen.query_one("#helm-catalog-name", Input).value = ADDRESS.name
        selected = screen.selected_chart()
        screen.select_version()
        await wait_for(lambda: isinstance(app.screen, HelmLifecycleScreen))
        review = app.screen
        await pilot.pause()
        assert review.chart.sha256 == selected.sha256
        assert review.chart.catalog_generation == screen.snapshot.generation
        assert review.address == ADDRESS and review.operation is HelmLifecycleKind.INSTALL
        review.prepare()
        await wait_for(lambda: review.intent is not None and review.operation_count == 0)
        assert "Native Helm dry-run" in review.viewer.text
        assert "owned-private-lifecycle-value" not in review.viewer.text
        assert not fixture.api.mutations
        assert all(
            any(arg.startswith("--dry-run=") for arg in call["argv"]) for call in fixture.previews()
        )
        await review.action_back()
        await wait_for(lambda: app.screen is screen)
        assert screen.selected_chart() == selected and screen.table.row_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_completion", [False, True])
async def test_repository_update_remove_reviews_bind_displayed_generation(
    tmp_path, monkeypatch, hold_completion
):
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test() as pilot:
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        form.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=1)
        screen.query_one("#helm-catalog-repository", Select).value = "owned"
        await pilot.pause()
        await catalog_ready(screen, rows=1)
        screen.update_repository()
        await wait_for(lambda: isinstance(app.screen, HelmRepositoryScreen))
        update = app.screen
        await pilot.pause()
        assert update.repository.name == "owned"
        assert update.expected_generation == screen.snapshot.generation
        update.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=1)
        screen.remove_repository()
        await wait_for(lambda: isinstance(app.screen, HelmRepositoryScreen))
        removal = app.screen
        await fixture.service.catalog.update("owned")
        before = len(fixture.api.requests)
        if hold_completion:
            async with held_owner_completion(removal, monkeypatch) as (entered, held):
                removal.confirm()
                await wait_for(entered.is_set)
                await wait_for(lambda: removal.operation_count == 0)
                assert len(held) == 1 and held[0][1][0].done()
                assert "generation" not in str(removal.query_one(".helm-catalog-status").content)
                assert removal.query_one("#helm-repository-confirm", Button).disabled
                assert app.screen is removal
                assert len(fixture.api.requests) == before
                assert fixture.service.catalog.snapshot.repositories
        else:
            removal.confirm()
        await wait_for(
            lambda: (
                app.screen is removal
                and removal.operation_count == 0
                and "generation" in str(removal.query_one(".helm-catalog-status").content)
            )
        )
        assert app.screen is removal
        assert "generation" in str(removal.query_one(".helm-catalog-status").content)
        assert len(fixture.api.requests) == before
        assert fixture.service.catalog.snapshot.repositories
        await removal.action_back()
        await pilot.pause()
        await catalog_ready(screen, rows=1)
        screen.remove_repository()
        await wait_for(lambda: isinstance(app.screen, HelmRepositoryScreen))
        await pilot.pause()
        app.screen.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=0)
        assert fixture.service.catalog.snapshot.repositories == () and not fixture.api.mutations


@pytest.mark.asyncio
async def test_read_only_loads_existing_cache_without_fetch_or_change(tmp_path):
    async with catalog_app(tmp_path) as (app, screen, fixture):
        await fixture.service.catalog.add(
            "owned", fixture.origin + "/charts", allow_loopback_http=True
        )
        fixture.service.policy.tighten()
        before = len(fixture.api.requests)
        async with app.run_test() as pilot:
            await catalog_ready(screen, rows=1)
            for name in ("add", "update", "remove", "select"):
                assert screen.query_one("#helm-catalog-" + name, Button).disabled
            screen.add_repository()
            screen.select_version()
            await pilot.pause()
            assert app.screen is screen and len(fixture.api.requests) == before
            with pytest.raises(AppError, match="Read-only"):
                await fixture.service.catalog.add(
                    "blocked", fixture.origin + "/charts", allow_loopback_http=True
                )
            assert fixture.calls() == []


@pytest.mark.asyncio
async def test_all_namespace_install_requires_choice_and_upgrade_keeps_address(tmp_path):
    async with catalog_app(tmp_path, namespace=None) as (app, screen, fixture):
        await fixture.service.catalog.add(
            "owned", fixture.origin + "/charts", allow_loopback_http=True
        )
        async with app.run_test() as pilot:
            await catalog_ready(screen, rows=1)
            screen.query_one("#helm-catalog-name", Input).value = ADDRESS.name
            screen.select_version()
            await pilot.pause()
            assert app.screen is screen
            assert "concrete namespace" in str(screen.query_one(".helm-catalog-status").content)
            assert not any(path.endswith(".tgz") for method, path, query in fixture.api.requests)
    async with catalog_app(
        tmp_path / "upgrade", existing=True, namespace=None, operation=HelmLifecycleKind.UPGRADE
    ) as (app, screen, fixture):
        await fixture.service.catalog.add(
            "owned", fixture.origin + "/charts", allow_loopback_http=True
        )
        async with app.run_test() as pilot:
            await catalog_ready(screen, rows=1)
            screen.select_version()
            await wait_for(lambda: isinstance(app.screen, HelmLifecycleScreen))
            assert (
                app.screen.address == ADDRESS and app.screen.operation is HelmLifecycleKind.UPGRADE
            )


@pytest.mark.asyncio
async def test_cover_cancels_registration_and_clears_private_fields(tmp_path):
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test() as pilot:
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        form.query_one("#helm-repository-auth", Select).value = "bearer"
        await pilot.pause()
        form.query_one("#helm-repository-token", Input).value = "owned-private-pending-token"
        fixture.api.hold_index = True
        form.confirm()
        await fixture.api.index_started.wait()
        cover = ModalScreen()
        app.push_screen(cover)
        await wait_for(lambda: form.operation_count == 0)
        assert form.query_one("#helm-repository-token", Input).value == ""
        assert fixture.service.catalog.snapshot.repositories == ()
        fixture.api.index_release.set()
        cover.dismiss()
        await pilot.pause()
        assert app.screen is form
        assert "owned-private-pending-token" not in str(
            form.query_one(".helm-catalog-status").content
        )
        await form.action_back()
        await catalog_ready(screen, rows=0)
        assert screen.snapshot.repositories == ()


@pytest.mark.asyncio
async def test_registered_oci_chart_versions_are_selected_by_exact_content(tmp_path):
    artifact = oci_artifact("owned-chart", "1.0.0", chart_package())
    requests = []
    async with (
        history_http(oci_handler({"owned": artifact}, requests)) as origin,
        catalog_app(tmp_path) as (app, screen, fixture),
        app.run_test() as pilot,
    ):
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        form.query_one("#helm-repository-kind", Select).value = "oci"
        form.query_one("#helm-repository-url", Input).value = (
            "oci://" + origin.removeprefix("http://") + "/owned/owned-chart"
        )
        form.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=1)
        selected = screen.selected_chart()
        assert selected.manifest_digest == artifact.manifest_digest
        assert selected.version == "1.0.0"
        assert not any(path.endswith("/_catalog") for path, query, auth in requests)
        screen.query_one("#helm-catalog-name", Input).value = ADDRESS.name
        screen.select_version()
        await wait_for(lambda: isinstance(app.screen, HelmLifecycleScreen))
        await pilot.pause()
        assert app.screen.chart.package == artifact.package
        assert app.screen.chart.manifest_digest == artifact.manifest_digest
        assert any("/blobs/" in path for path, query, auth in requests)


@pytest.mark.asyncio
async def test_large_cached_render_keeps_visible_selection_scroll_and_latest_filter(tmp_path):
    async with catalog_app(tmp_path) as (app, screen, fixture):
        fixture.api.packages = {
            ("owned-chart", f"1.0.{index}"): chart_package(version=f"1.0.{index}")
            for index in range(200)
        }
        await fixture.service.catalog.add(
            "owned", fixture.origin + "/charts", allow_loopback_http=True
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await catalog_ready(screen, rows=200)
            screen.table.move_cursor(row=75)
            screen.table.scroll_to(y=70, x=10, animate=False, immediate=True)
            await pilot.pause()
            selected = screen.selected_chart()
            scroll = screen.table.scroll_y
            requests = len(fixture.api.requests)
            screen.refresh_catalog()
            await catalog_ready(screen, rows=200)
            assert screen.selected_chart() == selected and screen.table.scroll_y == scroll
            screen.query_one("#helm-catalog-search", Input).value = "owned"
            screen.query_one("#helm-catalog-search", Input).value = "1.0.1"
            await pilot.pause()
            await catalog_ready(screen)
            assert screen.selected_chart() == selected
            assert all(
                "1.0.1" in screen.table.get_row_at(index)[2].plain
                for index in range(screen.table.row_count)
            )
            assert len(fixture.api.requests) == requests


@pytest.mark.asyncio
async def test_scope_change_and_invalid_form_inputs_never_publish_late_authority(tmp_path):
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test() as pilot:
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        form.query_one(
            "#helm-repository-url", Input
        ).value = "https://private:owned-sensitive@owned.invalid/charts?token=owned-sensitive"
        form.confirm()
        await wait_for(
            lambda: (
                app.screen is form
                and form.operation_count == 0
                and "without credentials or queries"
                in str(form.query_one(".helm-catalog-status").content)
            )
        )
        assert "owned-sensitive" not in str(form.query_one(".helm-catalog-status").content)
        assert fixture.api.requests == [] and fixture.service.catalog.snapshot.repositories == ()
        fixture.service.current = lambda request: False
        form.validate_target()
        screen.validate_target()
        assert form.invalidated and screen.invalidated
        assert form.query_one("#helm-repository-confirm", Button).disabled
        assert screen.query_one("#helm-catalog-add", Button).disabled
        form.confirm()
        screen.add_repository()
        assert fixture.api.requests == []


@pytest.mark.asyncio
async def test_explicit_ca_and_separate_origin_fields_survive_registration(tmp_path):
    certificate(tmp_path)
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test() as pilot:
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        ca = tmp_path / "fixture-cert"
        form.query_one("#helm-repository-ca", Input).value = str(ca)
        form.query_one("#helm-repository-token-origins", Input).value = fixture.origin
        form.query_one("#helm-repository-download-origins", Input).value = fixture.origin
        form.confirm()
        await wait_for(lambda: app.screen is screen)
        await catalog_ready(screen, rows=1)
        repository = screen.snapshot.repositories[0]
        assert repository.ca_file == ca
        assert repository.token_origins == (fixture.origin,)
        assert repository.download_origins == (fixture.origin,)


@pytest.mark.asyncio
async def test_unexpected_cached_load_error_withholds_private_exception_text(tmp_path, monkeypatch):
    async with catalog_app(tmp_path) as (app, screen, fixture):
        original = fixture.service.catalog.load
        calls = []

        async def failure():
            calls.append("load")
            if len(calls) == 1:
                raise RuntimeError("owned-private-catalog-exception")
            return await original()

        monkeypatch.setattr(fixture.service.catalog, "load", failure)
        async with app.run_test() as pilot:
            await catalog_ready(screen, rows=0)
            await wait_for(
                lambda: (
                    app.screen is screen
                    and screen.operation_count == 0
                    and "private details were withheld"
                    in str(screen.query_one(".helm-catalog-status").content)
                )
            )
            status = str(screen.query_one(".helm-catalog-status").content)
            assert "private details were withheld" in status
            assert "owned-private-catalog-exception" not in status
            assert fixture.api.requests == [] and fixture.calls() == []
            assert screen.query_one("#helm-catalog-add", Button).disabled
            screen.add_repository()
            assert app.screen is screen and calls == ["load"]
            screen.refresh_catalog()
            await catalog_ready(screen, rows=0)
            assert calls == ["load", "load"] and screen.problem is None
            assert not screen.query_one("#helm-catalog-add", Button).disabled
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_invalid_cached_search_keeps_problem_until_explicit_successful_reload(tmp_path):
    async with catalog_app(tmp_path) as (app, screen, fixture), app.run_test() as pilot:
        await catalog_ready(screen, rows=0)
        screen.query_one("#helm-catalog-search", Input).value = "x" * 4097
        await pilot.pause()
        await catalog_ready(screen, rows=0)
        assert "bound" in screen.problem and screen.query_one("#helm-catalog-add", Button).disabled
        screen.query_one("#helm-catalog-search", Input).value = "owned"
        await pilot.pause()
        await catalog_ready(screen, rows=0)
        assert screen.problem is not None
        screen.refresh_catalog()
        await catalog_ready(screen, rows=0)
        assert screen.problem is None and fixture.api.requests == []


@pytest.mark.asyncio
async def test_small_repository_form_scrolls_to_last_field_and_default_enter_cancels(tmp_path):
    async with (
        catalog_app(tmp_path) as (app, screen, fixture),
        app.run_test(size=(40, 12)) as pilot,
    ):
        await catalog_ready(screen, rows=0)
        form = await add_form(app, screen, fixture, pilot)
        assert app.focused.id == "helm-repository-cancel"
        await pilot.press("shift+tab", "shift+tab")
        assert app.focused.id == "helm-repository-download-origins"
        await pilot.pause()
        field = form.query_one("#helm-repository-download-origins", Input)
        region = form.query_one("#helm-repository-fields").region
        await wait_for(lambda: field.region.y >= region.y and field.region.bottom <= region.bottom)
        assert field.region.y >= region.y and field.region.bottom <= region.bottom
        form.set_focus(form.query_one("#helm-repository-cancel", Button))
        await pilot.press("enter")
        await wait_for(lambda: app.screen is screen)
        assert fixture.service.catalog.snapshot.repositories == () and fixture.api.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_actual_app_catalog_route_nested_help_scope_refresh_and_owner_cleanup(tmp_path, size):
    async with lifecycle_source(tmp_path) as fixture:
        root = tmp_path / "root-context"
        root.mkdir()
        services = []

        def factory(client, current):
            service = HelmService(
                client,
                fixture.service.policy,
                fixture.service.settings,
                fixture.client.environment,
                tmp_path,
                current,
                catalog_directory=tmp_path / "root-catalog",
            )
            services.append(service)
            return service

        app = KubeRichApp(
            Settings(),
            logging.Logger("owned-catalog-root", level=100),
            catalog=catalog_fixture(root, fixture.origin),
            connection=ConnectionRequest(namespace=ADDRESS.namespace),
            initial_command=Command.HELM_CATALOG,
            environment=fixture.client.environment,
            directory=tmp_path,
            helm_factory=factory,
        )
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: isinstance(app.screen, HelmCatalogScreen))
            screen = app.screen
            await catalog_ready(screen, rows=0)
            assert fixture.calls() == []
            assert screen.command_input is not None
            for name in ("add", "back"):
                assert screen.query_one("#helm-catalog-" + name, Button).region.bottom <= size[1]
            screen.add_repository()
            await wait_for(lambda: isinstance(app.screen, HelmRepositoryScreen))
            form = app.screen
            await pilot.pause()
            form.query_one("#helm-repository-auth", Select).value = "bearer"
            await pilot.pause()
            form.query_one("#helm-repository-token", Input).value = "owned-private-root-token"
            app.action_navigation_help()
            await wait_for(lambda: isinstance(app.screen, NavigationHelpScreen))
            await pilot.pause()
            await wait_for(lambda: form.query_one("#helm-repository-token", Input).value == "")
            assert form.query_one("#helm-repository-token", Input).value == ""
            assert "owned-private-root-token" not in repr(app.state)
            await pilot.press("escape")
            await wait_for(lambda: app.screen is form)
            await form.action_back()
            await pilot.pause()
            await catalog_ready(screen, rows=0)
            app.workspace.refresh_helm()
            await wait_for(lambda: screen.invalidated and screen.operation_count == 0)
            app.command_routes.route(screen, "ctx")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert form.invalidated and screen.invalidated
            assert form.operation_count == 0 and screen.operation_count == 0
        assert all(service.operation_count == 0 for service in services)
