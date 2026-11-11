"""Admission payloads stay concealed across independent inspection and artifact codecs."""

import copy

import pytest
import yaml

from kuberich.domain.admission_privacy import admission_document, concealed_admission_field
from kuberich.domain.exports import DocumentSource, ResourceSource, SupportSource, read_artifact
from kuberich.domain.resources import ApiResource, resource_record
from tests.unit.test_exports import ID, capture, prepared, report

MARKER = "SYNTHETIC_ADMISSION_ARBITRARY_PAYLOAD"
KINDS = (
    ("ValidatingAdmissionPolicy", "validatingadmissionpolicies"),
    ("ValidatingAdmissionPolicyBinding", "validatingadmissionpolicybindings"),
    ("MutatingAdmissionPolicy", "mutatingadmissionpolicies"),
    ("MutatingAdmissionPolicyBinding", "mutatingadmissionpolicybindings"),
    ("ValidatingWebhookConfiguration", "validatingwebhookconfigurations"),
    ("MutatingWebhookConfiguration", "mutatingwebhookconfigurations"),
)


def source(kind, plural):
    resource = ApiResource(
        "admissionregistration.k8s.io", "v1beta1", plural, kind, False, frozenset({"get"})
    )
    body = {
        "apiVersion": resource.api_version,
        "kind": kind,
        "metadata": {"name": "owned", "uid": "owned-uid", "resourceVersion": "opaque"},
        "spec": {
            "policyName": "owned-policy",
            "validations": [{"expression": MARKER, "message": MARKER, "messageExpression": MARKER}],
            "variables": [{"name": "owned", "expression": MARKER}],
            "auditAnnotations": [{"key": "owned", "valueExpression": MARKER}],
            "mutations": [
                {"patchType": "JSONPatch", "jsonPatch": {"expression": MARKER, "patch": MARKER}}
            ],
        },
        "status": {
            "typeChecking": {
                "expressionWarnings": [{"fieldRef": "spec.validations[0]", "warning": MARKER}]
            }
        },
        "webhooks": [
            {
                "clientConfig": {
                    "url": MARKER,
                    "caBundle": MARKER,
                    "service": {"name": "owned", "path": MARKER},
                },
                "matchConditions": [{"name": "owned", "expression": MARKER}],
            }
        ],
    }
    return ResourceSource(resource=resource, record=resource_record(resource, body)), body


@pytest.mark.parametrize("kind,plural", KINDS)
def test_direct_document_sensitive_preview_and_nested_support_share_default_concealment(
    kind, plural
):
    import json

    resource, body = source(kind, plural)
    original = copy.deepcopy(body)
    default = prepared(resource, "resource-yaml")
    document = prepared(DocumentSource(page="yaml", text=yaml.safe_dump(body)), "resource-yaml")
    nested = prepared(
        SupportSource(resource=capture(resource)),
        "support",
        report_json=json.dumps(report()).encode(),
    )
    for result in (default, document, nested):
        assert MARKER.encode() not in result.payload
        assert MARKER not in result.preview
        assert b"[REDACTED]" in result.payload
        assert read_artifact(result.payload, artifact_id=ID).payload == result.payload
    sensitive = prepared(resource, "resource-yaml", sensitive=True)
    assert MARKER.encode() in sensitive.payload
    assert MARKER not in sensitive.preview
    assert read_artifact(sensitive.payload, artifact_id=ID).payload == default.payload
    revealed = read_artifact(sensitive.payload, artifact_id=ID, sensitive=True)
    assert MARKER.encode() in revealed.payload and MARKER not in revealed.preview
    assert body == original


@pytest.mark.parametrize("container", ["list", "document"])
def test_nested_admission_objects_in_generic_documents_use_their_own_descriptor(container):
    _resource, body = source(*KINDS[0])
    raw = {
        "apiVersion": "v1",
        "kind": "List",
        "metadata": {"name": "owned-list", "uid": "list-uid"},
        "items": [body],
    }
    if container == "list":
        api = ApiResource("", "v1", "lists", "List", False, frozenset({"get"}))
        retained = ResourceSource(resource=api, record=resource_record(api, raw))
    else:
        retained = DocumentSource(page="yaml", text=yaml.safe_dump(raw))
    assert MARKER.encode() not in prepared(retained, "resource-yaml").payload


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {},
        {"apiVersion": 3},
        {"apiVersion": "other.example/v1", "kind": "ValidatingAdmissionPolicy"},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": []},
        {"apiVersion": "admissionregistration.k8s.io/v1", "kind": "Other"},
    ],
)
def test_only_recognized_admission_descriptors_enable_schema_payload_concealment(value):
    assert not admission_document(value)
    assert not concealed_admission_field("ordinary")


def test_other_resource_fields_remain_available_in_default_exports():
    api = ApiResource("other.example", "v1", "objects", "Object", False, frozenset({"get"}))
    body = {
        "metadata": {"name": "owned", "uid": "owned"},
        "spec": {
            "expression": "ordinary",
            "message": "ordinary",
            "url": "ordinary",
            "path": "ordinary",
        },
    }
    resource = ResourceSource(resource=api, record=resource_record(api, body))
    assert prepared(resource, "resource-yaml").payload.count(b"ordinary") == 4


@pytest.mark.parametrize(
    "version,recognized",
    [
        ("admissionregistration.k8s.io/v1", True),
        ("admissionregistration.k8s.io/v1beta1", True),
        ("admissionregistration.k8s.io/v1alpha1", True),
        ("admissionregistration.k8s.io/future", True),
        ("admissionregistration.k8s.io/", True),
        ("admissionregistration.k8s.io", False),
        ("https://admissionregistration.k8s.io/v1", False),
        ("foreign.example/admissionregistration.k8s.io/v1", False),
        ("admissionregistration.k8s.io.foreign.example/v1", False),
        ("foreign-admissionregistration.k8s.io/v1", False),
    ],
)
def test_api_group_classification_uses_literal_partition_and_preserves_version_independent_privacy(
    version, recognized
):
    from kuberich.domain.inspection import REDACTED, redacted

    body = {
        "apiVersion": version,
        "kind": "ValidatingAdmissionPolicy",
        "spec": {"expression": MARKER},
    }
    assert admission_document(body) is recognized
    assert redacted(body)["spec"]["expression"] == (REDACTED if recognized else MARKER)
