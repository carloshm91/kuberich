"""Public Textual contracts needed before deferring inactive resource views."""

import asyncio
from contextlib import suppress

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical

from kuberich.domain.namespaces import NamespaceRow
from kuberich.domain.navigation import ContextRow
from kuberich.ui.contexts import ContextTable
from kuberich.ui.namespaces import NamespaceTable


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["namespaces", "contexts"])
async def test_real_table_setup_registration_configuration_and_focus_are_synchronous(kind):
    released = asyncio.Event()

    class HeldNamespaceTable(NamespaceTable):
        async def on_mount(self):
            await released.wait()

    class HeldContextTable(ContextTable):
        async def on_mount(self):
            await released.wait()

    class ContractApp(App):
        def __init__(self):
            super().__init__()
            self.host = Vertical()
            self.table = HeldNamespaceTable() if kind == "namespaces" else HeldContextTable()
            self.completions = []
            self.before_registration = False
            self.before_mount_completion = False
            self.focused_before_mount_completion = False

        def compose(self) -> ComposeResult:
            yield self.host

        async def on_mount(self):
            # Existing eager model setup retains columns even when a view has
            # not entered the DOM. No framework private registration is used.
            self.table.setup()
            self.before_registration = not self.is_mounted(self.table)

            def ensure_registered():
                if not self.is_mounted(self.table):
                    self.completions.append(self.host.mount(self.table))

            ensure_registered()
            ensure_registered()
            self.before_mount_completion = self.is_mounted(self.table) and not self.table.is_mounted
            if isinstance(self.table, NamespaceTable):
                self.table.configure_view(None, force=True)
            self.set_focus(self.table)
            self.focused_before_mount_completion = self.focused is self.table
            if isinstance(self.table, NamespaceTable):
                assert await self.table.apply_rows(
                    (
                        NamespaceRow("owned-alpha", "alpha", "Active", None),
                        NamespaceRow("owned-beta", "beta", "Active", None),
                    ),
                    1,
                    lambda: True,
                )
            else:
                assert await self.table.apply_rows(
                    (
                        ContextRow("alpha", "owned-cluster", "owned-user", "default"),
                        ContextRow("beta", "owned-cluster", "owned-user", "default"),
                    ),
                    lambda: True,
                )
            self.table.move_cursor(row=1, scroll=False)
            self.selected_before_completion = self.table.capture_viewport().selected
            self.cursor_before_completion = self.table.cursor_coordinate
            assert not self.table.is_mounted
            released.set()
            await self.completions[0]

    app = ContractApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.before_registration and app.before_mount_completion
        assert app.focused_before_mount_completion and app.focused is app.table
        assert app.table.is_mounted and app.table.parent is app.host
        assert app.table.row_count == 2
        assert app.table.capture_viewport().selected == app.selected_before_completion
        assert app.selected_before_completion == ("owned-beta" if kind == "namespaces" else "beta")
        assert app.table.cursor_coordinate == app.cursor_before_completion
        assert app.table.cursor_row == 1
        assert len(app.table.columns) == (3 if kind == "namespaces" else 5)
        assert app.table.region.width > 0 and app.table.region.height > 0
        assert app.host.children.count(app.table) == 1
        assert len(app.completions) == 1


@pytest.mark.asyncio
async def test_framework_exit_waits_for_a_held_mount_until_the_handler_is_released():
    entered, released, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class HeldTable(NamespaceTable):
        async def on_mount(self):
            entered.set()
            try:
                await released.wait()
            finally:
                ended.set()

    class ClosingApp(App):
        def __init__(self):
            super().__init__()
            self.host = Vertical()
            self.table = HeldTable()
            self.completion = None
            self.native_completion = None

        def compose(self) -> ComposeResult:
            yield self.host

        async def on_mount(self):
            self.table.setup()
            self.native_completion = asyncio.ensure_future(self.host.mount(self.table))

            async def own_completion():
                try:
                    await asyncio.shield(self.native_completion)
                except asyncio.CancelledError:
                    while not self.native_completion.done():
                        with suppress(asyncio.CancelledError):
                            await asyncio.shield(self.native_completion)
                    self.native_completion.result()
                    raise

            self.completion = asyncio.create_task(own_completion())
            await entered.wait()
            self.exit()

        async def on_unmount(self):
            if self.completion is not None:
                self.completion.cancel()
                with suppress(asyncio.CancelledError):
                    await self.completion

    app = ClosingApp()
    running = asyncio.create_task(app.run_async(headless=True, size=(100, 30)))
    entered_wait = asyncio.create_task(entered.wait())
    try:
        done, _ = await asyncio.wait({entered_wait}, timeout=3)
        assert entered_wait in done
        done, _ = await asyncio.wait({running}, timeout=0.05)
        # Textual owns this handler and cannot process its queued Prune until
        # it returns. A completion owner must not assume exit cancels it.
        assert running not in done and not ended.is_set()
    finally:
        released.set()
        entered_wait.cancel()
        await asyncio.gather(entered_wait, return_exceptions=True)
        done, _ = await asyncio.wait({running}, timeout=3)
        assert running in done
        running.result()
    assert app.return_code == 0 and ended.is_set()
    assert not app.table.is_attached
    assert app.completion is not None and app.native_completion is not None
    assert app.completion.done()
    if not app.completion.cancelled():
        assert app.completion.result() is None
    assert app.native_completion.done() and not app.native_completion.cancelled()
    assert app.native_completion.result() is None


@pytest.mark.asyncio
async def test_quit_immediately_after_real_table_registration_drains_native_mount():
    class ClosingApp(App):
        def __init__(self):
            super().__init__()
            self.host = Vertical()
            self.table = NamespaceTable()
            self.completion = None
            self.mounted_at_registration = False

        def compose(self) -> ComposeResult:
            yield self.host

        def on_mount(self):
            self.table.setup()
            self.completion = asyncio.ensure_future(self.host.mount(self.table))
            assert self.is_mounted(self.table)
            self.mounted_at_registration = self.table.is_mounted
            self.exit()

        async def on_unmount(self):
            if self.completion is not None:
                await asyncio.shield(self.completion)

    app = ClosingApp()
    running = asyncio.create_task(app.run_async(headless=True, size=(100, 30)))
    done, _ = await asyncio.wait({running}, timeout=3)
    assert running in done
    running.result()
    assert app.return_code == 0 and not app.table.is_attached
    assert app.completion is not None
    assert app.completion.done() and not app.completion.cancelled()
    assert app.completion.result() is None
