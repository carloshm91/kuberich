"""Forward benchmark entry captures a current owned attempt before opening review."""

from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Input

from kuberich.domain.port_forwards import ForwardState, PortMapping
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.services.port_forwards import ForwardInfo
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.port_forwards import ForwardScreen
from tests.support.workspace import wait_for


class ForwardBenchmarkHost(App):
    def __init__(self, screen):
        super().__init__()
        self.initial_screen = screen

    def compose(self) -> ComposeResult:
        yield Button("Root", id="root")

    def on_mount(self):
        self.push_screen(self.initial_screen)


def forward():
    return ForwardInfo(
        uuid4(),
        ResourceTarget(SessionIdentity("synthetic", 1), "", "services", "team", "web", "uid"),
        (PortMapping(0, 80),),
        "127.0.0.1",
        state=ForwardState.READY,
        attempt=1,
    )


def screen_for(manager, callback):
    return ForwardScreen(
        manager,
        WorkspaceChrome(lambda: ("synthetic", "synthetic", "synthetic", "team", "Ready"), "test"),
        ("synthetic", "services"),
        benchmark=callback,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_ready_owned_forward_entry_keeps_input_and_attempt_capture(size):
    info = forward()
    manager = SimpleNamespace(infos=(info,))
    opened = []
    screen = screen_for(manager, opened.append)
    app = ForwardBenchmarkHost(screen)
    async with app.run_test(size=size) as pilot:
        await wait_for(lambda: screen.table.row_count == 1)
        button = screen.query_one("#forward-list-benchmark", Button)
        assert not button.disabled and button.region.area
        await pilot.press("B")
        assert opened == [info] and len(app.screen_stack) == 2
        screen.action_filter()
        await pilot.press("B")
        assert screen.query_one("#forward-list-filter", Input).value == "B"
        assert opened == [info]
        screen.query_one("#forward-list-filter", Input).value = ""
        await pilot.press("enter")
        manager.infos = (replace(info, attempt=2),)
        screen.action_benchmark_selected()
        assert opened == [info]
        screen.refresh_sessions()
        screen.action_benchmark_selected()
        assert opened[-1].attempt == 2
        for state in (ForwardState.RECONNECTING, ForwardState.STOPPED, ForwardState.FAILED):
            manager.infos = (replace(info, state=state),)
            screen.refresh_sessions()
            assert button.disabled
            screen.action_benchmark_selected()
            assert len(opened) == 2
        screen.back()
        await pilot.pause()
        assert len(app.screen_stack) == 1


@pytest.mark.asyncio
async def test_forward_benchmark_entry_handles_empty_and_unconfigured_views():
    manager = SimpleNamespace(infos=())
    opened = []
    screen = screen_for(manager, opened.append)
    app = ForwardBenchmarkHost(screen)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert screen.query_one("#forward-list-benchmark", Button).disabled
        screen.action_benchmark_selected()
        assert not opened
        screen.benchmark = None
        screen.action_benchmark_selected()
        assert not opened
