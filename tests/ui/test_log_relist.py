"""Owned HTTP recovery distinguishes an unknown list prefix from lost Pod identity."""

import asyncio
import copy
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain import watches
from kuberich.domain.views import ViewStatus
from kuberich.errors import AppError
from kuberich.services.logs import LogStream
from kuberich.services.workspace import MAX_LOG_READS, ViewSubscription
from kuberich.ui.app import KubeRichApp
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.logs import LogScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workers import CoroutineCalls
from tests.support.workspace import wait_for, workspace_api

TARGET = "owned-selected"
POD_PATH = f"/api/v1/namespaces/team/pods/{TARGET}"
TARGET_UID = f"owned-{TARGET}"
EVIDENCE = Path(__file__).resolve().parents[2] / "artifacts/terminal/log-relist"


class RelistApi:
    def __init__(self, expiry="frame"):
        self.expiry = expiry
        self.selected = pod(TARGET)
        self.other = pod("owned-first")
        self.commands = asyncio.Queue()
        self.log_lines = asyncio.Queue()
        self.relisting = False
        self.mode = "paged"
        self.pod_status = 200
        self.replace_on_log_open = False
        self.watch_count = self.log_count = self.active = 0
        self.requests = []
        self.first_started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.release_second = asyncio.Event()
        self.closed = asyncio.Event()

    def release(self):
        self.closed.set()
        self.release_first.set()
        self.release_second.set()

    async def handler(self, request):
        self.requests.append((request.method, request.path, dict(request.query)))
        self.active += 1
        try:
            if request.path.endswith("/log"):
                self.log_count += 1
                if self.replace_on_log_open:
                    self.selected = pod(TARGET, uid="replacement-after-preflight")
                response = web.StreamResponse()
                await response.prepare(request)
                await response.write(b"initial-owned-line\n")
                while (
                    not self.closed.is_set()
                    and request.transport is not None
                    and not request.transport.is_closing()
                ):
                    try:
                        value = await asyncio.wait_for(self.log_lines.get(), 0.02)
                    except TimeoutError:
                        continue
                    await response.write(value)
                return response
            if request.path == POD_PATH:
                if self.pod_status != 200:
                    return web.Response(status=self.pod_status)
                return web.json_response(self.selected)
            if request.path == "/api/v1/namespaces/other/pods" and "watch" not in request.query:
                return web.json_response(collection())
            if "watch" in request.query:
                self.watch_count += 1
                if self.expiry == "http" and self.watch_count == 2:
                    self.relisting = True
                    return web.Response(status=410)
                response = web.StreamResponse()
                await response.prepare(request)
                while (
                    not self.closed.is_set()
                    and request.transport is not None
                    and not request.transport.is_closing()
                ):
                    try:
                        command = await asyncio.wait_for(self.commands.get(), 0.02)
                    except TimeoutError:
                        continue
                    if command == "expire":
                        if self.expiry == "frame":
                            self.relisting = True
                            await response.write(frame({"type": "ERROR", "object": {"code": 410}}))
                        return response
                    await response.write(frame(command))
                return response
            if not self.relisting:
                return web.json_response(collection(self.other, self.selected, rv="initial-list"))
            if request.query.get("continue") == "last-page":
                self.second_started.set()
                await self.release_second.wait()
                return web.json_response(collection(self.selected, rv="relisted"))
            self.first_started.set()
            await self.release_first.wait()
            if self.mode == "failed":
                return web.Response(status=403)
            if self.mode == "absent":
                return web.json_response(collection(self.other, rv="relisted"))
            if self.mode == "replacement-prefix":
                return web.json_response(
                    collection(
                        pod(TARGET, uid="replacement-on-first-page"),
                        rv="relisted",
                        token="last-page",
                    )
                )
            return web.json_response(collection(self.other, rv="relisted", token="last-page"))
        except ConnectionResetError:
            return web.Response()
        finally:
            self.active -= 1


