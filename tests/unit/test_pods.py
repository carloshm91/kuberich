"""Semantic examples of pod health and numeric/chronological ordering."""

from dataclasses import replace
from datetime import timedelta

import pytest

from kubetrol.domain.pods import PodColumn, age, order, pod_row
from kubetrol.errors import AppError
from tests.support.pods import NOW, pod, record
from tests.support.resources import item


def state(*, name="app", ready=False, restarts=0, started=None, **value):
    return {
        "name": name,
        "ready": ready,
        "restartCount": restarts,
        "started": started,
        "state": value,
    }


@pytest.mark.parametrize(
    "value,expected",
    [
        ({}, "Unknown"),
        ({"phase": "Pending"}, "Pending"),
        (
            {
                "phase": "Failed",
                "reason": "Evicted",
                "containerStatuses": [state(terminated={"exitCode": 0, "reason": "Completed"})],
            },
            "Evicted",
        ),
        (
            {
                "phase": "Running",
                "containerStatuses": [state(waiting={"reason": "CrashLoopBackOff"})],
            },
            "CrashLoopBackOff",
        ),
        (
            {
                "phase": "Pending",
                "containerStatuses": [state(waiting={"reason": "ImagePullBackOff"})],
            },
            "ImagePullBackOff",
        ),
        (
            {
                "phase": "Succeeded",
                "containerStatuses": [state(terminated={"exitCode": 0, "reason": "Completed"})],
            },
            "Completed",
        ),
        (
            {"phase": "Failed", "containerStatuses": [state(terminated={"exitCode": 17})]},
            "ExitCode:17",
        ),
        (
            {
                "phase": "Failed",
                "containerStatuses": [state(terminated={"exitCode": 143, "signal": 15})],
            },
            "Signal:15",
        ),
        (
            {
                "phase": "Failed",
                "containerStatuses": [state(terminated={"exitCode": 137, "reason": "OOMKilled"})],
            },
            "OOMKilled",
        ),
        (
            {
                "phase": "Running",
                "conditions": [{"type": "PodScheduled", "reason": "SchedulingGated"}],
            },
            "SchedulingGated",
        ),
        ({"phase": "Running", "containerStatuses": [state(waiting={})]}, "Running"),
        (
            {"phase": None, "reason": 3, "conditions": "invalid", "containerStatuses": [None]},
            "Unknown",
        ),
    ],
)
def test_health_reason_overrides_bare_phase(value, expected):
    manifest = item()
    manifest["status"] = value
    assert pod_row(record(manifest)).status == expected


def test_missing_uid_is_rejected_and_missing_status_is_unknown():
    manifest = item()
    with pytest.raises(AppError, match="UID"):
        pod_row(replace(record(manifest), uid=None))
    manifest["metadata"]["uid"] = "owned"
    row = pod_row(record(manifest))
    assert row.cells(NOW) == ("team", "one", "0/1", "Unknown", "0", "—")
    assert pod_row(replace(record(manifest), namespace=None)).namespace == "—"


@pytest.mark.parametrize(
    "phase,reason,expected",
    [
        ("Running", "", "Terminating"),
        ("Unknown", "NodeLost", "Unknown"),
        ("Succeeded", "Completed", "Completed"),
        ("Failed", "Evicted", "Evicted"),
    ],
)
def test_deletion_preserves_terminal_phases_and_lost_nodes(phase, reason, expected):
    manifest = pod()
    manifest["metadata"]["deletionTimestamp"] = NOW.isoformat()
    manifest["status"].update(phase=phase, reason=reason)
    assert pod_row(record(manifest)).status == expected


@pytest.mark.parametrize(
    "init_state,expected",
    [
        (state(name="prepare", running={}), "Init:0/1"),
        (state(name="prepare", waiting={"reason": "PodInitializing"}), "Init:0/1"),
        (state(name="prepare", waiting={"reason": "CrashLoopBackOff"}), "Init:CrashLoopBackOff"),
        (state(name="prepare", terminated={"exitCode": 1, "reason": "Error"}), "Init:Error"),
        (state(name="prepare", terminated={"exitCode": 2}), "Init:ExitCode:2"),
        (state(name="prepare", terminated={"exitCode": 137, "signal": 9}), "Init:Signal:9"),
    ],
)
def test_init_failure_and_progress_precede_application_state(init_state, expected):
    manifest = pod(restarts=12, ready=False)
    manifest["spec"]["initContainers"] = [{"name": "prepare"}]
    init_state["restartCount"] = 3
    manifest["status"]["initContainerStatuses"] = [init_state]
    row = pod_row(record(manifest))
    assert row.status == expected and row.restarts == 3
    assert row.cells(NOW)[2] == "0/1"


