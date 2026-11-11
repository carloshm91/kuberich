"""Default inspection redaction, identity association, field names and literal search."""

import copy

import pytest
import yaml

from kuberich.domain.inspection import (
    REDACTED,
    document,
    inspection_documents,
    redacted,
    text_matches,
)
from kuberich.domain.resources import resource_record
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.inspection import EVENTS
from tests.support.pods import pod


def target():
    return ResourceTarget(SessionIdentity("owned", 1), "", "pods", "team", "api", "owned-api")


def event(uid="owned-api", namespace="team", *, regarding=False):
    return resource_record(
        EVENTS,
        {
            "metadata": {"name": "event", "namespace": "team", "uid": "event-uid"},
            "regarding" if regarding else "involvedObject": {"uid": uid, "namespace": namespace},
            "type": "Warning",
            "reason": "BackOff",
            "message": "[red]literal[/red] token=synthetic-hidden-value",
            "count": 3,
        },
        "team",
    )


def test_pod_details_api_serialization_fields_managed_and_uid_events_are_redacted():
    raw = pod("api")
    raw.update(apiVersion="v1", kind="Pod")
    raw["metadata"].update(
        annotations={"last-applied": "synthetic-hidden-value"},
        managedFields=[
            {
                "manager": "kubectl",
                "operation": "Update",
                "fieldsV1": {"v:synthetic-hidden-value": {}},
            }
        ],
    )
    raw["spec"].update(nodeName="worker", serviceAccountName="default", restartPolicy="Always")
    raw["spec"]["containers"][0].update(
        env=[{"name": "ORDINARY", "value": "synthetic-hidden-value"}],
        args=["synthetic-hidden-value"],
        command=["synthetic-hidden-value"],
    )
    original = copy.deepcopy(raw)
    result = inspection_documents(
        raw, (event(), event("other"), event(namespace="other"), event(regarding=True)), target()
    )
    assert raw == original
    for text in (result.yaml, result.managed_yaml, result.details, result.events):
        assert "synthetic-hidden-value" not in text and REDACTED in text
    regular, managed = yaml.safe_load(result.yaml), yaml.safe_load(result.managed_yaml)
    assert "managedFields" not in regular["metadata"]
    assert managed["metadata"]["managedFields"][0]["manager"] == "kubectl"
    assert managed["metadata"]["managedFields"][0]["fieldsV1"] == REDACTED
    assert regular["status"]["containerStatuses"][0]["restartCount"] == 0
    details = yaml.safe_load(result.details)
    assert details["scheduling"]["nodeName"] == "worker"
    assert len(yaml.safe_load(result.events)) == 2
    assert "[red]literal[/red]" in result.events


@pytest.mark.parametrize("kind", ["Secret", "ConfigMap"])
def test_opaque_payloads_hidden_without_losing_api_names_or_numbers(kind):
    raw = {
        "kind": kind,
        "apiVersion": "v1",
        "metadata": {},
        "data": {"synthetic-hidden-value": "do-not-display"},
        "stringData": "do-not-display",
        "binaryData": {"file": "do-not-display"},
        "password": "do-not-display",
        "immutable": True,
    }
    result = inspection_documents(raw, (), target())
    value = yaml.safe_load(result.yaml)
    assert value["data"] == {"synthetic-hidden-value": REDACTED}
    assert value["stringData"] == REDACTED and value["immutable"] is True
    assert "do-not-display" not in result.yaml
    assert "No related events" in result.events
    assert yaml.safe_load(result.details)["spec"] == {}


def test_controls_credentials_and_plain_values_preserve_safe_readability():
    safe = redacted(
        {
            "values": ["hello\nworld", "Bearer abc123", "\x1b[2J", 4, None],
            "secretKeyRef": {"name": "existing", "key": "field"},
        }
    )
    assert safe["values"][0] == "hello\nworld"
    assert "abc123" not in str(safe) and "\x1b" not in str(safe)
    assert safe["secretKeyRef"]["name"] == "existing"


def test_nested_and_oversized_fields_are_rejected_without_partial_exports():
    with pytest.raises(AppError, match="nesting"):
        redacted({}, depth=65)
    with pytest.raises(AppError, match="field exceeds"):
        redacted("x" * 65537)
    with pytest.raises(AppError, match="not truncated"):
        document("x" * 262145)


def test_search_is_literal_case_insensitive_keeps_character_coordinates_and_bounds():
    assert text_matches("你好 [x] [X]\nsecond [x]", "[x]") == ((0, 3, 6), (0, 7, 10), (1, 7, 10))
    assert text_matches("anything", "") == ()
    assert text_matches("anything", "x" * 257) == ()
    assert text_matches("anything", "absent") == ()


def test_malformed_pod_and_event_reference_and_large_events_keep_resource_details():
    raw = {"kind": "Pod", "metadata": {}, "spec": None}
    with pytest.raises(AppError, match="specification"):
        inspection_documents(raw, (), target())
    raw["spec"] = {}
    malformed = event().manifest
    malformed["involvedObject"] = "invalid"
    record = resource_record(EVENTS, malformed, "team")
    assert "No related events" in inspection_documents(raw, (record,), target()).events
    large = event().manifest
    large["message"] = "x" * 60000
    record = resource_record(EVENTS, large, "team")
    result = inspection_documents(raw, (record,) * 5, target())
    assert "events exceed" in result.events and "containers" in result.details