@asynccontextmanager
async def opened_log(
    tmp_path, monkeypatch, expiry="frame", *, containers_first=False, read_only=True
):
    api = RelistApi(expiry)
    calls = CoroutineCalls()
    monkeypatch.setattr(LogStream, "run", calls.observe(LogStream.run))
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    EVIDENCE.mkdir(exist_ok=True, mode=0o700)
    directory = Path(tempfile.mkdtemp(prefix=tmp_path.name + "-", dir=EVIDENCE))
    directory.chmod(0o700)
    frames = []

    async def ns(request):
        return namespaces("team", "other")

    @asynccontextmanager
    async def audited_api():
        try:
            async with workspace_api(ns, api.handler) as url:
                yield url
        finally:
            cleanup = {
                "active_requests": api.active,
                "observed_readers": len(calls.tasks),
                "readers_drained": all(task.done() for task in calls.tasks),
                "registered_leases": app.workspace.log_read_count,
                "retained_log_screens": app.operations.retained_log_count,
            }
            path = directory / "cleanup.json"
            path.write_text(json.dumps(cleanup, indent=2) + "\n")
            path.chmod(0o600)
            assert api.active == 0 and cleanup["readers_drained"]
            assert cleanup["registered_leases"] == cleanup["retained_log_screens"] == 0

    async with audited_api() as url:
        app = KubeRichApp(
            Settings(read_only=read_only),
            logging.Logger("owned-log-relist", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        try:
            async with app.run_test(size=(100, 30)) as pilot:
                await wait_for(lambda: app.resources.row_count == 2)
                app.resources.move_cursor(row=app.resources.get_row_index(TARGET_UID))
                if containers_first:
                    await pilot.press("enter")
                    await wait_for(lambda: isinstance(app.screen, ContainerScreen))
                    await pilot.press("enter")
                else:
                    await pilot.press("l")
                await wait_for(lambda: isinstance(app.screen, LogScreen))
                screen = app.screen
                await wait_for(lambda: bool(screen.history.entries))
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)

                def capture(stage):
                    view = app.workspace.store.observation
                    snapshot = view.snapshot
                    frames.append(
                        {
                            "stage": stage,
                            "status": view.status.name,
                            "revision": view.revision,
                            "uids": None if snapshot is None else [r.uid for r in snapshot.items],
                            "complete": None if snapshot is None else snapshot.collection.complete,
                            "limited": None if snapshot is None else snapshot.collection.limited,
                            "target_uid": screen.stream.target.uid,
                            "current": screen.stream.current(),
                            "stale": screen.stale,
                            "message": screen.message,
                            "read_done": None if calls.latest is None else calls.latest.done(),
                            "log_count": api.log_count,
                            "registered_leases": app.workspace.log_read_count,
                            "history": [str(entry.line) for entry in screen.history.entries],
                        }
                    )
                    path = directory / f"{len(frames):02}-{stage}.svg"
                    path.write_text(app.export_screenshot())
                    path.chmod(0o600)

                capture("opened")
                try:
                    yield app, pilot, screen, api, calls, capture
                finally:
                    capture("final")
                    api.release()
        finally:
            api.release()
            (directory / "frames.json").write_text(json.dumps(frames, indent=2) + "\n")
            (directory / "api.json").write_text(json.dumps(api.requests, indent=2) + "\n")
            for path in directory.iterdir():
                path.chmod(0o600)
            print(f"Owned log relist evidence: {directory}")


@pytest.mark.asyncio
@pytest.mark.parametrize("expiry", ["frame", "http"])
@pytest.mark.parametrize("containers_first", [False, True])
async def test_same_uid_log_read_survives_empty_then_incomplete_relist(
    tmp_path, monkeypatch, expiry, containers_first
):
    async with opened_log(tmp_path, monkeypatch, expiry, containers_first=containers_first) as (
        app,
        pilot,
        screen,
        api,
        calls,
        capture,
    ):
        owner = calls.latest
        target = screen.stream.target
        await api.commands.put("expire")
        await asyncio.wait_for(api.first_started.wait(), 5)
        view = app.workspace.store.observation
        assert view.status is ViewStatus.RELISTING and view.snapshot is None
        capture("relisting-empty")
        assert not screen.stale and screen.stream.current()
        assert calls.latest is owner and owner is not None and not owner.done()
        await api.log_lines.put(b"during-empty-relist\n")
        await wait_for(
            lambda: any("during-empty-relist" in str(e.line) for e in screen.history.entries)
        )
        api.release_first.set()
        await asyncio.wait_for(api.second_started.wait(), 5)
        view = app.workspace.store.observation
        assert view.status is ViewStatus.LOADING and view.snapshot is not None
        assert not view.snapshot.collection.complete and not view.snapshot.collection.limited
        assert TARGET_UID not in {r.uid for r in view.snapshot.items}
        capture("incomplete-prefix")
        assert not screen.stale and screen.stream.current()
        await api.log_lines.put(b"during-incomplete-prefix\n")
        await wait_for(
            lambda: any("during-incomplete-prefix" in str(e.line) for e in screen.history.entries)
        )
        api.release_second.set()
        await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
        capture("complete-same-uid")
        assert screen.stream.target == target and target.uid == TARGET_UID
        assert screen.stream.current() and not screen.stale
        assert calls.latest is owner and not owner.done() and api.log_count == 1
        before = screen.wrap
        await pilot.press("w")
        await wait_for(lambda: screen.wrap is not before)
        await api.log_lines.put(b"after-complete-relist\n")
        await wait_for(
            lambda: any("after-complete-relist" in str(e.line) for e in screen.history.entries)
        )
        assert any("initial-owned-line" in str(e.line) for e in screen.history.entries)
        await pilot.press("escape")
        await wait_for(lambda: owner.done())
        if containers_first:
            assert isinstance(app.screen, ContainerScreen)
            assert app.workspace.log_read_count == 1 and app.screen.stream.current()
            await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1 and app.workspace.log_read_count == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["delete", "replacement", "complete-absence", "scope", "failed", "budget-eviction"]
)
async def test_log_recovery_never_keeps_a_known_lost_or_obsolete_target(
    tmp_path, monkeypatch, change
):
    async with opened_log(tmp_path, monkeypatch) as (app, pilot, screen, api, calls, capture):
        owner = calls.latest
        if change in {"complete-absence", "failed"}:
            api.mode = "absent" if change == "complete-absence" else "failed"
            api.release_first.set()
            await api.commands.put("expire")
            await asyncio.wait_for(api.first_started.wait(), 5)
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status
                    is (ViewStatus.FAILED if change == "failed" else ViewStatus.LIVE)
                )
            )
        elif change == "scope":
            app.workspace.select_namespace("other")
        else:
            value = copy.deepcopy(api.selected)
            if change == "replacement":
                value["metadata"]["uid"] = "replacement-uid"
                value["metadata"]["resourceVersion"] = "replacement-version"
                api.selected = value
            elif change == "budget-eviction":
                snapshot = app.workspace.store.observation.snapshot
                assert snapshot is not None
                monkeypatch.setattr(
                    watches, "MAX_RESOURCE_BYTES", snapshot.collection.retained_bytes + 10
                )
                value["metadata"]["resourceVersion"] = "over-budget-version"
                value["spec"]["owned-padding"] = "x" * 10_000
            await api.commands.put(
                {
                    "type": "DELETED" if change == "delete" else "MODIFIED",
                    "object": value,
                }
            )
        await wait_for(lambda: screen.stale)
        await wait_for(lambda: owner is not None and owner.done())
        capture("known-invalidated")
        if change == "budget-eviction":
            snapshot = app.workspace.store.observation.snapshot
            assert snapshot is not None and snapshot.collection.limited
            assert TARGET_UID not in {record.uid for record in snapshot.items}
        assert not screen.history.entries and not screen.body.rows
        assert not screen.stream.current() and "stale" in screen.message
        screen.action_copy()
        assert not app.clipboard
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_same_name_replacement_on_unfinished_first_page_revokes_the_read(
    tmp_path, monkeypatch
):
    async with opened_log(tmp_path, monkeypatch) as (app, _pilot, screen, api, calls, _capture):
        api.mode = "replacement-prefix"
        api.release_first.set()
        await api.commands.put("expire")
        await asyncio.wait_for(api.second_started.wait(), 5)
        await wait_for(lambda: screen.stale and calls.latest.done())
        view = app.workspace.store.observation
        assert not view.snapshot.collection.complete and not view.snapshot.collection.limited
        assert not screen.stream.current() and not screen.history.entries


