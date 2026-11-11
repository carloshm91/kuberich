"""Public debug commands, strict HTTP reviews and retained terminal ownership in Pilot."""

import asyncio
import copy
import json
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from textual.widgets import Checkbox, DataTable, Input

from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.domain.ephemeral_debug import EphemeralDebugOptions, declaration
from kuberich.domain.mutations import MutationState
from kuberich.domain.views import ViewStatus
from kuberich.services.ephemeral_debug import EphemeralDebugService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.ephemeral_debug import EphemeralDebugScreen
from kuberich.ui.terminal import ShellScreen
from tests.support import ephemeral_debug_terminal as debug_support
from tests.support.connections import catalog_fixture
from tests.support.ephemeral_debug_terminal import DebugHandler, debug_api
from tests.support.workspace import wait_for

IMAGE = "example.test/debug@sha256:" + "a" * 64
CHILD = r"""
import os,tty
from pathlib import Path
root=Path(__file__).parent
tty.setraw(0)
(root/'debug-child-pid').write_text(str(os.getpid()))
os.write(1,b'DEBUG REMOTE caf\xc3\xa9\r\n')
data=b''
while True:
    chunk=os.read(0,4096)
    data+=chunk
    (root/'debug-input').write_bytes(data)
    if b'\x03' in chunk:
        os.write(1,b'REMOTE INTERRUPT\r\n')
    if b'exit\r' in data:
        break
"""


@asynccontextmanager
async def debug_app(tmp_path, *, readonly=False, helper=True, initial=None):
    if helper:
        binary = tmp_path / "kubectl"
        binary.write_text(f"#!{sys.executable}\n" + CHILD)
        binary.chmod(0o700)
    with debug_api() as api:
        app = KubeRichApp(
            Settings(read_only=readonly),
            logging.Logger("ephemeral-debug-ui", level=100),
            catalog=catalog_fixture(tmp_path, f"http://127.0.0.1:{api.server_port}"),
            initial_command=initial or Command.PODS,
            environment={**os.environ, "PATH": str(tmp_path)},
            directory=tmp_path,
        )
        yield app, api


async def open_debug(app):
    await wait_for(lambda: app.state.status is ViewStatus.LIVE and app.state.selected is not None)
    await app.run_command(":debug")
    await wait_for(lambda: isinstance(app.screen, EphemeralDebugScreen))
    screen = app.screen
    await wait_for(lambda: screen.owner.observation.remote is not None)
    return screen


async def prepare(screen, pilot, *, name="debug-one", target="app"):
    screen.query_one("#debug-image", Input).value = IMAGE
    screen.query_one("#debug-name", Input).value = name
    screen.query_one("#debug-target", Input).value = target
    await pilot.pause()
    screen.review_button.press()
    await wait_for(lambda: screen.review is not None and not screen.busy)


def patches(api, *, dry=None):
    return [
        request
        for request in api.requests
        if request[0] == "PATCH" and (dry is None or (request[2].get("dryRun") == ["All"]) == dry)
    ]


def existing(api, name="debug-existing", *, state="running", image=IMAGE):
    pod = copy.deepcopy(api.pod)
    entry = declaration(EphemeralDebugOptions(name, IMAGE, ("sh",)))
    entry["image"] = image
    pod["spec"].setdefault("ephemeralContainers", []).append(entry)
    status = (
        {"running": {"startedAt": "2026-11-10T00:01:00Z"}}
        if state == "running"
        else {"terminated": {"exitCode": 7, "reason": "Error"}}
    )
    pod["status"].setdefault("ephemeralContainerStatuses", []).append(
        {
            "name": name,
            "containerID": "containerd://owned-" + name,
            "restartCount": 0,
            "state": status,
        }
    )
    api.pod = pod


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_open_and_enter_default_to_cancel_without_any_patch(tmp_path, size):
    async with debug_app(tmp_path) as (app, api), app.run_test(size=size) as pilot:
        await wait_for(
            lambda: app.state.status is ViewStatus.LIVE and app.state.selected is not None
        )
        state, viewport = app.state, app.resources.capture_viewport()
        screen = await open_debug(app)
        assert app.focused is screen.cancel_button
        assert screen.query_one("#debug-image", Input).value == ""
        assert json.loads(screen.query_one("#debug-command", Input).value) == ["sh"]
        assert screen.query_one("#debug-name", Input).value.startswith("debug-")
        assert screen.query_one("#debug-root-readonly", Checkbox).value
        assert screen.add_button.disabled and screen.attach_button.disabled
        assert app.ephemeral_debug_manager.active_count == 1
        for button in screen.query("Button"):
            assert button.region.width > 0 and button.region.bottom <= size[1]
        await pilot.press("enter")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert not patches(api)
        assert app.ephemeral_debug_manager.active_count == 0
        assert app.retained_ephemeral_debug_view_count == 0
        assert app.state == state and app.resources.capture_viewport() == viewport


