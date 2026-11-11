"""Public outer shutdown drains every owner after refused private Helm cleanup."""

import asyncio
import logging
import shutil
import sys
from pathlib import Path

import pytest

from kuberich.adapters.helm_files import HelmCommandFiles
from kuberich.config.schema import Settings
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.helm import HelmDriver, HelmScope
from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError
from kuberich.services.authorization_workspace import AuthorizationWorkspace
from kuberich.services.commands import Command
from kuberich.services.diagnostic_workspace import DiagnosticWorkspace
from kuberich.services.helm import HelmService
from kuberich.services.helm_workspace import HelmWorkspace
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.helm_catalog import HelmCatalogScreen
from kuberich.ui.shutdown import TerminalSignals
from tests.support.connections import catalog_fixture
from tests.support.helm_lifecycle import ADDRESS, lifecycle_source
from tests.support.workspace import wait_for

pytestmark = pytest.mark.fast


def leaves(error):
    if isinstance(error, BaseExceptionGroup):
        return [leaf for child in error.exceptions for leaf in leaves(child)]
    return [error]


def factory_for(fixture, directory, services):
    def factory(client, current):
        service = HelmService(
            client,
            fixture.service.policy,
            fixture.service.settings,
            fixture.client.environment,
            directory,
            current,
            catalog_directory=directory / "outer-catalog",
        )
        services.append(service)
        return service

    return factory


async def refuse_prepared_inputs(monkeypatch, fixture, service, request, directory):
    staging = directory / "captured-command-owner"
    staging.mkdir()
    created = []

    def owned_files(_parent, **inputs):
        result = HelmCommandFiles(staging, **inputs)
        created.append(result)
        return result

    monkeypatch.setattr("kuberich.services.helm_lifecycle.HelmCommandFiles", owned_files)
    await service.prepare_lifecycle(
        request, ADDRESS, HelmLifecycleKind.INSTALL, chart=fixture.chart
    )
    assert len(created) == 1 and fixture.previews()
    original = created[0].path
    retired = staging / "retired-inputs"
    original.rename(retired)
    original.mkdir(mode=0o700)
    sentinel = original / "replacement-sentinel"
    sentinel.write_text("owned replacement must survive")
    return created[0], retired, sentinel


def restore_inputs(files, retired, sentinel):
    assert sentinel.read_text() == "owned replacement must survive"
    assert (retired / "chart.tgz").is_file()
    shutil.rmtree(files.path)
    retired.rename(files.path)
    files.close()


def assert_workspace_closed(owner, client, api, directory):
    assert owner.sessions.client is None
    assert client.api is None and api.rest_client.pool_manager.closed and not directory.exists()
    ownership = owner.ownership
    assert ownership.close_complete
    assert ownership.watch_count == ownership.operation_count == ownership.helm_count == 0
    assert ownership.authorization_count == ownership.diagnostics_count == 0
    assert ownership.metrics_count == ownership.pulse_count == ownership.relationships_count == 0
    assert ownership.subscription_count == ownership.discovery_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["none", "diagnostics", "session", "caller-cancel"])
