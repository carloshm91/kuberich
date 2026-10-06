"""Actual container selection, shell preparation, cancellation and retained views."""

import asyncio
import json
import logging
from pathlib import Path

import pytest
from aiohttp import web
from textual.containers import VerticalScroll

import kubetrol.ui.containers as module
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionProblem, ConnectionState
from kubetrol.domain.processes import ProcessResult, ProcessStatus
from kubetrol.errors import AppError, ExecutableUnavailable
from kubetrol.ui.app import KubetrolApp
from kubetrol.ui.containers import ContainerScreen
from kubetrol.ui.logs import LogScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


async def ns(request):
    return namespaces("team")


def app_for(tmp_path, url, *, readonly=False):
    return KubetrolApp(
        Settings(read_only=readonly, shell=("/bin/bash", "-l")),
        logging.Logger("shell", level=100),
        catalog=catalog_fixture(tmp_path, url),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_selected_container_configured_shell_repeat_and_both_retained_viewports(
    tmp_path, size, monkeypatch
):
    value = pod("api")
    value["spec"]["containers"] += [{"name": f"worker-{i:02}"} for i in range(24)]
    executed = []

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async def handoff(app, runner, command, *, guard):
        guard()
        file = Path(command.argv[1].split("=", 1)[1])
        assert json.loads(file.read_text())["current-context"] == "kubetrol-test-one"
        executed.append((command, file))
        await asyncio.sleep(0)
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(module, "terminal_handoff", handoff)
    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            before = app.resources.capture_viewport()
            await pilot.press("colon", *"shell", "enter")
            assert isinstance(app.screen, ContainerScreen)
            containers = app.screen
            await pilot.press("G", "up")
            row, scroll = containers.table.cursor_row, containers.table.scroll_y
            for key in ["s", "x"]:
                count = len(executed)
                await pilot.press(key)
                await wait_for(
                    lambda count=count: (
                        len(executed) == count + 1 and containers._shell_task is None
                    )
                )
                command, path = executed[-1]
                assert command.target.container == "worker-22"
                assert command.argv[-3:] == ("--", "/bin/bash", "-l")
                assert "Shell closed" in str(containers.status.content)
                assert not path.exists() and app.screen is containers
                assert containers.table.cursor_row == row and containers.table.scroll_y == scroll
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"shell-return-{size[0]}.svg", path=str(output))
            await pilot.press("escape")
            assert app.resources.capture_viewport() == before
            await pilot.press("x")
            assert isinstance(app.screen, ContainerScreen)
            await pilot.press("escape", "slash", *"x", "escape")
            assert len(app.screen_stack) == 1
            await pilot.press("colon", *"x")
            assert app.command_input.value == "x" and len(app.screen_stack) == 1
            await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,expected",
    [
        (ProcessResult(ProcessStatus.FAILED, 1), "pods/exec"),
        (ProcessResult(ProcessStatus.FAILED, 127), "preferences"),
        (ProcessResult(ProcessStatus.SIGNALLED, -2), "interrupted"),
        (ExecutableUnavailable("safe"), "Install kubectl"),
        (AppError("owned safe failure"), "owned safe failure"),
        (ConnectionProblem(ConnectionState.TIMEOUT, "owned timeout"), "owned timeout"),
    ],
)
async def test_shell_failures_return_to_the_selected_view_and_cleanup(
    tmp_path, outcome, expected, monkeypatch
):
    value = pod("api")
    paths = []

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async def handoff(app, runner, command, *, guard):
        paths.append(Path(command.argv[1].split("=", 1)[1]))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(module, "terminal_handoff", handoff)
    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=(40, 12)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "s")
            containers = app.screen
            await wait_for(lambda: paths and containers._shell_task is None)
            assert expected in str(containers.status.content) and app.screen is containers
            assert not paths[0].exists()
            assert containers.table.cursor_row == 0
            feedback = containers.query_one("#container-feedback", VerticalScroll)
            feedback.focus()
            feedback.scroll_end(animate=False)
            await pilot.pause()
            if expected == "pods/exec":
                assert feedback.scroll_y > 0
            await pilot.press("escape")
            assert app.resources.selected_uid == value["metadata"]["uid"]


@pytest.mark.asyncio
async def test_readonly_blocks_both_entry_routes_before_pod_preflight(tmp_path, monkeypatch):
    gets = []
    value = pod("api")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if not request.path.endswith("/pods"):
            gets.append(request.path)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url, readonly=True)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("x")
            assert "Read-only" in str(app.status.content) and len(app.screen_stack) == 1
            await pilot.press("enter", "s")
            assert "Read-only" in str(app.screen.status.content) and not gets
            await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "scope", "cursor"])
async def test_delayed_preparation_captures_target_and_owns_cancellation(
    tmp_path, action, monkeypatch
):
    started, release = asyncio.Event(), asyncio.Event()
    value = pod("api")
    value["spec"]["containers"].append({"name": "worker"})
    executed = []

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(value))
        started.set()
        await release.wait()
        return web.json_response(value)

    async def handoff(app, runner, command, *, guard):
        executed.append(command.target.container)
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(module, "terminal_handoff", handoff)
    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "down", "s")
            containers = app.screen
            await started.wait()
            task = containers._shell_task
            containers.action_shell()
            assert containers._shell_task is task
            if action == "cancel":
                await pilot.press("escape")
                assert task.done() and task.cancelled()
            elif action == "scope":
                app._namespace_selected("default")
            else:
                await pilot.press("up")
            release.set()
            if action != "cancel":
                await wait_for(lambda: task.done())
            assert executed == (["worker"] if action == "cursor" else [])
            if action == "scope":
                assert "stale" in str(containers.status.content)
            if action != "cancel":
                await pilot.press("escape")


@pytest.mark.asyncio
async def test_native_handoff_refuses_headless_and_retains_container_view(tmp_path):
    value = pod("api")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter", "s")
            containers = app.screen
            await wait_for(lambda: containers._shell_task is None)
            assert "native terminal" in str(containers.status.content)
            assert not list(Path(app.sessions.client.directory.name).glob("exec-*.json"))
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_missing_controller_and_delayed_parent_actions_are_noops(tmp_path):
    value = pod("api")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/log"):
            return web.Response(body=b"owned log\n")
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async with workspace_api(ns, handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await pilot.press("enter")
            containers = app.screen
            shell = containers.shell
            containers.shell = None
            assert not containers.check_action("shell", ())
            containers.action_shell()
            containers.shell = shell
            await pilot.press("enter")
            assert isinstance(app.screen, LogScreen)
            containers.action_shell()
            assert containers._shell_task is None
            await pilot.press("escape", "escape")


@pytest.mark.asyncio
async def test_shell_without_a_connected_selection_is_actionable():
    app = KubetrolApp(Settings(), logging.Logger("empty-shell"))
    async with app.run_test() as pilot:
        await pilot.press("x")
        assert "Select a connected resource" in str(app.status.content)
