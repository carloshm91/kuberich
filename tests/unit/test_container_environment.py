"""Independent environment vectors, hostile payloads and conservative API limits."""

import base64
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from kuberich.domain.container_inspection import (
    MAX_DEPENDENCY_EDGES,
    MAX_ENV_ROWS,
    MAX_RESOLUTION_BYTES,
    ContainerIdentity,
    ReasonCode,
    SourceRead,
    SourceRef,
    build_inspection,
    metadata_table,
    reference_plan,
    resolve_selected,
)
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

NOW = datetime(2026, 11, 5, tzinfo=UTC)
APP = ContainerIdentity("containers", "worker", "App")


def resource(kind, name, **fields):
    return resource_record(
        ApiResource(
            "",
            "v1",
            "pods" if kind == "Pod" else "secrets" if kind == "Secret" else "configmaps",
            kind,
            True,
            frozenset({"get"}),
        ),
        {
            "apiVersion": "v1",
            "kind": kind,
            "metadata": {
                "name": name,
                "namespace": "team",
                "uid": name + "-uid",
                "resourceVersion": "rv-1",
            },
            **fields,
        },
        "team",
    )


def inspect(env=(), env_from=(), sources=(), *, metadata=None, extra=None, resources=None, reads=2):
    fields = {
        "spec": {
            "containers": [
                {
                    "name": "worker",
                    "env": list(env),
                    "envFrom": list(env_from),
                    **({"resources": resources} if resources is not None else {}),
                }
            ],
            **(extra or {}),
        }
    }
    record = resource("Pod", "owned-pod", **fields)
    if metadata:
        data = record.manifest
        data["metadata"].update(metadata)
        record = replace(record, _manifest=json.dumps(data).encode())
    target = ResourceTarget(
        SessionIdentity("owned", 1), "", "pods", "team", record.name, record.uid, "worker"
    )
    snapshot = build_inspection(
        record,
        APP,
        tuple(sources),
        target=target,
        snapshot_id=UUID(int=74),
        started_at=NOW,
        observed_at=NOW,
        reads=reads,
    )
    return snapshot, record


def source(kind="ConfigMap", name="settings", state="available", **fields):
    return SourceRead(
        SourceRef(kind, "team", name),
        state,
        resource(kind, name, **fields) if state == "available" else None,
        NOW,
    )


def resolve(observed, record, ordinal, sources=(), *, family="env", key=None):
    return resolve_selected(observed, (family, ordinal, key), record, tuple(sources))


def keyref(name, key="plain", *, optional=False, kind="configMapKeyRef"):
    return {
        "name": name,
        "valueFrom": {kind: {"name": "settings", "key": key, "optional": optional}},
    }


@pytest.mark.parametrize(
    "expression,expected,complete",
    [
        ("", "", True),
        ("plain", "plain", True),
        ("$", "$", True),
        ("$x", "$x", True),
        ("$$", "$", True),
        ("$$(BASE)", "$(BASE)", True),
        ("$$$(BASE)", "$initial", True),
        ("$(BASE)/$(BASE)", "initial/initial", True),
        ("$(BASE", "$(BASE", True),
        ("$(BASE)$(MISSING)", "initial$(MISSING)", False),
        ("$()", "$()", False),
        ("$(BASE\n)", "$(BASE\n)", False),
        ("before$(BASE)after", "beforeinitialafter", True),
    ],
)
def test_one_pass_dollar_grammar_has_independent_known_vectors(expression, expected, complete):
    observed, record = inspect(
        [{"name": "BASE", "value": "initial"}, {"name": "RESULT", "value": expression}]
    )
    result = resolve(observed, record, 1)
    assert (result.text, result.complete) == (expected, complete)
    assert bool(result.reasons) is not complete


def test_duplicate_names_bind_to_prior_declaration_and_forward_references_stay_unknown():
    observed, record = inspect(
        [
            {"name": "X", "value": "one"},
            {"name": "X", "value": "$(X)/two"},
            {"name": "F", "value": "$(LATER)"},
            {"name": "LATER", "value": "three"},
            {"name": "SELF", "value": "$(SELF)"},
        ]
    )
    assert observed.entries[0].precedence == "overridden"
    assert observed.entries[1].dependencies[0].entry == ("env", 0, None)
    assert resolve(observed, record, 1).text == "one/two"
    assert resolve(observed, record, 2).text == "$(LATER)"
    assert resolve(observed, record, 4).reasons == (ReasonCode.UNKNOWN_VARIABLE,)