def test_ordered_init_progress_missing_states_and_completed_init_restarts():
    manifest = pod(restarts=10)
    manifest["spec"]["initContainers"] = [{"name": "first"}, {"name": "second"}]
    manifest["status"]["initContainerStatuses"] = [
        state(name="second", running={}, restarts=2),
        state(name="first", terminated={"exitCode": 0}, restarts=5),
    ]
    row = pod_row(record(manifest))
    assert row.status == "Init:1/2" and row.restarts == 7
    manifest["status"]["initContainerStatuses"][0]["state"] = {"terminated": {"exitCode": 0}}
    row = pod_row(record(manifest))
    assert row.status == "Running" and row.restarts == 10
    manifest["status"]["initContainerStatuses"] = []
    assert pod_row(record(manifest)).status == "Init:0/2"
    manifest["status"]["conditions"].append({"type": "Initialized", "status": "True"})
    assert pod_row(record(manifest)).status == "Running"


def test_restartable_sidecars_readiness_restarts_and_ephemeral_exclusion():
    manifest = pod(restarts=10)
    manifest["spec"]["initContainers"] = [
        {"name": "init"},
        {"name": "sidecar", "restartPolicy": "Always"},
    ]
    manifest["spec"]["ephemeralContainers"] = [{"name": "debug"}]
    manifest["status"]["initContainerStatuses"] = [
        state(name="init", terminated={"exitCode": 0}, restarts=100),
        state(name="sidecar", running={}, ready=True, started=True, restarts=2),
    ]
    manifest["status"]["ephemeralContainerStatuses"] = [
        state(name="debug", running={}, ready=True, restarts=1000)
    ]
    row = pod_row(record(manifest))
    assert row.cells(NOW)[2:5] == ("2/2", "Running", "12")
    manifest["status"]["initContainerStatuses"][1]["started"] = False
    assert pod_row(record(manifest)).cells(NOW)[2:5] == ("1/2", "Init:1/2", "102")
    manifest["status"]["conditions"].append({"type": "Initialized", "status": "True"})
    assert pod_row(record(manifest)).cells(NOW)[2:5] == ("1/2", "Running", "12")
    manifest["status"]["initContainerStatuses"][1]["state"] = {
        "waiting": {"reason": "CrashLoopBackOff"}
    }
    assert pod_row(record(manifest)).cells(NOW)[2:5] == ("1/2", "CrashLoopBackOff", "12")
    manifest["status"]["phase"] = "Succeeded"
    manifest["status"]["containerStatuses"][0]["state"] = {
        "terminated": {"exitCode": 0, "reason": "Completed"}
    }
    assert pod_row(record(manifest)).status == "Completed"


@pytest.mark.parametrize("ready_condition,expected", [("True", "Running"), ("False", "NotReady")])
def test_completed_container_does_not_mask_a_running_peer(ready_condition, expected):
    manifest = pod()
    manifest["spec"]["containers"].append({"name": "other"})
    manifest["status"]["conditions"][0]["status"] = ready_condition
    manifest["status"]["containerStatuses"].append(
        state(name="other", terminated={"exitCode": 0, "reason": "Completed"}, restarts=2)
    )
    row = pod_row(record(manifest))
    assert row.status == expected and row.ready == 1 and row.containers == 2 and row.restarts == 2


@pytest.mark.parametrize("bad", [None, False, True, -1, "10", 2.5])
def test_untyped_restart_counts_cannot_become_numeric_values(bad):
    manifest = pod(restarts=bad)
    assert pod_row(record(manifest)).restarts == 0


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "0s"),
        (59, "59s"),
        (60, "1m"),
        (3599, "59m"),
        (3600, "1h"),
        (86400, "1d"),
        (31536000, "1y"),
        (-60, "0s"),
    ],
)
def test_age_boundaries_and_clock_skew(seconds, expected):
    assert age(NOW - timedelta(seconds=seconds), NOW) == expected
    assert age(None, NOW) == "—"


@pytest.mark.parametrize("column", list(PodColumn))
def test_typed_sorting_stable_ties_and_reverse_with_unknown_age_last(column):
    values = (
        pod_row(record(pod("z-two", restarts=2, created=NOW - timedelta(minutes=2)))),
        pod_row(record(pod("a-ten", restarts=10, created=NOW - timedelta(hours=1), ready=False))),
        pod_row(record(pod("b-unknown", restarts=100))),
    )
    sorted_values = order(values, column)
    if column is PodColumn.RESTARTS:
        assert [row.restarts for row in sorted_values] == [2, 10, 100]
    elif column is PodColumn.AGE:
        assert [row.name for row in sorted_values] == ["z-two", "a-ten", "b-unknown"]
        assert [row.name for row in order(values, column, True)] == ["a-ten", "z-two", "b-unknown"]
    elif column is PodColumn.READY:
        assert sorted_values[0].ready == 0
    else:
        assert sorted_values == order(tuple(reversed(values)), column)
    assert set(order(values, column, True)) == set(values)
    assert order((), column) == ()


def test_readiness_sorts_by_fraction_and_duplicate_names_tie_by_uid():
    row = pod_row(record(pod()))
    low = replace(row, uid="low", ready=2, containers=10)
    high = replace(row, uid="high", ready=1, containers=2)
    assert order((high, low), PodColumn.READY) == (low, high)
    assert order((replace(row, uid="b"), replace(row, uid="a")), PodColumn.NAME)[0].uid == "a"
