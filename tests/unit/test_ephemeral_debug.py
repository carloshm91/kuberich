"""Permanent debug intent, complete-name validation and remote instance evidence."""

import copy
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from kuberich.domain.ephemeral_debug import (
    EphemeralDebugOptions,
    admitted_profile,
    append_identity,
    debug_session_row,
    declaration,
    discover_ephemeral,
    inspect_debug_instance,
    new_debug_name,
    prepare_intent,
    session_rows,
    validate_current,
    verify_debug_declaration,
    verify_debug_instance,
)
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError

IMAGE = "registry.invalid/debug@sha256:" + "a" * 64


def target():
    return ResourceTarget(SessionIdentity("synthetic", 1), "", "pods", "team", "owned", "uid-1")


def options(**kwargs):
    return EphemeralDebugOptions("debug-one", IMAGE, ("/bin/sh",), **kwargs)


def pod():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": "owned",
            "namespace": "team",
            "uid": "uid-1",
            "resourceVersion": "opaque/version",
        },
        "spec": {
            "containers": [{"name": "work", "image": "synthetic"}],
            "initContainers": [{"name": "init", "image": "synthetic"}],
        },
        "status": {
            "phase": "Running",
            "containerStatuses": [
                {
                    "name": "work",
                    "containerID": "runtime://work-1",
                    "restartCount": 0,
                    "state": {"running": {"startedAt": "2026-11-10T00:00:00Z"}},
                }
            ],
            "initContainerStatuses": [{"name": "init", "state": {"running": {}}}],
        },
    }


def appended(intent, value):
    result = copy.deepcopy(value)
    result["spec"].setdefault("ephemeralContainers", []).append(declaration(intent.options))
    result["metadata"]["resourceVersion"] = "opaque/append"
    return result


def test_review_is_immutable_bounded_and_never_contains_old_configuration():
    value = pod()
    value["spec"]["ephemeralContainers"] = [
        {
            "name": "old",
            "image": IMAGE,
            "env": [{"name": "SENSITIVE", "value": "private-existing-value"}],
        }
    ]
    intent = prepare_intent(target(), value, options(target_container="work"))
    operations = json.loads(intent.body)
    assert operations[:2] == [
        {"op": "test", "path": "/metadata/uid", "value": "uid-1"},
        {"op": "test", "path": "/metadata/resourceVersion", "value": "opaque/version"},
    ]
    assert operations[2]["path"] == "/spec/ephemeralContainers/-"
    assert intent.path == "/api/v1/namespaces/team/pods/owned/ephemeralcontainers"
    assert "permanently" in intent.effects[0]
    assert "private-existing" not in repr(intent) and b"private-existing" not in intent.body
    assert len(intent.previous_entries[0]) == 32
    with pytest.raises(FrozenInstanceError):
        intent.options.name = "other"
    validate_current(intent, value)
    assert len({new_debug_name() for _ in range(5)}) == 5


@pytest.mark.parametrize("existing", [None, []])
def test_absent_or_empty_list_uses_conditional_whole_list_add(existing):
    value = pod()
    if existing is not None:
        value["spec"]["ephemeralContainers"] = existing
    intent = prepare_intent(target(), value, options())
    assert json.loads(intent.body)[2] == {
        "op": "add",
        "path": "/spec/ephemeralContainers",
        "value": [declaration(intent.options)],
    }
    assert intent.target_instance is None
    assert admitted_profile(intent, appended(intent, value))


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": "a" * 64},
        {"name": "Upper"},
        {"name": "a.b"},
        {"image": "debug:latest"},
        {"image": "x" * 1025},
        {"image": None},
        {"command": []},
        {"command": ()},
        {"command": ("x",) * 33},
        {"command": ("\x1b[31m",)},
        {"command": ("x" * 8192, "a")},
        {"command": ("\ud800",)},
        {"target_container": "bad/name"},
        {"run_as_user": 0},
        {"run_as_group": True},
        {"run_as_user": 2**31},
        {"read_only_root_filesystem": 1},
    ],
)
def test_reject_unsupported_or_unbounded_options(change):
    with pytest.raises(AppError):
        replace(options(), **change)


def test_reviewed_supported_security_is_exact_and_no_root_fallback():
    selected = replace(
        options(target_container="init"),
        run_as_user=1234,
        run_as_group=2345,
        read_only_root_filesystem=False,
    )
    intent = prepare_intent(target(), pod(), selected)
    assert intent.target_instance.category == "initContainers"
    security = declaration(selected)["securityContext"]
    assert security == {
        "privileged": False,
        "allowPrivilegeEscalation": False,
        "runAsNonRoot": True,
        "runAsUser": 1234,
        "runAsGroup": 2345,
        "readOnlyRootFilesystem": False,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }


@pytest.mark.parametrize(
    "path,value",
    [
        (("apiVersion",), "apps/v1"),
        (("kind",), "Node"),
        (("metadata", "name"), "foreign"),
        (("metadata", "namespace"), "other"),
        (("metadata", "uid"), "replacement"),
        (("metadata", "resourceVersion"), ""),
        (("metadata", "deletionTimestamp"), "now"),
        (("metadata", "annotations"), {"kubernetes.io/config.mirror": ""}),
        (("status", "phase"), "Succeeded"),
        (("status", "phase"), "Pending"),
        (("spec", "os"), {"name": "windows"}),
        (("spec", "containers"), []),
        (("spec", "containers"), None),
        (("spec", "initContainers"), [{}]),
        (("spec", "hostPID"), "true"),
        (("spec", "securityContext"), {"runAsUser": "private-invalid"}),
        (("spec", "securityContext"), {"runAsNonRoot": "yes"}),
        (("spec", "imagePullSecrets"), [{"name": "bad/name"}]),
    ],
)
def test_invalid_or_unusable_pod_never_prepares(path, value):
    payload = pod()
    holder = payload
    for key in path[:-1]:
        holder = holder[key]
    holder[path[-1]] = value
    with pytest.raises(AppError):
        prepare_intent(target(), payload, options())


@pytest.mark.parametrize(
    "selected",
    [
        lambda t: replace(t, group="apps"),
        lambda t: replace(t, resource="nodes"),
        lambda t: replace(t, namespace=None),
    ],
)
def test_only_exact_pod_address_is_allowed(selected):
    with pytest.raises(AppError):
        prepare_intent(selected(target()), pod(), options())


@pytest.mark.parametrize("category", ["containers", "initContainers", "ephemeralContainers"])
def test_every_name_including_completed_debug_entries_is_reserved(category):
    value = pod()
    value["spec"].setdefault(category, []).append({"name": "debug-one", "image": IMAGE})
    with pytest.raises(AppError, match="already exists"):
        prepare_intent(target(), value, options())
    value["spec"][category].append({"name": "work"})
    with pytest.raises(AppError, match="ambiguous"):
        prepare_intent(target(), value, replace(options(), name="unique"))


def test_complete_launch_name_validation_refuses_oversize_instead_of_truncation():
    value = pod()
    value["spec"]["ephemeralContainers"] = [
        {"name": f"old-{i}", "image": IMAGE} for i in range(4096)
    ]
    with pytest.raises(AppError, match="complete-read"):
        prepare_intent(target(), value, options())
    value["spec"]["ephemeralContainers"].append({"name": "overflow"})
    with pytest.raises(AppError, match="complete-read"):
        prepare_intent(target(), value, options())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["status"]["containerStatuses"].clear(),
        lambda p: p["status"]["containerStatuses"].append(
            copy.deepcopy(p["status"]["containerStatuses"][0])
        ),
        lambda p: p["status"]["containerStatuses"][0].update(state={"terminated": {"exitCode": 0}}),
        lambda p: p["status"]["containerStatuses"][0].update(restartCount=-1),
        lambda p: p["status"]["containerStatuses"][0].update(containerID="\x1b"),
        lambda p: p["status"]["containerStatuses"][0].update(state={"running": {}, "waiting": {}}),
    ],
)
def test_target_requires_one_observed_running_instance(mutation):
    value = pod()
    mutation(value)
    with pytest.raises(AppError):
        prepare_intent(target(), value, options(target_container="work"))


@pytest.mark.parametrize("name", ["absent", "old"])
def test_target_cannot_be_an_ephemeral_container(name):
    value = pod()
    value["spec"]["ephemeralContainers"] = [{"name": "old", "image": IMAGE}]
    with pytest.raises(AppError, match="regular or init"):
        prepare_intent(target(), value, options(target_container=name))


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p["metadata"].update(resourceVersion="new"), "resourceVersion"),
        (
            lambda p: p["spec"].update(ephemeralContainers=[{"name": "other", "image": IMAGE}]),
            "declarations changed",
        ),
        (
            lambda p: p["status"]["containerStatuses"][0].update(
                containerID="runtime://replacement"
            ),
            "instance",
        ),
        (lambda p: p["spec"].update(hostPID=True), "context changed"),
        (lambda p: p["spec"]["containers"][0].update(image="changed"), "context changed"),
    ],
)
def test_fresh_validation_never_rebases_a_review(mutation, match):
    value = pod()
    intent = prepare_intent(target(), value, options(target_container="work"))
    mutation(value)
    with pytest.raises(AppError, match=match):
        validate_current(intent, value)


