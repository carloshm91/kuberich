"""Actual manifest/status cases qualify deterministic container details."""

from copy import deepcopy

import pytest

from kubetrol.domain.containers import CONTAINER_COLUMNS, container_rows
from kubetrol.errors import AppError


def test_name_matched_app_init_and_sidecar_data_are_distinct_and_do_not_invent_metrics():
    manifest = {
        "spec": {
            "containers": [
                {
                    "name": "api",
                    "image": "example/api:v1",
                    "resources": {
                        "requests": {"cpu": "250m", "memory": "64Mi"},
                        "limits": {"cpu": "1", "memory": "128Mi"},
                    },
                    "readinessProbe": {},
                    "livenessProbe": {"httpGet": {}},
                    "ports": [
                        {"name": "http", "containerPort": 8080},
                        {"containerPort": 9000, "protocol": "UDP"},
                    ],
                },
                {"name": "worker", "image": "example/worker:v2", "startupProbe": {}},
            ],
            "initContainers": [
                {"name": "init"},
                {"name": "agent", "restartPolicy": "Always"},
            ],
        },
        "status": {
            "containerStatuses": [
                {
                    "name": "worker",
                    "ready": False,
                    "restartCount": 3,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                },
                {"name": "api", "ready": True, "restartCount": 0, "state": {"running": {}}},
                {"name": "other", "ready": True},
            ],
            "initContainerStatuses": [
                {"name": "agent", "ready": True, "restartCount": 2, "state": {"running": {}}},
                {
                    "name": "init",
                    "ready": False,
                    "restartCount": 0,
                    "state": {"terminated": {"exitCode": 0}},
                },
            ],
        },
    }
    before = deepcopy(manifest)
    api, worker, init, agent = container_rows(manifest)
    assert api.cells() == (
        "api",
        "App",
        "true",
        "Running",
        "0",
        "example/api:v1",
        "on:on:off",
        "250m/1",
        "64Mi/128Mi",
        "http:8080/TCP, 9000/UDP",
    )
    assert worker.ready == "false" and worker.state == "CrashLoopBackOff" and worker.restarts == "3"
    assert worker.probes == "off:off:on" and worker.cpu == "—/—"
    assert init.kind == "Init" and init.state == "Completed"
    assert agent.kind == "Sidecar" and agent.restarts == "2"
    assert "CPU" not in CONTAINER_COLUMNS and "MEM" not in CONTAINER_COLUMNS
    assert manifest == before


@pytest.mark.parametrize(
    "state, expected",
    [
        (None, "Unknown"),
        ({}, "Unknown"),
        ({"waiting": {}}, "Waiting"),
        ({"terminated": {}}, "Terminated"),
        ({"terminated": {"reason": "OOMKilled", "exitCode": 137}}, "OOMKilled"),
        ({"terminated": {"reason": "", "exitCode": 2}}, "ExitCode:2"),
        ({"terminated": {"exitCode": False}}, "Terminated"),
        ({"running": "broken", "waiting": "broken", "terminated": "broken"}, "Unknown"),
    ],
)
def test_missing_and_terminated_status_is_explicit(state, expected):
    row = container_rows(
        {
            "spec": {"containers": [{"name": "app"}]},
            "status": {"containerStatuses": [{"name": "app", "state": state}]},
        }
    )[0]
    assert row.state == expected and row.ready == "—" and row.restarts == "—"
    assert row.image == "—" and row.ports == "—"


@pytest.mark.parametrize("bad", [None, True, -1, "2", {}, 1.5])
def test_malformed_counts_ready_status_and_configuration_do_not_look_healthy(bad):
    row = container_rows(
        {
            "spec": {
                "containers": [
                    {
                        "name": "app",
                        "image": bad,
                        "resources": {"requests": None},
                        "readinessProbe": bad,
                    }
                ]
            },
            "status": {
                "containerStatuses": [bad, {}, {"name": "app", "ready": bad, "restartCount": bad}]
            },
        }
    )[0]
    assert row.restarts == "—" and row.ready == ("true" if bad is True else "—")
    assert row.cpu == "—/—" and row.memory == "—/—"


def test_ports_are_bounded_and_bad_entries_are_not_interpreted_as_declarations():
    spec = {
        "containers": [
            {
                "name": "app",
                "ports": [
                    None,
                    {},
                    {"containerPort": True},
                    {"containerPort": 0},
                    {"containerPort": 65536},
                ],
            }
        ]
    }
    assert container_rows({"spec": spec})[0].ports == "—"
    spec["containers"][0]["ports"] = [{"containerPort": 80}] * 17
    assert container_rows({"spec": spec})[0].ports == ", ".join(["80/TCP"] * 16 + ["…"])
    spec["containers"][0]["image"] = "a" * 600
    assert len(container_rows({"spec": spec})[0].image) == 512
    assert container_rows({"spec": {}}) == ()
    assert (
        container_rows({"spec": {"containers": [{"name": "app"}]}, "status": []})[0].state
        == "Unknown"
    )


def test_invalid_or_duplicate_declarations_preserve_existing_validation():
    with pytest.raises(AppError, match="Duplicate"):
        container_rows({"spec": {"containers": [{"name": "app"}, {"name": "app"}]}})
