"""Production node-shell routes with owned HTTP, Pilot and an actual local PTY."""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web
from textual.widgets import Button, Static

from kuberich.adapters.node_shell_files import JournalLease, NodeShellJournal
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.domain.commands import Command
from kuberich.domain.mutations import MutationState
from kuberich.domain.node_shell_journal import JournalState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import ResourceCommand
from kuberich.services.node_shell import NodeShellManager, NodeShellState
from kuberich.services.node_shell_recovery import RecoveryJournalError
from kuberich.ui.app import KubeRichApp
from kuberich.ui.node_shell import NodeShellRecoveryScreen, NodeShellScreen
from kuberich.ui.terminal import ShellScreen
from tests.contract.test_node_shell import IMAGE, NodeApi
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, descriptor, legacy_roots
from tests.support.watches import frame
from tests.support.workspace import stable_watch, wait_for

CHILD = r"""
import os,tty
from pathlib import Path
root=Path(__file__).parent
tty.setraw(0)
(root/'node-child-pid').write_text(str(os.getpid()))
os.write(1,b'NODE REMOTE caf\xc3\xa9\r\n')
data=b''
while True:
    chunk=os.read(0,4096)
    data+=chunk
    (root/'node-input').write_bytes(data)
    if b'\x03' in chunk:
        os.write(1,b'REMOTE INTERRUPT\r\n')
    if b'exit\r' in data:
        break
"""


class NodeUIApi(NodeApi):
    def __init__(self):
        super().__init__()
        self.reads = []
        self.denied_node = False
        self.node_os = "linux"
        self.dry_run_status = 201
        self.node_updates = asyncio.Queue()
        self.node_gate = asyncio.Event()
        self.node_gate.set()
        self.node_requested = asyncio.Event()

    def node(self):
        return {
            "apiVersion": "v1",
            "kind": "Node",
            "metadata": {
                "name": "owned-node",
                "uid": self.node_uid,
                "resourceVersion": "node-version",
            },
            "status": {
                "nodeInfo": {"operatingSystem": self.node_os, "kubeletVersion": "v1.36.4"},
                "conditions": [{"type": "Ready", "status": "True"}],
            },
        }

    async def handle(self, request):
        self.reads.append((request.method, request.path))
        roots = legacy_roots()
        roots["/api/v1"]["resources"].append(descriptor("nodes", namespaced=False, kind="Node"))
        if request.path in roots:
            return web.json_response(roots[request.path])
        if request.path == "/api/v1/namespaces":
            return await stable_watch(request) if "watch" in request.query else namespaces("team")
        if request.path == "/api/v1/nodes":
            if "watch" in request.query:
                response = web.StreamResponse()
                await response.prepare(request)
                while request.transport is not None and not request.transport.is_closing():
                    try:
                        event = await asyncio.wait_for(self.node_updates.get(), 0.02)
                        await response.write(frame(event))
                    except TimeoutError:
                        continue
                return response
            return web.json_response({**collection(self.node()), "kind": "NodeList"})
        if request.path == "/api/v1/nodes/owned-node":
            self.node_requested.set()
            await self.node_gate.wait()
            return web.Response(status=403) if self.denied_node else web.json_response(self.node())
        if (
            request.method == "POST"
            and request.query.get("dryRun") == "All"
            and self.dry_run_status != 201
        ):
            return web.Response(status=self.dry_run_status, text="private-admission-policy-message")
        return await super().handle(request)