@pytest.mark.asyncio
@pytest.mark.parametrize("hold_return", [False, True])
async def test_review_exact_options_add_once_then_explicit_attach_and_return(
    tmp_path, monkeypatch, hold_return
):
    async with debug_app(tmp_path) as (app, api), app.run_test(size=(100, 30)) as pilot:
        original_push = app.push_screen
        returned = asyncio.Event()
        held = []

        def push(screen, callback=None, *args, **kwargs):
            if hold_return and isinstance(screen, ShellScreen):
                original_callback = callback

                def capture(result):
                    held.append((original_callback, result))
                    returned.set()

                callback = capture
            return original_push(screen, callback, *args, **kwargs)

        monkeypatch.setattr(app, "push_screen", push)
        screen = await open_debug(app)
        await prepare(screen, pilot)
        assert len(patches(api, dry=True)) == 1 and not patches(api, dry=False)
        assert app.focused is screen.cancel_button and not screen.add_button.disabled
        preview = str(screen.preview.content)
        for value in (
            "Add permanently",
            "owned-debug-pod-uid",
            "opaque/debug-v1",
            IMAGE,
            "containerd://owned-app-instance",
            "RuntimeDefault",
            "runAsUser",
            "1000",
            "hostPID",
            "serviceAccountName",
            '"stdinOnce": false',
        ):
            assert value in preview
        screen.add_button.press()
        screen.add_button.press()
        await wait_for(lambda: len(patches(api, dry=False)) == 1 and not screen.busy)
        assert app.screen is screen and app.processes.active_count == 0
        assert screen.selected().state == "running"
        assert not screen.attach_button.disabled and screen.add_button.disabled
        assert "Append/startup result: Succeeded" in str(screen.feedback.content)
        screen.table.focus()
        await pilot.press("enter")
        assert app.screen is screen and app.processes.active_count == 0
        screen.attach_button.press()
        await wait_for(lambda: isinstance(app.screen, ShellScreen))
        terminal = app.screen
        await wait_for(
            lambda: "DEBUG REMOTE café" in "\n".join(terminal.terminal.model.screen.display)
        )
        await pilot.press("ctrl+c")
        await wait_for(
            lambda: "REMOTE INTERRUPT" in "\n".join(terminal.terminal.model.screen.display)
        )
        await pilot.resize_terminal(40, 12)
        await pilot.press("ctrl+right_square_bracket")
        await wait_for(lambda: app.screen is screen and app.processes.active_count == 0)
        if hold_return:
            await wait_for(returned.is_set)
            assert "Append/startup result: Succeeded" in str(screen.feedback.content)
            assert len(held) == 1
            callback, result = held.pop()
            callback(result)
        await wait_for(
            lambda: (
                app.screen is screen
                and app.processes.active_count == 0
                and "does not establish remote completion" in str(screen.feedback.content)
            )
        )
        assert screen.selected().state == "running"
        assert not list(Path(app.sessions.client.directory.name).glob("exec-*.json"))
        pid = int((tmp_path / "debug-child-pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        await pilot.press("escape")
        assert app.retained_ephemeral_debug_view_count == 0
        assert app.ephemeral_debug_manager.active_count == 0
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1
        assert not any(request[0] == "DELETE" for request in api.requests)


@pytest.mark.asyncio
async def test_readonly_inspects_existing_remote_states_but_blocks_all_effects(tmp_path):
    async with debug_app(tmp_path, readonly=True) as (app, api):
        existing(api)
        existing(api, "debug-completed", state="terminated")
        async with app.run_test() as pilot:
            screen = await open_debug(app)
            assert [(row.name, row.state, row.exit_code) for row in screen.rows] == [
                ("debug-existing", "running", None),
                ("debug-completed", "terminated", 7),
            ]
            assert screen.review_button.disabled and screen.add_button.disabled
            assert screen.attach_button.disabled
            screen.prepare()
            screen.attach()
            await pilot.pause()
            assert not patches(api) and app.processes.active_count == 0
            assert "Read-only inspection" in str(screen.feedback.content)
            await pilot.press("escape")
            assert app.ephemeral_debug_manager.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "value"),
    [
        ("debug-image", IMAGE.replace("a" * 64, "b" * 64)),
        ("debug-command", '["sh", "-i"]'),
        ("debug-name", "debug-two"),
        ("debug-target", ""),
        ("debug-user", "1001"),
        ("debug-group", "1002"),
        ("debug-root-readonly", False),
    ],
)
async def test_each_option_edit_invalidates_review_and_requires_new_dry_run(
    tmp_path, selector, value
):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        await prepare(screen, pilot)
        field = screen.query_one("#" + selector)
        field.value = value
        await pilot.pause()
        assert screen.review is None and screen.add_button.disabled
        screen.add()
        assert not patches(api, dry=False)
        screen.review_button.press()
        await wait_for(lambda: screen.review is not None and not screen.busy)
        assert len(patches(api, dry=True)) == 2
        screen.add_button.press()
        await pilot.pause()
        await wait_for(lambda: not screen.busy)
        assert len(patches(api, dry=False)) == 1
        await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["denied", "unsupported", "windows", "target", "collision"])
