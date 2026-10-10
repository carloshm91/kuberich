"""Select a genuine waiting membership response without leasing live server state."""

import asyncio
from copy import deepcopy

import pytest
from aiohttp import web
from kubernetes_asyncio import client

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.resources import ResourceSnapshot, api_resource, resource_record
from scripts import verify_aggregate_logs_kind as verification
from tests.support.resources import collection, descriptor, pod_resource, reader_fixture

UID = "owned-crash-uid"


def pod(*, uid=UID, name="owned-crash", namespace="team", state=None, restarts=3):
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": name, "namespace": namespace, "uid": uid, "resourceVersion": "obj/1"},
        "status": {
            "containerStatuses": [
                {
                    "name": "app",
                    "image": "synthetic",
                    "imageID": "owned://image",
                    "ready": False,
                    "restartCount": restarts,
                    "state": state
                    if state is not None
                    else {"waiting": {"reason": "CrashLoopBackOff"}},
                    "lastState": {"terminated": {"exitCode": 1, "containerID": "owned://last"}},
                }
            ]
        },
    }


def snapshot(value):
    return ResourceSnapshot(
        pod_resource(), "team", "observed/1", (resource_record(pod_resource(), value),)
    )


@pytest.mark.parametrize(
    "options",
    [
        {"uid": "recreated"},
        {"name": "other"},
        {"namespace": "other"},
        {"restarts": 0},
        {"restarts": 2},
        {"restarts": True},
        {"state": {"running": {}}},
        {"state": {"terminated": {"containerID": "owned://last"}}},
        {"state": {"waiting": {"reason": "PodInitializing"}}},
        {"state": {}},
    ],
)
def test_unrelated_early_or_nonwaiting_records_cannot_select_the_first_snapshot(options):
    assert verification.waiting_crash_record(snapshot(pod(**options)), "team", UID) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "init"),
        ("state", None),
        ("lastState", None),
        ("lastState", {}),
        ("lastState", {"terminated": {"containerID": ""}}),
        ("lastState", {"terminated": {"containerID": 17}}),
    ],
)
def test_missing_or_unknown_instance_evidence_does_not_admit(field, value):
    manifest = pod()
    manifest["status"]["containerStatuses"][0][field] = value
    assert verification.waiting_crash_record(snapshot(manifest), "team", UID) is None


@pytest.mark.parametrize(
    "status", [None, {}, {"containerStatuses": None}, {"containerStatuses": [None]}]
)
def test_incomplete_status_is_not_a_waiting_instance(status):
    manifest = pod()
    manifest["status"] = status
    assert verification.waiting_crash_record(snapshot(manifest), "team", UID) is None


def test_selected_record_is_the_original_immutable_snapshot_member():
    value = snapshot(pod())
    assert verification.waiting_crash_record(value, "team", UID) is value.items[0]


@pytest.mark.asyncio
async def test_http_list_selection_returns_the_whole_genuine_response_and_only_gates_once(tmp_path):
    responses = [
        pod(uid="recreated"),
        pod(state={"running": {}}),
        pod(state={"terminated": {"containerID": "owned://last"}}),
        pod(),
        pod(state={"running": {}}, restarts=4),
    ]
    calls = []
    waiting = deepcopy(responses[3])
    unrelated = pod(name="another", uid="other")

    async def handler(request):
        calls.append(dict(request.query))
        value = responses.pop(0)
        return web.json_response(collection(value, unrelated, rv=f"snapshot/{len(calls)}"))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        result = await selected.list(pod_resource(), "team", page_size=7)
        assert len(calls) == 4 and all(call["limit"] == "7" for call in calls)
        assert result.items[0].manifest == waiting
        assert result.items[1].manifest == unrelated
        assert result.resource_version == evidence["membership_resource_version"] == "snapshot/4"
        assert evidence["membership_waiting_uid"] == UID and evidence["list_attempts"] == 4
        assert not selected.pending
        subsequent = await selected.list(pod_resource(), "team", page_size=7)
        assert len(calls) == 5 and subsequent.resource_version == "snapshot/5"
        assert "running" in subsequent.items[0].manifest["status"]["containerStatuses"][0]["state"]


@pytest.mark.asyncio
async def test_other_namespace_reads_pass_through_without_consuming_the_gate(tmp_path):
    async def handler(request):
        return web.json_response(collection(pod(namespace="other", state={"running": {}})))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        result = await selected.list(pod_resource(), "other")
        assert result.items[0].namespace == "other" and selected.pending and not evidence