@asynccontextmanager
async def node_app(tmp_path, *, enabled=True, readonly=False, initial=None, api=None):
    api = api or NodeUIApi()
    server = web.Application()
    server.router.add_route("*", "/{path:.*}", api.handle)
    runner = web.AppRunner(server, shutdown_timeout=0.1)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    binary = tmp_path / "kubectl"
    binary.write_text(f"#!{sys.executable}\n" + CHILD)
    binary.chmod(0o700)
    document = parse_document(
        {
            "schema_version": 1,
            "node_shell": {"enabled": enabled, "image": IMAGE, "namespace": "team"},
        }
    )
    preferences = PreferenceSource(ConfigLocation(tmp_path / "preferences.yaml", True), document)
    manager = NodeShellManager(NodeShellJournal(tmp_path / "node-state"))
    app = KubeRichApp(
        Settings(read_only=readonly),
        logging.Logger("node-shell-ui", level=100),
        catalog=catalog_fixture(tmp_path, f"http://127.0.0.1:{runner.addresses[0][1]}"),
        preferences=preferences,
        node_shell_manager=manager,
        initial_command=initial or ResourceCommand(RESOURCE_ALIASES["node"]),
        environment={**os.environ, "PATH": str(tmp_path)},
        directory=tmp_path,
    )
    try:
        yield app, api
    finally:
        api.release.set()
        await manager.close()
        await runner.cleanup()


async def review(app):
    await app.run_command(":node-shell")
    await wait_for(lambda: isinstance(app.screen, NodeShellScreen))
    screen = app.screen
    await wait_for(lambda: screen.intent is not None or not screen.busy)
    return screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_default_cancel_exact_create_real_pty_and_uid_cleanup_retains_node(tmp_path, size):
    async with node_app(tmp_path) as (app, api):
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            viewport = app.standard_table.capture_viewport()
            screen = await review(app)
            assert app.focused is screen.query_one("#node-shell-cancel", Button)
            assert not api.posts and len(api.dry_runs) == 1
            preview = str(screen.query_one("#node-shell-profile", Static).content)
            for text in (
                "owned-node",
                IMAGE,
                "host PID",
                "/host",
                "host root",
                "no automatic chroot",
                "Token automount disabled; service links disabled",
            ):
                assert text in preview
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not api.posts and app.node_shell_manager.active_count == 0
            assert app.retained_node_shell_view_count == 0
            screen = await review(app)
            screen.create()
            screen.create()
            await wait_for(lambda: isinstance(app.screen, ShellScreen))
            terminal = app.screen
            await wait_for(
                lambda: "NODE REMOTE" in "\n".join(terminal.terminal.model.screen.display)
            )
            assert len(api.posts) == 1 and api.pod is not None
            assert "owned-node" in str(terminal.query_one("#shell-target", Static).content)
            assert "diagnostic" in str(terminal.query_one("#shell-heading", Static).content)
            await pilot.press("q", "ctrl+c")
            await wait_for(
                lambda: "REMOTE INTERRUPT" in "\n".join(terminal.terminal.model.screen.display)
            )
            assert app.is_running and app.screen is terminal
            await pilot.resize_terminal(80, 25)
            await pilot.press("ctrl+right_square_bracket")
            await wait_for(
                lambda: app.screen is screen and app.node_shell_manager.active_count == 0
            )
            assert api.pod is None and len(api.deletes) == 1
            assert api.deletes[0]["preconditions"] == {"uid": "returned-owned-uid"}
            assert await app.node_shell_manager.scan() == ()
            assert app.processes.active_count == 0
            assert app.node_shell_manager.records[-1].state is NodeShellState.CLOSED
            assert not list(Path(app.sessions.client.directory.name).glob("exec-*.json"))
            pid = int((tmp_path / "node-child-pid").read_text())
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
            await pilot.press("escape")
            await wait_for(lambda: app.retained_node_shell_view_count == 0)
            assert app.standard_table.capture_viewport() == viewport
        assert app.sessions.client is None and app.processes.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["disabled", "readonly", "windows", "denied", "admission"])
async def test_creation_prerequisites_fail_without_post_and_escape_drains(tmp_path, mode):
    api = NodeUIApi()
    api.node_os = "windows" if mode == "windows" else "linux"
    api.denied_node = mode == "denied"
    api.dry_run_status = 403 if mode == "admission" else 201
    async with (
        node_app(tmp_path, enabled=mode != "disabled", readonly=mode == "readonly", api=api) as (
            app,
            api,
        ),
        app.run_test() as pilot,
    ):
        await wait_for(lambda: app.standard_table.row_count == 1)
        await app.run_command(":node-shell")
        if mode in {"disabled", "readonly"}:
            assert len(app.screen_stack) == 1
            assert (
                "disabled" in str(app.status.content).lower()
                or "read-only" in str(app.status.content).lower()
            )
        else:
            await wait_for(lambda: isinstance(app.screen, NodeShellScreen))
            screen = app.screen
            await wait_for(lambda: not screen.busy)
            assert screen.intent is None
            assert "private-admission" not in str(
                screen.query_one("#node-shell-feedback", Static).content
            )
            await pilot.press("escape")
            await wait_for(lambda: app.retained_node_shell_view_count == 0)
        assert not api.posts and not api.deletes and app.node_shell_manager.active_count == 0