def test_opaque_version_can_be_ignored_only_for_explicit_postappend_check():
    value = pod()
    value["spec"].update(
        securityContext={
            "runAsUser": 1000,
            "runAsGroup": 2000,
            "runAsNonRoot": True,
            "fsGroup": 3000,
        },
        imagePullSecrets=[{"name": "pull-reference"}],
    )
    intent = prepare_intent(target(), value, options())
    value["metadata"]["resourceVersion"] = "opaque/different"
    validate_current(intent, value, require_version=False)
    assert json.loads(intent.inherited)["imagePullSecrets"] == ["pull-reference"]


def test_receipt_allows_only_enumerated_ordinary_defaults():
    value = pod()
    intent = prepare_intent(target(), value, options())
    response = appended(intent, value)
    expected = admitted_profile(intent, response)
    entry = response["spec"]["ephemeralContainers"][0]
    entry.pop("terminationMessagePath")
    entry.pop("terminationMessagePolicy")
    entry.pop("stdinOnce")
    entry["resources"] = {}
    assert admitted_profile(intent, response) == expected
    assert append_identity(intent, response).name == "debug-one"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p["spec"]["ephemeralContainers"][-1].update(
            env=[{"name": "injected", "value": "private"}]
        ),
        lambda p: p["spec"]["ephemeralContainers"][-1].update(
            volumeMounts=[{"name": "token", "mountPath": "/token"}]
        ),
        lambda p: p["spec"]["ephemeralContainers"][-1].update(command=["/bin/other"]),
        lambda p: p["spec"]["ephemeralContainers"][-1].update(resources={"limits": {"cpu": "1"}}),
        lambda p: p["spec"]["ephemeralContainers"][-1]["securityContext"].update(privileged=True),
        lambda p: p["spec"]["ephemeralContainers"].append({"name": "injected", "image": IMAGE}),
        lambda p: p["spec"]["containers"][0].update(image="injected"),
    ],
)
def test_admission_profile_drift_keeps_independent_append_identity(mutation):
    value = pod()
    intent = prepare_intent(target(), value, options())
    response = appended(intent, value)
    mutation(response)
    assert append_identity(intent, response).target == intent.target
    with pytest.raises(AppError):
        admitted_profile(intent, response)


def test_prior_entries_cannot_be_removed_edited_or_reordered_and_identity_requires_addition():
    value = pod()
    value["spec"]["ephemeralContainers"] = [{"name": "old", "image": IMAGE}]
    intent = prepare_intent(target(), value, options())
    with pytest.raises(AppError, match="exactly one"):
        append_identity(intent, value)
    response = appended(intent, value)
    response["spec"]["ephemeralContainers"][0]["image"] = "changed"
    with pytest.raises(AppError, match="existing ephemeral"):
        admitted_profile(intent, response)


def test_running_receipt_rechecks_workload_target_and_debug_instance():
    value = pod()
    intent = prepare_intent(target(), value, options(target_container="work"))
    response = appended(intent, value)
    response["status"]["ephemeralContainerStatuses"] = [
        {
            "name": "debug-one",
            "containerID": "runtime://debug",
            "restartCount": 0,
            "state": {"running": {}},
        }
    ]
    profile = admitted_profile(intent, response)
    instance = verify_debug_instance(intent, response, profile)
    assert instance.container_id == "runtime://debug"
    observed = inspect_debug_instance(intent.target, response, "debug-one")
    assert observed[:2] == (instance, intent.target_instance)
    assert len(observed[2]) == 32
    with pytest.raises(AppError, match="context changed"):
        verify_debug_instance(intent, response, b"other")
    response["status"]["containerStatuses"][0]["restartCount"] = 1
    with pytest.raises(AppError, match="context changed"):
        verify_debug_instance(intent, response, profile)
    with pytest.raises(AppError, match="Select one"):
        inspect_debug_instance(intent.target, response, "absent")


def test_existing_untargeted_attach_requires_explicit_running_status():
    value = pod()
    intent = prepare_intent(target(), value, options())
    response = appended(intent, value)
    response["status"]["ephemeralContainerStatuses"] = [
        {"name": "debug-one", "state": {"running": {}}}
    ]
    assert inspect_debug_instance(intent.target, response, "debug-one")[1] is None
    response["status"]["ephemeralContainerStatuses"][0]["state"] = {"terminated": {"exitCode": 0}}
    with pytest.raises(AppError):
        inspect_debug_instance(intent.target, response, "debug-one")