def test_source_values_are_not_recursively_expanded_and_secret_payloads_never_enter_metadata():
    marker = "private_hidden_payload"
    config = source(data={"plain": "$(UNOBSERVED)"})
    secret = source(
        "Secret",
        "credentials",
        data={"plain": base64.b64encode(marker.encode()).decode(), "empty": "", "binary": "/w=="},
    )
    observed, record = inspect(
        [{"name": "DERIVED", "value": "$(plain)"}],
        [
            {"configMapRef": {"name": "settings"}},
            {"secretRef": {"name": "credentials"}, "prefix": "S_"},
        ],
        [config, secret],
    )
    assert resolve(observed, record, 0, [config, secret]).text == "$(UNOBSERVED)"
    assert (
        resolve(observed, record, 1, [config, secret], family="envFrom", key="plain").text == marker
    )
    assert resolve(observed, record, 1, [config, secret], family="envFrom", key="empty").text == ""
    assert (
        resolve(observed, record, 1, [config, secret], family="envFrom", key="binary").text is None
    )
    for value in (
        observed,
        *(metadata_table(observed, section) for section in ("environment", "image", "sources")),
    ):
        assert marker not in repr(value) and "$(UNOBSERVED)" not in repr(value)
    assert "binary" in metadata_table(observed, "sources").rows[1].cells[-1]


def test_later_envfrom_overrides_prefix_collisions_and_explicit_assignment_wins():
    first = source(data={"X": "first", "A_X": "earlier"})
    second = source(name="later", data={"X": "second"})
    observed, record = inspect(
        [{"name": "A_X", "value": "$(A_X)/explicit"}],
        [
            {"configMapRef": {"name": "settings"}},
            {"configMapRef": {"name": "later"}, "prefix": "A_"},
        ],
        [first, second],
    )
    assert [entry.precedence for entry in observed.entries] == [
        "overridden",
        "effective",
        "overridden",
        "effective",
    ]
    assert resolve(observed, record, 0, [first, second]).text == "second/explicit"


@pytest.mark.parametrize("missing", ["object", "key"])
def test_optional_absence_skips_assignment_without_erasing_prior_binding(missing):
    config = source(state="not-found") if missing == "object" else source(data={})
    observed, record = inspect(
        [
            {"name": "X", "value": "earlier"},
            keyref("X", optional=True),
            {"name": "RESULT", "value": "$(X)"},
        ],
        sources=[config],
    )
    assert observed.entries[1].precedence == "skipped"
    assert observed.entries[0].precedence == "effective"
    assert resolve(observed, record, 2, [config]).text == "earlier"
    assert resolve(observed, record, 1, [config]).reasons == (ReasonCode.OPTIONAL_MISSING,)


def test_optional_missing_envfrom_does_not_create_unknown_barrier():
    first, absent = source(data={"X": "earlier"}), source(name="absent", state="not-found")
    observed, record = inspect(
        [{"name": "RESULT", "value": "$(X)"}],
        [
            {"configMapRef": {"name": "settings"}},
            {"configMapRef": {"name": "absent", "optional": True}},
        ],
        [first, absent],
    )
    assert observed.entries[1].precedence == "skipped"
    assert resolve(observed, record, 0, [first, absent]).text == "earlier"