@pytest.mark.asyncio
async def test_recovery_initial_command_lists_local_state_without_connection(tmp_path):
    async with (
        node_app(tmp_path, initial=Command.NODE_SHELL_RECOVER) as (app, api),
        app.run_test() as pilot,
    ):
        await wait_for(
            lambda: isinstance(app.screen, NodeShellRecoveryScreen) and not app.screen.busy
        )
        assert app.sessions.client is None and api.reads == []
        assert app.screen.records == ()
        await pilot.press("escape")
        await wait_for(lambda: app.retained_node_shell_view_count == 0)


@pytest.mark.asyncio
async def test_priority_escape_drains_pending_ready_and_keeps_create_history_honest(tmp_path):
    api = NodeUIApi()
    api.ready = False
    async with node_app(tmp_path, api=api) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        screen.create()
        await wait_for(lambda: api.pod is not None)
        assert app.node_shell_manager.active_count == 1
        await pilot.press("escape")
        assert len(app.screen_stack) == 1 and app.retained_node_shell_view_count == 0
        assert api.pod is None and len(api.deletes) == 1
        assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
        assert app.node_shell_manager.records[-1].state is NodeShellState.CLOSED
        assert await app.node_shell_manager.scan() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", ["disabled", "readonly", "context", "node"])
async def test_live_exec_stops_and_uid_cleanup_finishes_on_owner_changes(tmp_path, stop):
    async with node_app(tmp_path) as (app, api), app.run_test():
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        screen.create()
        await wait_for(lambda: isinstance(app.screen, ShellScreen))
        terminal = app.screen
        await wait_for(lambda: (tmp_path / "node-child-pid").exists())
        if stop in {"disabled", "readonly"}:
            raw = {
                "schema_version": 1,
                "read_only": stop == "readonly",
                "node_shell": {"enabled": stop != "disabled", "image": IMAGE, "namespace": "team"},
            }
            app.live_preferences.adopt(parse_document(raw))
            assert terminal.stop_requested, "valid tightening stops remote input synchronously"
        elif stop == "context":
            app.workspace.connect("kuberich-test-Two")
        elif stop == "node":
            old = api.node()
            api.node_uid = "same-name-replacement"
            await api.node_updates.put({"type": "DELETED", "object": old})
            await api.node_updates.put({"type": "ADDED", "object": api.node()})
        await wait_for(lambda: app.node_shell_manager.active_count == 0)
        assert api.pod is None and len(api.posts) == 1 and len(api.deletes) == 1
        assert await app.node_shell_manager.scan() == ()
        assert app.processes.active_count == 0


@pytest.mark.asyncio
async def test_new_image_reload_invalidates_review_but_preserves_live_exec(tmp_path):
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        document = parse_document(
            {
                "schema_version": 1,
                "node_shell": {
                    "enabled": True,
                    "image": "fixture/new@sha256:" + "b" * 64,
                    "namespace": "team",
                },
            }
        )
        app.live_preferences.adopt(document)
        await wait_for(lambda: app.node_shell_manager.active_count == 0)
        screen.create()
        assert not api.posts
        await pilot.press("escape")
        screen = await review(app)
        screen.create()
        await wait_for(lambda: isinstance(app.screen, ShellScreen))
        terminal = app.screen
        await wait_for(lambda: (tmp_path / "node-child-pid").exists())
        app.live_preferences.adopt(
            parse_document(
                {
                    "schema_version": 1,
                    "node_shell": {
                        "enabled": True,
                        "image": IMAGE,
                        "namespace": "team",
                        "limits": {"cpu": "500m", "memory": "256Mi"},
                    },
                }
            )
        )
        assert not terminal.stop_requested
        assert app.node_shell_manager.active_count == 1
        await pilot.press(*"exit", "enter")
        await wait_for(lambda: app.screen is screen and app.node_shell_manager.active_count == 0)
        assert api.pod is None and len(api.posts) == 1


