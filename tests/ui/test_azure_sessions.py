"""Azure error/login navigation, explicit invocation and stale-result rejection."""

import asyncio
import json
import logging
from pathlib import Path

import pytest
from textual.widgets import Static

from kubetrol.config.catalog import KubeCatalog
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionState
from kubetrol.domain.processes import ProcessResult, ProcessStatus
from kubetrol.errors import AppError, ExecutableUnavailable
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.scopes import ConnectionScreen
from tests.support.azure import TOKEN, VERSION, azure_control, azure_entry
from tests.support.connections import catalog_fixture, namespaces
from tests.support.workspace import wait_for, workspace_api


@pytest.mark.asyncio
async def test_device_prompt_exposes_safe_login_hint_and_headless_refuses_handoff(tmp_path):
    entry = azure_entry(tmp_path, login="devicecode")
    azure_control(tmp_path, prompt=True)

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        app = KubetrolApp(
            Settings(),
            logging.Logger("azure-contract"),
            catalog=catalog_fixture(tmp_path, url, entry),
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
            await pilot.press("colon", *"status", "enter")
            assert isinstance(app.screen, ConnectionScreen)
            message = str(app.screen.query_one("#connection-details", Static).content)
            assert ":login" in message and "SYNTHETIC-ONLY" not in message
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename="azure-login-recovery.svg", path=str(output))
            await pilot.press("escape", "colon", *"login", "enter")
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
            assert "native terminal" in app.sessions.observation.message
            await pilot.press("c")
            await wait_for(lambda: app.context_table.row_count == 2)
            await pilot.press("ctrl+q")
        assert app.sessions.client is None and app.processes.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("result", ["success", "failed", "missing", "permission", "invalid"])
async def test_explicit_login_reuses_normal_session_contract_and_safe_outcomes(
    tmp_path, monkeypatch, result
):
    entry = azure_entry(tmp_path, mode="Always")
    invoked = []

    async def handoff(app, runner, command, **options):
        invoked.append(command)
        assert options["timeout"] == 300 and command.terminal_input
        assert json.loads(dict(command.environment)["KUBERNETES_EXEC_INFO"])["spec"]["interactive"]
        if result == "missing":
            raise ExecutableUnavailable("private-exception")
        if result == "permission":
            raise AppError("private-exception")
        return ProcessResult(
            ProcessStatus.FAILED if result == "failed" else ProcessStatus.SUCCEEDED,
            1 if result == "failed" else 0,
            b"private-invalid-token"
            if result == "invalid"
            else json.dumps(
                {"kind": "ExecCredential", "apiVersion": VERSION, "status": {"token": TOKEN}}
            ).encode(),
        )

    monkeypatch.setattr("kubetrol.ui.app.terminal_handoff", handoff)

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        return namespaces("team")

    async with workspace_api(handler) as url:
        app = KubetrolApp(
            Settings(read_only=True),
            logging.Logger("azure-contract"),
            catalog=catalog_fixture(tmp_path, url, entry),
        )
        async with app.run_test() as pilot:
            await app._connection_task
            assert app.sessions.observation.state is ConnectionState.AUTH_ERROR and not invoked
            await pilot.press("colon", *"login", "enter")
            await app._connection_task
            assert len(invoked) == 1
            assert app.sessions.observation.state is (
                ConnectionState.CONNECTED if result == "success" else ConnectionState.AUTH_ERROR
            )
            assert all(
                value not in app.sessions.observation.message for value in ("private-", TOKEN)
            )
            await pilot.press("ctrl+q")
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_context_replacement_cancels_login_and_rejects_late_credentials(
    tmp_path, monkeypatch
):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def handoff(*args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            return ProcessResult(
                ProcessStatus.SUCCEEDED,
                0,
                json.dumps(
                    {"kind": "ExecCredential", "apiVersion": VERSION, "status": {"token": TOKEN}}
                ).encode(),
            )

    monkeypatch.setattr("kubetrol.ui.app.terminal_handoff", handoff)
    entry = azure_entry(tmp_path, mode="Always")

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        catalog = catalog_fixture(tmp_path, url, entry)
        # The second context is an independently qualified static fixture user.
        catalog.contexts["kubetrol-test-Two"].data["user"] = "other"
        catalog.users["other"] = type(catalog.users["owned"])(
            {"token": "static-synthetic"}, tmp_path
        )
        app = KubetrolApp(Settings(), logging.Logger("azure-contract"), catalog=catalog)
        async with app.run_test() as pilot:
            await app._connection_task
            app.action_login()
            await started.wait()
            app._start_connection("kubetrol-test-Two")
            await app._connection_task
            assert cancelled.is_set()
            assert app.sessions.observation.identity.context == "kubetrol-test-Two"
            assert (
                app.sessions.client.configuration.api_key["BearerToken"]
                == "Bearer static-synthetic"
            )
            await pilot.press("ctrl+q")


@pytest.mark.asyncio
async def test_login_without_a_context_uses_local_catalogue_navigation():
    app = KubetrolApp(Settings(), logging.Logger("azure-contract"), catalog=KubeCatalog())
    async with app.run_test() as pilot:
        await pilot.press("colon", *"login", "enter")
        assert app.sessions.client is None and app._connection_task is None
        assert "No contexts found" in str(app.status.content)


@pytest.mark.asyncio
async def test_current_login_cancellation_exposes_retry_instead_of_remaining_connecting(
    tmp_path, monkeypatch
):
    async def handoff(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr("kubetrol.ui.app.terminal_handoff", handoff)
    entry = azure_entry(tmp_path, mode="Always")
    app = KubetrolApp(
        Settings(),
        logging.Logger("azure-contract"),
        catalog=catalog_fixture(tmp_path, "http://127.0.0.1:1", entry),
    )
    async with app.run_test() as pilot:
        await app._connection_task
        await pilot.press("colon", *"login", "enter")
        await app._connection_task
        assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
        assert "cancelled" in str(app.status.content) and ":login" in str(app.status.content)
        assert app.workspace.store.observation.connection.state is ConnectionState.AUTH_ERROR
        assert app.sessions.client is None
