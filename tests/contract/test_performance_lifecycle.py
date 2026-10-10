"""Repeated owned HTTP/process lifecycles measure resources rather than latency."""

import asyncio
import hashlib
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.port_forwards import ForwardState, parse_mappings
from kuberich.domain.views import ViewStatus
from kuberich.domain.watches import SyncStatus
from kuberich.services import watches
from kuberich.services.access import AccessPolicy
from kuberich.services.port_forwards import ForwardManager
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.watches import ListWatch
from kuberich.services.workspace import WorkspaceService
from tests.contract.test_performance_workload import workload
from tests.contract.test_port_forwards import state, unavailable
from tests.support.connections import catalog_fixture, namespaces
from tests.support.performance_terminal import require_normal_gc
from tests.support.port_forwards import manifest, source
from tests.support.resources import collection, item, pod_resource, reader_fixture
from tests.support.watches import event, frame
from tests.support.workspace import stable_watch, wait_for, workspace_api

ROOT = Path(__file__).resolve().parents[2]
WARMUP = 3
CYCLES = 36


def resources():
    directory = "/proc/self/fd" if sys.platform == "linux" else "/dev/fd"
    tasks = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
    return {
        "descriptors": len(os.listdir(directory)),
        "threads": len(threading.enumerate()),
        "tasks": len(tasks),
        "task_names": sorted(task.get_name() for task in tasks),
    }


async def warm_native_executor():
    """Populate the ordinary lazy worker pool without changing its capacity."""
    await asyncio.to_thread(lambda: None)
    executor = asyncio.get_running_loop()._default_executor
    capacity = executor._max_workers
    release = threading.Event()
    lock = threading.Lock()
    ready = threading.Event()
    started = 0

    def hold():
        nonlocal started
        with lock:
            started += 1
            if started == capacity:
                ready.set()
        assert release.wait(10)

    tasks = [asyncio.create_task(asyncio.to_thread(hold)) for _ in range(capacity)]
    try:
        await wait_for(ready.is_set)
    finally:
        release.set()
        await asyncio.gather(*tasks)
    assert len(executor._threads) == capacity and executor._work_queue.qsize() == 0
    return {"native_worker_capacity": capacity, "workers_populated": len(executor._threads)}


@contextmanager
def evidence(name):
    paths = [
        *sorted((ROOT / "src/kuberich").rglob("*.py")),
        Path(__file__),
        ROOT / "tests/support/connections.py",
        ROOT / "tests/support/resources.py",
        ROOT / "tests/support/port_forwards.py",
        ROOT / "tests/support/watches.py",
        ROOT / "tests/support/workspace.py",
        ROOT / "tests/support/performance_terminal.py",
        ROOT / "tests/support/performance_workload.py",
        ROOT / "tests/contract/test_port_forwards.py",
        ROOT / "tests/contract/test_performance_workload.py",
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    ]

    def inputs():
        return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    require_normal_gc()
    report = {
        "scenario": name,
        "python": sys.version,
        "platform": sys.platform,
        "warmup_cycles": WARMUP,
        "measured_cycles": CYCLES,
        "source_before": inputs(),
        "samples": [],
        "result": "failed",
        "scope": "owned lifecycle resource counts; not latency or sustained RSS qualification",
    }
    try:
        yield report
        report["source_after"] = inputs()
        assert report["source_after"] == report["source_before"]
        assert len(report["samples"]) == CYCLES
        report["result"] = "passed"
    except BaseException as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        report["source_after"] = inputs()
        folder = ROOT / "artifacts/backend"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"performance-lifecycle-{name}-{time.time_ns()}.json").write_text(
            json.dumps(report, indent=2)
        )


def sample(report, index, baseline, **facts):
    current = resources()
    if index < WARMUP:
        return current
    report["samples"].append({"cycle": index - WARMUP, **current, **facts})
    assert {k: current[k] for k in ("descriptors", "threads", "tasks")} == {
        k: baseline[k] for k in ("descriptors", "threads", "tasks")
    }, (baseline, current)
    return baseline