@pytest.mark.asyncio
async def test_container_parent_keeps_its_read_lease_while_sibling_operations_remain_strict(
    tmp_path, monkeypatch
):
    async with opened_log(tmp_path, monkeypatch, containers_first=True, read_only=False) as (
        app,
        pilot,
        _screen,
        api,
        calls,
        _capture,
    ):
        await pilot.press("escape")
        await wait_for(lambda: calls.latest.done())
        parent = app.screen
        assert isinstance(parent, ContainerScreen)
        assert app.workspace.log_read_count == 1 and app.operations.retained_log_count == 1
        await api.commands.put("expire")
        await asyncio.wait_for(api.first_started.wait(), 5)
        assert parent.stream.current() and not parent.invalidated
        assert not parent.shell.current() and not parent.attach.current()
        assert not parent.transfers.current()
        before = len(api.requests)
        for key in ("s", "a", "u", "d", "e"):
            await pilot.press(key)
            assert app.screen is parent
        assert len(api.requests) == before and app.operations.retained_inspection_count == 0
        assert app.workspace.log_read_count == 1
        await pilot.press("enter")
        await wait_for(lambda: isinstance(app.screen, LogScreen))
        child = app.screen
        await wait_for(lambda: bool(child.history.entries))
        assert child.stream is parent.stream and child.stream.current()
        assert api.log_count == 2 and app.workspace.log_read_count == 1
        await pilot.press("escape")
        await wait_for(lambda: app.screen is parent and calls.latest.done())
        assert app.workspace.log_read_count == 1
        await pilot.press("escape")
        await wait_for(lambda: app.workspace.log_read_count == 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "replacement", "complete-absence", "budget-eviction"])
