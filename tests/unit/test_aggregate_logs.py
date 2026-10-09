"""Actual ownership chains and independently bounded, identifiable retained output."""

import json
from dataclasses import replace

import pytest

from kuberich.domain.aggregate_logs import (
    MAX_SOURCES,
    AggregateHistory,
    LogSource,
    aggregate_line,
    container_starts,
    intermediate_resource,
    owned_by,
    sources,
    workload_kind,
)
from kuberich.domain.logs import LogDecoder, LogLine
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from tests.support.pods import pod, record


def target(resource="pods", group="", uid="owned-api", name="api", namespace="team"):
    return ResourceTarget(SessionIdentity("owned", 1), group, resource, namespace, name, uid)


def owner(target, owner_kind, **changes):
    return {
        "apiVersion": f"{target.group}/v1" if target.group else "v1",
        "kind": owner_kind,
        "uid": target.uid,
        "name": target.name,
        "controller": True,
        **changes,
    }


def owned_pod(parent, owner_kind, **changes):
    value = pod("child")
    value["metadata"]["ownerReferences"] = [owner(parent, owner_kind, **changes)]
    return record(value)


@pytest.mark.parametrize(
    "group,name,kind",
    [
        ("", "pods", "Pod"),
        ("", "replicationcontrollers", "ReplicationController"),
        ("apps", "deployments", "Deployment"),
        ("apps", "replicasets", "ReplicaSet"),
        ("apps", "statefulsets", "StatefulSet"),
        ("apps", "daemonsets", "DaemonSet"),
        ("batch", "jobs", "Job"),
        ("batch", "cronjobs", "CronJob"),
    ],
)
def test_supported_scope_and_controller_chain(group, name, kind):
    parent = target(name, group)
    assert workload_kind(parent) == kind
    middle = intermediate_resource(parent)
    if middle is not None:
        raw = {
            "metadata": {
                "name": "middle",
                "namespace": "team",
                "uid": "middle-uid",
                "resourceVersion": "1",
                "ownerReferences": [owner(parent, kind)],
            }
        }
        intermediate = resource_record(middle, raw)
        controller = ResourceTarget(
            parent.session, middle.group, middle.name, "team", "middle", "middle-uid"
        )
        child = owned_pod(controller, middle.kind)
        assert not sources(parent, (child,))[0]
        actual, excess = sources(parent, (child,), (intermediate,))
        assert len(actual) == 1 and excess == 0
        wrong_parent = replace(parent, uid="recreated-parent")
        assert not sources(wrong_parent, (child,), (intermediate,))[0]
        assert not sources(
            parent, (owned_pod(controller, middle.kind, kind="Wrong"),), (intermediate,)
        )[0]
    elif kind == "Pod":
        assert sources(parent, (record(pod("api")),))[0]
        assert not sources(parent, (record(pod("other", uid="owned-api")),))[0]
    else:
        assert sources(parent, (owned_pod(parent, kind),))[0]
        assert not sources(parent, (record(pod("api")),))[0]


@pytest.mark.parametrize(
    "change",
    [
        {"uid": "different"},
        {"name": "different"},
        {"kind": "Wrong"},
        {"controller": False},
        {"apiVersion": "wrong/v1"},
        {"apiVersion": "bad/group/v1"},
        {"apiVersion": None},
    ],
)
def test_labels_and_incorrect_controller_references_do_not_establish_membership(change):
    parent = target("replicasets", "apps")
    assert not owned_by(owned_pod(parent, "ReplicaSet", **change), parent, "ReplicaSet")


@pytest.mark.parametrize("owners", [[], [None], [{"controller": False}], [{"controller": True}]])
def test_absent_or_noncontroller_owner_is_not_membership(owners):
    parent = target("jobs", "batch")
    raw = pod("child")
    raw["metadata"]["ownerReferences"] = owners
    assert not owned_by(record(raw), parent, "Job")


@pytest.mark.parametrize("owners", [{}, [None] * 129])
def test_malformed_excessive_ownership_fails_closed(owners):
    raw = pod("child")
    raw["metadata"]["ownerReferences"] = owners
    parent = target("deployments", "apps")
    middle = intermediate_resource(parent)
    middle_raw = {
        "metadata": {
            "name": "middle",
            "namespace": "team",
            "uid": "middle",
            "resourceVersion": "1",
            "ownerReferences": [owner(parent, "Deployment")],
        }
    }
    with pytest.raises(AppError, match="owner references"):
        owned_by(record(raw), parent, "Deployment")
    with pytest.raises(AppError, match="owner references"):
        sources(parent, (record(raw),), (resource_record(middle, middle_raw),))