@pytest.mark.asyncio
async def test_repeated_context_churn_drains_live_forwards_and_coalesces_slow_subscriptions(
    tmp_path,
):
    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        namespace = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        if request.path.endswith("/pods/web"):
            return web.json_response(manifest())
        if "watch" in request.query:
            values = []
            for number in range(64):
                value = event("MODIFIED", f"load-{number % 40}", str(number), namespace=namespace)
                value["object"]["metadata"]["annotations"] = {"owned-large": "x" * 8192}
                values.append(value)
            return await stable_watch(request, *values)
        return web.json_response(
            collection(*(item(f"load-{n}", namespace=namespace) for n in range(40)))
        )

    with evidence("context-forward") as report:
        report["executor_warmup"] = await warm_native_executor()
        baseline = None
        async with ProcessRunner(AccessPolicy(False)) as runner:
            manager = ForwardManager(runner, check_interval=0.01)
            try:
                for index in range(WARMUP + CYCLES):
                    async with workspace_api(ns, handler) as url:
                        catalog = catalog_fixture(tmp_path, url)
                        before = (tmp_path / "fixture-config").read_bytes()
                        sessions = SessionService(catalog, ConnectionRequest())
                        sessions.before_close = manager.stop_for_client
                        owner = WorkspaceService(sessions)
                        subscription = owner.subscribe()
                        try:
                            await owner.connect("kuberich-test-one")
                            await wait_for(
                                lambda owner=owner: (
                                    owner.store.observation.status is ViewStatus.LIVE
                                    and owner.store.observation.snapshot.resource_version == "63"
                                )
                            )
                            client, watch = sessions.client, owner._watch
                            pool = client.api.rest_client.pool_manager
                            directory = Path(client.directory.name)
                            assert len(owner.store.observation.snapshot.items) == 40
                            assert subscription._pending is owner.store.observation
                            assert (await anext(subscription)) is owner.store.observation
                            identity = manager.start(
                                source(ResourceReader(client), tmp_path),
                                parse_mappings(":80"),
                            )
                            ready = await state(manager, identity, ForwardState.READY)
                            await owner.connect("kuberich-test-Two")
                            await wait_for(
                                lambda owner=owner: (
                                    owner.store.observation.status is ViewStatus.LIVE
                                    and owner.store.observation.snapshot.resource_version == "63"
                                )
                            )
                            assert watch.done() and pool.closed and not directory.exists()
                            assert (
                                await state(manager, identity, ForwardState.STOPPED)
                            ).message == ("Stopped for connection change.")
                            assert (
                                not manager._live
                                and manager.active_count == runner.active_count == 0
                            )
                            assert len(manager.infos) <= 32
                            assert subscription._pending is owner.store.observation
                            await unavailable(ready.ports[0].local)
                            with pytest.raises(ProcessLookupError):
                                os.kill(ready.pid, 0)
                            assert (tmp_path / "fixture-config").read_bytes() == before
                        finally:
                            await owner.close()
                        assert not owner._subscriptions and sessions.client is None
                        assert owner._watch is None and owner._operation is None
                        assert owner._discovery is None and subscription._pending is None
                        assert owner.store.observation.snapshot is None
                    baseline = sample(
                        report,
                        index,
                        baseline,
                        retained_forward_history=len(manager.infos),
                        active_forwards=manager.active_count,
                        active_processes=runner.active_count,
                        child_pid=ready.pid,
                        child_reaped=True,
                        source_kubeconfig_unchanged=True,
                    )
                assert len(manager.infos) == 32
            finally:
                await manager.close()
        report["after_close"] = {
            "active_processes": runner.active_count,
            "active_forwards": manager.active_count,
        }


@pytest.mark.asyncio
async def test_repeated_large_watch_slow_consumer_cancellation_has_no_parser_queue(
    tmp_path, monkeypatch
):
    parsed = 0
    original = watches.watch_event

    def observe(*args):
        nonlocal parsed
        parsed += 1
        return original(*args)

    monkeypatch.setattr(watches, "watch_event", observe)
    active = 0

    async def handler(request):
        nonlocal active
        if "watch" not in request.query:
            return web.json_response(collection(item()))
        response = web.StreamResponse()
        await response.prepare(request)
        active += 1
        try:
            value = event("MODIFIED")
            value["object"]["metadata"]["annotations"] = {"owned-large": "x" * 65536}
            encoded = frame(value)
            for _ in range(128):
                await response.write(encoded)
            while request.transport is not None and not request.transport.is_closing():
                await asyncio.sleep(0.005)
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            active -= 1
        return response

    with evidence("slow-watch") as report:
        report["executor_warmup"] = await warm_native_executor()
        baseline = None
        for index in range(WARMUP + CYCLES):
            started = asyncio.Event()
            before = parsed

            async def sink(update, started=started):
                if update.event:
                    started.set()
                    await asyncio.Event().wait()

            async with reader_fixture(tmp_path, handler) as reader:
                task = asyncio.create_task(ListWatch(reader).run(pod_resource(), "team", sink))
                try:
                    async with asyncio.timeout(5):
                        await started.wait()
                    await asyncio.sleep(0.03)
                    assert parsed == before + 1
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    assert not reader.session.api.rest_client.pool_manager.connector._acquired
                finally:
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
            assert active == 0
            baseline = sample(
                report,
                index,
                baseline,
                parsed_while_held=parsed - before,
                active_source_watches=active,
                watch_task_drained=task.done(),
            )