async def test_quiet_log_read_stays_revoked_when_ui_coalesces_later_presence(
    tmp_path, monkeypatch, change
):
    next_observation = ViewSubscription.__anext__
    holding = [False]
    entered, resume = asyncio.Event(), asyncio.Event()

    async def paused(subscription):
        observation = await next_observation(subscription)
        if holding[0]:
            entered.set()
            await resume.wait()
        return observation

    monkeypatch.setattr(ViewSubscription, "__anext__", paused)
    async with opened_log(tmp_path, monkeypatch) as (app, _pilot, screen, api, calls, capture):
        owner = calls.latest
        holding[0] = True
        other = copy.deepcopy(api.other)
        other["metadata"]["resourceVersion"] = "pause-ui"
        try:
            await api.commands.put({"type": "MODIFIED", "object": other})
            await asyncio.wait_for(entered.wait(), 5)
            if change == "complete-absence":
                api.mode = "absent"
                api.release_first.set()
                await api.commands.put("expire")
                await wait_for(
                    lambda: (
                        app.workspace.store.observation.status is ViewStatus.LIVE
                        and app.workspace.store.observation.snapshot is not None
                        and TARGET_UID
                        not in {r.uid for r in app.workspace.store.observation.snapshot.items}
                    )
                )
            else:
                value = copy.deepcopy(api.selected)
                if change == "replacement":
                    value["metadata"]["uid"] = "temporary-replacement"
                elif change == "budget-eviction":
                    snapshot = app.workspace.store.observation.snapshot
                    before_limit = watches.MAX_RESOURCE_BYTES
                    monkeypatch.setattr(
                        watches, "MAX_RESOURCE_BYTES", snapshot.collection.retained_bytes + 10
                    )
                    value["spec"]["owned-padding"] = "x" * 10_000
                value["metadata"]["resourceVersion"] = "contrary-evidence"
                await api.commands.put(
                    {"type": "DELETED" if change == "delete" else "MODIFIED", "object": value}
                )
                await wait_for(
                    lambda: (
                        TARGET_UID
                        not in {r.uid for r in app.workspace.store.observation.snapshot.items}
                    )
                )
                if change == "budget-eviction":
                    monkeypatch.setattr(watches, "MAX_RESOURCE_BYTES", before_limit)
            restored = copy.deepcopy(api.selected)
            restored["metadata"]["resourceVersion"] = "restored-presence"
            await api.commands.put({"type": "ADDED", "object": restored})
            await wait_for(
                lambda: any(
                    r.uid == TARGET_UID and r.resource_version == "restored-presence"
                    for r in app.workspace.store.observation.snapshot.items
                )
            )
            assert not screen.stale and owner is not None and not owner.done()
            assert not screen.stream.current()
            capture("revoked-before-ui-resume")
            resume.set()
            await wait_for(lambda: screen.stale and owner.done())
            assert not screen.history.entries and not screen.body.rows and api.log_count == 1
        finally:
            holding[0] = False
            resume.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("deleted", ["unrelated", "old-incarnation"])
async def test_unrelated_delete_preserves_the_captured_quiet_log_read(
    tmp_path, monkeypatch, deleted
):
    async with opened_log(tmp_path, monkeypatch) as (app, _pilot, screen, api, calls, capture):
        owner = calls.latest
        target = screen.stream.target
        record = copy.deepcopy(api.other if deleted == "unrelated" else api.selected)
        if deleted == "old-incarnation":
            record["metadata"]["uid"] = "older-pod-incarnation-uid"
        version = "accepted-delete-" + deleted
        record["metadata"]["resourceVersion"] = version
        await api.commands.put({"type": "DELETED", "object": record})
        await wait_for(lambda: app.workspace.store.observation.snapshot.resource_version == version)
        snapshot = app.workspace.store.observation.snapshot
        assert any(item.uid == TARGET_UID and item.name == TARGET for item in snapshot.items)
        assert screen.stream.target == target
        capture("accepted-" + deleted + "-delete")
        assert not screen.stale and screen.stream.current()
        marker = "after-" + deleted + "-delete"
        await api.log_lines.put((marker + "\n").encode())
        await wait_for(lambda: any(marker in str(e.line) for e in screen.history.entries))
        assert not screen.stale and screen.stream.current()
        assert calls.latest is owner and not owner.done() and api.log_count == 1


