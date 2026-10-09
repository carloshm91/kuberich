"""Real Textual confirmation, target selection, focus, invalidation and client cleanup."""

import asyncio
import logging
from pathlib import Path

import pytest
from textual.widgets import Button, Input, SelectionList, Static

from kuberich.config.schema import Settings
from kuberich.domain.mutations import MutationState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.mutations import result_text
from kuberich.ui.operations import ResourceOperationScreen
from tests.support.connections import catalog_fixture
from tests.support.operations import operation_api
from tests.support.workspace import wait_for


def test_large_batch_renders_each_outcome_without_hiding_later_targets():
    from dataclasses import replace

    from kuberich.domain.mutations import MutationResult
    from tests.support.operations import selection

    target = selection()[1]
    items = tuple(
        (
            replace(target, name=f"owned-{i}-" + "x" * 230),
            MutationResult(MutationState.DENIED, "Permission denied. " + "x" * 400),
        )
        for i in range(100)
    )
    result = MutationResult(MutationState.REJECTED, "Batch finished\n" + "hidden" * 10000, items)
    rendered = result_text(result).plain
    assert len(rendered) > 16384 and "owned-99-" in rendered
    assert "hidden" not in rendered and rendered.count("Permission denied.") == 100


def app_fixture(tmp_path, url, alias="cm", *, readonly=False):
    return KubeRichApp(
        Settings(read_only=readonly),
        logging.getLogger("owned-operations-ui"),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=ResourceCommand(RESOURCE_ALIASES[alias], "team"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
@pytest.mark.parametrize(
    "alias,command",
    [("cm", ":delete"), ("cj", ":trigger"), ("cj", ":suspend"), ("job", ":suspend")],
)
async def test_default_cancel_then_separate_confirmation_changes_actual_api(
    tmp_path, size, alias, command
):
    async with operation_api(alias) as (url, api):
        app = app_fixture(tmp_path, url, alias)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(command)
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            assert app.focused is screen.query_one("#operation-cancel", Button)
            screen.confirm()
            assert not api.requests
            screen.review()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            assert app.focused is screen.query_one("#operation-cancel", Button)
            assert not api.requests
            assert "private-template" not in str(
                screen.query_one("#operation-preview", Static).content
            )
            output = Path("artifacts/ui")
            output.mkdir(parents=True, exist_ok=True)
            await pilot.pause()
            screenshot = app.export_screenshot(title="KubeRich · owned resource operation")
            assert "synthetic-operation" not in screenshot and "private-template" not in screenshot
            if size[0] == 100:
                if command == ":delete":
                    assert "Finalizers:" in screenshot
                elif command == ":trigger":
                    assert screen.intent.created_name in screenshot
            (output / f"operation-{command[1:]}-{alias}-{size[0]}x{size[1]}.svg").write_text(
                screenshot
            )
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not api.requests
            app._submit_command(command)
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            if command == ":delete":
                screen.confirm()
                assert not api.requests
                assert "DELETE 1" in str(screen.query_one("#operation-feedback", Static).content)
                screen.query_one("#operation-count", Input).value = "DELETE 1"
                await pilot.pause()
                assert screen.intent is not None
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


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_batch_requires_selection_exact_count_and_retains_partial_results(tmp_path, size):
    async with operation_api(count=3) as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 3)
            app._submit_command(":deletebatch")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            targets = screen.query_one(SelectionList)
            assert not targets.selected
            screen.review()
            await wait_for(lambda: screen._operation_task.done())
            assert screen.intent is None and not api.requests
            targets.select(0).select(1)
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            screen.query_one("#operation-count", Input).value = "DELETE 3"
            screen.confirm()
            assert not api.requests
            screen.query_one("#operation-count", Input).value = "DELETE 2"
            api.write_status["owned-2"] = 403
            screen.confirm()
            await wait_for(lambda: screen._operation_task.done())
            assert len(api.requests) == 2
            assert "owned-one" not in api.values and "owned-3" in api.values
            assert "Permission denied" in str(
                screen.query_one("#operation-preview", Static).content
            )
            assert "owned-2" in app.mutations.records[-1].result.message


@pytest.mark.asyncio
async def test_batch_bounds_and_filtered_view_limit_captured_candidates(tmp_path):
    async with operation_api(count=101) as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 101)
            app._submit_command(":deletebatch")
            assert len(app.screen_stack) == 1
            assert "100 rows" in str(app.status.content)
            app.filter_input.value = "owned-one"
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":deletebatch")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            assert len(app.screen.sources) == 1
            assert app.screen.sources[0].target.name == "owned-one"
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not api.requests