@pytest.mark.asyncio
async def test_permission_failure_is_not_polled_or_reclassified_as_waiting(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response({"message": "owned denial"}, status=403)

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        with pytest.raises(ConnectionProblem):
            await selected.list(pod_resource(), "team")
        assert len(calls) == 1 and selected.pending and not evidence


@pytest.mark.asyncio
async def test_cancelled_held_list_is_drained_without_a_completed_admission(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        started.set()
        await release.wait()
        return web.json_response(collection(pod()))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        task = asyncio.create_task(selected.list(pod_resource(), "team"))
        try:
            await asyncio.wait_for(started.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert selected.pending and not evidence
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [False, True])
async def test_held_direct_log_read_does_not_select_an_old_get_as_membership(tmp_path, previous):
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    current = pod(state={"running": {}}, restarts=4)
    waiting = pod(restarts=4)
    waiting["status"]["containerStatuses"][0]["lastState"]["terminated"]["containerID"] = (
        "owned://next"
    )
    listings = [current, waiting]

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("/log"):
            assert request.query["previous"].lower() == str(previous).lower()
            started.set()
            await release.wait()
            return web.Response(text="owned-crash-output\n")
        if request.path.endswith("/owned-crash"):
            return web.json_response(pod(state={"running": {}}))
        return web.json_response(collection(listings.pop(0), rv=f"member/{len(calls)}"))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)

        async def admit():
            await verification.crash_admission_precondition(
                client.CoreV1Api(reader.session.api), "team", UID, previous, evidence
            )
            return await selected.list(pod_resource(), "team")

        task = asyncio.create_task(admit())
        try:
            await asyncio.wait_for(started.wait(), 5)
            assert "membership_resource_version" not in evidence
            release.set()
            result = await asyncio.wait_for(task, 5)
            assert result.items[0].manifest == waiting and len(calls) == 4
            assert evidence["direct_finished_monotonic"] < evidence["membership_observed_monotonic"]
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_recreated_uid_fails_precondition_before_any_log_read(tmp_path):
    calls = []

    async def handler(request):
        calls.append(request.path)
        return web.json_response(pod(uid="recreated"))

    async with reader_fixture(tmp_path, handler) as reader:
        with pytest.raises(AssertionError):
            await verification.crash_admission_precondition(
                client.CoreV1Api(reader.session.api), "team", UID, False, {}
            )
        assert len(calls) == 1 and not calls[0].endswith("/log")


@pytest.mark.asyncio
@pytest.mark.parametrize("version,name", [("v1", "services"), ("owned.example/v1", "pods")])
async def test_other_resource_reads_do_not_consume_the_core_pod_gate(tmp_path, version, name):
    resource = api_resource(version, descriptor(name))

    async def handler(request):
        value = pod(state={"running": {}})
        value["apiVersion"] = version
        payload = collection(value)
        payload["apiVersion"] = version
        return web.json_response(payload)

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        result = await selected.list(resource, "team")
        assert result.resource == resource and selected.pending and not evidence


@pytest.mark.asyncio
async def test_missing_waiting_instance_hits_the_owned_deadline_without_admission(
    tmp_path, monkeypatch
):
    async def short_deadline(predicate):
        async with asyncio.timeout(0.03):
            while not await predicate():
                await asyncio.sleep(0)

    monkeypatch.setattr(verification, "wait_for", short_deadline)

    async def handler(request):
        return web.json_response(collection(pod(uid="recreated")))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        selected = verification.CrashWaitingReader(reader.session, "team", UID, evidence)
        with pytest.raises(TimeoutError):
            await selected.list(pod_resource(), "team")
        assert evidence["list_attempts"] > 0 and selected.pending
        assert "membership_resource_version" not in evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [False, True])
async def test_log_availability_waits_for_a_started_instance_and_actual_output(tmp_path, previous):
    calls, reads = [], []

    async def handler(request):
        calls.append(request.path)
        if request.path.endswith("/log"):
            assert request.query["previous"].lower() == str(previous).lower()
            reads.append(request.path)
            return web.Response(text="owned-crash-output\n" if len(reads) == 2 else "")
        return web.json_response(pod(state={"running": {}}, restarts=2 if len(calls) == 1 else 3))

    async with reader_fixture(tmp_path, handler) as reader:
        evidence = {}
        value = await verification.crash_admission_precondition(
            client.CoreV1Api(reader.session.api), "team", UID, previous, evidence
        )
        assert value.metadata.uid == UID and value.status.container_statuses[0].restart_count == 3
        assert len(reads) == 2 and len(calls) == 5 and not calls[0].endswith("/log")
        assert evidence["direct_finished_monotonic"] > evidence["direct_started_monotonic"]
