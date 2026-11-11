"""Descriptor-aware concealment for admission declarations in ordinary documents."""

from typing import Any

_ADMISSION_KINDS = frozenset(
    {
        "ValidatingAdmissionPolicy",
        "ValidatingAdmissionPolicyBinding",
        "MutatingAdmissionPolicy",
        "MutatingAdmissionPolicyBinding",
        "ValidatingWebhookConfiguration",
        "MutatingWebhookConfiguration",
    }
)
_ADMISSION_PAYLOADS = frozenset(
    {
        "expression",
        "message",
        "messageExpression",
        "valueExpression",
        "warning",
        "patch",
        "url",
        "path",
    }
)


def admission_document(value: Any) -> bool:
    """Classify the Kubernetes group while keeping version interpretation separate."""
    if not isinstance(value, dict):
        return False
    version, kind = value.get("apiVersion"), value.get("kind")
    if not isinstance(version, str):
        return False
    group, separator, _version = version.partition("/")
    return (
        group == "admissionregistration.k8s.io"
        and separator == "/"
        and isinstance(kind, str)
        and kind in _ADMISSION_KINDS
    )


def concealed_admission_field(key: str) -> bool:
    return key in _ADMISSION_PAYLOADS
