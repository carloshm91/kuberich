"""Bounded, redacted inspection documents with Kubernetes field names."""

import re
from dataclasses import dataclass
from itertools import islice
from typing import Any

import yaml

from kubetrol.diagnostics.redaction import sanitize_text
from kubetrol.domain.resources import ResourceRecord
from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError

MAX_VIEW_TEXT = 262144
MAX_MATCHES = 10000
REDACTED = "[REDACTED]"
_SENSITIVE = re.compile(
    r"password|passwd|token|credential|private[-_]?key|client[-_]?key|authorization|"
    r"api[-_]?key|access[-_]?key|secret(?!Ref|KeyRef|Name)",
    re.IGNORECASE,
)


def redacted(value: Any, *, key: str = "", secret: bool = False, depth: int = 0) -> Any:
    """Conservative default: hide opaque payloads, annotations and inline execution data."""
    if depth > 64:
        raise AppError("Resource nesting exceeds the inspection limit.")
    if key in {"annotations", "fieldsV1", "command", "args"} or _SENSITIVE.search(key):
        return REDACTED
    if secret and key in {"data", "stringData", "binaryData"}:
        return {name: REDACTED for name in value} if isinstance(value, dict) else REDACTED
    if isinstance(value, dict):
        # Environment literals may be credentials even when their name is innocuous.
        inline_env = "name" in value and "value" in value
        return {
            sanitize_text(str(name)): REDACTED
            if inline_env and name == "value"
            else redacted(item, key=str(name), secret=secret, depth=depth + 1)
            for name, item in value.items()
        }
    if isinstance(value, list):
        return [redacted(item, secret=secret, depth=depth + 1) for item in value]
    if isinstance(value, str):
        if len(value) > 65536:
            raise AppError("Resource field exceeds the inspection text limit.")
        return sanitize_text(value, allow_newlines=True)
    return value


def document(value: Any) -> str:
    text = yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=100)
    if len(text) > MAX_VIEW_TEXT:
        raise AppError("Resource exceeds the inspection text limit; content was not truncated.")
    return text


@dataclass(frozen=True)
class InspectionDocuments:
    yaml: str
    managed_yaml: str
    details: str
    events: str


def inspection_documents(
    manifest: dict[str, Any], events: tuple[ResourceRecord, ...], target: ResourceTarget
) -> InspectionDocuments:
    safe = redacted(manifest, secret=manifest.get("kind") in {"Secret", "ConfigMap"})
    managed_yaml = document(safe)
    metadata = safe.get("metadata", {})
    metadata.pop("managedFields", None)
    ordinary = document(safe)
    details = {"kind": safe.get("kind"), "apiVersion": safe.get("apiVersion"), "metadata": metadata}
    if safe.get("kind") == "Pod":
        spec = safe.get("spec", {})
        if not isinstance(spec, dict):
            raise AppError("Invalid pod specification for inspection.")
        details["scheduling"] = {
            key: spec[key]
            for key in ("nodeName", "serviceAccountName", "priorityClassName", "restartPolicy")
            if key in spec
        }
        details["containers"] = spec.get("containers", [])
        details["initContainers"] = spec.get("initContainers", [])
        details["volumes"] = spec.get("volumes", [])
    else:
        details["spec"] = safe.get("spec", {})
    details["status"] = safe.get("status", {})
    related = []
    for event in events:
        raw = event.manifest
        reference = raw.get("involvedObject", raw.get("regarding", {}))
        if (
            isinstance(reference, dict)
            and reference.get("uid") == target.uid
            and reference.get("namespace") == target.namespace
        ):
            related.append(redacted(raw))
    try:
        event_text = document(related) if related else "No related events returned for this UID.\n"
    except AppError:
        event_text = "Related events exceed the inspection text limit; content was not truncated.\n"
    return InspectionDocuments(ordinary, managed_yaml, document(details), event_text)


def text_matches(text: str, query: str) -> tuple[tuple[int, int, int], ...]:
    """Literal per-line search; bounded query and document keep navigation predictable."""
    if not query or len(query) > 256:
        return ()
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return tuple(
        islice(
            (
                (row, match.start(), match.end())
                for row, line in enumerate(text.splitlines())
                for match in pattern.finditer(line)
            ),
            MAX_MATCHES,
        )
    )
