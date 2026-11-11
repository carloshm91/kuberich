"""Exact reviewed Helm inputs and safe lifecycle observations, independent of widgets."""

import hashlib
import json
from dataclasses import dataclass
from difflib import unified_diff
from enum import StrEnum
from typing import Any
from uuid import UUID

from kuberich.domain.helm import (
    MAX_HELM_OUTPUT_BYTES,
    MAX_HELM_RENDER_BYTES,
    HelmDocumentKind,
    HelmOutcome,
    HelmRelease,
    HelmReleaseKey,
    HelmRequest,
    helm_cell,
)
from kuberich.domain.helm_cli import helm_json
from kuberich.domain.helm_documents import helm_document_text
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls


class HelmLifecycleKind(StrEnum):
    INSTALL = "install"
    UPGRADE = "upgrade"
    UNINSTALL = "uninstall"


@dataclass(frozen=True, slots=True)
class HelmLifecycleOptions:
    run_hooks: bool = False
    wait: bool = True
    timeout_seconds: int = 300
    keep_history: bool = True
    cascade: str = "background"
    skip_crds: bool = True

    def __post_init__(self) -> None:
        if (
            any(
                type(value) is not bool
                for value in (self.run_hooks, self.wait, self.keep_history, self.skip_crds)
            )
            or type(self.timeout_seconds) is not int
            or not 1 <= self.timeout_seconds <= 600
        ):
            raise AppError("Helm options require boolean flags and a timeout of 1-600 seconds.")
        if not isinstance(self.cascade, str) or self.cascade not in {
            "background",
            "foreground",
            "orphan",
        }:
            raise AppError("Choose background, foreground or orphan deletion propagation.")
        if not self.skip_crds:
            raise AppError("Chart CRDs must already be served; CRD installation is not supported.")


@dataclass(frozen=True, slots=True, repr=False)
class HelmValuesLease:
    identity: UUID
    sha256: str
    source: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.identity, UUID)
            or not isinstance(self.source, str)
            or self.source
            not in {
                "defaults",
                "supplied",
                "edited",
            }
        ):
            raise AppError("Helm values require an owned source identity.")
        digest_text(self.sha256)


@dataclass(frozen=True, slots=True)
class HelmValuesDisclosureIntent:
    identity: UUID
    request: HelmRequest
    address: HelmReleaseKey
    values: HelmValuesLease


@dataclass(frozen=True, slots=True)
class HelmLifecycleIntent:
    identity: UUID
    request: HelmRequest
    address: HelmReleaseKey
    operation: HelmLifecycleKind
    options: HelmLifecycleOptions
    effects: tuple[str, ...]
    preview_text: str
    dry_run: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, UUID) or not isinstance(self.request, HelmRequest):
            raise AppError("Helm lifecycle requires a captured request and review identity.")
        if not isinstance(self.address, HelmReleaseKey) or not isinstance(
            self.operation, HelmLifecycleKind
        ):
            raise AppError("Helm lifecycle requires an explicit release address and operation.")
        if not isinstance(self.options, HelmLifecycleOptions):
            raise AppError("Helm lifecycle options are invalid.")
        if self.request.scope.namespace not in {None, self.address.namespace}:
            raise AppError("Helm lifecycle address differs from the selected namespace.")
        if not isinstance(self.effects, tuple) or len(self.effects) > 512:
            raise AppError("Helm lifecycle effects exceed their limit.")
        for value in (*self.effects, self.dry_run):
            helm_cell(value)
        if (
            not isinstance(self.preview_text, str)
            or escape_controls(self.preview_text, allow_newlines=True) != self.preview_text
            or len(self.preview_text.encode()) > MAX_HELM_RENDER_BYTES
        ):
            raise AppError("Helm lifecycle preview exceeds its byte limit.")