async def test_workspace_refused_helm_cleanup_still_closes_read_owners_and_session(
    tmp_path, monkeypatch, extra
):
    async with lifecycle_source(tmp_path / "fixture") as fixture:
        context = tmp_path / "context"
        context.mkdir()
        services = []
        sessions = SessionService(
            catalog_fixture(context, fixture.origin), ConnectionRequest(namespace=ADDRESS.namespace)
        )
        owner = WorkspaceService(sessions, helm_factory=factory_for(fixture, tmp_path, services))
        owner.prepare_resource(ResourceSelection("namespaces"))
        subscription = owner.subscribe()
        await owner.connect("kuberich-test-one")
        identity = sessions.observation.identity
        await owner.select_helm(
            HelmScope(identity, ADDRESS.namespace, HelmDriver.SECRET), collect=False
        )
        service, request = owner.helm_service, owner.helm_request
        assert service is not None and request is not None
        client = sessions.client
        api = client.api
        directory = Path(client.directory.name)
        files, retired, sentinel = await refuse_prepared_inputs(
            monkeypatch, fixture, service, request, tmp_path
        )
        closed = []
        held, release = asyncio.Event(), asyncio.Event()
        for cls, label in (
            (HelmWorkspace, "helm-read"),
            (DiagnosticWorkspace, "diagnostics"),
            (AuthorizationWorkspace, "authorization"),
        ):
            original = cls.stop

            async def stop(self, original=original, label=label):
                if label == "diagnostics" and extra == "caller-cancel":
                    held.set()
                    await release.wait()
                await original(self)
                closed.append(label)
                if label == extra:
                    raise AppError("Owned additional diagnostics cleanup failure.")

            monkeypatch.setattr(cls, "stop", stop)
        original_close = sessions.close

        async def close_session():
            await original_close()
            closed.append("session")
            if extra == "session":
                raise AppError("Owned additional session cleanup failure.")

        monkeypatch.setattr(sessions, "close", close_session)
        closing = asyncio.create_task(owner.close())
        try:
            async with asyncio.timeout(5):
                if extra == "caller-cancel":
                    await held.wait()
                    closing.cancel()
                    await asyncio.sleep(0)
                    closing.cancel()
                    assert directory.exists() and not closing.done()
                    release.set()
                with pytest.raises((AppError, BaseExceptionGroup)) as observed:
                    await closing
            failures = leaves(observed.value)
            assert all(isinstance(error, AppError) for error in failures)
            assert any("Private Helm input cleanup" in str(error) for error in failures)
            assert len(failures) == (2 if extra in {"diagnostics", "session"} else 1)
            assert closed == ["helm-read", "diagnostics", "authorization", "session"]
            assert_workspace_closed(owner, client, api, directory)
            with pytest.raises(StopAsyncIteration):
                await anext(subscription)
            assert service.operation_count == 0
        finally:
            release.set()
            await asyncio.gather(closing, return_exceptions=True)
            restore_inputs(files, retired, sentinel)


