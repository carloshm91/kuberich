"""A deferred header refresh must not query a view already removed from the DOM."""

import pytest
from textual.app import App, ComposeResult

from kuberich.ui.chrome import POD_SHORTCUTS, WorkspaceChrome, WorkspaceHeader


@pytest.mark.asyncio
async def test_queued_shortcut_render_after_view_removal_does_not_fail_the_app():
    chrome = WorkspaceChrome(lambda: ("owned", "owned", "owned", "default", "Ready"), "0.0.1.dev0")
    header = WorkspaceHeader(chrome, POD_SHORTCUTS)

    class HeaderApp(App):
        def compose(self) -> ComposeResult:
            yield header

    app = HeaderApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await header.remove()
        assert not header.is_attached
        app.call_after_refresh(header.render_shortcuts)
        await pilot.pause()
        assert app.is_running and app.return_code is None