@pytest.mark.parametrize(
    "state,reason",
    [
        ("not-found", ReasonCode.SOURCE_NOT_FOUND),
        ("forbidden", ReasonCode.SOURCE_FORBIDDEN),
        ("timed-out", ReasonCode.SOURCE_TIMED_OUT),
        ("unreachable", ReasonCode.SOURCE_UNREACHABLE),
        ("invalid", ReasonCode.SOURCE_INVALID),
        ("unsupported", ReasonCode.SOURCE_UNSUPPORTED),
        ("not-collected-limit", ReasonCode.REFERENCE_LIMIT),
    ],
)
def test_source_failures_have_fixed_metadata_and_prefix_scoped_unknown_barriers(state, reason):
    known, absent = (
        source(data={"P_X": "earlier", "X": "known"}),
        source(name="unreadable", state=state),
    )
    observed, record = inspect(
        [
            {"name": "A", "value": "$(P_X)"},
            {"name": "B", "value": "$(X)"},
            {"name": "P_X", "value": "explicit"},
            {"name": "C", "value": "$(P_X)"},
        ],
        [
            {"configMapRef": {"name": "settings"}},
            {"secretRef": {"name": "unreadable"}, "prefix": "P_"},
        ],
        [known, replace(absent, ref=SourceRef("Secret", "team", "unreadable"))],
    )
    actual_sources = [known, replace(absent, ref=SourceRef("Secret", "team", "unreadable"))]
    assert reason in observed.notices and not observed.complete
    if state == "not-collected-limit":
        assert resolve(observed, record, 1, actual_sources).text is None
    else:
        assert resolve(observed, record, 0, actual_sources).text == "$(P_X)"
        assert resolve(observed, record, 0, actual_sources).reasons == (ReasonCode.UNKNOWN_BINDING,)
        assert resolve(observed, record, 1, actual_sources).text == "known"
        assert resolve(observed, record, 3, actual_sources).text == "explicit"


@pytest.mark.parametrize(
    "fields",
    [
        {"data": []},
        {"data": {"plain": 42}},
        {"data": {"bad/key": "value"}},
        {"data": {"plain": "!notbase64"}},
    ],
)
def test_malformed_source_data_is_fixed_invalid_state(fields):
    invalid = source("Secret", **fields)
    observed, record = inspect([keyref("X", kind="secretKeyRef")], sources=[invalid])
    assert observed.sources[0].state == "invalid"
    assert resolve(observed, record, 0, [invalid]).reasons == (ReasonCode.SOURCE_INVALID,)


def test_binarydata_and_stringdata_do_not_become_environment_inputs():
    config = source(binaryData={"plain": "dGV4dA=="})
    observed, record = inspect([keyref("X")], [{"configMapRef": {"name": "settings"}}], [config])
    assert len(observed.entries) == 1 and observed.entries[0].reason == ReasonCode.MISSING_KEY
    assert observed.sources[0].keys[0].section == "binaryData"
    secret = source("Secret", data={"plain": "dGV4dA=="}, stringData={"plain": "must-not-use"})
    observed, record = inspect([keyref("X", kind="secretKeyRef")], sources=[secret])
    assert observed.sources[0].state == "unsupported"
    assert resolve(observed, record, 0, [secret]).text is None


@pytest.mark.parametrize(
    "path,expected,reason",
    [
        ("metadata.name", "owned-pod", None),
        ("metadata.namespace", "team", None),
        ("metadata.uid", "owned-pod-uid", None),
        ("metadata.labels['example.io/normal']", "", None),
        ("metadata.annotations['note']", "private-field-value", None),
        ("metadata.labels['absent']", None, ReasonCode.MISSING_FIELD),
        ("metadata.labels['typed']", None, ReasonCode.MISSING_FIELD),
        ("spec.nodeName", "owned-node", None),
        ("spec.serviceAccountName", "", None),
        ("status.podIP", None, ReasonCode.RUNTIME_FIELD),
        ("status.podIPs", None, ReasonCode.RUNTIME_FIELD),
        ("status.hostIP", None, ReasonCode.RUNTIME_FIELD),
        ("status.hostIPs", None, ReasonCode.RUNTIME_FIELD),
        ("metadata.labels", None, ReasonCode.UNSUPPORTED_FIELD),
        ("metadata.annotations", None, ReasonCode.UNSUPPORTED_FIELD),
        ('metadata.labels["note"]', None, ReasonCode.UNSUPPORTED_FIELD),
        ("metadata.labels['bad\nkey']", None, ReasonCode.UNSUPPORTED_FIELD),
        (None, None, ReasonCode.UNSUPPORTED_FIELD),
        ([], None, ReasonCode.UNSUPPORTED_FIELD),
    ],
)
def test_downward_api_uses_typed_allowlist_and_distinguishes_present_empty(path, expected, reason):
    observed, record = inspect(
        [{"name": "FIELD", "valueFrom": {"fieldRef": {"fieldPath": path}}}],
        metadata={
            "labels": {"example.io/normal": "", "typed": 42},
            "annotations": {"note": "private-field-value"},
        },
        extra={"nodeName": "owned-node", "serviceAccountName": ""},
    )
    result = resolve(observed, record, 0)
    assert (result.text, result.complete, result.reasons) == (
        expected,
        reason is None,
        () if reason is None else (reason,),
    )
    assert "private-field-value" not in repr(observed)


