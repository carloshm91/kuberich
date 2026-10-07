"""Provider processes cannot block local navigation or survive terminal exit."""

import asyncio
import logging
import os
from pathlib import Path

import pytest
from textual.widgets import Static

from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionState
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.scopes import ConnectionScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.eks import aws_entry, control
from tests.support.workspace import wait_for, workspace_api


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["waiting", "sso"])
async def test_aws_wait_and_sso_errors_preserve_navigation_and_cleanup(tmp_path, failure):
    entry = aws_entry(tmp_path)
    control(
        tmp_path,
        **(
            {"sleep": True}
            if failure == "waiting"
            else {"error": "Error loading SSO Token: private-secret"}
        ),
    )

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        app = KubetrolApp(
            Settings(),
            logging.Logger("eks-local-contract"),
            catalog=catalog_fixture(tmp_path, url, entry),
        )
        async with app.run_test(size=(120, 30)) as pilot:
            if failure == "waiting":
                await wait_for(lambda: (tmp_path / "pid").exists())
                assert app.sessions.observation.state is ConnectionState.CONNECTING
            else:
                await app._connection_task
                assert app.sessions.observation.state is ConnectionState.AUTH_ERROR
                await pilot.press("colon", *"status", "enter")
                assert isinstance(app.screen, ConnectionScreen)
                message = str(app.screen.query_one("#connection-details", Static).content)
                assert "aws sso login --profile PROFILE" in message
                assert "private-secret" not in message
                output = Path("artifacts/ui").resolve()
                output.mkdir(parents=True, exist_ok=True)
                app.save_screenshot(filename="eks-sso-recovery.svg", path=str(output))
                await pilot.press("escape")
            async with asyncio.timeout(5):
                await pilot.press("c")
                await wait_for(lambda: app.context_table.row_count == 2)
                assert app._resource_name == "contexts" and len(app.screen_stack) == 1
                await pilot.press("ctrl+q")
        assert app.sessions.client is None
        if failure == "waiting":
            with pytest.raises(ProcessLookupError):
                os.kill(int((tmp_path / "pid").read_text()), 0)