def observe_app_closers(monkeypatch, app, *, presenter_failure=False):
    closed = []
    for owner, method, label in (
        (app.appearance_controller, "close", "appearance"),
        (app.benchmarks, "close", "benchmarks"),
        (app.command_routes, "close", "routes"),
        (app.interactions, "close", "interactions"),
        (app.exports, "stop_owned", "exports"),
        (app.metric_history, "close", "history"),
        (app.clipboard_queue, "close", "clipboard"),
        (app.live_preferences, "close", "preferences"),
        (app.plugins, "close", "plugins"),
        (app.operations.ephemeral_debug, "close", "debug"),
        (app.operations.node_maintenance, "close", "maintenance"),
        (app.operations.node_shells, "close", "shells"),
        (app.mutations, "close", "mutations"),
        (app.forwards, "close", "forwards"),
        (app.processes, "close", "processes"),
        (app.workspace, "close", "workspace"),
        (app.presenter, "close", "presenter"),
        (app.views, "close", "views"),
    ):
        original = getattr(owner, method)

        async def close(original=original, label=label):
            try:
                await original()
                if label == "presenter" and presenter_failure:
                    raise RuntimeError("Owned additional presenter cleanup failure.")
            finally:
                closed.append(label)

        monkeypatch.setattr(owner, method, close)
    restore = TerminalSignals.restore

    def signals(self):
        restore(self)
        closed.append("signals")

    monkeypatch.setattr(TerminalSignals, "restore", signals)
    return closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin", ["workspace", "workspace-and-presenter", "workspace-cancel", "screen"]
)
async def test_app_public_shutdown_drains_all_outer_owners_after_helm_cleanup_failure(
    tmp_path, monkeypatch, origin
):
    async with lifecycle_source(tmp_path / "fixture") as fixture:
        context = tmp_path / "context"
        context.mkdir()
        services = []
        app = KubeRichApp(
            Settings(),
            logging.Logger("owned-helm-outer-close", level=100),
            catalog=catalog_fixture(context, fixture.origin),
            connection=ConnectionRequest(namespace=ADDRESS.namespace),
            initial_command=Command.HELM_CATALOG,
            environment=fixture.client.environment,
            directory=tmp_path,
            helm_factory=factory_for(fixture, tmp_path, services),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: isinstance(app.screen, HelmCatalogScreen))
            await wait_for(lambda: app.screen.operation_count == 0)
            await pilot.pause()
            screen = app.screen
            service, request = app.workspace.helm_service, app.workspace.helm_request
            client = app.sessions.client
            api = client.api
            directory = Path(client.directory.name)
            cleanup = None
            if origin != "screen":
                cleanup = await refuse_prepared_inputs(
                    monkeypatch, fixture, service, request, tmp_path
                )
            child = await app.processes.background(
                ProcessCommand(
                    (sys.executable, "-c", "import time; time.sleep(60)"),
                    (),
                    tmp_path,
                    ProcessMode.BACKGROUND,
                    ProcessPurpose.AUTHENTICATE,
                )
            )
            assert app.processes.active_count == 1
            closed = observe_app_closers(
                monkeypatch, app, presenter_failure=origin == "workspace-and-presenter"
            )
            original_stop = screen.stop_owned

            async def stop_screen():
                await original_stop()
                closed.append("helm-screen")
                if origin == "screen":
                    raise AppError("Private Helm input cleanup could not be verified.")

            monkeypatch.setattr(screen, "stop_owned", stop_screen)
            held, release, drained = asyncio.Event(), asyncio.Event(), asyncio.Event()
            second = None
            original_second_stop = None
            if origin == "screen":
                second = HelmCatalogScreen(service=service, request=request, runner=app.processes)
                app.push_screen(second)
                await wait_for(lambda: app.screen is second and second.operation_count == 0)
                await pilot.pause()
                original_second_stop = second.stop_owned

                async def stop_second():
                    held.set()
                    await release.wait()
                    await original_second_stop()
                    drained.set()

                monkeypatch.setattr(second, "stop_owned", stop_second)
                original_client_close = app.operations.close_for_client

                async def close_client(selected):
                    await original_client_close(selected)
                    raise AppError("Owned additional client-operation cleanup failure.")

                monkeypatch.setattr(app.operations, "close_for_client", close_client)
            elif origin == "workspace-cancel":
                original_workspace_close = app.workspace.close

                async def close_workspace():
                    held.set()
                    await release.wait()
                    await original_workspace_close()

                monkeypatch.setattr(app.workspace, "close", close_workspace)
            closing = asyncio.create_task(app.on_unmount())
            try:
                async with asyncio.timeout(5):
                    if origin in {"screen", "workspace-cancel"}:
                        await held.wait()
                        await asyncio.sleep(0)
                        assert not closing.done() and not drained.is_set()
                        closing.cancel()
                        await asyncio.sleep(0)
                        closing.cancel()
                        assert not closing.done()
                        release.set()
                    with pytest.raises((AppError, BaseExceptionGroup)) as observed:
                        await closing
                failures = leaves(observed.value)
                assert any("Private Helm input cleanup" in str(error) for error in failures)
                if origin == "workspace-and-presenter":
                    assert any(isinstance(error, RuntimeError) for error in failures)
                if origin == "screen":
                    assert any(
                        "client-operation cleanup failure" in str(error) for error in failures
                    )
                assert "helm-screen" in closed
                assert [label for label in closed if label != "helm-screen"] == [
                    "appearance",
                    "benchmarks",
                    "routes",
                    "interactions",
                    "exports",
                    "history",
                    "clipboard",
                    "preferences",
                    "plugins",
                    "debug",
                    "maintenance",
                    "shells",
                    "mutations",
                    "forwards",
                    "processes",
                    "workspace",
                    "presenter",
                    "views",
                    "signals",
                ]
                assert_workspace_closed(app.workspace, client, api, directory)
                assert app.processes.active_count == 0 and child.output.exited.done()
                assert all(service.operation_count == 0 for service in services)
                if origin == "screen":
                    assert drained.is_set()
            finally:
                release.set()
                await asyncio.gather(closing, return_exceptions=True)
                if cleanup is not None:
                    restore_inputs(*cleanup)

                # Public shutdown was explicitly exercised above. Textual's later
                # unmount notification must not replay its immutable failed close.
                async def already_drained(self):
                    pass

                monkeypatch.setattr(KubeRichApp, "on_unmount", already_drained)
                monkeypatch.setattr(screen, "stop_owned", original_stop)
                if second is not None:
                    monkeypatch.setattr(second, "stop_owned", original_second_stop)