async def test_refused_review_never_enables_add_or_substitutes_options(tmp_path, monkeypatch, mode):
    if mode == "unsupported":
        roots = debug_support.debug_roots()
        roots["/api/v1"]["resources"] = [
            row
            for row in roots["/api/v1"]["resources"]
            if row["name"] != "pods/ephemeralcontainers"
        ]
        monkeypatch.setattr(debug_support, "debug_roots", lambda: roots)
    async with debug_app(tmp_path) as (app, api):
        api.denied = mode == "denied"
        if mode == "windows":
            api.pod["spec"]["os"] = {"name": "windows"}
        if mode == "collision":
            existing(api, "debug-one")
        async with app.run_test() as pilot:
            screen = await open_debug(app)
            screen.query_one("#debug-image", Input).value = IMAGE
            screen.query_one("#debug-name", Input).value = "debug-one"
            screen.query_one("#debug-target", Input).value = (
                "missing" if mode == "target" else "app"
            )
            await pilot.pause()
            screen.review_button.press()
            await wait_for(lambda: "Review unavailable" in str(screen.feedback.content))
            assert screen.review is None and screen.add_button.disabled
            assert screen.query_one("#debug-image", Input).value == IMAGE
            assert not patches(api, dry=False)
            await pilot.press("escape")
            assert app.retained_ephemeral_debug_view_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("selector", "value"),
    [
        ("debug-command", "[1]"),
        ("debug-command", "{"),
        ("debug-user", ""),
        ("debug-group", "0"),
        ("debug-image", "debug:latest"),
    ],
)
async def test_invalid_options_fail_locally_without_dry_run(tmp_path, selector, value):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        screen.query_one("#debug-image", Input).value = IMAGE
        screen.query_one("#" + selector, Input).value = value
        await pilot.pause()
        screen.review_button.press()
        await wait_for(lambda: "Review unavailable" in str(screen.feedback.content))
        assert screen.review is None and not patches(api)
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_edit_during_inflight_dry_run_discards_late_review(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = DebugHandler.do_PATCH

    def held(handler):
        if "dryRun=All" in handler.path:
            entered.set()
            assert release.wait(5)
        original(handler)

    monkeypatch.setattr(DebugHandler, "do_PATCH", held)
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        try:
            screen = await open_debug(app)
            screen.query_one("#debug-image", Input).value = IMAGE
            await pilot.pause()
            screen.review_button.press()
            await wait_for(entered.is_set)
            screen.query_one("#debug-root-readonly", Checkbox).value = False
            await pilot.pause()
            release.set()
            await wait_for(lambda: not screen.busy)
            assert screen.review is None and screen.add_button.disabled
            assert "Options changed during preparation" in str(screen.feedback.content)
            screen.review_button.press()
            await wait_for(lambda: screen.review is not None and not screen.busy)
            assert not screen.review.intent.options.read_only_root_filesystem
            assert len(patches(api, dry=True)) == 2 and not patches(api, dry=False)
            await pilot.press("escape")
        finally:
            release.set()


@pytest.mark.asyncio
async def test_unverified_admission_is_permanent_but_explicit_attach_is_refused(
    tmp_path, monkeypatch
):
    original = DebugHandler.respond

    def respond(handler, payload=None, *, status=200):
        if handler.command == "PATCH" and "dryRun=All" not in handler.path:
            payload["spec"]["ephemeralContainers"][-1]["env"] = [
                {"name": "PRIVATE", "value": "synthetic-admission-secret"}
            ]
        original(handler, payload, status=status)

    monkeypatch.setattr(DebugHandler, "respond", respond)
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        await prepare(screen, pilot)
        screen.add_button.press()
        await pilot.pause()
        await wait_for(lambda: not screen.busy and screen.table.row_count == 1)
        assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
        assert "Attachment is blocked" in str(screen.outcomes.content)
        assert "synthetic-admission-secret" not in str(screen.outcomes.content)
        screen.attach_button.press()
        await wait_for(lambda: "Attach unavailable" in str(screen.feedback.content))
        assert not (tmp_path / "debug-child-pid").exists()
        assert app.processes.active_count == 0 and len(patches(api, dry=False)) == 1
        await pilot.press("escape")
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1


@pytest.mark.asyncio
async def test_escape_during_held_review_drains_without_any_real_append(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = DebugHandler.do_PATCH

    def held(handler):
        entered.set()
        assert release.wait(5)
        original(handler)

    monkeypatch.setattr(DebugHandler, "do_PATCH", held)
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        try:
            screen = await open_debug(app)
            screen.query_one("#debug-image", Input).value = IMAGE
            await pilot.pause()
            screen.review_button.press()
            await wait_for(entered.is_set)
            screen.prepare()
            screen.attach()
            await pilot.press("escape")
            assert len(app.screen_stack) == 1
            assert app.retained_ephemeral_debug_view_count == 0
            assert app.ephemeral_debug_manager.active_count == 0
            assert screen.owner.operation_count == 0 and not patches(api, dry=False)
            await screen.action_back()
            assert len(app.screen_stack) == 1
        finally:
            release.set()


@pytest.mark.asyncio
async def test_unexpected_worker_fault_reaches_fatal_boundary_after_owned_cleanup(
    tmp_path, monkeypatch
):
    async def fail(owner, options):
        raise RuntimeError("synthetic-debug-worker-fault")

    monkeypatch.setattr(EphemeralDebugService, "prepare", fail)
    async with debug_app(tmp_path) as (app, api):
        with pytest.raises(RuntimeError, match="synthetic-debug-worker-fault"):
            async with app.run_test() as pilot:
                screen = await open_debug(app)
                screen.query_one("#debug-image", Input).value = IMAGE
                await pilot.pause()
                screen.review_button.press()
                await wait_for(lambda: app.ephemeral_debug_manager.active_count == 0)
        assert app.retained_ephemeral_debug_view_count == 0
        assert app.sessions.client is None and app.processes.active_count == 0
        assert not patches(api)


@pytest.mark.asyncio
async def test_enter_in_form_never_reviews_and_closed_actions_refuse_new_owner(tmp_path):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        screen.query_one("#debug-image", Input).value = IMAGE
        screen.query_one("#debug-image", Input).focus()
        await pilot.press("enter")
        assert screen.review is None and not patches(api)
        app.operations.ephemeral_debug.open()
        assert app.retained_ephemeral_debug_view_count == 1
        await pilot.press("escape")
        await app.operations.ephemeral_debug.close()
        await app.run_command(":debug")
        await pilot.pause()
        assert len(app.screen_stack) == 1 and app.ephemeral_debug_manager.active_count == 0
        assert "active or draining" in str(app.status.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["discovery", "review-pod", "attach-pod"])
async def test_denied_preparation_reads_remain_nonfatal_and_never_start_a_process(
    tmp_path, monkeypatch, phase
):
    original, denied_path = DebugHandler.do_GET, [None]

    def get(handler):
        if urlsplit(handler.path).path == denied_path[0]:
            handler.respond({"private": "synthetic-denial-secret"}, status=403)
            return
        original(handler)

    monkeypatch.setattr(DebugHandler, "do_GET", get)
    async with debug_app(tmp_path) as (app, api):
        existing(api)
        async with app.run_test() as pilot:
            screen = await open_debug(app)
            denied_path[0] = (
                "/api/v1" if phase == "discovery" else "/api/v1/namespaces/team/pods/debug-workload"
            )
            if phase == "attach-pod":
                screen.attach_button.press()
                expected = "Attach unavailable"
            else:
                screen.query_one("#debug-image", Input).value = IMAGE
                await pilot.pause()
                screen.review_button.press()
                expected = "Review unavailable"
            await wait_for(lambda: expected in str(screen.feedback.content))
            assert app.is_running and app.screen is screen
            assert "synthetic-denial-secret" not in str(screen.feedback.content)
            assert app.processes.active_count == 0 and not patches(api)
            await pilot.press("escape")
            assert app.ephemeral_debug_manager.active_count == 0


@pytest.mark.asyncio
async def test_bounded_observation_discloses_incomplete_pending_waiting_and_unknown(tmp_path):
    async with debug_app(tmp_path) as (app, api):
        entry = declaration(EphemeralDebugOptions("debug-zero", IMAGE, ("sh",)))
        api.pod["spec"]["ephemeralContainers"] = [
            {**entry, "name": f"debug-{number:03}"} for number in range(257)
        ]
        api.pod["status"]["ephemeralContainerStatuses"] = [
            {"name": "debug-000", "state": {"waiting": {"reason": "[red]café[/red]"}}},
            {"name": "debug-001", "state": {"waiting": {}, "running": {}}},
            {"name": "debug-002", "state": {"waiting": {"reason": "\x1b[2J"}}},
        ]
        async with app.run_test(size=(40, 12)) as pilot:
            screen = await open_debug(app)
            assert screen.table.row_count == 256
            assert [row.state for row in screen.rows[:4]] == [
                "waiting",
                "unknown",
                "unknown",
                "pending",
            ]
            assert "INCOMPLETE (first 256 sessions)" in str(screen.summary.content)
            cell = screen.table.get_cell("debug-000", "reason")
            assert "[red]café[/red]" in cell.plain and "\x1b" not in cell.plain
            assert screen.attach_button.disabled
            await pilot.resize_terminal(100, 30)
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_stale_denied_observation_retains_rows_and_viewport_then_recovers(
    tmp_path, monkeypatch
):
    original, denied = DebugHandler.do_GET, [False]

    def observe(handler):
        if denied[0] and urlsplit(handler.path).path.endswith("/pods/debug-workload"):
            handler.respond({"private": "synthetic-secret-detail"}, status=403)
            return
        original(handler)

    monkeypatch.setattr(DebugHandler, "do_GET", observe)
    async with debug_app(tmp_path) as (app, api):
        for number in range(20):
            existing(api, f"debug-{number:02}", image=IMAGE + "-café-[red]")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await open_debug(app)
            screen.table.focus()
            screen.table.move_cursor(row=12)
            screen.table.scroll_to(x=8, y=9, animate=False, immediate=True, force=True)
            await pilot.pause()
            selected, offset = screen.selected(), screen.table.scroll_offset
            await screen.owner.observe()
            assert screen.selected() == selected and screen.table.scroll_offset == offset
            denied[0] = True
            await wait_for(lambda: screen.owner.observation.stale)
            assert screen.table.row_count == 20 and screen.selected() == selected
            assert screen.table.scroll_offset == offset and screen.attach_button.disabled
            assert "STALE" in str(screen.summary.content) and "denied" in str(
                screen.summary.content
            )
            assert "synthetic-secret-detail" not in str(screen.summary.content)
            denied[0] = False
            await wait_for(lambda: not screen.owner.observation.stale)
            assert not screen.attach_button.disabled
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_complete_review_is_required_before_enabling_add_even_for_valid_escaped_argv(
    tmp_path,
):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        screen.query_one("#debug-image", Input).value = IMAGE
        screen.query_one("#debug-command", Input).value = json.dumps(["\\" * 8190])
        await pilot.pause()
        screen.review_button.press()
        await wait_for(lambda: "Complete debug review exceeds" in str(screen.feedback.content))
        assert screen.review is None and screen.add_button.disabled
        assert len(patches(api, dry=True)) == 1 and not patches(api, dry=False)
        screen.add()
        assert not patches(api, dry=False)
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_table_render_fault_during_append_drains_before_fatal_and_retains_receipt(
    tmp_path, monkeypatch
):
    original = DataTable.coordinate_to_cell_key

    def fail(table, coordinate):
        if table.id == "debug-sessions" and table.row_count and api.appended.is_set():
            raise RuntimeError("synthetic-debug-table-fault")
        return original(table, coordinate)

    async with debug_app(tmp_path) as (app, api):
        existing(api)
        with pytest.raises(RuntimeError, match="synthetic-debug-table-fault"):
            async with app.run_test() as pilot:
                screen = await open_debug(app)
                await prepare(screen, pilot)
                monkeypatch.setattr(DataTable, "coordinate_to_cell_key", fail)
                screen.add_button.press()
                await wait_for(lambda: app.retained_ephemeral_debug_view_count == 0)
        assert app.ephemeral_debug_manager.active_count == 0
        assert app.ephemeral_debug_manager.records[-1].result.state is MutationState.SUCCEEDED
        assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
        assert len(patches(api, dry=False)) == 1
        assert app.sessions.client is None and app.processes.active_count == 0
        assert screen.owner.operation_count == 0


@pytest.mark.asyncio
async def test_lost_append_receipt_stays_uncertain_and_never_autoattaches_or_retries(tmp_path):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        await prepare(screen, pilot)
        api.drop_response = True
        screen.add_button.press()
        await pilot.pause()
        await wait_for(lambda: not screen.busy)
        await wait_for(lambda: screen.table.row_count == 1)
        assert app.mutations.records[-1].result.state is MutationState.UNCERTAIN
        assert "uncertain" in str(screen.outcomes.content).lower()
        assert len(patches(api, dry=False)) == 1 and app.processes.active_count == 0
        assert screen.attach_button.disabled
        screen.attach()
        await pilot.pause()
        assert app.screen is screen and app.processes.active_count == 0
        await pilot.press("escape")
        assert len(app.ephemeral_debug_manager.records) == 1
        assert app.ephemeral_debug_manager.records[0].result.state is MutationState.UNCERTAIN
        assert len(api.pod["spec"]["ephemeralContainers"]) == 1


@pytest.mark.asyncio
async def test_changed_version_and_policy_rechecked_at_explicit_add(tmp_path):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        await prepare(screen, pilot)
        api.pod["metadata"]["resourceVersion"] = "changed-after-review"
        screen.add_button.press()
        await pilot.pause()
        await wait_for(lambda: not screen.busy)
        assert app.mutations.records[-1].result.state is MutationState.CONFLICT
        assert not patches(api, dry=False)
        screen.review_button.press()
        await wait_for(lambda: screen.review is not None and not screen.busy)
        app.commands.policy.tighten()
        screen.add()
        assert "policy changed" in str(screen.feedback.content)
        assert not patches(api, dry=False)
        await wait_for(lambda: app.ephemeral_debug_manager.active_count == 0)
        await pilot.press("escape")


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["policy", "context", "quit"])
async def test_active_terminal_drains_before_client_release_and_preserves_remote_entry(
    tmp_path, stop
):
    async with debug_app(tmp_path) as (app, api):
        existing(api)
        async with app.run_test() as pilot:
            screen = await open_debug(app)
            screen.attach_button.press()
            await wait_for(lambda: isinstance(app.screen, ShellScreen))
            terminal = app.screen
            await wait_for(lambda: (tmp_path / "debug-child-pid").exists())
            directory = Path(app.sessions.client.directory.name)
            if stop == "policy":
                app.commands.policy.tighten()
                await wait_for(lambda: terminal.stop_requested)
            elif stop == "context":
                app.workspace.connect("kuberich-test-Two")
            else:
                await pilot.press("ctrl+q")
            if stop != "quit":
                # Service retirement precedes the screen's final cleanup callback.
                await wait_for(
                    lambda: (
                        app.ephemeral_debug_manager.active_count == 0
                        and app.processes.active_count == 0
                        and app.retained_ephemeral_debug_view_count == 0
                    )
                )
                assert app.processes.active_count == 0
                assert app.retained_ephemeral_debug_view_count == 0
                await pilot.press("escape")
        assert app.ephemeral_debug_manager.active_count == 0
        assert app.retained_ephemeral_debug_view_count == 0
        assert app.sessions.client is None and app.processes.active_count == 0
        assert not list(directory.glob("exec-*.json"))
        pid = int((tmp_path / "debug-child-pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert screen.owner.operation_count == 0
        assert not patches(api) and len(api.pod["spec"]["ephemeralContainers"]) == 1


@pytest.mark.asyncio
async def test_repeated_cancel_retains_screen_until_sent_append_receipt_drains(
    tmp_path, monkeypatch
):
    entered, release = threading.Event(), threading.Event()
    original = DebugHandler.respond

    def respond(handler, payload=None, *, status=200):
        if handler.command == "PATCH" and "dryRun=All" not in handler.path:
            entered.set()
            assert release.wait(5)
        original(handler, payload, status=status)

    monkeypatch.setattr(DebugHandler, "respond", respond)
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        try:
            screen = await open_debug(app)
            await prepare(screen, pilot)
            screen.add_button.press()
            await wait_for(entered.is_set)
            directory = Path(app.sessions.client.directory.name)
            closing = asyncio.create_task(screen.stop_owned())
            await asyncio.sleep(0)
            await wait_for(lambda: screen.review_button.disabled and screen.add_button.disabled)
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            assert app.retained_ephemeral_debug_view_count == 1
            assert app.ephemeral_debug_manager.active_count == 1 and directory.is_dir()
            release.set()
            await closing
            await screen.stop_owned()
            assert app.retained_ephemeral_debug_view_count == 0
            assert app.ephemeral_debug_manager.active_count == 0
            assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
            assert len(patches(api, dry=False)) == 1
            await pilot.press("escape")
        finally:
            release.set()


@pytest.mark.asyncio
async def test_live_rows_update_and_disappear_without_moving_selected_name_or_scroll(tmp_path):
    async with debug_app(tmp_path) as (app, api):
        for number in range(20):
            existing(api, f"debug-{number:02}")
        async with app.run_test(size=(100, 30)) as pilot:
            screen = await open_debug(app)
            screen.table.focus()
            screen.table.move_cursor(row=12)
            screen.table.scroll_to(x=8, y=9, animate=False, immediate=True, force=True)
            await pilot.pause()
            selected, offset = screen.selected().name, screen.table.scroll_offset
            pod = copy.deepcopy(api.pod)
            pod["spec"]["ephemeralContainers"] = [
                entry for entry in pod["spec"]["ephemeralContainers"] if entry["name"] != "debug-04"
            ]
            pod["status"]["ephemeralContainerStatuses"] = [
                status
                for status in pod["status"]["ephemeralContainerStatuses"]
                if status["name"] != "debug-04"
            ]
            pod["status"]["ephemeralContainerStatuses"][0]["state"] = {
                "terminated": {"exitCode": 7, "reason": "Completed"}
            }
            pod["metadata"]["resourceVersion"] = "opaque/status-changed"
            api.pod = pod
            await screen.owner.observe()
            assert screen.table.row_count == 19
            assert "debug-04" not in screen.table.rows
            assert screen.table.get_cell("debug-00", "state").plain == "terminated"
            assert screen.table.get_cell("debug-00", "reason").plain == "Completed · exit 7"
            assert screen.selected().name == selected and screen.table.scroll_offset == offset
            assert not screen.attach_button.disabled
            assert not patches(api)
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_queued_option_change_is_rechecked_before_add_handler_delivery(tmp_path):
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        screen = await open_debug(app)
        await prepare(screen, pilot)
        review = screen.review
        screen.query_one("#debug-name", Input).value = "debug-edited-before-event"
        assert screen.review is review, "Input.Changed is still queued"
        screen.add()
        assert screen.review is None and screen.add_button.disabled
        assert "options, target or policy changed" in str(screen.feedback.content)
        assert not app.mutations.records and not patches(api, dry=False)
        await pilot.pause()
        assert not patches(api, dry=False)
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_escape_cancels_and_drains_attach_preparation_get(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    preparing, finished = asyncio.Event(), asyncio.Event()
    original_get, original_prepare = DebugHandler.do_GET, EphemeralDebugService.prepare_shell

    def held(handler):
        if preparing.is_set() and urlsplit(handler.path).path.endswith("/pods/debug-workload"):
            entered.set()
            assert release.wait(5)
        original_get(handler)

    async def prepare_shell(owner, name):
        preparing.set()
        try:
            return await original_prepare(owner, name)
        finally:
            finished.set()

    monkeypatch.setattr(DebugHandler, "do_GET", held)
    monkeypatch.setattr(EphemeralDebugService, "prepare_shell", prepare_shell)
    async with debug_app(tmp_path) as (app, api):
        existing(api)
        async with app.run_test() as pilot:
            try:
                screen = await open_debug(app)
                screen.attach_button.press()
                await wait_for(entered.is_set)
                await pilot.press("escape")
                assert finished.is_set() and len(app.screen_stack) == 1
                assert app.ephemeral_debug_manager.active_count == 0
                assert app.retained_ephemeral_debug_view_count == 0
                assert screen.owner.operation_count == 0
                assert app.processes.active_count == 0
                assert not (tmp_path / "debug-child-pid").exists()
                assert not patches(api)
            finally:
                release.set()


@pytest.mark.asyncio
async def test_stopped_before_queued_mount_never_subscribes_or_starts_an_owner(
    tmp_path, monkeypatch
):
    original_push, original_subscribe = KubeRichApp.push_screen, EphemeralDebugService.subscribe
    subscriptions = []

    def push(host, screen, *args, **kwargs):
        if isinstance(screen, EphemeralDebugScreen):
            screen.request_stop()
        return original_push(host, screen, *args, **kwargs)

    def subscribe(owner, listener):
        subscriptions.append(owner)
        return original_subscribe(owner, listener)

    monkeypatch.setattr(KubeRichApp, "push_screen", push)
    monkeypatch.setattr(EphemeralDebugService, "subscribe", subscribe)
    async with debug_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(
            lambda: app.state.status is ViewStatus.LIVE and app.state.selected is not None
        )
        await app.run_command(":debug")
        await wait_for(lambda: isinstance(app.screen, EphemeralDebugScreen))
        screen = app.screen
        await wait_for(lambda: app.ephemeral_debug_manager.active_count == 0)
        await pilot.pause()
        assert not subscriptions and screen.owner.operation_count == 0
        assert app.retained_ephemeral_debug_view_count == 0
        assert not any(
            request[0] == "GET" and request[1].endswith("/pods/debug-workload")
            for request in api.requests
        )
        assert not patches(api)
        await pilot.press("escape")
