"""Real HTTP concurrency, UID churn, source isolation and drained aggregate ownership."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from itertools import pairwise

import pytest
from aiohttp import web

from kuberich.domain.aggregate_logs import AggregateHistory
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.logs import LogOptions
from kuberich.domain.resources import ApiResource
from kuberich.errors import AppError
from kuberich.services.aggregate_logs import AggregateLogs
from tests.support.aggregate_logs import PODS, AggregateApi, reference, workload
from tests.support.backend_heartbeat import HeartbeatDiagnostic, write_heartbeat_diagnostic
from tests.support.resources import reader_fixture
from tests.support.workspace import wait_for


async def finish(owner, task, api):
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await owner.close()
    await wait_for(lambda: api.active == 0 and api.watch_active == 0)
    assert not owner._owned and all(
        state.task is None or state.task.done() for state in owner.states.values()
    )


@pytest.mark.asyncio
async def test_real_eight_reader_admission_waiting_selection_filter_eof_and_explicit_reopen(
    tmp_path,
):
    api = AggregateApi(count=10)
    api.eof.add(("pod-00", "app"))
    api.denied.add(("pod-01", "app"))
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        try:
            await wait_for(
                lambda: (
                    len(owner.states) == 10
                    and sum(state.status == "active" for state in owner.states.values()) == 8
                )
            )
            await wait_for(lambda: api.active == 8)
            assert api.peak <= 8
            await wait_for(lambda: owner.states["owned-pod-00", "app"].status == "ended")
            assert owner.states["owned-pod-01", "app"].status == "failed"
            assert api.requests["pod-00", "app"] == 1 and api.requests["pod-01", "app"] == 1
            with pytest.raises(AppError, match="at most eight"):
                owner.choose(frozenset(owner.states))
            with pytest.raises(AppError, match="at most eight"):
                owner.choose(frozenset({("unknown", "app")}))
            selected = ("owned-pod-09", "app")
            owner.choose(frozenset({selected}))
            await wait_for(lambda: api.active == 1)
            assert owner.states[selected].status == "active"
            before = api.requests.copy()
            history.filter = selected
            assert "pod-09" in history.export() and "pod-08" not in history.export()
            await asyncio.sleep(0.05)
            assert api.requests == before  # Display filtering makes zero reader requests.
            owner.choose(frozenset({("owned-pod-00", "app")}))
            await wait_for(lambda: api.active == 0)
            assert api.requests["pod-00", "app"] == 1
            owner.choose(frozenset({("owned-pod-00", "app")}), reopen=True)
            await wait_for(lambda: api.requests["pod-00", "app"] == 2)
            owner.choose(None)
            await wait_for(lambda: api.active > 0)
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_live_regular_init_ephemeral_add_remove_same_name_recreation_and_late_output(
    tmp_path,
):
    api = AggregateApi(count=1)
    value = api.pods["pod-00"]
    value["spec"]["initContainers"] = [{"name": "init"}]
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()
        blocked, release = asyncio.Event(), asyncio.Event()

        async def retain(source, number, line):
            if "held-late" in line.text:
                blocked.set()
                await release.wait()
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        try:
            await wait_for(lambda: api.active == 2)
            value = deepcopy(value)
            value["spec"]["ephemeralContainers"] = [{"name": "debug"}]
            await api.update("MODIFIED", value)
            await wait_for(lambda: api.active == 3)
            await api.emit("pod-00", "app", b"held-late\n")
            await wait_for(blocked.is_set)
            old_number = owner.states["owned-pod-00", "app"].number
            await api.update("DELETED", value)
            replacement = deepcopy(value)
            replacement["metadata"]["uid"] = "replacement-pod"
            await api.update("ADDED", replacement)
            await wait_for(lambda: ("owned-pod-00", "app") not in owner.states)
            release.set()
            await wait_for(lambda: ("replacement-pod", "app") in owner.states and api.active == 3)
            await wait_for(lambda: "replacement-pod" in history.export())
            assert "held-late" not in history.export()
            assert (
                "owned-pod-00" in history.export()
                and owner.states["replacement-pod", "app"].number != old_number
            )
            assert len(owner.retired) == 3 and all(state.task.done() for state in owner.retired)
            replacement["spec"]["initContainers"] = []
            await api.update("MODIFIED", replacement)
            await wait_for(lambda: api.active == 2)
        finally:
            release.set()
            await finish(owner, task, api)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["context", "resource", "group", "kind", "scope", "verbs", "container"]
)
async def test_mismatched_capture_refuses_before_any_transport(tmp_path, mismatch):
    api, requests = AggregateApi(), []

    async def handler(request):
        requests.append(request.path)
        return await api.handler(request)

    async with reader_fixture(tmp_path, handler) as reader:
        owner = api.owner(reader)
        target, resource = owner.target, owner.resource
        if mismatch == "context":
            target = replace(target, session=replace(target.session, context="other"))
        elif mismatch == "container":
            target = replace(target, container="app")
        else:
            resource = replace(
                resource,
                **{
                    "resource": {"name": "jobs"},
                    "group": {"group": "wrong"},
                    "kind": {"kind": "Wrong"},
                    "scope": {"namespaced": False},
                    "verbs": {"verbs": frozenset({"get"})},
                }[mismatch],
            )
        with pytest.raises(AppError, match="captured client"):
            AggregateLogs(reader.session, resource, target, owner.policy, lambda: True)
        assert not requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "group,name,kind,middle_name,middle_kind",
    [
        ("apps", "deployments", "Deployment", "replicasets", "ReplicaSet"),
        ("batch", "cronjobs", "CronJob", "jobs", "Job"),
    ],
)
async def test_live_intermediate_ownership_uid_replacement_and_no_hidden_replay(
    tmp_path, group, name, kind, middle_name, middle_kind
):
    resource = ApiResource(group, "v1", name, kind, True, PODS.verbs)
    middle_resource = ApiResource(group, "v1", middle_name, middle_kind, True, PODS.verbs)
    api = AggregateApi(resource=resource, count=1)
    middle = workload(middle_resource, "middle", "middle-uid", [reference(api.parent)])
    api.collections[middle_name] = {"middle": middle}
    api.resources[middle_name] = middle_resource
    api.pods["pod-00"]["metadata"]["ownerReferences"] = [reference(middle)]
    unrelated = deepcopy(api.pods["pod-00"])
    unrelated["metadata"].update(name="lookalike", uid="lookalike-uid", labels={"app": "workload"})
    unrelated["metadata"]["ownerReferences"][0]["uid"] = "wrong-middle"
    api.pods["lookalike"] = unrelated
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        try:
            await wait_for(lambda: api.active == 1 and api.watch_active == 2)
            assert not api.requests["lookalike", "app"]
            await api.update("DELETED", middle, resource=middle_name)
            await wait_for(lambda: api.active == 0 and not owner.states)
            await api.update("ADDED", middle, resource=middle_name)
            await wait_for(lambda: len(owner.states) == 1)
            assert owner.states["owned-pod-00", "app"].status == "ended"
            assert api.requests["pod-00", "app"] == 1
            owner.choose(frozenset(owner.states), reopen=True)
            await wait_for(lambda: api.active == 1)
            replacement = deepcopy(middle)
            replacement["metadata"]["uid"] = "replacement-middle"
            await api.update("DELETED", middle, resource=middle_name)
            await api.update("ADDED", replacement, resource=middle_name)
            await wait_for(lambda: api.active == 0)
            assert "lookalike" not in history.export()
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_many_tiny_lines_slow_source_heartbeat_and_two_levels_of_retention(tmp_path):
    api = AggregateApi(count=2)
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner = api.owner(reader)
        history = AggregateHistory(
            max_lines=600, max_bytes=262144, source_lines=300, source_bytes=65536
        )
        heartbeats, late_received = [], asyncio.Event()
        received = 0

        async def retain(source, number, line):
            nonlocal received
            owner.require_source(source, number)
            history.retain(source, number, line)
            received += 1
            if "slow-source-live" in line.text:
                late_received.set()

        async def heartbeat():
            while True:
                heartbeats.append(asyncio.get_running_loop().time())
                await asyncio.sleep(0.005)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        pulse = asyncio.create_task(heartbeat())
        diagnostic = HeartbeatDiagnostic(asyncio.get_running_loop().time)
        try:
            with diagnostic:
                await wait_for(lambda: api.active == 2)
                await api.emit("pod-00", "app", b"x\n" * 32768)
                await api.emit("pod-01", "app", b"slow-source-live\n")
                await wait_for(late_received.is_set)
                async with asyncio.timeout(30):
                    while received < 32770:
                        await asyncio.sleep(0.005)
                assert len(history.records) <= 600 and history.buffer.size_bytes <= 262144
                assert all(len(numbers) <= 300 for numbers in history.by_source.values())
                assert all(size <= 65536 for size in history.sizes.values())
                assert len(heartbeats) > 3
                assert max(b - a for a, b in pairwise(heartbeats)) < 0.15
        finally:
            pulse.cancel()
            await asyncio.gather(pulse, return_exceptions=True)
            try:
                await finish(owner, task, api)
            finally:
                write_heartbeat_diagnostic(
                    diagnostic,
                    heartbeats,
                    {
                        "received_lines": received,
                        "slow_source_received": late_received.is_set(),
                        "retained_lines": len(history.records),
                        "retained_bytes": history.buffer.size_bytes,
                        "per_source_lines": list(map(len, history.by_source.values())),
                        "per_source_bytes": list(history.sizes.values()),
                        "after_close": {
                            "owner_tasks": len(owner._owned),
                            "api_log_streams": api.active,
                            "api_watches": api.watch_active,
                        },
                    },
                )


@pytest.mark.asyncio
async def test_manual_empty_admission_uid_churn_and_bounded_removed_metadata(tmp_path):
    api = AggregateApi(count=1)
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory(max_lines=4)

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        try:
            await wait_for(lambda: api.active == 1)
            owner.choose(frozenset(owner.states))
            value = deepcopy(api.pods["pod-00"])
            for index in range(70):
                await api.update("DELETED", value)
                await wait_for(lambda: not owner.states and api.active == 0)
                assert owner.selected == frozenset()
                value["metadata"]["uid"] = f"replacement-{index}"
                await api.update("ADDED", value)
                await wait_for(lambda: bool(owner.states))
                assert api.active == 0 and owner.selected == frozenset()
                owner.choose(frozenset(owner.states))
                await wait_for(lambda: api.active == 1)
                await wait_for(lambda index=index: f"replacement-{index}" in history.export())
            assert len(owner.states) == 1 and len(owner.retired) == 64
            assert all(state.task.done() for state in owner.retired)
            assert len(history.records) <= 4 and len(history.by_source) <= 4
            assert "replacement-69" in history.export()
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_excess_catalogue_refuses_without_opening_any_reader(tmp_path):
    api = AggregateApi(count=257)
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner = api.owner(reader)

        async def retain(source, number, line):
            pytest.fail("An excess catalogue must refuse admission before log delivery")

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        with pytest.raises(AppError, match="exceeds 256 sources"):
            await task
        assert owner.excess == 1 and not owner.states and not api.requests
        await finish(owner, task, api)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["uid", "name", "stale"])
async def test_parent_or_generation_replacement_refuses_before_membership(tmp_path, change):
    api, paths = AggregateApi(), []

    async def handler(request):
        paths.append(request.path)
        return await api.handler(request)

    async with reader_fixture(tmp_path, handler) as reader:
        owner = api.owner(reader, current=lambda: change != "stale")
        if change != "stale":
            api.parent["metadata"][change] = "replacement"

        async def retain(source, number, line):
            pytest.fail("A replaced parent must not deliver logs")

        with pytest.raises((AppError, ConnectionProblem)):
            await owner.run(LogOptions(), retain, lambda message: None)
        assert len(paths) == (0 if change == "stale" else 1)
        assert not api.requests and not owner._owned
        await owner.close()


@pytest.mark.asyncio
async def test_per_source_head_snapshot_and_running_owner_cannot_restart(tmp_path):
    api = AggregateApi(count=2)
    for index in range(2):
        api.initial[f"pod-{index:02}", "app"] = b"first\nsecond\nthird\n"
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(
            owner.run(LogOptions(), retain, lambda message: None, head_lines=2)
        )
        try:
            await wait_for(lambda: len(owner.states) == 2 and api.active == 0)
            await wait_for(lambda: len(history.records) == 4)
            assert all(state.status == "ended" for state in owner.states.values())
            assert "third" not in history.export()
            with pytest.raises(AppError, match="already running"):
                await owner.run(LogOptions(), retain, lambda message: None)
            owner.choose(None)
            await asyncio.sleep(0.02)
            assert sum(api.requests.values()) == 2
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_pending_regular_init_ephemeral_start_evidence_and_preopen_400_no_replay(tmp_path):
    api = AggregateApi(count=1)
    value = api.pods["pod-00"]
    value["spec"].update(initContainers=[{"name": "init"}], ephemeralContainers=[{"name": "debug"}])
    value["status"] = {
        "phase": "Pending",
        "containerStatuses": [{"name": "app", "state": {"waiting": {"reason": "PodInitializing"}}}],
    }
    preopen = True
    rejected = 0

    async def handler(request):
        nonlocal rejected
        if request.path.endswith("/log") and request.query["container"] == "app" and preopen:
            rejected += 1
            return web.Response(status=400, text="synthetic-private-error")
        return await api.handler(request)

    async with reader_fixture(tmp_path, handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        try:
            await wait_for(lambda: len(owner.states) == 3)
            assert all(state.status == "starting" for state in owner.states.values())
            assert not api.requests and rejected == 0
            value = deepcopy(value)
            value["status"]["initContainerStatuses"] = [
                {"name": "init", "state": {"running": {"startedAt": "init-start"}}}
            ]
            await api.update("MODIFIED", value)
            await wait_for(lambda: api.active == 1)
            assert owner.states["owned-pod-00", "app"].status == "starting"
            value["status"]["containerStatuses"][0]["state"] = {
                "running": {"startedAt": "app-start"}
            }
            await api.update("MODIFIED", value)
            await wait_for(
                lambda: rejected == 1 and owner.states["owned-pod-00", "app"].status == "starting"
            )
            value["status"]["conditions"] = [{"type": "Ready", "status": "False"}]
            await api.update("MODIFIED", value)
            await asyncio.sleep(0.05)
            assert rejected == 1
            preopen = False
            value["status"]["containerStatuses"][0]["containerID"] = "owned://actual-instance"
            value["status"]["ephemeralContainerStatuses"] = [
                {"name": "debug", "state": {"running": {"startedAt": "debug-start"}}}
            ]
            await api.update("MODIFIED", value)
            await wait_for(lambda: api.active == 3)
            assert "synthetic-private-error" not in history.export() and api.peak <= 8
            # A completed read never replays because start evidence changes later.
            owner.choose(frozenset({("owned-pod-00", "app")}), reopen=True)
            await wait_for(lambda: api.active == 1)
            stream = owner.states["owned-pod-00", "app"].task
            api.eof.add(("pod-00", "app"))
            owner.choose(frozenset())
            await wait_for(lambda: api.active == 0 and stream.done())
            owner.choose(frozenset({("owned-pod-00", "app")}))
            await wait_for(lambda: owner.states["owned-pod-00", "app"].status == "ended")
            requests = api.requests.copy()
            value["status"]["containerStatuses"][0]["restartCount"] = 1
            await api.update("MODIFIED", value)
            await asyncio.sleep(0.05)
            assert (
                api.requests == requests and owner.states["owned-pod-00", "app"].status == "ended"
            )
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [False, True])
async def test_waiting_crashloop_last_instance_logs_enroll_once_without_hidden_replay(
    tmp_path, previous
):
    api = AggregateApi(count=1)
    value = api.pods["pod-00"]
    value["status"] = {
        "phase": "Running",
        "containerStatuses": [
            {
                "name": "app",
                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                "lastState": {
                    "terminated": {
                        "containerID": "owned://previous-1",
                        "startedAt": "start",
                        "finishedAt": "finish",
                    }
                },
                "restartCount": 2,
                "ready": False,
                "started": False,
            }
        ],
    }
    api.eof.add(("pod-00", "app"))
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner, history = api.owner(reader), AggregateHistory()

        async def retain(source, number, line):
            owner.require_source(source, number)
            history.retain(source, number, line)

        task = asyncio.create_task(
            owner.run(
                LogOptions(previous=previous, follow=not previous), retain, lambda message: None
            )
        )
        try:
            await wait_for(
                lambda: (
                    bool(history.records) and owner.states["owned-pod-00", "app"].status == "ended"
                )
            )
            assert api.requests["pod-00", "app"] == 1
            value["status"]["containerStatuses"][0]["lastState"]["terminated"]["containerID"] = (
                "owned://previous-2"
            )
            value["status"]["containerStatuses"][0]["restartCount"] = 3
            await api.update("MODIFIED", value)
            await asyncio.sleep(0.05)
            assert api.requests["pod-00", "app"] == 1
        finally:
            await finish(owner, task, api)


@pytest.mark.asyncio
async def test_unexpected_consumer_failure_drains_all_watchers_and_readers(tmp_path):
    api = AggregateApi(count=2)
    async with reader_fixture(tmp_path, api.handler) as reader:
        owner = api.owner(reader)

        async def retain(source, number, line):
            raise RuntimeError("owned consumer failure")

        task = asyncio.create_task(owner.run(LogOptions(), retain, lambda message: None))
        with pytest.raises(RuntimeError, match="owned consumer failure"):
            await task
        assert owner.closed and not owner._owned
        with pytest.raises(AppError, match="owner has stopped"):
            owner.choose(None)
        await finish(owner, task, api)
