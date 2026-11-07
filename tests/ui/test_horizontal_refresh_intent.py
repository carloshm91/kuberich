"""Horizontal user actions survive queued authorization refresh restoration."""

import asyncio
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path

import pytest
from textual.actions import SkipAction

from kuberich.domain.authorization import AuthorizationMode
from kuberich.services.authorization_commands import authorization_command
from kuberich.ui.authorization import AuthorizationTable
from tests.support.authorization_ui import GROUP, AuthorizationAPI, authorization_api
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for
from tests.ui.test_authorization import ready, select
from tests.ui.test_authorization_table import Host, row
from tests.ui.test_navigation import make_app
from tests.unit.test_authorization_rows import observed

EVIDENCE = Path(__file__).resolve().parents[2] / "artifacts/terminal/horizontal-refresh"


class Trace:
    def __init__(self, app, table, tmp_path):
        self.app, self.table = app, table
        self.events = []
        self.dropped = 0
        EVIDENCE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        EVIDENCE.mkdir(exist_ok=True, mode=0o700)
        self.directory = Path(tempfile.mkdtemp(prefix=tmp_path.name + "-", dir=EVIDENCE))
        self.directory.chmod(0o700)

    def note(self, stage, **details):
        if len(self.events) >= 512:
            self.dropped += 1
            return
        table = self.table
        self.events.append(
            {
                "sequence": len(self.events),
                "monotonic": time.monotonic(),
                "stage": stage,
                "x": table.scroll_x,
                "target_x": table.scroll_target_x,
                "y": table.scroll_y,
                "target_y": table.scroll_target_y,
                "max_x": table.max_scroll_x,
                "selected": table.selected_key(),
                "focus": type(self.app.focused).__name__,
                "has_focus": table.has_focus,
                "animated_x": self.app.animator.is_being_animated(table, "scroll_x"),
                **details,
            }
        )

    def instrument(self, monkeypatch):
        table = self.table
        original_scroll = table.scroll_to
        original_restore = table.restore_viewport

        def scroll_to(*args, **kwargs):
            self.note(
                "scroll_to:enter",
                requested_x=kwargs.get("x", args[0] if args else None),
                requested_y=kwargs.get("y", args[1] if len(args) > 1 else None),
                animate=kwargs.get("animate", True),
                immediate=kwargs.get("immediate", False),
            )
            result = original_scroll(*args, **kwargs)
            self.note("scroll_to:return")
            return result

        def restore(viewport):
            self.note("restore_viewport:enter", restore_x=viewport.x, restore_y=viewport.y)
            result = original_restore(viewport)
            self.note("restore_viewport:return")
            return result

        monkeypatch.setattr(table, "scroll_to", scroll_to)
        monkeypatch.setattr(table, "restore_viewport", restore)
        self.app.watch(table, "scroll_x", lambda value: self.note("observed_x", value=value))
        self.app.watch(
            table, "scroll_target_x", lambda value: self.note("observed_target_x", value=value)
        )

    def write(self):
        self.note("final")
        (self.directory / "trace.json").write_text(
            json.dumps(
                {
                    "events": self.events,
                    "dropped": self.dropped,
                },
                indent=2,
            )
            + "\n"
        )
        (self.directory / "frame.svg").write_text(self.app.export_screenshot())
        for path in self.directory.iterdir():
            path.chmod(0o600)
        print(f"Owned horizontal refresh evidence: {self.directory}")