def test_wrong_scope_uid_and_source_catalogue_are_bounded():
    parent = target("replicasets", "apps")
    child = owned_pod(parent, "ReplicaSet")
    assert not owned_by(replace(child, namespace="other"), parent, "ReplicaSet")
    assert not sources(parent, (replace(child, namespace="other"), replace(child, uid=None)))[0]
    many = tuple(
        replace(child, name=f"child-{i:03}", uid=f"uid-{i}") for i in range(MAX_SOURCES + 3)
    )
    actual, excess = sources(parent, many)
    assert len(actual) == MAX_SOURCES and excess == 3
    for invalid in (replace(parent, resource="widgets"), replace(parent, namespace=None)):
        with pytest.raises(AppError, match="namespaced"):
            workload_kind(invalid)


def test_regular_init_ephemeral_source_identity_and_empty_manifest():
    raw = pod("api")
    raw["spec"]["initContainers"] = [{"name": "init"}]
    raw["spec"]["ephemeralContainers"] = [{"name": "debug"}]
    actual, _ = sources(target(), (record(raw),))
    assert [source.container for source in actual] == ["app", "init", "debug"]
    assert actual[0].key == ("owned-api", "app")
    raw["spec"]["containers"] = []
    assert not sources(target(), (record(pod("other")),))[0]


@pytest.mark.parametrize(
    "payload",
    [
        '{"safe":"value","nested":[1,2.5,null,true]}',
        '["safe",{"nested":"value"}]',
        '{"pass\\u0077ord":"private-value","safe":"\\u001b[red]"}',
    ],
)
def test_structured_projection_decodes_redacts_and_preserves_identity(payload):
    source = LogSource("team", "api", "uid-original", "app")
    value = aggregate_line(3, source, 7, LogLine("2026-10-09T12:00:00Z " + payload))
    export = json.loads(value.text(json_mode=True))
    assert export["source"] == {
        "id": 7,
        "namespace": "team",
        "pod": "api",
        "container": "app",
        "uid": "uid-original",
    }
    assert export["line"] == 3 and export["timestamp"] == "2026-10-09T12:00:00Z"
    assert "private-value" not in value.text(json_mode=True)
    assert "\x1b" not in value.text(json_mode=False)
    assert json.loads(value.text(json_mode=True, timestamps=False))["timestamp"] is None
    assert "2026-" not in value.text(json_mode=False, timestamps=False)
    assert value.size_bytes >= len(value.text(json_mode=True).encode())


@pytest.mark.parametrize(
    "payload",
    [
        '{"broken":',
        "[" * 18 + "0" + "]" * 18,
        "[" + ",".join("0" for _ in range(513)) + "]",
        '{"n":NaN}',
        '{"n":Infinity}',
        '{"n":-Infinity}',
    ],
)
def test_invalid_excessive_or_nonfinite_json_is_withheld(payload):
    value = aggregate_line(1, LogSource("team", "api", "uid", "app"), 1, LogLine(payload))
    assert "unavailable" in value.payload and value.structured is None
    assert json.loads(value.text(json_mode=True))["payload"] == value.payload


@pytest.mark.parametrize("json_mode", [False, True])
def test_real_decoder_expansion_stays_bounded_with_prefix_body_and_export(json_mode):
    line = LogDecoder().feed(b"\x00" * 8192 + b"\n")[0]
    history = AggregateHistory()
    source = LogSource(
        "team", "workload-pod", "f732947d-1c41-47d2-8e08-c268fd6869f0", "application"
    )
    history.retain(source, 1, line)
    history.json_mode = json_mode
    assert len(history.entries) == 1 and "aggregate payload truncated" in history.export()
    assert len(history.display_entries(False)[0].line.text) <= 8192 * 6 + 32
    assert source.uid in history.export()
    structured = LogDecoder().feed(("{" + '"message":"' + "x" * 6000 + '"}\n').encode())[0]
    history.retain(source, 1, structured)
    assert history.records[2].structured is None


