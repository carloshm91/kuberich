"""Controlled container geometry distinguishes an early key from compact-ready input."""

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.containers import ContainerScreen


class ContainerResizeHost(App):
    def __init__(self):
        super().__init__()
        target = ResourceTarget(
            SessionIdentity("synthetic", 1), "", "pods", "default", "owned", "pod-uid"
        )
        self.containers = ContainerScreen(
            SimpleNamespace(target=target, require_current=lambda: None),
            {"spec": {"containers": [{"name": "app"}, {"name": "worker"}]}},
            chrome=WorkspaceChrome(
                lambda: ("synthetic", "synthetic", "synthetic", "default", "Ready"), "test"
            ),
            inspect_container=lambda _identity: None,
        )

    def compose(self) -> ComposeResult:
        yield Button("Root")

    def on_mount(self):
        self.push_screen(self.containers)


def visible_rows(table):
    return "\n".join(table.render_line(line).text for line in range(table.size.height))


@pytest.mark.asyncio
@pytest.mark.parametrize("compact_ready", [False, True])
async def test_single_last_row_key_waits_for_owned_compact_geometry(compact_ready):
    app = ContainerResizeHost()
    async with app.run_test(size=(100, 30)) as pilot:
        table = app.containers.table
        assert table.row_count == 2 and "worker" in visible_rows(table)
        if not compact_ready:
            # Hold the compact layout until after the one key is handled.
            await pilot.press("G")
            assert table.cursor_row == 1 and table.scroll_y == 0
        await pilot.resize_terminal(40, 12)
        hint = app.containers.query_one("#container-hints", Static)
        assert (
            hint.display and hint.region.y == 3 and app.size.width == 40 and app.size.height == 12
        )
        if compact_ready:
            await pilot.press("G")
        assert table.cursor_row == 1
        assert ("worker" in visible_rows(table)) is compact_ready