@pytest.mark.parametrize(
    "selector",
    [
        {"fieldPath": "metadata.name", "apiVersion": "v2"},
        {"fieldPath": "metadata.name", "other": "bad"},
    ],
)
def test_downward_unknown_versions_or_members_fail_closed(selector):
    observed, record = inspect([{"name": "X", "valueFrom": {"fieldRef": selector}}])
    assert resolve(observed, record, 0).reasons == (ReasonCode.UNSUPPORTED_FIELD,)


@pytest.mark.parametrize(
    "resource_name,value,divisor,expected",
    [
        ("requests.cpu", "1250m", "1", "2"),
        ("requests.cpu", "1m", "0.0001", "1"),
        ("requests.cpu", "0.0011", "0.0019", "1"),
        ("requests.cpu", "0", "1", "0"),
        ("limits.cpu", "+2", "500m", "4"),
        ("requests.memory", "1.1", "1.9", "1"),
        ("limits.memory", "1Gi", "1Mi", "1024"),
        ("requests.memory", "2Ki", "1Ki", "2"),
        ("requests.ephemeral-storage", "1.1k", "1k", "2"),
        ("limits.ephemeral-storage", "1e3", "1E2", "10"),
        ("requests.memory", ".1", "1", "1"),
        ("requests.memory", "1n", "1u", "1"),
        ("requests.memory", "9007199254740992", "1", "9007199254740992"),
        ("requests.memory", "9007199254740991", "3", "3002399751580331"),
    ],
)
def test_resource_quantities_use_two_stage_rounding_and_reference_float64_ratio(
    resource_name, value, divisor, expected
):
    family, kind = resource_name.split(".")
    observed, record = inspect(
        [
            {
                "name": "AMOUNT",
                "valueFrom": {"resourceFieldRef": {"resource": resource_name, "divisor": divisor}},
            }
        ],
        resources={family: {kind: value}},
    )
    result = resolve(observed, record, 0)
    assert (result.text, result.complete) == (expected, True)


@pytest.mark.parametrize(
    "selector,resources,reason",
    [
        ({"resource": "limits.cpu"}, {}, ReasonCode.NODE_DEPENDENT),
        ({"resource": "limits.memory"}, {"limits": {"memory": "0"}}, ReasonCode.NODE_DEPENDENT),
        ({"resource": "requests.cpu"}, {}, ReasonCode.MISSING_RESOURCE),
        ({"resource": "requests.hugepages-2Mi"}, {}, ReasonCode.UNSUPPORTED_RESOURCE),
        ({"resource": []}, {}, ReasonCode.UNSUPPORTED_RESOURCE),
        ({"resource": "requests.cpu", "unknown": 1}, {}, ReasonCode.UNSUPPORTED_RESOURCE),
        ({"resource": "requests.cpu", "containerName": "absent"}, {}, ReasonCode.MISSING_CONTAINER),
        ({"resource": "requests.cpu", "divisor": "0"}, {}, ReasonCode.INVALID_QUANTITY),
        ({"resource": "requests.cpu", "divisor": "-1"}, {}, ReasonCode.INVALID_QUANTITY),
        ({"resource": "requests.cpu", "divisor": "bogus"}, {}, ReasonCode.INVALID_QUANTITY),
        ({"resource": "requests.cpu", "divisor": 1}, {}, ReasonCode.INVALID_QUANTITY),
        ({"resource": "requests.cpu", "divisor": "1" * 129}, {}, ReasonCode.INVALID_QUANTITY),
        ({"resource": "requests.cpu", "divisor": "1e101"}, {}, ReasonCode.QUANTITY_LIMIT),
        ({"resource": "requests.cpu", "divisor": "1E"}, {}, ReasonCode.QUANTITY_LIMIT),
        ({"resource": "requests.cpu"}, {"requests": {"cpu": "-1"}}, ReasonCode.INVALID_QUANTITY),
        (
            {"resource": "requests.memory"},
            {"requests": {"memory": "9007199254740993"}},
            ReasonCode.QUANTITY_LIMIT,
        ),
        (
            {"resource": "requests.memory"},
            {"requests": {"memory": []}},
            ReasonCode.INVALID_QUANTITY,
        ),
    ],
)
def test_unsupported_missing_node_default_and_invalid_resource_inputs_stay_unresolved(
    selector, resources, reason
):
    observed, record = inspect(
        [{"name": "X", "valueFrom": {"resourceFieldRef": selector}}], resources=resources
    )
    assert resolve(observed, record, 0).reasons == (reason,)