@pytest.mark.asyncio
async def test_changed_options_and_selection_invalidate_pending_review(tmp_path):
    async with operation_api(count=2) as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 2)
            app._submit_command(":deletebatch")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            targets = screen.query_one(SelectionList)
            targets.select(0)
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            targets.select(1)
            await pilot.pause()
            assert screen.intent is None
            screen.query_one("#operation-grace", Input).value = "-1"
            screen.review()
            await wait_for(lambda: screen._operation_task.done())
            assert screen.intent is None and not api.requests
            screen.query_one("#operation-grace", Input).value = "0"
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            # Capture changes synchronously before queued Input.Changed can run.
            screen.query_one("#operation-propagation", Input).value = "Background"
            screen.confirm()
            assert not api.requests
            assert "changed" in str(screen.query_one("#operation-feedback", Static).content)
            await pilot.pause()
            api.read_delay = 0.05
            screen.review()
            await asyncio.sleep(0.02)
            screen.query_one("#operation-propagation", Input).value = "Orphan"
            await wait_for(lambda: screen._operation_task.done())
            assert screen.intent is None and not api.requests
            assert "changed" in str(screen.query_one("#operation-feedback", Static).content)


@pytest.mark.asyncio
async def test_resume_then_changed_capture_and_denied_write_are_visible(tmp_path):
    async with operation_api("cj") as (url, api):
        api.value["spec"]["suspend"] = True
        app = app_fixture(tmp_path, url, "cj")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":resume")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            current = screen.source.current
            screen.source.current = lambda: False
            screen.confirm()
            assert not api.requests
            screen.source.current = current
            api.write_status["owned-one"] = 403
            screen.confirm()
            await wait_for(lambda: screen._operation_task.done())
            assert app.mutations.records[-1].result.state is MutationState.DENIED
            assert api.value["spec"]["suspend"] is True


@pytest.mark.asyncio
async def test_readonly_and_wrong_api_fail_closed_without_screen_or_writes(tmp_path):
    async with operation_api() as (url, api):
        app = app_fixture(tmp_path, url, readonly=True)
        async with app.run_test():
            await wait_for(lambda: app.standard_table.row_count == 1)
            for command in (":delete", ":deletebatch", ":trigger", ":suspend", ":resume"):
                app._submit_command(command)
                assert len(app.screen_stack) == 1
            from kuberich.domain.operations import ResourceAction

            app.action_resource_operation(ResourceAction.DELETE)
            assert not api.requests
        app = app_fixture(tmp_path, url)
        async with app.run_test():
            await wait_for(lambda: app.standard_table.row_count == 1)
            for command in (":trigger", ":suspend", ":resume"):
                app._submit_command(command)
                assert len(app.screen_stack) == 1
            assert not api.requests


@pytest.mark.asyncio
async def test_context_cleanup_drains_preparation_and_confirmed_writes(tmp_path):
    async with operation_api("cj") as (url, api):
        app = app_fixture(tmp_path, url, "cj")
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":trigger")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            api.read_delay = 0.2
            screen.review()
            await asyncio.sleep(0.02)
            await app._close_client_operations(app.sessions.client)
            assert screen._operation_task.done() and not api.requests
            await pilot.press("escape")
            # A new client session owns subsequent writes, never the retired one.
            app.action_retry()
            await wait_for(
                lambda: app.standard_table.row_count == 1 and app._connection_task.done()
            )
            api.read_delay = 0
            app._submit_command(":trigger")
            await wait_for(lambda: isinstance(app.screen, ResourceOperationScreen))
            screen = app.screen
            await pilot.pause()
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            api.mode = "stall"
            screen.confirm()
            await api.entered.wait()
            await app._close_client_operations(app.sessions.client)
            assert screen._operation_task.done()
            assert app.mutations.records[-1].result.state is MutationState.UNCERTAIN
            assert len(api.jobs) == 1 and len(api.requests) == 1
