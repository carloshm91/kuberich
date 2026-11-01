"""Actual root-screen lifecycle gates rendering across stacked modal workspaces."""

import pytest
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.ui.foreground import ForegroundGate
from kuberich.ui.workspace_screen import WorkspaceScreen


class LifecycleHost(App[None]):
    def __init__(self):
        self.requests = []
        self.foreground = ForegroundGate(lambda: self.requests.append("paint"))
        super().__init__()

    def get_default_screen(self) -> WorkspaceScreen:
        return WorkspaceScreen(self.foreground)

    def compose(self) -> ComposeResult:
        yield Static("Owned root workspace")


@pytest.mark.asyncio
async def test_actual_root_receives_non_bubbling_resume_and_suspend_once_per_cover():
    app = LifecycleHost()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, WorkspaceScreen) and app.foreground.active
        initial = len(app.requests)
        await app.push_screen(ModalScreen())
        await pilot.pause()
        assert not app.foreground.active and len(app.requests) == initial
        await app.push_screen(ModalScreen())
        await pilot.pause()
        assert not app.foreground.active
        await app.pop_screen()
        await pilot.pause()
        assert not app.foreground.active and len(app.requests) == initial
        await app.pop_screen()
        await pilot.pause()
        assert app.foreground.active and len(app.requests) == initial + 1
    assert app.foreground.closed and not app.foreground.active