@dataclass(frozen=True, slots=True)
class HelmOperationObservation:
    outcome: HelmOutcome
    message: str
    observed: HelmRelease | None = None
    may_have_started: bool = False
    resources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, HelmOutcome) or type(self.may_have_started) is not bool:
            raise AppError("Invalid Helm operation observation.")
        helm_cell(self.message)
        if self.observed is not None and not isinstance(self.observed, HelmRelease):
            raise AppError("Invalid observed Helm release.")
        if not isinstance(self.resources, tuple) or len(self.resources) > 256:
            raise AppError("Helm resource observations exceed their limit.")
        for resource in self.resources:
            helm_cell(resource)


def digest_text(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise AppError("Helm inputs require an exact SHA256 digest.")
    return value


def values_bytes(data: bytes) -> bytes:
    """A complete bounded JSON-compatible YAML mapping, never parser source excerpts."""
    from kuberich.domain.editing import parse_manifest

    parse_manifest(data)
    return data


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class HelmRenderedRelease:
    manifest: bytes
    hooks: tuple[bytes, ...]
    values: bytes
    apply_method: str
    hook_effects: tuple[str, ...] = ()


def _hook_effects(hook: dict[str, Any]) -> str:
    allowed = {
        "events": {
            "pre-install",
            "post-install",
            "pre-delete",
            "post-delete",
            "pre-upgrade",
            "post-upgrade",
            "pre-rollback",
            "post-rollback",
            "test",
            "test-success",
        },
        "delete_policies": {"before-hook-creation", "hook-succeeded", "hook-failed"},
        "output_log_policies": {"hook-succeeded", "hook-failed"},
    }
    fields: dict[str, tuple[str, ...]] = {}
    for field, permitted in allowed.items():
        values = hook.get(field, [])
        if (
            not isinstance(values, list)
            or len(values) > 32
            or any(not isinstance(value, str) or value not in permitted for value in values)
        ):
            raise AppError("Helm hook effect metadata is unsupported or incomplete.")
        fields[field] = tuple(values)
    weight = hook.get("weight", 0)
    if type(weight) is not int or not -(2**63) <= weight < 2**63:
        raise AppError("Helm hook weight is unsupported.")
    return (
        "events "
        + (", ".join(fields["events"]) or "unspecified")
        + "; delete policies "
        + ", ".join(fields["delete_policies"] or ("before-hook-creation",))
        + "; weight "
        + str(weight)
        + "; output log policies "
        + (", ".join(fields["output_log_policies"]) or "none")
        + "; hook resources may outlive the release."
    )


def rendered_release(
    data: bytes, address: HelmReleaseKey, revision: int | None = None
) -> HelmRenderedRelease:
    raw = helm_json(data)
    if (
        not isinstance(raw, dict)
        or raw.get("name") != address.name
        or raw.get("namespace") != address.namespace
    ):
        raise AppError("Helm returned a different release address.")
    if type(raw.get("version")) is not int or (revision is not None and raw["version"] != revision):
        raise AppError("Helm returned a different release revision.")
    manifest, hooks, values = raw.get("manifest", ""), raw.get("hooks", []), raw.get("config", {})
    method = raw.get("apply_method", "")
    if (
        not isinstance(manifest, str)
        or not isinstance(hooks, list)
        or len(hooks) > 256
        or not isinstance(method, str)
        or method not in {"", "csa", "ssa"}
    ):
        raise AppError("Helm release preparation has unsupported structure or apply method.")
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise AppError("Helm supplied values must be a mapping.")
    bodies = []
    effects = []
    for hook in hooks:
        body = hook.get("manifest") if isinstance(hook, dict) else None
        if not isinstance(body, str):
            raise AppError("Helm hook preparation is incomplete.")
        bodies.append(body.encode())
        effects.append(_hook_effects(hook))
    # helm_json already bounds the entire envelope, including every hook body.
    encoded_values = json.dumps(values, allow_nan=False).encode()
    values_bytes(encoded_values)
    return HelmRenderedRelease(
        manifest.encode(), tuple(bodies), encoded_values, method, tuple(effects)
    )


def manifest_objects(data: bytes) -> tuple[dict[str, Any], ...]:
    from kuberich.domain.editing import parse_manifest_documents

    if not data.strip():
        return ()
    return parse_manifest_documents(data, max_bytes=MAX_HELM_OUTPUT_BYTES, max_documents=256)


def normalized_manifest(value: dict[str, Any]) -> dict[str, Any]:
    """Remove documented server-owned comparison fields without changing desired bytes."""
    result = dict(value)
    result.pop("status", None)
    meta = result.get("metadata", {})
    if not isinstance(meta, dict):
        raise AppError("Rendered object metadata must be a mapping.")
    result["metadata"] = {
        key: item
        for key, item in meta.items()
        if key
        not in {
            "uid",
            "resourceVersion",
            "managedFields",
            "creationTimestamp",
            "generation",
            "selfLink",
            "deletionTimestamp",
            "deletionGracePeriodSeconds",
        }
    }
    return result


def helm_owned_manifest(
    value: dict[str, Any], address: HelmReleaseKey, namespace: str | None
) -> dict[str, Any]:
    """Project the pinned Helm ownership visitor without changing native input bytes."""
    meta = value.get("metadata")
    if not isinstance(meta, dict):
        raise AppError("Helm resource metadata must be a mapping.")
    labels, annotations = meta.get("labels", {}), meta.get("annotations", {})
    if labels is None:
        labels = {}
    if annotations is None:
        annotations = {}
    if (
        not isinstance(labels, dict)
        or not isinstance(annotations, dict)
        or any(
            not isinstance(key, str) or not isinstance(item, str)
            for fields in (labels, annotations)
            for key, item in fields.items()
        )
    ):
        raise AppError("Helm resource labels and annotations must contain strings.")
    metadata = {
        **meta,
        "labels": {**labels, "app.kubernetes.io/managed-by": "Helm"},
        "annotations": {
            **annotations,
            "meta.helm.sh/release-name": address.name,
            "meta.helm.sh/release-namespace": address.namespace,
        },
    }
    if namespace is not None:
        metadata["namespace"] = namespace
    else:
        metadata.pop("namespace", None)
    return {**value, "metadata": metadata}


def helm_release_owns(body: dict[str, Any], address: HelmReleaseKey) -> bool:
    meta = body.get("metadata")
    if not isinstance(meta, dict):
        return False
    labels, annotations = meta.get("labels"), meta.get("annotations")
    return (
        isinstance(labels, dict)
        and isinstance(annotations, dict)
        and labels.get("app.kubernetes.io/managed-by") == "Helm"
        and annotations.get("meta.helm.sh/release-name") == address.name
        and annotations.get("meta.helm.sh/release-namespace") == address.namespace
    )


def resource_observation(
    label: str, body: dict[str, Any] | None, address: HelmReleaseKey, *, removed: bool
) -> str:
    if body is None:
        return label + ": absent"
    if not helm_release_owns(body, address):
        return label + ": present; release ownership is unverified"
    metadata = body["metadata"]
    if metadata.get("deletionTimestamp") is not None:
        return label + ": present; deletion pending (finalizers may delay completion)"
    if metadata["annotations"].get("helm.sh/resource-policy") == "keep":
        return label + ": present; retained by resource-policy keep"
    if removed:
        return label + ": present; deletion or retention is not verified"
    return label + ": present; release ownership verified"


def live_diff(live: dict[str, Any] | None, desired: dict[str, Any] | None, label: str) -> str:
    """Redact the two sides independently; hidden changes remain visible as a fact."""

    def safe(value: dict[str, Any] | None) -> str:
        if value is None:
            return ""
        encoded = json.dumps(normalized_manifest(value), allow_nan=False).encode()
        return helm_document_text(encoded, HelmDocumentKind.MANIFEST, disclosed=False)

    before, after = safe(live), safe(desired)
    difference = "".join(
        unified_diff(
            before.splitlines(True),
            after.splitlines(True),
            fromfile="live/" + label,
            tofile="rendered/" + label,
        )
    )
    if not difference and live != desired:
        difference = label + ": changes hidden by redaction or server-field normalization.\n"
    return difference or label + ": unchanged.\n"