@pytest.mark.parametrize("family", ["containers", "initContainers"])
def test_explicit_resource_container_name_selects_only_regular_or_init(family):
    extra = (
        {"initContainers": [{"name": "other", "resources": {"requests": {"cpu": "250m"}}}]}
        if family == "initContainers"
        else {}
    )
    name = "other" if family == "initContainers" else "worker"
    observed, record = inspect(
        [
            {
                "name": "X",
                "valueFrom": {
                    "resourceFieldRef": {
                        "resource": "requests.cpu",
                        "containerName": name,
                        "divisor": "1m",
                    }
                },
            }
        ],
        extra=extra,
        resources={"requests": {"cpu": "500m"}},
    )
    assert resolve(observed, record, 0).text == ("250" if family == "initContainers" else "500")


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"name": ""},
        {"name": "bad=name", "value": "private"},
        {"name": "bad\x1bname"},
        {"name": "okay", "value": 42},
        {"name": "okay", "unexpected": "private"},
        {"name": "okay", "valueFrom": {}},
        {"name": "okay", "valueFrom": []},
        {
            "name": "okay",
            "value": "private",
            "valueFrom": {"fieldRef": {"fieldPath": "metadata.name"}},
        },
        {"name": "okay", "valueFrom": {"fieldRef": {}, "resourceFieldRef": {}}},
        {"name": "okay", "valueFrom": {"futureField": {"private": "ignored"}}},
        {"name": "okay", "valueFrom": {"configMapKeyRef": {"name": "BAD", "key": "plain"}}},
        {"name": "okay", "valueFrom": {"configMapKeyRef": {"name": 1, "key": "plain"}}},
        {"name": "okay", "valueFrom": {"configMapKeyRef": {"name": "settings", "key": "bad/key"}}},
        {"name": "okay", "valueFrom": {"configMapKeyRef": {"name": "settings", "key": None}}},
        {
            "name": "okay",
            "valueFrom": {
                "configMapKeyRef": {"name": "settings", "key": "plain", "optional": "yes"}
            },
        },
        {
            "name": "okay",
            "valueFrom": {
                "configMapKeyRef": {"name": "settings", "key": "plain", "future": "private"}
            },
        },
    ],
)
def test_invalid_and_unknown_declarations_are_visible_errors_and_never_fabricated_values(env):
    config = source(data={"plain": "actual"})
    observed, record = inspect([env], sources=[config])
    assert observed.entries[0].reason == ReasonCode.INVALID_DECLARATION
    assert resolve(observed, record, 0, [config]).text is None
    assert "private" not in repr(observed)


@pytest.mark.parametrize(
    "declaration",
    [
        {},
        {"configMapRef": {}},
        {"configMapRef": {"name": "BAD"}},
        {"configMapRef": {"name": "settings"}, "secretRef": {"name": "settings"}},
        {"configMapRef": {"name": "settings", "optional": "yes"}},
        {"configMapRef": {"name": "settings", "future": 1}},
        {"configMapRef": {"name": "settings"}, "future": 1},
        {"configMapRef": {"name": "settings"}, "prefix": "P" * 4097},
    ],
)
def test_invalid_envfrom_is_preserved_as_unknown_barrier(declaration):
    config = source(data={"X": "known"})
    observed, record = inspect([{"name": "RESULT", "value": "$(X)"}], [declaration], [config])
    assert observed.entries[0].id == ("envFrom", 0, None)
    assert observed.entries[0].precedence == "unknown"
    assert resolve(observed, record, 0, [config]).complete is False


def test_printable_admitted_names_are_not_restricted_to_shell_identifiers():
    observed, record = inspect(
        [{"name": "a.b-c space:+", "value": "kept"}, {"name": "D", "value": "$(a.b-c space:+)"}]
    )
    assert resolve(observed, record, 1).text == "kept"


