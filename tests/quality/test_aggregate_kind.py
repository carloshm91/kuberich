"""The owned CrashLoop scenario requires a fresh real waiting observation."""

from datetime import UTC, datetime, timedelta

import pytest
from kubernetes_asyncio import client

from scripts.verify_aggregate_logs_kind import CrashWaitingWindow

NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)


def fixture(*, restarts=3, age=1, waiting="CrashLoopBackOff", container_id="owned://last"):
    return client.V1Pod(
        status=client.V1PodStatus(
            container_statuses=[
                client.V1ContainerStatus(
                    name="app",
                    ready=False,
                    restart_count=restarts,
                    image="synthetic",
                    image_id="owned://image",
                    state=client.V1ContainerState(
                        waiting=client.V1ContainerStateWaiting(reason=waiting)
                    ),
                    last_state=client.V1ContainerState(
                        terminated=client.V1ContainerStateTerminated(
                            exit_code=1,
                            container_id=container_id,
                            finished_at=NOW - timedelta(seconds=age),
                        )
                    ),
                )
            ]
        )
    )


def seeded():
    window = CrashWaitingWindow()
    value = fixture()
    value.status.container_statuses[0].state = client.V1ContainerState(
        terminated=client.V1ContainerStateTerminated(exit_code=1, container_id="owned://last")
    )
    assert not window.observe(value, 0)
    return window


@pytest.mark.parametrize("age", [0, 100, 10000])
def test_observed_transition_uses_monotonic_receipt_not_server_timestamp(age):
    window = seeded()
    assert window.observe(fixture(age=age), 1)
    assert window.observe(fixture(age=age), 4)
    assert not window.observe(fixture(age=age), 4.001)
    assert not window.observe(fixture(age=age), 0.9)


def test_an_already_waiting_observation_has_no_transition_or_new_admission_window():
    window = CrashWaitingWindow()
    assert not window.observe(fixture(), 0)
    assert not window.observe(fixture(), 100)


@pytest.mark.parametrize(
    "options",
    [
        {"restarts": 0},
        {"restarts": 2},
        {"waiting": "PodInitializing"},
        {"container_id": ""},
        {"container_id": "owned://another"},
    ],
)
def test_early_unknown_or_replaced_instances_cannot_enroll(options):
    assert not seeded().observe(fixture(**options), 1)


@pytest.mark.parametrize(
    "absent", ["pod-status", "statuses", "state", "waiting", "last", "terminated"]
)
def test_incomplete_waiting_observations_cannot_enroll(absent):
    window = seeded()
    value = fixture()
    status = value.status.container_statuses[0]
    if absent == "pod-status":
        value.status = None
    elif absent == "statuses":
        value.status.container_statuses = None
    elif absent == "state":
        status.state = None
    elif absent == "waiting":
        status.state = client.V1ContainerState(running=client.V1ContainerStateRunning())
    elif absent == "last":
        status.last_state = None
    else:
        status.last_state = client.V1ContainerState()
    assert not window.observe(value, 1)


def test_a_new_termination_opens_a_new_window_and_running_invalidates_it():
    window = seeded()
    assert window.observe(fixture(), 0)
    assert not window.observe(fixture(), 5)
    value = fixture(container_id="owned://next")
    value.status.container_statuses[0].state = client.V1ContainerState(
        terminated=client.V1ContainerStateTerminated(exit_code=1, container_id="owned://next")
    )
    assert not window.observe(value, 6)
    assert window.observe(fixture(container_id="owned://next"), 7)
    value.status.container_statuses[0].state = client.V1ContainerState(
        running=client.V1ContainerStateRunning()
    )
    assert not window.observe(value, 8)
    assert not window.observe(fixture(container_id="owned://next"), 9)