def test_per_source_and_aggregate_bounds_arrival_ids_marks_filter_and_recreated_uid():
    history = AggregateHistory(max_lines=5, max_bytes=2000, source_lines=2, source_bytes=1000)
    original = LogSource("team", "same-name", "old-uid", "app")
    replacement = replace(original, uid="new-uid")
    history.retain(original, 1, LogLine("2026-10-09T12:00:03Z first"))
    history.mark(1)
    history.mark(1)
    history.mark(1)
    for i in range(8):
        history.retain(
            original if i % 2 else replacement,
            1 if i % 2 else 2,
            LogLine(f"2026-10-09T12:00:00Z line-{i}"),
        )
    assert len(history.records) == 4 and all(
        len(numbers) <= 2 for numbers in history.by_source.values()
    )
    assert list(history.records) == sorted(history.records)
    assert 1 not in history.marks and history.buffer.dropped_lines == 5
    assert history.buffer.size_bytes == sum(value.size_bytes for value in history.records.values())
    history.filter = original.key
    assert len(history.entries) == 2 and "new-uid" not in history.export()
    assert all("2026-" not in entry.line.text for entry in history.display_entries(False))
    assert "old-uid" in history.export(clipboard=True)
    with pytest.raises(AppError, match="no longer retained"):
        history.mark(1)
    with pytest.raises(AppError, match="captured source"):
        history.append(LogLine("unattributed"))
    assert history.clear() == 4 and not history.records and not history.sizes
    assert history.next_number == 10


def test_source_byte_and_global_byte_and_line_limits_are_independent():
    source = LogSource("team", "api", "uid", "app")
    history = AggregateHistory(source_bytes=1)
    history.retain(source, 1, LogLine("oversized"))
    assert not history.records and not history.by_source and history.buffer.dropped_lines == 1
    for options in ({"max_bytes": 1}, {"max_lines": 1}):
        history = AggregateHistory(**options)
        history.retain(source, 1, LogLine("first"))
        history.retain(replace(source, uid="other"), 2, LogLine("second"))
        assert len(history.records) <= 1 and history.buffer.dropped_lines >= 1
    for options in (
        {"source_lines": 0},
        {"source_lines": 501},
        {"source_bytes": 0},
        {"source_bytes": 262145},
    ):
        with pytest.raises(AppError, match="retention"):
            AggregateHistory(**options)
    history = AggregateHistory()
    for i in range(600):
        history.retain(replace(source, uid=str(i)), i, LogLine("x" * 2000))
    with pytest.raises(AppError, match="1 MiB"):
        history.export(clipboard=True)


@pytest.mark.parametrize(
    "payload",
    [
        "[INFO] Listening on port 8080",
        "[red]literal[/red]",
        "[2026-10-09 17:00:00] request completed",
        "[1] worker started",
        "[1234] worker started",
    ],
)
def test_bracket_prefixed_plain_logs_stay_literal_in_both_modes_and_exports(payload):
    source = LogSource("team", "api", "uid", "app")
    history = AggregateHistory()
    history.retain(source, 1, LogDecoder().feed((payload + "\n").encode())[0])
    assert history.records[1].payload == payload and payload in history.export()
    assert payload in history.display_entries(False)[0].line.text
    history.json_mode = True
    assert json.loads(history.export())["payload"] == payload


@pytest.mark.parametrize("key", ["token", "pass\\u0077ord", "authorization"])
def test_actual_decoder_preserves_useful_json_fields_and_redacts_decoded_credentials(key):
    raw = (
        '2026-10-09T12:00:00Z {"message":"request complete","'
        + key
        + '":"synthetic-private","count":3,"nested":[{"control":"\\u001b"}]}\n'
    ).encode()
    line = LogDecoder().feed(raw)[0]
    assert "synthetic-private" not in line.text and "\x1b" not in line.text
    history = AggregateHistory()
    history.retain(LogSource("team", "api", "uid", "app"), 1, line)
    history.json_mode = True
    value = json.loads(history.export())["payload"]
    assert value["message"] == "request complete" and value["count"] == 3
    assert value["password" if key == "pass\\u0077ord" else key] == "[REDACTED]"
    assert "uid" in history.entries[0].line.text


def test_decoded_json_control_expansion_is_bounded_before_retention():
    line = LogDecoder().feed(('{"message":"' + "\u202e" * 6000 + '"}\n').encode())[0]
    assert "unavailable" in line.text and len(line.text) < 8192


@pytest.mark.parametrize(
    "payload,expected",
    [
        ('"Bearer\\u0020synthetic-private"', "Bearer [REDACTED]"),
        ("42", 42),
        ("-12.5", -12.5),
        ("true", True),
        ("false", False),
        ("null", None),
        ("[1]", [1]),
        ("[]", []),
    ],
)
def test_valid_json_scalars_are_typed_and_sanitized_after_real_decoder(payload, expected):
    line = LogDecoder().feed((payload + "\n").encode())[0]
    history = AggregateHistory()
    history.retain(LogSource("team", "api", "uid", "app"), 1, line)
    history.json_mode = True
    assert json.loads(history.export())["payload"] == expected
    assert "synthetic-private" not in history.export()