def test_runtime_file_source_is_explicitly_unsupported_without_reading_any_file():
    observed, record = inspect(
        [{"name": "FILE", "valueFrom": {"fileKeyRef": {"path": "/no-access", "key": "plain"}}}]
    )
    assert observed.entries[0].origin == "file-key-ref"
    assert resolve(observed, record, 0).reasons == (ReasonCode.UNSUPPORTED_RUNTIME_SOURCE,)


@pytest.mark.parametrize("text", ["", "ordinary", "with\x00nul"])
def test_explicit_data_keys_preserve_empty_and_reject_nul_completion(text):
    config = source(data={"plain": text})
    observed, record = inspect([keyref("X")], sources=[config])
    result = resolve(observed, record, 0, [config])
    assert result.text == text and result.complete is ("\x00" not in text)
    assert observed.entries[0].resolution == (
        "empty-hidden" if text == "" else "text-resolvable-hidden"
    )


def test_binary_key_prevents_disclosure_and_dependent_literal_is_incomplete():
    secret = source("Secret", data={"plain": "/w=="})
    observed, record = inspect(
        [keyref("X", kind="secretKeyRef"), {"name": "Y", "value": "$(X)"}], sources=[secret]
    )
    assert observed.entries[0].resolution == "binary"
    assert resolve(observed, record, 0, [secret]).reasons == (ReasonCode.BINARY_VALUE,)
    assert resolve(observed, record, 1, [secret]).complete is False


def test_missing_source_reads_and_available_without_payload_are_not_successful_empty_sources():
    observed, record = inspect([keyref("X")])
    assert observed.sources[0].state == "unreachable"
    assert resolve(observed, record, 0).text is None
    missing = SourceRead(SourceRef("ConfigMap", "team", "settings"), "available", None, NOW)
    observed, record = inspect([keyref("X")], sources=[missing])
    assert observed.sources[0].state == "invalid"
    assert resolve(observed, record, 0, [missing]).reasons == (ReasonCode.SOURCE_INVALID,)


def test_mismatched_source_identity_never_supplies_a_requested_key():
    wrong = replace(
        source(name="different", data={"plain": "wrong"}),
        ref=SourceRef("ConfigMap", "team", "settings"),
    )
    observed, record = inspect([keyref("X")], sources=[wrong])
    assert observed.sources[0].state == "invalid"
    assert resolve(observed, record, 0, [wrong]).text is None


@pytest.mark.parametrize(
    "change",
    [
        "pod-bytes",
        "source-bytes",
        "source-version",
        "source-uid",
        "source-disappeared",
        "source-appeared",
        "source-count",
        "pod-metadata-only",
        "snapshot-entry",
        "unknown-entry",
    ],
)
def test_selected_resolution_independently_rejects_changed_bindings_and_forged_metadata(change):
    config = source(data={"plain": "first"})
    observed, record = inspect([keyref("X")], sources=[config])
    supplied = [config]
    entry = ("env", 0, None)
    if change == "pod-bytes":
        data = record.manifest
        data["spec"]["containers"][0]["env"].append({"name": "NEW", "value": "second"})
        record = replace(record, _manifest=json.dumps(data).encode())
    elif change == "pod-metadata-only":
        record = replace(record, metadata_only=True)
    elif change == "source-appeared":
        absent = source(state="not-found")
        observed, record = inspect([keyref("X", optional=True)], sources=[absent])
    elif change == "source-disappeared":
        supplied = [source(state="not-found")]
    elif change == "source-count":
        observed = replace(observed, sources=())
    elif change == "snapshot-entry":
        observed = replace(observed, entries=(replace(observed.entries[0], name="other"),))
    elif change == "unknown-entry":
        entry = ("env", 42, None)
    else:
        data = config.record.manifest
        if change == "source-bytes":
            data["data"]["plain"] = "second"
        elif change == "source-version":
            data["metadata"]["resourceVersion"] = "rv-2"
        else:
            data["metadata"]["uid"] = "replacement"
        updated = resource_record(
            ApiResource("", "v1", "configmaps", "ConfigMap", True, frozenset({"get"})), data, "team"
        )
        supplied = [replace(config, record=updated)]
    result = resolve_selected(observed, entry, record, tuple(supplied))
    assert result.text is None and result.complete is False
    assert result.reasons == (
        ReasonCode.ENTRY_UNAVAILABLE if change == "unknown-entry" else ReasonCode.STALE_BINDING,
    )