async def settle(app, table):
    assert await asyncio.wait_for(table.wait_for_refresh(), 5)
    await wait_for(lambda: not app.animator.is_being_animated(table, "scroll_x"))
    assert await asyncio.wait_for(table.wait_for_refresh(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["left", "right"])
@pytest.mark.parametrize("order", ["no-refresh", "refresh-before", "refresh-after"])
@pytest.mark.parametrize("dispatch", ["profile", "native"])
@pytest.mark.parametrize("cursor_visible", [True, False])
async def test_authorization_step_survives_unchanged_row_refresh(
    tmp_path, monkeypatch, direction, order, dispatch, cursor_visible
):
    app = Host()
    data = observed()
    rows = tuple(
        row(str(index), details=("owned-long-detail-" * 18, "second-line")) for index in range(15)
    )
    async with app.run_test(size=(60, 14)):
        table = app.table
        assert isinstance(table, AuthorizationTable)
        table.show_cursor = cursor_visible
        assert await table.apply_rows(rows, data, lambda: True)
        await settle(app, table)
        table.move_cursor(row=5, scroll=False)
        table.focus()
        await settle(app, table)
        start = table.max_scroll_x if direction == "left" else 20
        assert table.max_scroll_x > 60
        table.scroll_to(x=start, y=4, animate=False, immediate=True, force=True)
        await settle(app, table)
        viewport = table.capture_viewport()
        trace = Trace(app, table, tmp_path)
        trace.instrument(monkeypatch)
        try:
            trace.note(
                "ready",
                order=order,
                direction=direction,
                dispatch=dispatch,
                cursor_visible=cursor_visible,
            )
            if order == "refresh-before":
                trace.note("apply_rows:before-action")
                assert await table.apply_rows(rows, data, lambda: True)
            trace.note("action:enter", direction=direction)
            action = "action_scroll_" if dispatch == "profile" else "action_cursor_"
            getattr(table, action + direction)()
            trace.note("action:return", direction=direction)
            if order == "refresh-after":
                trace.note("apply_rows:after-action")
                assert await table.apply_rows(rows, data, lambda: True)
            await settle(app, table)
            trace.note("settled")
            expected = start + (-1 if direction == "left" else 1)
            assert table.scroll_x == table.scroll_target_x == expected
            assert table.selected_key() == viewport.selected and table.scroll_y == viewport.y
            assert table.has_focus
        finally:
            trace.write()


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["left", "right"])
@pytest.mark.parametrize("dispatch", ["profile", "native"])
async def test_actual_app_age_refresh_preserves_the_concurrent_authorization_step(
    tmp_path, monkeypatch, direction, dispatch
):
    api = AuthorizationAPI()
    role = api.objects[(GROUP, "roles", "team", "reader")]
    role["rules"] = [
        {
            "verbs": ["get", "list"],
            "apiGroups": [""],
            "resources": ["pods"],
            "resourceNames": [f"owned-resource-{index}-" + "x" * 128],
        }
        for index in range(5)
    ]
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url), initial=authorization_command("rbac roles"))
        async with app.run_test(size=(100, 30)) as pilot:
            await ready(app, AuthorizationMode.ROLES)
            target = select(
                app,
                lambda item: (
                    item.object_ref is not None
                    and item.object_ref.kind == "Role"
                    and item.object_ref.namespace == "team"
                ),
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.ROLE)
            table = app.authorization_table
            selected = select(
                app,
                lambda item: item.key.startswith("rule:") and item.object_ref == target.object_ref,
            )
            await settle(app, table)
            start = table.max_scroll_x if direction == "left" else 20
            assert table.max_scroll_x > 60
            table.scroll_to(x=start, animate=False, immediate=True, force=True)
            await settle(app, table)
            viewport = table.capture_viewport()
            snapshot = app.workspace.store.observation.authorization
            reads = tuple(api.reads)
            trace = Trace(app, table, tmp_path)
            trace.instrument(monkeypatch)
            original_apply = table.apply_rows
            armed, applied = [True], asyncio.Event()

            async def apply_rows(rows, data, current):
                if not armed[0]:
                    return await original_apply(rows, data, current)
                armed[0] = False
                trace.note(
                    "refresh_apply:enter",
                    same_snapshot=data is snapshot,
                    observed_uid=selected.object_ref.uid,
                )
                trace.note("action:enter", direction=direction, dispatch=dispatch)
                action = "action_scroll_" if dispatch == "profile" else "action_cursor_"
                getattr(table, action + direction)()
                trace.note("action:return", direction=direction, dispatch=dispatch)
                result = await original_apply(rows, data, current)
                trace.note("refresh_apply:return", applied=result)
                applied.set()
                return result

            monkeypatch.setattr(table, "apply_rows", apply_rows)
            try:
                trace.note("refresh_ages:requested")
                app.presenter.refresh_ages()
                await asyncio.wait_for(applied.wait(), 5)
                await settle(app, table)
                trace.note("settled")
                assert app.workspace.store.observation.authorization is snapshot
                assert tuple(api.reads) == reads
                assert selected.object_ref.uid == role["metadata"]["uid"]
                assert table.selected_key() == viewport.selected and table.scroll_y == viewport.y
                assert (
                    table.has_focus
                    and table.row_at(viewport.selected).object_ref == selected.object_ref
                )
                expected = start + (-1 if direction == "left" else 1)
                assert table.scroll_x == table.scroll_target_x == expected
            finally:
                trace.write()
    assert api.active_watches == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["left", "right"])
