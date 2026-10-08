"""Bounded YAML edits, immutable identity and conditional structural differences."""

import json
import shlex
from collections.abc import Hashable, Mapping
from difflib import unified_diff
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent
from yaml.nodes import MappingNode, Node

from kuberich.domain.inspection import document, redacted
from kuberich.domain.mutations import MutationIntent, patch_intent
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_object
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import freeze_arguments

MAX_EDIT_BYTES = 1024 * 1024
_MUTABLE_METADATA = frozenset({"annotations", "labels", "finalizers", "ownerReferences"})
_YAML_TAGS = frozenset(
    "tag:yaml.org,2002:" + name for name in ("str", "null", "bool", "int", "float", "map", "seq")
)


def editor_arguments(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Quoted argv from trusted local settings; expansions and shell operators are literal."""
    value = next(
        (environment[key] for key in ("KUBERICH_EDITOR", "VISUAL", "EDITOR") if key in environment),
        "vi",
    )
    try:
        if not isinstance(value, str) or len(value) > 8192:
            raise ValueError
        arguments = freeze_arguments(shlex.split(value, posix=True))
        if len(arguments) > 32 or arguments[0].startswith("-"):
            raise ValueError
        return arguments
    except (AppError, ValueError):
        raise AppError("Editor must be a bounded, quoted executable argument list.") from None


class _EditLoader(yaml.SafeLoader):
    # Kubernetes timestamps remain strings; explicit unsupported YAML tags fail.
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.yaml_implicit_resolvers = {
            key: [rule for rule in rules if rule[0] != "tag:yaml.org,2002:timestamp"]
            for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }

    def construct_object(self, node: Node, deep: bool = False) -> Any:
        if node.tag not in _YAML_TAGS:
            raise AppError("Manifest YAML must contain ordinary JSON-compatible values.")
        return super().construct_object(node, deep)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[str] = set()
        for key, _ in node.value:
            if key.tag != "tag:yaml.org,2002:str" or key.value in seen:
                raise AppError("Manifest mapping keys must be unique strings.")
            seen.add(key.value)
        return super().construct_mapping(node, deep)


def parse_manifest(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_EDIT_BYTES:
        raise AppError("Editable manifests must be nonempty UTF-8 of at most 1 MiB.")
    try:
        text = data.decode("utf-8")
        depth = 0
        for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader)):
            if isinstance(event, AliasEvent):
                raise AppError("Manifest YAML aliases are not supported.")
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > 64 or count > 100000:
                raise AppError("Manifest structure exceeds its nesting or node limit.")
        value = yaml.load(text, Loader=_EditLoader)
        value = resource_object(value)
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return value
    except (yaml.YAMLError, ValueError, TypeError, UnicodeError, RecursionError):
        # Parser exceptions can include the source line and sensitive values.
        raise AppError("Invalid manifest YAML or JSON-compatible UTF-8 values.") from None


def editable_manifest(record: ResourceRecord) -> dict[str, Any]:
    value = record.manifest
    value.pop("status", None)
    resource_object(value.get("metadata")).pop("managedFields", None)
    return value


def manifest_text(record: ResourceRecord, target: ResourceTarget) -> bytes:
    target.require_current(target.session, uid=record.uid or "")
    try:
        text = (
            f"# Context: {target.session.context}\n"
            "# Identity and server-owned metadata must remain unchanged. Status/managedFields omitted.\n"
            + yaml.safe_dump(editable_manifest(record), allow_unicode=True, sort_keys=False)
        )
        data = text.encode("utf-8")
        parse_manifest(data)
        return data
    except (yaml.YAMLError, UnicodeError, RecursionError):
        raise AppError("Resource cannot be represented as a bounded editable manifest.") from None


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _differences(old: Any, new: Any, path: str, changes: list[dict[str, Any]]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in new:
                changes.append({"op": "remove", "path": child})
            elif key not in old:
                changes.append({"op": "add", "path": child, "value": new[key]})
            else:
                _differences(old[key], new[key], child, changes)
            if len(changes) > 128:
                raise AppError("Edit exceeds 128 structural changes; split it into smaller edits.")
    elif _canonical(old) != _canonical(new):
        changes.append({"op": "replace", "path": path, "value": new})


def edited_intent(
    resource: ApiResource, target: ResourceTarget, original: ResourceRecord, data: bytes
) -> MutationIntent | None:
    baseline, edited = editable_manifest(original), parse_manifest(data)
    for key in ("apiVersion", "kind"):
        if edited.get(key) != baseline.get(key):
            raise AppError("Edit cannot change API version or resource kind.")
    metadata = resource_object(edited.get("metadata"))
    before = resource_object(baseline.get("metadata"))
    fixed = {key: value for key, value in before.items() if key not in _MUTABLE_METADATA}
    after = {key: value for key, value in metadata.items() if key not in _MUTABLE_METADATA}
    if _canonical(fixed) != _canonical(after) or "status" in edited:
        raise AppError("Edit cannot change identity, server metadata or status.")
    changes: list[dict[str, Any]] = []
    _differences(baseline, edited, "", changes)
    return patch_intent(resource, target, original, changes) if changes else None


def edit_preview(original: ResourceRecord, data: bytes) -> str:
    """Preview is redacted separately; its placeholders never become request values."""
    baseline, edited = editable_manifest(original), parse_manifest(data)
    secret = baseline.get("kind") in {"Secret", "ConfigMap"}
    old = document(redacted(baseline, secret=secret))
    new = document(redacted(edited, secret=secret))
    difference = "".join(
        unified_diff(
            old.splitlines(True), new.splitlines(True), fromfile="original", tofile="edited"
        )
    )
    return difference or "Changed values are hidden by the preview's redaction policy.\n"