@pytest.mark.parametrize("change", ["name", "namespace", "uid", "group", "resource", "container"])
def test_build_requires_exact_captured_target(change):
    observed, record = inspect()
    wrong = replace(observed.target, **{change: "different"})
    with pytest.raises(AppError, match="stale"):
        build_inspection(
            record,
            APP,
            (),
            target=wrong,
            snapshot_id=UUID(int=1),
            started_at=NOW,
            observed_at=NOW,
            reads=2,
        )


def test_prefix_barrier_marks_prior_matching_bindings_unknown_and_skips_invalid_names():
    config = source(data={"X": "one"})
    denied = source(name="denied", state="forbidden")
    observed, _record = inspect(
        [{"name": "RESULT", "value": "$(X)"}],
        [{"configMapRef": {"name": "settings"}}, {"configMapRef": {"name": "denied"}}],
        [config, denied],
    )
    assert observed.entries[0].precedence == "unknown"
    invalid, _record = inspect(
        env_from=[{"configMapRef": {"name": "settings"}, "prefix": "="}], sources=[config]
    )
    assert invalid.entries[0].reason == ReasonCode.INVALID_NAME


def test_reference_limit_is_first_use_ordered_and_disables_partial_resolution():
    refs = [{"configMapRef": {"name": f"source-{number}"}} for number in range(33)]
    observed, record = inspect([{"name": "X", "value": "independent"}], refs)
    plan = reference_plan(record, APP)
    assert plan.total == 33 and plan.limited and len(plan.refs) == 32
    assert observed.sources[-1].state == "not-collected-limit"
    assert ReasonCode.REFERENCE_LIMIT in observed.notices
    assert resolve(observed, record, 0).text is None


@pytest.mark.parametrize("reads", [-1, 65, True])
def test_read_budget_evidence_is_bounded_and_typed(reads):
    observed, record = inspect([{"name": "X", "value": "known"}], reads=reads)
    assert ReasonCode.READ_LIMIT in observed.notices
    assert resolve(observed, record, 0).text is None


def test_combined_serialized_input_limit_does_not_parse_or_keep_over_budget_values():
    sources = [
        source(name=f"source-{number}", data={"plain": "x" * 1048576}) for number in range(4)
    ]
    observed, record = inspect(
        [{"name": "X", "value": "known"}],
        [{"configMapRef": {"name": item.ref.name}} for item in sources],
        sources,
    )
    assert ReasonCode.INPUT_LIMIT in observed.notices
    assert all(item.state == "not-collected-limit" for item in observed.sources)
    assert resolve(observed, record, 0, sources).text is None


def test_provenance_row_limit_never_discards_precedence_silently():
    observed, record = inspect([{"name": "X", "value": "v"} for _ in range(MAX_ENV_ROWS + 1)])
    assert ReasonCode.ROW_LIMIT in observed.notices and not observed.complete
    assert resolve(observed, record, 0).text is None


def test_dependency_limit_is_explicit_and_a_forged_clearance_cannot_enable_disclosure():
    observed, record = inspect([{"name": "X", "value": "$(X)" * (MAX_DEPENDENCY_EDGES + 1)}])
    assert ReasonCode.DEPENDENCY_LIMIT in observed.notices
    forged = replace(observed, notices=())
    assert resolve(forged, record, 0).reasons == (ReasonCode.STALE_BINDING,)


def test_selected_resolution_bounds_output_and_working_set_but_does_not_resolve_unrelated_values():
    huge = "x" * (MAX_RESOLUTION_BYTES + 1)
    observed, record = inspect(
        [{"name": "HUGE", "value": huge}, {"name": "SMALL", "value": "known"}]
    )
    assert resolve(observed, record, 0).reasons == (ReasonCode.RESOLUTION_LIMIT,)
    assert resolve(observed, record, 1).text == "known"
    observed, record = inspect(
        [{"name": "A", "value": "x" * 600000}, {"name": "B", "value": "$(A)"}]
    )
    assert resolve(observed, record, 1).reasons == (ReasonCode.RESOLUTION_LIMIT,)
    observed, record = inspect(
        [
            {
                "name": "FIELD",
                "valueFrom": {"fieldRef": {"fieldPath": "metadata.annotations['plain']"}},
            }
        ],
        metadata={"annotations": {"plain": huge}},
    )
    assert resolve(observed, record, 0).reasons == (ReasonCode.RESOLUTION_LIMIT,)


