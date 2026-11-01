"""Owned deferred registration uses real tables and public native lifecycle."""

import asyncio
from contextlib import suppress

import pytest
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from kuberich.domain.namespaces import NamespaceRow
from kuberich.ui.contexts import ContextTable
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.view_mounts import ViewMounts, wait_for_mount


class MountApp(App):
    def __init__(self, *, wait=wait_for_mount, start=True, host=None):
        super().__init__()
        self.host = host if host is not None else Vertical()
        self.anchor = Static("Owned empty state")
        self.tables = (PodTable(), NamespaceTable(), ContextTable())
        for index, table in enumerate(self.tables):
            table.display = index == 0
        self.owner = None
        self.wait, self.start_after_refresh = wait, start
        self.errors = []

    def compose(self) -> ComposeResult:
        with self.host:
            yield self.tables[0]
            yield self.anchor

    def on_mount(self):
        for table in self.tables:
            table.setup()
        self.owner = ViewMounts(
            self, self.host, self.tables, self.anchor, self.errors.append, wait=self.wait
        )
        if self.start_after_refresh:
            self.call_after_refresh(self.owner.start)

    def exit(self, result=None, return_code=0, message=None):
        if self.owner is not None:
            self.owner.stop()
        super().exit(result=result, return_code=return_code, message=message)

    async def on_unmount(self):
        if self.owner is not None:
            await self.owner.close()


@pytest.mark.asyncio
async def test_background_mount_preserves_selected_geometry_and_registers_each_table_once():
    app = MountApp(start=False)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        assert app.owner is not None
        initial_region = app.tables[0].region
        app.owner.start()
        app.owner.start()
        await app.owner.wait_ready()
        await pilot.pause()
        for table, expected_columns in zip(app.tables, (6, 3, 5), strict=True):
            app.owner.ensure(table)
            assert table.is_mounted and app.is_mounted(table)
            assert app.host.children.count(table) == 1
            assert len(table.columns) == expected_columns
        assert app.tables[0].region == initial_region
        assert app.errors == []
        with pytest.raises(ValueError, match="owned resource tables"):
            app.owner.ensure(NamespaceTable())


@pytest.mark.asyncio
async def test_eager_task_factory_cannot_register_inactive_tables_inside_refresh_scheduler():
    app = MountApp(start=False)
    async with app.run_test() as pilot:
        assert app.owner is not None
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        loop.set_task_factory(asyncio.eager_task_factory)
        try:
            assert app.owner.start() is None
            assert not app.is_mounted(app.tables[1]) and not app.is_mounted(app.tables[2])
            await app.owner.wait_ready()
        finally:
            loop.set_task_factory(original)
        await pilot.pause()
        assert all(table.is_mounted for table in app.tables)


@pytest.mark.asyncio
async def test_early_route_configures_focuses_and_preserves_rows_before_background_is_started():
    app = MountApp(start=False)
    async with app.run_test(size=(100, 30)) as pilot:
        assert app.owner is not None
        table = app.tables[1]
        app.owner.ensure(table)
        app.owner.ensure(table)
        app.tables[0].display, table.display = False, True
        table.configure_view(None, force=True)
        app.set_focus(table)
        assert await table.apply_rows(
            (
                NamespaceRow("owned-a", "alpha", "Active", None),
                NamespaceRow("owned-b", "beta", "Active", None),
            ),
            1,
            lambda: True,
        )
        table.move_cursor(row=1, scroll=False)
        app.owner.start()
        await app.owner.wait_ready()
        await pilot.pause()
        assert app.focused is table and table.selected_uid == "owned-b"
        assert table.cursor_row == 1 and table.row_count == 2
        assert app.host.children.count(table) == 1
        assert len(table.columns) == 3 and table.region.width > 0
        assert app.errors == []