@pytest.mark.asyncio
async def test_log_registration_is_bounded_and_release_is_idempotent(tmp_path, monkeypatch):
    async with opened_log(tmp_path, monkeypatch) as (app, _pilot, screen, api, _calls, _capture):
        leases = []
        try:
            for _ in range(MAX_LOG_READS - 1):
                leases.append(
                    app.workspace.open_log_read(
                        screen.stream.client, screen.stream.target, lambda: True
                    )
                )
            assert app.workspace.log_read_count == MAX_LOG_READS
            with pytest.raises(AppError, match="Too many"):
                app.workspace.open_log_read(
                    screen.stream.client, screen.stream.target, lambda: True
                )
        finally:
            for lease in leases:
                lease.release()
                lease.release()
        assert app.workspace.log_read_count == 1
        await api.commands.put("expire")
        await asyncio.wait_for(api.first_started.wait(), 5)
        with pytest.raises(AppError, match="Select a current Pod"):
            app.workspace.open_log_read(screen.stream.client, screen.stream.target, lambda: True)
        assert app.workspace.log_read_count == 1 and screen.stream.current()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "race", ["before-open", "after-headers", "missing-container", "denied-get"]
)
async def test_fresh_log_open_during_unknown_membership_still_rejects_changed_target(
    tmp_path, monkeypatch, race
):
    async with opened_log(tmp_path, monkeypatch) as (_app, pilot, screen, api, calls, capture):
        owner = calls.latest
        await api.commands.put("expire")
        await asyncio.wait_for(api.first_started.wait(), 5)
        if race == "before-open":
            api.selected = pod(TARGET, uid="replacement-before-log-open")
        elif race == "after-headers":
            api.replace_on_log_open = True
        elif race == "missing-container":
            api.selected["spec"]["containers"] = []
        else:
            api.pod_status = 403
        await pilot.press("v")
        await wait_for(lambda: calls.latest is not owner and calls.latest.done())
        capture("fresh-open-rejected")
        assert not screen.history.entries and not screen.body.rows
        assert api.log_count == (2 if race == "after-headers" else 1)
        assert owner.done() and screen.message != "Receiving logs"


@pytest.mark.asyncio
@pytest.mark.parametrize("containers_first", [False, True])
async def test_failed_log_screen_creation_releases_its_registration(
    tmp_path, monkeypatch, containers_first
):
    async with opened_log(tmp_path, monkeypatch) as (app, pilot, _screen, api, calls, _capture):
        await pilot.press("escape")
        await wait_for(lambda: app.workspace.log_read_count == 0 and calls.latest.done())
        before = len(api.requests)

        def refused(*args, **kwargs):
            raise RuntimeError("controlled-owned-screen-open-failure")

        with monkeypatch.context() as patch:
            patch.setattr(app, "push_screen", refused)
            with pytest.raises(RuntimeError, match="controlled-owned-screen-open-failure"):
                app.operations.open_logs(uid=TARGET_UID, containers_first=containers_first)
        assert app.workspace.log_read_count == app.operations.retained_log_count == 0
        assert len(api.requests) == before and api.log_count == 1


@pytest.mark.asyncio
async def test_detached_log_view_remains_owned_until_client_cleanup_drains_it(
    tmp_path, monkeypatch
):
    async with opened_log(tmp_path, monkeypatch) as (app, pilot, screen, _api, calls, _capture):
        stop = screen.stop_owned
        entered, release = asyncio.Event(), asyncio.Event()
        stops = []

        async def held_stop():
            stops.append(True)
            entered.set()
            await release.wait()
            await stop()

        monkeypatch.setattr(screen, "stop_owned", held_stop)
        press = asyncio.create_task(pilot.press("escape"))
        closing = None
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await wait_for(lambda: screen not in app.screen_stack)
            assert app.workspace.log_read_count == app.operations.retained_log_count == 1
            closing = asyncio.create_task(app.operations.close_for_client(screen.stream.client))
            await wait_for(lambda: len(stops) == 2)
            release.set()
            await asyncio.wait_for(asyncio.gather(press, closing), 5)
            assert app.workspace.log_read_count == app.operations.retained_log_count == 0
            assert all(task.done() for task in calls.tasks)
        finally:
            release.set()
            for task in (press, closing):
                if task is not None:
                    task.cancel()
            await asyncio.gather(
                *(task for task in (press, closing) if task is not None), return_exceptions=True
            )