@pytest.mark.asyncio
async def test_repeated_startup_cancellation_reaps_children_and_private_configurations(tmp_path):
    async def handler(request):
        return web.json_response(manifest())

    with evidence("forward-startup") as report:
        report["executor_warmup"] = await warm_native_executor()
        baseline = None
        async with ProcessRunner(AccessPolicy(False)) as runner:
            manager = ForwardManager(runner, startup_timeout=5)
            try:
                for index in range(WARMUP + CYCLES):
                    pid_path = tmp_path / "forward-child.pid"
                    pid_path.unlink(missing_ok=True)
                    async with reader_fixture(tmp_path, handler) as reader:
                        directory = Path(reader.session.directory.name)
                        identity = manager.start(
                            source(reader, tmp_path, mode="silent"), parse_mappings(":80")
                        )
                        await wait_for(pid_path.exists)
                        pid = int(pid_path.read_text())
                        assert manager.active_count == runner.active_count == 1
                        closing = asyncio.create_task(manager.stop_for_client(reader.session))
                        await asyncio.sleep(0)
                        closing.cancel()
                        await asyncio.sleep(0)
                        closing.cancel()
                        with pytest.raises(asyncio.CancelledError):
                            await closing
                        assert (await state(manager, identity, ForwardState.STOPPED)).ports == ()
                        assert (
                            manager.active_count == runner.active_count == 0 and not manager._live
                        )
                        assert not list(directory.glob("forward-*.json"))
                        with pytest.raises(ProcessLookupError):
                            os.kill(pid, 0)
                    assert not directory.exists()
                    baseline = sample(
                        report,
                        index,
                        baseline,
                        active_forwards=manager.active_count,
                        active_processes=runner.active_count,
                        retained_forward_history=len(manager.infos),
                        child_pid=pid,
                        child_reaped=True,
                    )
                assert len(manager.infos) == 32
            finally:
                await manager.close()


@pytest.mark.asyncio
async def test_slow_snapshot_consumer_recovers_expired_bounded_source_through_real_list_watch(
    tmp_path,
):
    class Recovered(Exception):
        pass

    with evidence("expired-recovery") as report:
        report["executor_warmup"] = await warm_native_executor()
        baseline = None
        for index in range(WARMUP + CYCLES):
            # The same paced producer uses a small owned replay ring only for
            # this protocol regression; the measured 1,000-event ring is unchanged.
            async with workload(3, event_history=3) as (owned, http):
                catalog = catalog_fixture(tmp_path, str(http._base_url))
                config_before = (tmp_path / "fixture-config").read_bytes()
                client = KubernetesSession(catalog.select("kuberich-test-one"), 5)
                versions, statuses, problems = [], [], []

                async def sink(
                    update,
                    owned=owned,
                    http=http,
                    versions=versions,
                    statuses=statuses,
                    problems=problems,
                ):
                    statuses.append(update.status.name)
                    assert len(statuses) <= 8
                    if update.status is SyncStatus.RELISTING:
                        assert update.snapshot is None and update.problem.status == 410
                        problems.append(update.problem.status)
                    if update.status is SyncStatus.SNAPSHOT:
                        versions.append(update.snapshot.resource_version)
                        assert len(update.snapshot.items) == 3
                        if len(versions) == 1:
                            assert versions[0] == "q03/0"
                            async with http.post("/__q03/start") as response:
                                assert response.status == 200
                            await wait_for(lambda owned=owned: owned.serial >= 7)
                            async with http.post("/__q03/pause") as response:
                                assert response.status == 200
                            await wait_for(lambda owned=owned: all(t.done() for t in owned.workers))
                            assert owned.events.maxlen == len(owned.events) == 3
                    if update.status is SyncStatus.LIVE and len(versions) == 2:
                        assert versions[1] == f"q03/{owned.serial}" and versions[1] != versions[0]
                        assert problems == [410]
                        raise Recovered

                try:
                    await client.open()
                    async with asyncio.timeout(5):
                        with pytest.raises(Recovered):
                            await ListWatch(ResourceReader(client)).run(
                                pod_resource(), "team", sink
                            )
                    assert not client.api.rest_client.pool_manager.connector._acquired
                    await wait_for(lambda owned=owned: owned.stats["active_watches"] == 0)
                    assert owned.stats["expired_watch"] == 1
                    assert owned.snapshots == {}
                    assert list(owned.watch_versions) == versions
                    assert (tmp_path / "fixture-config").read_bytes() == config_before
                finally:
                    await client.close()
                source_after = owned.receipt()
            assert source_after["active_watches"] == source_after["active_logs"] == 0
            assert not any(not t.done() for t in owned.workers)
            baseline = sample(
                report,
                index,
                baseline,
                versions=versions,
                statuses=statuses,
                expired_watches=source_after["expired_watch"],
                fixture_replay_capacity=3,
                retained_replay_events=source_after["event_history"],
                source_workers_drained=True,
                recovered_rows=3,
                source_kubeconfig_unchanged=True,
            )


@pytest.mark.asyncio
async def test_resource_observer_sees_an_actual_held_descriptor_task_and_thread(tmp_path):
    before = resources()
    release = threading.Event()
    started = threading.Event()

    def hold():
        started.set()
        release.wait(5)

    thread = threading.Thread(target=hold, name="owned-lifecycle-negative")
    task = asyncio.create_task(asyncio.Event().wait(), name="owned-lifecycle-negative")
    try:
        thread.start()
        assert started.wait(1)
        with (tmp_path / "owned-descriptor").open("wb"):
            during = resources()
            assert during["descriptors"] == before["descriptors"] + 1
            assert during["threads"] == before["threads"] + 1
            assert during["tasks"] == before["tasks"] + 1
    finally:
        release.set()
        thread.join(1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not thread.is_alive() and resources() == before