def test_match_cap_bounds_memory_for_large_ordinary_documents():
    assert len(text_matches("x" * 20000, "x")) == 10000


@pytest.mark.parametrize(
    "kind",
    [
        "ValidatingAdmissionPolicy",
        "MutatingAdmissionPolicy",
        "ValidatingAdmissionPolicyBinding",
        "MutatingAdmissionPolicyBinding",
        "ValidatingWebhookConfiguration",
        "MutatingWebhookConfiguration",
    ],
)
@pytest.mark.parametrize("version", ["v1", "v1beta1", "v1alpha1", "future"])
def test_admission_payload_concealment_precedes_default_yaml_managed_copy_and_details(
    kind, version
):
    canary = "SYNTHETIC_ADMISSION_FREEFORM_PAYLOAD"
    raw = {
        "apiVersion": "admissionregistration.k8s.io/" + version,
        "kind": kind,
        "metadata": {"name": "owned", "uid": "owned-uid"},
        "spec": {
            "policyName": "owned-policy",
            "validations": [{"expression": canary, "message": canary, "messageExpression": canary}],
            "variables": [{"name": "declared", "expression": canary}],
            "matchConditions": [{"name": "declared", "expression": canary}],
            "auditAnnotations": [{"key": "declared", "valueExpression": canary}],
            "mutations": [
                {"patchType": "ApplyConfiguration", "applyConfiguration": {"expression": canary}},
                {"patchType": "JSONPatch", "jsonPatch": {"expression": canary, "patch": canary}},
            ],
        },
        "status": {
            "conditions": [{"type": "Ready", "status": "True", "message": canary}],
            "typeChecking": {
                "expressionWarnings": [{"fieldRef": "spec.validations[0]", "warning": canary}]
            },
        },
        "webhooks": [
            {
                "name": "declared.webhook",
                "clientConfig": {
                    "url": canary,
                    "caBundle": canary,
                    "service": {"name": "owned-service", "path": canary},
                },
                "matchConditions": [{"name": "declared", "expression": canary}],
            }
        ],
    }
    original = copy.deepcopy(raw)
    documents = inspection_documents(raw, (), target())
    assert raw == original
    for text in (documents.yaml, documents.managed_yaml, documents.details):
        assert canary not in text
        assert REDACTED in text
    safe = yaml.safe_load(documents.yaml)
    assert safe["spec"]["policyName"] == "owned-policy"
    assert safe["spec"]["mutations"][0]["patchType"] == "ApplyConfiguration"
    assert safe["webhooks"][0]["clientConfig"]["service"]["name"] == "owned-service"


@pytest.mark.parametrize(
    "identity",
    [
        {},
        {"apiVersion": "other.example/v1", "kind": "ValidatingAdmissionPolicy"},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "Other"},
        {"apiVersion": None, "kind": "ValidatingAdmissionPolicy"},
    ],
)
def test_admission_concealment_preserves_other_resources_intentional_plain_fields(identity):
    plain = {
        "expression": "plain-expression",
        "message": "plain-message",
        "url": "https://owned.example/plain",
        "path": "/plain",
    }
    safe = redacted({**identity, "spec": plain})
    assert safe["spec"] == plain


def test_malformed_admission_kind_is_not_treated_as_a_reviewed_schema():
    raw = {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": [],
        "spec": {"expression": "plain"},
    }
    assert redacted(raw)["spec"] == {"expression": "plain"}


@pytest.mark.parametrize("kind", ["Pod", "Node"])
def test_existing_inspection_composes_bounded_scheduling_declarations_without_losing_original_fields(
    kind,
):
    raw = {
        "apiVersion": "v1",
        "kind": kind,
        "metadata": {},
        "spec": {
            "nodeName": "observed-node",
            "serviceAccountName": "default",
            "priorityClassName": "owned-priority",
            "nodeSelector": {"zone": "owned"},
            "tolerations": [{"key": "dedicated", "operator": "Exists", "effect": "NoSchedule"}],
            "taints": [{"key": "dedicated", "value": "owned", "effect": "NoSchedule"}],
        },
    }
    result = yaml.safe_load(inspection_documents(raw, (), target()).details)
    assert "schedulingDeclarations" in result and result["schedulingNotices"]
    serialized = str(result["schedulingDeclarations"])
    assert "declared" in serialized and "dedicated" in serialized
    if kind == "Pod":
        assert result["scheduling"]["nodeName"] == "observed-node"
        assert result["scheduling"]["serviceAccountName"] == "default"
    else:
        assert result["spec"]["taints"][0]["key"] == "dedicated"


def test_scheduling_projection_cannot_reintroduce_a_concealed_selector_value():
    marker = "SYNTHETIC_LABEL_VALUE_80"
    raw = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {},
        "spec": {"nodeSelector": {"token": marker}, "containers": []},
    }
    result = inspection_documents(raw, (), target())
    for text in (result.yaml, result.managed_yaml, result.details):
        assert marker not in text
    assert "schedulingDeclarations" in result.details