@pytest.mark.asyncio
async def test_quit_drains_node_exec_before_client_and_private_directory_close(tmp_path):
    async with node_app(tmp_path) as (app, api):
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            screen = await review(app)
            screen.create()
            await wait_for(lambda: isinstance(app.screen, ShellScreen))
            await wait_for(lambda: (tmp_path / "node-child-pid").exists())
            await pilot.press("ctrl+q")
        assert app.node_shell_manager.active_count == 0
        assert app.retained_node_shell_view_count == 0
        assert api.pod is None and len(api.deletes) == 1
        assert app.sessions.client is None and app.processes.active_count == 0
        pid = int((tmp_path / "node-child-pid").read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


async def pending_record(app, api, pilot, *, unknown=False):
    screen = await review(app)
    api.mode = "drop" if unknown else "normal"
    api.delete_status = 403
    screen.create()
    if unknown:
        await wait_for(lambda: app.node_shell_manager.active_count == 0)
    else:
        await wait_for(lambda: isinstance(app.screen, ShellScreen))
        await pilot.press("ctrl+right_square_bracket")
        await wait_for(lambda: app.screen is screen and app.node_shell_manager.active_count == 0)
    await pilot.press("escape")
    await wait_for(lambda: len(app.screen_stack) == 1)
    return (await app.node_shell_manager.scan())[0]


async def recovery(app):
    await app.run_command(":node-shell-recover")
    await wait_for(lambda: isinstance(app.screen, NodeShellRecoveryScreen) and not app.screen.busy)
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_recovery_known_uid_requires_default_cancel_then_exact_cleanup(tmp_path, size):
    async with node_app(tmp_path) as (app, api), app.run_test(size=size) as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        record = await pending_record(app, api, pilot)
        assert record.pod_uid == "returned-owned-uid" and len(api.deletes) == 1
        screen = await recovery(app)
        assert app.focused is screen.cancel_button and screen.records == (record,)
        screen.inspect()
        await wait_for(lambda: not screen.busy)
        assert "present_owned" in str(screen.feedback.content)
        assert len(api.deletes) == 1
        screen.cleanup()
        await wait_for(lambda: screen.review is not None)
        assert app.focused is screen.cancel_button and len(api.deletes) == 1
        await pilot.press("enter")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert api.pod is not None and len(api.deletes) == 1
        screen = await recovery(app)
        screen.cleanup()
        await wait_for(lambda: screen.review is not None)
        api.delete_status = 200
        screen.confirm()
        screen.confirm()
        await wait_for(lambda: not screen.busy)
        assert api.pod is None and len(api.deletes) == 2
        assert api.deletes[-1]["preconditions"] == {"uid": record.pod_uid}
        assert screen.records == () and app.pending_node_shell_record_count == 0
        await pilot.press("escape")
        assert app.retained_node_shell_view_count == 0


@pytest.mark.asyncio
async def test_unknown_create_stays_unowned_and_local_forget_works_read_only(tmp_path):
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        record = await pending_record(app, api, pilot, unknown=True)
        assert record.pod_uid is None and api.pod is not None and api.deletes == []
        app.commands.policy.tighten()
        screen = await recovery(app)
        screen.cleanup()
        await wait_for(lambda: not screen.busy)
        assert screen.review is None and api.deletes == []
        screen.inspect()
        await wait_for(lambda: not screen.busy)
        assert "present_unowned" in str(screen.feedback.content)
        screen.forget()
        await wait_for(lambda: screen.review is not None)
        assert screen.review.action == "forget" and app.focused is screen.cancel_button
        assert "No remote Pod" in str(screen.preview.content)
        screen.confirm()
        screen.confirm()
        await wait_for(lambda: not screen.busy)
        assert screen.records == () and "no remote Pod" in str(screen.feedback.content)
        assert api.pod is not None and api.deletes == [] and len(api.posts) == 1
        assert await app.node_shell_manager.scan() == ()
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_journal_failure_after_create_drains_then_reaches_fatal_boundary(
    tmp_path, monkeypatch
):
    original = JournalLease.write

    async def fail_owned(lease, record):
        if record.state is JournalState.OWNED:
            raise AppError("synthetic-private-journal-detail")
        await original(lease, record)

    monkeypatch.setattr(JournalLease, "write", fail_owned)
    async with node_app(tmp_path) as (app, api):
        with pytest.raises(AppError, match="ownership persistence failed"):
            async with app.run_test():
                await wait_for(lambda: app.standard_table.row_count == 1)
                screen = await review(app)
                screen.create()
                await wait_for(
                    lambda: len(api.posts) == 1 and app.node_shell_manager.active_count == 0
                )
        assert api.pod is None and len(api.deletes) == 1
        assert app.processes.active_count == 0 and not (tmp_path / "node-child-pid").exists()


@pytest.mark.asyncio
async def test_recovery_local_unlink_durability_failure_is_fatal_after_drain(tmp_path, monkeypatch):
    original = JournalLease.remove

    async def fail_after_unlink(lease, operation_id):
        await original(lease, operation_id)
        raise AppError("synthetic-private-unlink-detail")

    async with node_app(tmp_path) as (app, api):
        with pytest.raises(RecoveryJournalError, match="journal durability failed"):
            async with app.run_test() as pilot:
                await wait_for(lambda: app.standard_table.row_count == 1)
                await pending_record(app, api, pilot, unknown=True)
                screen = await recovery(app)
                screen.forget()
                await wait_for(lambda: screen.review is not None)
                monkeypatch.setattr(JournalLease, "remove", fail_after_unlink)
                screen.confirm()
                await wait_for(lambda: not screen.busy)
        assert api.pod is not None and api.deletes == []
        assert app.processes.active_count == 0 and app.retained_node_shell_view_count == 0


@pytest.mark.asyncio
async def test_escape_cancels_and_drains_held_preflight_without_create(tmp_path):
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        api.node_gate.clear()
        await app.run_command(":node-shell")
        await wait_for(lambda: api.node_requested.is_set())
        screen = app.screen
        screen.create()
        assert not api.posts
        await pilot.press("escape")
        assert len(app.screen_stack) == 1 and app.retained_node_shell_view_count == 0
        assert app.node_shell_manager.active_count == 0 and not api.posts
        api.node_gate.set()


@pytest.mark.asyncio
async def test_confirmation_checks_policy_before_any_create_even_without_observation(tmp_path):
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        app.commands.policy.tighten()
        screen.create()
        assert "policy changed" in str(screen.feedback.content)
        assert not api.posts
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_shell_revalidation_failure_cleans_owned_uid_without_opening_terminal(
    tmp_path, monkeypatch
):
    from kuberich.services.node_shell import NodeShellService

    original = NodeShellService.shell

    async def replace_before_exec(owner):
        owner.current = lambda: False
        return await original(owner)

    monkeypatch.setattr(NodeShellService, "shell", replace_before_exec)
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        screen = await review(app)
        screen.create()
        await wait_for(lambda: not screen.busy)
        assert app.screen is screen and api.pod is None and len(api.deletes) == 1
        assert "review again" in str(screen.feedback.content)
        assert not (tmp_path / "node-child-pid").exists()
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_recovery_empty_actions_and_reload_keep_local_state(tmp_path):
    async with (
        node_app(tmp_path, initial=Command.NODE_SHELL_RECOVER) as (app, api),
        app.run_test() as pilot,
    ):
        await wait_for(
            lambda: isinstance(app.screen, NodeShellRecoveryScreen) and not app.screen.busy
        )
        screen = app.screen
        screen.inspect()
        assert "Select a local" in str(screen.feedback.content)
        screen.reload()
        screen.inspect()
        await wait_for(lambda: not screen.busy)
        assert screen.records == () and api.reads == []
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_recovery_reload_preserves_selection_and_tightening_invalidates_cleanup_review(
    tmp_path,
):
    async with node_app(tmp_path) as (app, api), app.run_test() as pilot:
        await wait_for(lambda: app.standard_table.row_count == 1)
        record = await pending_record(app, api, pilot)
        screen = await recovery(app)
        screen.reload()
        await wait_for(lambda: not screen.busy)
        assert screen.selected() == record
        screen.cleanup()
        await wait_for(lambda: screen.review is not None)
        app.commands.policy.tighten()
        screen.validate_target()
        assert screen.review is None and screen.confirm_button.disabled
        screen.confirm()
        assert len(api.deletes) == 1
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_corrupt_local_journal_surfaces_on_startup_and_recovery_without_connection(tmp_path):
    async with node_app(tmp_path, initial=Command.NODE_SHELL_RECOVER) as (app, api):
        directory = tmp_path / "node-state"
        directory.mkdir(mode=0o700)
        record = directory / ("a" * 32 + ".json")
        record.write_text("corrupt-owned-metadata")
        record.chmod(0o600)
        async with app.run_test() as pilot:
            await wait_for(
                lambda: isinstance(app.screen, NodeShellRecoveryScreen) and not app.screen.busy
            )
            assert "recovery" in str(app.screen.feedback.content).lower()
            assert app.sessions.client is None and api.reads == []
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_terminal_cleanup_journal_failure_is_fatal_after_remote_absence(
    tmp_path, monkeypatch
):
    original = JournalLease.remove

    async def fail_after_remove(lease, operation_id):
        await original(lease, operation_id)
        raise AppError("synthetic-private-cleanup-detail")

    async with node_app(tmp_path) as (app, api):
        with pytest.raises(AppError, match="ownership persistence failed"):
            async with app.run_test() as pilot:
                await wait_for(lambda: app.standard_table.row_count == 1)
                screen = await review(app)
                screen.create()
                await wait_for(lambda: isinstance(app.screen, ShellScreen))
                await wait_for(lambda: (tmp_path / "node-child-pid").exists())
                monkeypatch.setattr(JournalLease, "remove", fail_after_remove)
                await pilot.press("ctrl+right_square_bracket")
                await wait_for(lambda: app.node_shell_manager.active_count == 0)
        assert api.pod is None and len(api.deletes) == 1 and app.processes.active_count == 0


@pytest.mark.asyncio
async def test_disabled_readonly_startup_record_can_be_forgotten_without_connection(tmp_path):
    from kuberich.domain.node_shell_journal import JournalRecord

    async with node_app(
        tmp_path, enabled=False, readonly=True, initial=Command.NODE_SHELL_RECOVER
    ) as (app, api):
        record = JournalRecord(
            operation_id="c" * 32,
            state=JournalState.CREATE_UNCERTAIN,
            context="kuberich-test-one",
            connection_fingerprint="d" * 64,
            namespace="team",
            namespace_uid="original-namespace",
            node_name="owned-node",
            node_uid="original-node",
            pod_name="kuberich-node-shell-" + "c" * 32,
            pod_uid=None,
            image_digest="a" * 64,
            created_at=1,
            updated_at=1,
            result_code="create_uncertain",
        )
        lease = await app.node_shell_manager.journal.acquire()
        try:
            await lease.write(record)
        finally:
            await lease.close()
        async with app.run_test() as pilot:
            await wait_for(
                lambda: isinstance(app.screen, NodeShellRecoveryScreen) and not app.screen.busy
            )
            screen = app.screen
            assert screen.records == (record,) and app.pending_node_shell_record_count == 1
            screen.inspect()
            await wait_for(lambda: not screen.busy)
            assert "explicitly connect" in str(screen.feedback.content)
            screen.forget()
            await wait_for(lambda: screen.review is not None)
            screen.confirm()
            await wait_for(lambda: not screen.busy)
            assert screen.records == () and api.reads == [] and app.sessions.client is None
            await pilot.press("escape")
            await app.run_command(":node-shell")
            assert len(app.screen_stack) == 1