@pytest.mark.parametrize("dispatch", ["profile", "native"])
async def test_boundary_step_revokes_older_restore_but_later_history_still_applies(
    direction, dispatch
):
    app = Host()
    rows = tuple(row(str(index), details=("owned-detail-" * 25,)) for index in range(10))
    async with app.run_test(size=(60, 14)):
        table = app.table
        await table.apply_rows(rows, observed(), lambda: True)
        await settle(app, table)
        table.move_cursor(row=4, scroll=False)
        table.focus()
        await settle(app, table)
        boundary = 0 if direction == "left" else table.max_scroll_x
        table.scroll_to(x=boundary, animate=False, immediate=True, force=True)
        await settle(app, table)
        before = table.capture_viewport()
        older = replace(before, x=9)
        table.restore_viewport(older)
        action = "action_scroll_" if dispatch == "profile" else "action_cursor_"
        getattr(table, action + direction)()
        await settle(app, table)
        assert table.scroll_x == table.scroll_target_x == boundary
        assert table.selected_key() == before.selected and table.scroll_y == before.y
        table.restore_viewport(older)
        await settle(app, table)
        assert table.capture_viewport() == older
        assert table.has_focus


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", ["left", "right"])
@pytest.mark.parametrize("dispatch", ["profile", "native"])
async def test_no_horizontal_extent_keeps_native_skip_action_and_focus(direction, dispatch):
    app = Host()
    async with app.run_test(size=(200, 14)):
        table = app.table
        await table.apply_rows((row("one", details=("short",)),), observed(), lambda: True)
        await settle(app, table)
        table.focus()
        assert table.max_scroll_x == 0 and not table.allow_horizontal_scroll
        with pytest.raises(SkipAction):
            action = "action_scroll_" if dispatch == "profile" else "action_cursor_"
            getattr(table, action + direction)()
        assert table.scroll_x == table.scroll_target_x == 0 and table.has_focus


@pytest.mark.asyncio
async def test_programmatic_horizontal_animation_keeps_its_public_owner_and_completion():
    app = Host()
    async with app.run_test(size=(60, 14)):
        table = app.table
        await table.apply_rows(
            (row("one", details=("owned-detail-" * 25,)),), observed(), lambda: True
        )
        await settle(app, table)
        table.scroll_to(x=20, animate=False, immediate=True, force=True)
        await settle(app, table)
        finished = asyncio.Event()
        table.scroll_left(animate=True, duration=0.1, immediate=True, on_complete=finished.set)
        assert app.animator.is_being_animated(table, "scroll_x")
        await asyncio.wait_for(finished.wait(), 5)
        await settle(app, table)
        assert table.scroll_x == table.scroll_target_x == 19