@pytest.mark.asyncio
async def test_stop_before_first_refresh_releases_waiters_without_registering_inactive_tables():
    app = MountApp(start=False)
    async with app.run_test() as pilot:
        assert app.owner is not None
        waiting = asyncio.create_task(app.owner.wait_ready())
        await asyncio.sleep(0)
        app.owner.stop()
        app.owner.start()
        app.owner.ensure(app.tables[1])
        await app.owner.close()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await pilot.pause()
        assert not app.is_mounted(app.tables[1]) and not app.is_mounted(app.tables[2])
        assert app.errors == []


@pytest.mark.asyncio
async def test_quit_cancels_owned_completion_waits_and_drains_all_real_native_mounts():
    entered, ended = asyncio.Event(), asyncio.Event()
    waits = []

    async def hold_owned_wait(completion):
        waits.append(completion)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            ended.set()

    app = MountApp(wait=hold_owned_wait)

    async def quit_while_waiting(pilot):
        await entered.wait()
        await pilot.press("ctrl+q")

    running = asyncio.create_task(
        app.run_async(headless=True, size=(100, 30), auto_pilot=quit_while_waiting)
    )
    done, _ = await asyncio.wait({running}, timeout=3)
    assert running in done
    running.result()
    assert app.return_code == 0 and entered.is_set() and ended.is_set()
    assert waits and all(not table.is_attached for table in app.tables)
    assert app.errors == []


@pytest.mark.asyncio
async def test_completion_failure_is_reported_once_and_does_not_abandon_native_tables():
    problem = RuntimeError("Owned completion failure")

    async def fail_owned_wait(completion):
        await completion
        raise problem

    app = MountApp(wait=fail_owned_wait)
    async with app.run_test() as pilot:
        assert app.owner is not None
        with pytest.raises(RuntimeError, match="Owned completion failure"):
            await app.owner.wait_ready()
        await pilot.pause()
        assert app.errors == [problem]
        await app.owner.close()
    assert all(not table.is_attached for table in app.tables)


@pytest.mark.asyncio
async def test_cancelling_a_readiness_waiter_keeps_the_registration_owner_live():
    entered, released = asyncio.Event(), asyncio.Event()

    async def hold_owned_wait(completion):
        entered.set()
        await released.wait()
        await completion

    app = MountApp(wait=hold_owned_wait)
    async with app.run_test() as pilot:
        assert app.owner is not None
        await entered.wait()
        waiting = asyncio.create_task(app.owner.wait_ready())
        await asyncio.sleep(0)
        waiting.cancel()
        with suppress(asyncio.CancelledError):
            await waiting
        released.set()
        await app.owner.wait_ready()
        await pilot.pause()
        assert all(table.is_mounted for table in app.tables)
        assert app.errors == []


@pytest.mark.asyncio
async def test_close_retains_native_completion_when_its_owner_was_cancelled_before_start():
    entered, released, ended = asyncio.Event(), asyncio.Event(), asyncio.Event()

    class CompletionHost(Vertical):
        capture = False

        def __init__(self):
            super().__init__()
            self.completions = []

        def mount(self, *widgets, before=None, after=None):
            native = super().mount(*widgets, before=before, after=after)
            if not self.capture:
                return native

            async def owned_completion():
                await native
                entered.set()
                try:
                    await released.wait()
                finally:
                    ended.set()

            completion = asyncio.create_task(owned_completion())
            self.completions.append(completion)
            return completion

    host = CompletionHost()
    app = MountApp(start=False, host=host)
    async with app.run_test() as pilot:
        assert app.owner is not None
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        loop.set_task_factory(None)
        closing = None
        try:
            host.capture = True
            # No event-loop turn separates owner creation and cancellation.
            app.owner.ensure(app.tables[1])
            app.owner.stop()
            closing = asyncio.create_task(app.owner.close())
            await asyncio.wait_for(entered.wait(), timeout=3)
            assert not closing.done()
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            assert not closing.done()
        finally:
            released.set()
            if closing is not None:
                await closing
            loop.set_task_factory(original)
        await pilot.pause()
        assert ended.is_set()
        assert len(host.completions) == 1
        assert host.completions[0].done() and not host.completions[0].cancelled()
        assert host.completions[0].result() is None
        assert app.errors == []
