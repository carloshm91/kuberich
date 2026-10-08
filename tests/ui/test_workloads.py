"""Captured review, default cancel, independent progress and shutdown in real Textual screens."""

import asyncio
import logging

import pytest
from textual.widgets import Button, Input, Static

from kubetrol.config.schema import Settings
from kubetrol.domain.mutations import MutationState
from kubetrol.domain.registry import RESOURCE_ALIASES
from kubetrol.services.commands import ResourceCommand
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.workloads import WorkloadScreen
from tests.support.connections import catalog_fixture
from tests.support.workloads import workload_api
from tests.support.workspace import wait_for


def app_fixture(tmp_path, url, *, readonly=False):
    return KubetrolApp(
        Settings(read_only=readonly),
        logging.getLogger("owned-workloads-ui"),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=ResourceCommand(RESOURCE_ALIASES["deploy"], "team"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
@pytest.mark.parametrize("command", [":scale 3", ":restart", ":rollback 1"])
async def test_review_default_cancel_then_confirm_actual_write(tmp_path, size, command):
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(command)
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await pilot.pause()
            assert app.focused is screen.query_one("#workload-cancel", Button)
            screen.confirm()
            assert not api.requests
            screen.review()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            assert app.focused is screen.query_one("#workload-cancel", Button)
            assert not api.requests
            assert "owned-one" in str(screen.query_one("#workload-target", Static).content)
            assert "private-workload" not in str(
                screen.query_one("#workload-preview", Static).content
            )
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not api.requests
            app._submit_command(command)
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            screen.confirm()
            screen.confirm()
            await wait_for(
                lambda: bool(app.mutations.records) and app.mutations.records[-1].result is not None
            )
            assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
            assert len(api.requests) == 1
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert screen._operation_task.done()
            assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_denied_monitor_write_and_changed_policy_do_not_report_success(tmp_path):
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":rollout")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            await pilot.pause()
            screen = app.screen
            await screen.stop_owned()
            api.read_status = 403
            await screen._monitor()
            assert "HTTP 403" in str(screen.query_one("#workload-feedback", Static).content)
            await pilot.press("escape")
            api.read_status = None
            app._submit_command(":scale 3")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            await pilot.pause()
            screen = app.screen
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            original = screen.source.current
            screen.source.current = lambda: False
            screen.confirm()
            assert not api.requests
            screen.source.current = original
            api.patch_status = 403
            screen.confirm()
            await wait_for(lambda: screen._operation_task.done())
            assert app.mutations.records[-1].result.state is MutationState.DENIED
            assert len(api.requests) == 1
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert screen._operation_task.done()
            assert len(api.requests) == 1


@pytest.mark.asyncio
async def test_readonly_status_allowed_mutations_blocked_and_bad_fields_do_not_write(tmp_path):
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url, readonly=True)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            for command in (":scale 0", ":restart", ":rollback 1"):
                app._submit_command(command)
                assert len(app.screen_stack) == 1
            app._submit_command(":rollout")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await wait_for(
                lambda: screen._operation_task is not None and screen._operation_task.done()
            )
            assert "Complete:" in str(screen.query_one("#workload-feedback", Static).content)
            assert not api.requests
            await pilot.press("escape")
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":scale")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await pilot.pause()
            screen.query_one("#workload-argument", Input).value = "-1"
            await pilot.pause()
            screen.review()
            await wait_for(
                lambda: screen._operation_task is not None and screen._operation_task.done()
            )
            assert screen.intent is None and screen.query_one("#workload-confirm", Button).disabled
            assert not api.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["escape", "retry", "exit"])
async def test_owned_monitor_and_prepare_drain_before_context_cleanup(tmp_path, closing):
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url)
        screen = None
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            api.value["status"]["updatedReplicas"] = 0
            app._submit_command(":rollout")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await pilot.pause()
            old = app.sessions.client
            close = old.close

            async def checked_close():
                assert screen._operation_task.done()
                await close()

            old.close = checked_close
            if closing == "escape":
                await pilot.press("escape")
            elif closing == "retry":
                await pilot.press("f4")
                await wait_for(lambda: app.sessions.client is not old)
            else:
                app.exit()
        assert screen._operation_task.done() and not api.requests


@pytest.mark.asyncio
async def test_input_changed_during_held_preparation_and_pending_write_view_cancel(tmp_path):
    async with workload_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":scale 3")
            await wait_for(lambda: isinstance(app.screen, WorkloadScreen))
            screen = app.screen
            await pilot.pause()
            api.read_delay = 0.1
            screen.review()
            await asyncio.sleep(0.02)
            screen.query_one("#workload-argument", Input).value = "4"
            await pilot.pause()
            await wait_for(
                lambda: screen._operation_task is not None and screen._operation_task.done()
            )
            assert screen.intent is None and not api.requests
            api.read_delay = 0
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            api.stall = True
            screen.confirm()
            await api.entered.wait()
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert api.value["spec"]["replicas"] == 4
            assert app.mutations.records[-1].result is None
            api.release.set()
            await wait_for(lambda: app.mutations.records[-1].result is not None)
            assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