def test_nul_literal_is_incomplete_even_when_the_explicit_preview_retains_it():
    observed, record = inspect([{"name": "X", "value": "with\x00nul"}])
    result = resolve(observed, record, 0)
    assert result.text == "with\x00nul" and result.reasons == (ReasonCode.NUL_VALUE,)


def test_metadata_cells_are_bounded_with_an_explicit_omission_notice():
    config = source(data={"plain": "kept"})
    observed, _record = inspect(
        env_from=[{"configMapRef": {"name": "settings"}, "prefix": "p" * 4096}], sources=[config]
    )
    assert observed.entries[0].reason == ReasonCode.INVALID_NAME
    assert ReasonCode.METADATA_LIMIT in observed.notices
    for section in ("environment", "sources"):
        assert all(
            len(cell) <= 4096
            for row in metadata_table(observed, section).rows
            for cell in row.cells
        )


@pytest.mark.parametrize("source_kind", ["configMapRef", "secretRef"])
def test_envfrom_reference_forms_are_not_accepted_as_explicit_key_selectors(source_kind):
    config = source(
        "Secret" if source_kind == "secretRef" else "ConfigMap",
        data={"plain": "aGVsbG8="} if source_kind == "secretRef" else {"plain": "hello"},
    )
    observed, record = inspect(
        [{"name": "X", "valueFrom": {source_kind: {"name": "settings", "key": "plain"}}}],
        sources=[config],
    )
    assert observed.entries[0].reason == ReasonCode.INVALID_DECLARATION
    assert resolve(observed, record, 0, [config]).text is None


@pytest.mark.parametrize("family,value", [("env", {}), ("envFrom", "malformed")])
def test_malformed_declaration_arrays_are_visible_instead_of_successful_empty_metadata(
    family, value
):
    record = resource("Pod", "owned-pod", spec={"containers": [{"name": "worker", family: value}]})
    target = ResourceTarget(
        SessionIdentity("owned", 1), "", "pods", "team", record.name, record.uid
    )
    observed = build_inspection(
        record,
        APP,
        (),
        target=target,
        snapshot_id=UUID(int=74),
        started_at=NOW,
        observed_at=NOW,
        reads=2,
    )
    assert observed.entries[0].reason == ReasonCode.INVALID_DECLARATION
    assert observed.entries[0].id[0] == family


def test_null_optional_arrays_and_explicit_v1_field_selector_are_supported():
    record = resource(
        "Pod", "owned-pod", spec={"containers": [{"name": "worker", "envFrom": None, "env": None}]}
    )
    target = ResourceTarget(
        SessionIdentity("owned", 1), "", "pods", "team", record.name, record.uid
    )
    observed = build_inspection(
        record,
        APP,
        (),
        target=target,
        snapshot_id=UUID(int=74),
        started_at=NOW,
        observed_at=NOW,
        reads=2,
    )
    assert observed.entries == () and observed.complete
    observed, record = inspect(
        [
            {
                "name": "X",
                "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.name"}},
            }
        ]
    )
    assert resolve(observed, record, 0).text == "owned-pod"


def test_resolution_enforces_its_own_input_limit_against_unrelated_supplied_payloads():
    observed, record = inspect([{"name": "X", "value": "known"}])
    excess = tuple(
        source(name=f"source-{number}", data={"plain": "x" * 1048576}) for number in range(4)
    )
    assert resolve(observed, record, 0, excess).reasons == (ReasonCode.INPUT_LIMIT,)


@pytest.mark.parametrize("value,divisor", [("1K", "1"), ("1", "1K")])
def test_uppercase_decimal_k_is_not_a_kubernetes_quantity_suffix(value, divisor):
    observed, record = inspect(
        [
            {
                "name": "AMOUNT",
                "valueFrom": {
                    "resourceFieldRef": {"resource": "requests.memory", "divisor": divisor}
                },
            }
        ],
        resources={"requests": {"memory": value}},
    )
    result = resolve(observed, record, 0)
    assert result.text is None and result.reasons == (ReasonCode.INVALID_QUANTITY,)