@pytest.mark.parametrize("status", [None, "invalid", {}, {"containerStatuses": []}])
def test_unknown_container_start_does_not_assume_pod_phase(status):
    assert not container_starts({"status": status})


@pytest.mark.parametrize("entries", ["invalid", [{}] * 129])
def test_container_start_metadata_is_bounded(entries):
    with pytest.raises(AppError, match="container statuses"):
        container_starts({"status": {"containerStatuses": entries}})


def test_start_evidence_is_per_container_stable_and_limited_to_actual_start_fields():
    status = {
        "containerStatuses": [
            None,
            {},
            {"name": "invalid"},
            {"name": "wait", "state": {"waiting": {}}},
        ],
        "initContainerStatuses": [
            {
                "name": "init",
                "state": {
                    "terminated": {
                        "startedAt": "start",
                        "finishedAt": "finish",
                        "containerID": "owned://init",
                    }
                },
                "restartCount": 0,
            }
        ],
        "ephemeralContainerStatuses": [
            {
                "name": "debug",
                "state": {"running": {}},
                "containerID": "owned://" + "x" * 600,
                "restartCount": -1,
            }
        ],
    }
    starts = container_starts({"status": status})
    assert set(starts) == {"init", "debug"} and len(starts["debug"]) < 700
    status["initContainerStatuses"][0]["state"]["terminated"]["unrelated"] = "different"
    assert container_starts({"status": status}) == starts
    status["initContainerStatuses"][0]["restartCount"] = 1
    assert container_starts({"status": status})["init"] != starts["init"]


@pytest.mark.parametrize("previous", [False, True])
@pytest.mark.parametrize(
    "current",
    [
        None,
        {},
        {"waiting": {"reason": "CrashLoopBackOff"}},
        {"terminated": {}},
        {"terminated": {"containerID": ""}},
    ],
)
def test_waiting_or_missing_current_state_uses_last_terminated_logs(current, previous):
    item = {
        "name": "app",
        "state": current,
        "lastState": {
            "terminated": {
                "containerID": "owned://previous",
                "startedAt": "start",
                "finishedAt": "finish",
            }
        },
    }
    assert "app" in container_starts({"status": {"containerStatuses": [item]}}, previous=previous)


@pytest.mark.parametrize(
    "last",
    [
        None,
        "invalid",
        {},
        {"terminated": None},
        {"terminated": {}},
        {"terminated": {"containerID": ""}},
        {"terminated": {"containerID": 1}},
    ],
)
def test_previous_requires_actual_last_instance_identity(last):
    item = {"name": "app", "state": {"running": {}}, "lastState": last}
    assert "app" in container_starts({"status": {"containerStatuses": [item]}})
    assert not container_starts({"status": {"containerStatuses": [item]}}, previous=True)


@pytest.mark.parametrize(
    "payload",
    [
        "42 requests ready",
        "true story",
        "2026-10-09 event",
        "-12.5ms",
        "null response failure",
        "07",
        "-01",
        "1e",
    ],
)
def test_plain_numeric_and_keyword_prefixes_are_not_json_scalars(payload):
    line = LogDecoder().feed((payload + "\n").encode())[0]
    assert line.text == payload


@pytest.mark.parametrize(
    "payload",
    [
        '[1e,{"pass\\u0077ord":"synthetic-private"}]',
        '[invalid,5,{"pass\\u0077ord":"synthetic-private"}]',
        '[invalid,[5],{"pass\\u0077ord":"synthetic-private"}]',
        '{unquoted:4,"pass\\u0077ord":"synthetic-private"}',
        '{invalid,{"pass\\u0077ord":"synthetic-private"}}',
    ],
)
def test_malformed_apparent_structure_cannot_fall_back_to_encoded_credentials(payload):
    line = LogDecoder().feed((payload + "\n").encode())[0]
    history = AggregateHistory()
    history.retain(LogSource("team", "api", "uid", "app"), 1, line)
    assert "synthetic-private" not in history.export() and "unavailable" in history.export()
    assert "synthetic-private" not in history.display_entries(False)[0].line.text
    history.json_mode = True
    assert (
        "synthetic-private" not in history.export()
        and "unavailable" in json.loads(history.export())["payload"]
    )
