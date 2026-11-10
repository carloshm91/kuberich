"""Bounded Helm documents with structural default redaction and explicit disclosure."""

from collections.abc import Hashable
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent, DocumentStartEvent
from yaml.nodes import MappingNode, Node

from kuberich.domain.helm import (
    MAX_HELM_DEPTH,
    MAX_HELM_DOCUMENTS,
    MAX_HELM_NODES,
    MAX_HELM_OUTPUT_BYTES,
    MAX_HELM_RENDER_BYTES,
    HelmDocumentKind,
    HelmProblem,
)
from kuberich.domain.helm_cli import helm_json, helm_structure
from kuberich.domain.inspection import REDACTED, redacted
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

_TAGS = frozenset(
    "tag:yaml.org,2002:" + name for name in ("str", "null", "bool", "int", "float", "map", "seq")
)


def _invalid() -> HelmProblem:
    return HelmProblem(
        "invalid-output", "Helm document is not valid bounded UTF-8 JSON or ordinary manifest YAML."
    )


class _HelmLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.yaml_implicit_resolvers = {
            key: [rule for rule in rules if rule[0] != "tag:yaml.org,2002:timestamp"]
            for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
        }

    def construct_object(self, node: Node, deep: bool = False) -> Any:
        if node.tag not in _TAGS:
            raise _invalid()
        return super().construct_object(node, deep)

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        keys: set[str] = set()
        for key, _ in node.value:
            if key.tag != "tag:yaml.org,2002:str" or key.value in keys:
                raise _invalid()
            keys.add(key.value)
        return super().construct_mapping(node, deep)


def _manifests(text: str) -> list[dict[str, Any]]:
    depth = documents = 0
    for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader), 1):
        if isinstance(event, AliasEvent):
            raise _invalid()
        if isinstance(event, CollectionStartEvent):
            depth += 1
        elif isinstance(event, CollectionEndEvent):
            depth -= 1
        elif isinstance(event, DocumentStartEvent):
            documents += 1
        if depth > MAX_HELM_DEPTH or count > MAX_HELM_NODES or documents > MAX_HELM_DOCUMENTS:
            raise _invalid()
    result: list[dict[str, Any]] = []
    for value in yaml.load_all(text, Loader=_HelmLoader):
        if value is None:
            continue
        helm_structure(value)
        if (
            not isinstance(value, dict)
            or not isinstance(value.get("apiVersion"), str)
            or not isinstance(value.get("kind"), str)
            or not value["apiVersion"]
            or not value["kind"]
        ):
            raise _invalid()
        result.append(value)
    return result


def _secret_payloads(value: Any) -> Any:
    """Recognize every nested Kubernetes object, including Secret/ConfigMap List items."""
    if isinstance(value, dict):
        secret = value.get("kind") in {"Secret", "ConfigMap"}
        return {
            key: ({name: REDACTED for name in item} if isinstance(item, dict) else REDACTED)
            if secret and key in {"data", "stringData", "binaryData"}
            else _secret_payloads(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_secret_payloads(item) for item in value]
    return value


def _withheld(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _withheld(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_withheld(item) for item in value]
    return REDACTED


def helm_document_text(data: bytes, kind: HelmDocumentKind, *, disclosed: bool) -> str:
    if not isinstance(kind, HelmDocumentKind) or type(disclosed) is not bool:
        raise _invalid()
    if not isinstance(data, bytes) or len(data) > MAX_HELM_OUTPUT_BYTES:
        raise HelmProblem("output-limit", "Helm document exceeds the 8 MiB process-output limit.")
    try:
        source = data.decode("utf-8")
        if kind is HelmDocumentKind.NOTES:
            if source.startswith("NOTES:\n"):
                source = source[7:]
            text = (
                source
                if disclosed or not source
                else "Chart notes are withheld; review disclosure to read them.\n"
            )
        elif kind in {HelmDocumentKind.VALUES, HelmDocumentKind.ALL_VALUES}:
            value = helm_json(data)
            if value is None:
                text = (
                    "No supplied values.\n"
                    if kind is HelmDocumentKind.VALUES
                    else "Helm returned no computed values.\n"
                )
            elif not isinstance(value, dict):
                raise _invalid()
            else:
                safe = value if disclosed else redacted(_withheld(value))
                text = yaml.safe_dump(safe, allow_unicode=True, sort_keys=False)
        else:
            manifests = _manifests(source)
            safe = (
                manifests
                if disclosed
                else [redacted(_secret_payloads(value)) for value in manifests]
            )
            text = yaml.safe_dump_all(safe, allow_unicode=True, sort_keys=False)
        text = escape_controls(text, allow_newlines=True)
        if len(text.encode("utf-8")) > MAX_HELM_RENDER_BYTES:
            raise HelmProblem(
                "output-limit",
                "Helm document exceeds the 256 KiB rendered-text limit; content was not truncated.",
            )
        return text
    except HelmProblem:
        raise
    except (AppError, yaml.YAMLError, UnicodeError, ValueError, TypeError, RecursionError):
        # Parser exceptions contain source lines and must not cross this boundary.
        raise _invalid() from None