def discovery():
    return {
        "kind": "APIResourceList",
        "groupVersion": "v1",
        "resources": [
            {
                "name": "pods/ephemeralcontainers",
                "namespaced": True,
                "kind": "Pod",
                "verbs": ["get", "patch"],
            }
        ],
    }


def test_discovery_is_exact_subresource_capability_and_never_guessed():
    discover_ephemeral(discovery())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(kind="APIGroupList"),
        lambda p: p.update(groupVersion="v2"),
        lambda p: p.update(resources=[]),
        lambda p: p["resources"].append(p["resources"][0]),
        lambda p: p["resources"][0].update(namespaced=False),
        lambda p: p["resources"][0].update(kind="Other"),
        lambda p: p["resources"][0].update(verbs=None),
        lambda p: p["resources"][0].update(verbs=[1]),
        lambda p: p["resources"][0].update(verbs=["get"]),
    ],
)
def test_missing_or_malformed_discovery_refuses_support(mutation):
    value = discovery()
    mutation(value)
    with pytest.raises(AppError):
        discover_ephemeral(value)


@pytest.mark.parametrize(
    "state,expected,reason,code",
    [
        (None, "pending", None, None),
        ({"running": {}}, "running", None, None),
        (
            {"waiting": {"reason": "ImagePullBackOff", "message": "private-freeform"}},
            "waiting",
            "ImagePullBackOff",
            None,
        ),
        ({"waiting": {}}, "waiting", None, None),
        (
            {"terminated": {"exitCode": 2, "reason": "Error", "message": "private-freeform"}},
            "terminated",
            "Error",
            2,
        ),
        ({"terminated": {"exitCode": 0}}, "terminated", None, 0),
        ({"terminated": {"exitCode": "bad"}}, "unknown", None, None),
        ({"running": {}, "terminated": {}}, "unknown", None, None),
        ({}, "unknown", None, None),
        ({"other": {}}, "unknown", None, None),
        ({"waiting": {"reason": "\x1b[31m"}}, "unknown", None, None),
    ],
)
def test_rows_distinguish_remote_states_without_freeform_output(state, expected, reason, code):
    value = pod()
    value["spec"]["ephemeralContainers"] = [{"name": "old", "image": IMAGE}]
    if state is not None:
        value["status"]["ephemeralContainerStatuses"] = [{"name": "old", "state": state}]
    observation = session_rows(target(), value)
    row = observation.rows[0]
    assert (row.state, row.reason, row.exit_code) == (expected, reason, code)
    assert not observation.incomplete and "private-freeform" not in repr(observation)


def test_session_display_is_bounded_but_names_are_never_truncated_for_launch():
    value = pod()
    value["spec"]["ephemeralContainers"] = [
        {"name": f"old-{i}", "image": IMAGE} for i in range(257)
    ]
    observation = session_rows(target(), value)
    assert len(observation.rows) == 256 and observation.incomplete
    assert debug_session_row(target(), value, "old-256").state == "pending"
    with pytest.raises(AppError, match="unavailable"):
        debug_session_row(target(), value, "absent")
    with pytest.raises(AppError, match="already exists"):
        prepare_intent(target(), value, replace(options(), name="old-256"))
    value["status"]["ephemeralContainerStatuses"] = [
        {"name": "old-0", "state": {"running": {}}}
    ] * 2
    assert session_rows(target(), value).rows[0].state == "unknown"
    value["spec"]["ephemeralContainers"].append(value["spec"]["ephemeralContainers"][0])
    with pytest.raises(AppError, match="ambiguous names"):
        session_rows(target(), value)


def test_nonfinite_remote_declarations_refuse_fingerprints():
    value = pod()
    value["spec"]["ephemeralContainers"] = [
        {"name": "old", "image": IMAGE, "unknown": float("nan")}
    ]
    with pytest.raises(AppError, match="finite"):
        prepare_intent(target(), value, options())


def test_later_append_does_not_invalidate_an_earlier_verified_entry():
    value = pod()
    intent = prepare_intent(target(), value, options())
    response = appended(intent, value)
    expected = admitted_profile(intent, response)
    response["spec"]["ephemeralContainers"].append({"name": "later", "image": IMAGE})
    verify_debug_declaration(intent, response, expected)
    with pytest.raises(AppError, match="addition count"):
        admitted_profile(intent, response)
