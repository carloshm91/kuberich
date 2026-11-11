"""Bounded Pod/Node scheduling declarations, without evaluating a scheduler."""

import json
from collections.abc import Iterable
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.curated import (
    MAX_CURATED_CELL_CHARACTERS,
    MAX_CURATED_DETAIL_BYTES,
    MAX_CURATED_DETAIL_ROWS,
    CuratedDetails,
    DetailSection,
)
from kuberich.domain.relationships import structured_selector
from kuberich.errors import AppError

_INPUT_ITEMS = 64
_OMITTED = "Additional scheduling entries were omitted at the input or output bound."
_UNKNOWN = "A scheduling declaration is malformed or unavailable; no constraint is inferred."
_CAVEAT = "These are configured declarations and reported placement, not scheduler feasibility, eviction timing or proof of successful placement."


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    safe = sanitize_text(value)
    return (
        safe[: MAX_CURATED_CELL_CHARACTERS - 1] + "…"
        if len(safe) > MAX_CURATED_CELL_CHARACTERS
        else safe
    )


class _Projection:
    def __init__(self) -> None:
        self.sections: list[DetailSection] = []
        self.notices = [_CAVEAT]
        self.rows = 0
        self.used = 8192  # Fixed headings, notices and the complete JSON structure.

    def note(self, text: str) -> None:
        if text not in self.notices:
            self.notices.append(text)

    def items(self, value: object) -> list[Any] | None:
        if not isinstance(value, list):
            self.note(_UNKNOWN)
            return None
        if len(value) > _INPUT_ITEMS:
            self.note(_OMITTED)
        return value[:_INPUT_ITEMS]

    def section(
        self, title: str, columns: tuple[str, ...], rows: Iterable[tuple[str, ...]]
    ) -> None:
        retained = []
        omitted = 0
        self.used += len(json.dumps((title, columns), ensure_ascii=True).encode()) + 128
        for row in rows:
            safe = tuple(_text(value) for value in row)
            size = len(json.dumps(safe, ensure_ascii=True).encode()) + 8
            if self.rows >= MAX_CURATED_DETAIL_ROWS or self.used + size > MAX_CURATED_DETAIL_BYTES:
                omitted += 1
                self.note(_OMITTED)
            else:
                retained.append(safe)
                self.rows += 1
                self.used += size
        self.sections.append(DetailSection(title, columns, tuple(retained), omitted))


def _selector(raw: object, output: _Projection) -> str:
    try:
        selector = structured_selector(raw)
    except AppError:
        output.note(_UNKNOWN)
        return "—"
    return (
        "; ".join(
            f"{item.key} {item.operator} ({','.join(item.values)})"
            for item in selector.requirements
        )
        or "empty selector (all within declared scope)"
    )


def _strings(raw: object, output: _Projection) -> str:
    items = output.items(raw)
    if items is None or any(not isinstance(value, str) for value in items):
        output.note(_UNKNOWN)
        return "—"
    return ", ".join(_text(value) for value in items) or "empty list"


def _node_selectors(spec: dict[str, Any], output: _Projection) -> Iterable[tuple[str, ...]]:
    value = spec.get("nodeSelector", {})
    try:
        selector = structured_selector(value, direct=True)
    except AppError:
        output.note(_UNKNOWN)
        yield "—", "—", "Malformed nodeSelector"
        return
    if not selector.requirements:
        yield "nodeSelector", "empty map", "No declared label constraint"
    for item in selector.requirements[:_INPUT_ITEMS]:
        yield item.key, item.values[0], "All entries must match (AND); no eligibility verdict"
    if len(selector.requirements) > _INPUT_ITEMS:
        output.note(_OMITTED)


def _node_term(raw: object, path: str, output: _Projection) -> Iterable[tuple[str, ...]]:
    if not isinstance(raw, dict):
        output.note(_UNKNOWN)
        yield path, "term", "—", "Malformed node selector term"
        return
    expressions = output.items(raw.get("matchExpressions", []))
    fields = output.items(raw.get("matchFields", []))
    if expressions == [] and fields == []:
        yield path, "term", "empty term", "Matches no nodes"
    for field, entries in (("matchExpressions", expressions), ("matchFields", fields)):
        for index, value in enumerate(entries or []):
            item = value if isinstance(value, dict) else {}
            operator = item.get("operator")
            yield (
                path,
                f"{field}[{index}] {_text(item.get('key'))}",
                f"{operator} ({_strings(item.get('values', []), output)})"
                if operator in ("In", "NotIn", "Exists", "DoesNotExist", "Gt", "Lt")
                else "—",
                "Requirements within a term combine with AND; terms are alternatives (OR)",
            )


def _pod_term(raw: object, path: str, output: _Projection) -> Iterable[tuple[str, ...]]:
    if not isinstance(raw, dict):
        output.note(_UNKNOWN)
        yield path, "term", "—", "Malformed Pod affinity term"
        return
    label_selector = raw.get("labelSelector")
    yield (
        path,
        "labelSelector",
        "null (no matching Pods)" if label_selector is None else _selector(label_selector, output),
        "Configured subject selector; no request or scheduling evaluation",
    )
    namespace_selector = raw.get("namespaceSelector")
    namespaces = raw.get("namespaces", [])
    yield (
        path,
        "namespaces",
        "declaring Pod namespace"
        if namespaces in (None, []) and namespace_selector is None
        else _strings([] if namespaces is None else namespaces, output),
        "Static namespaces union namespaceSelector; omitted selector/list defaults to this Pod namespace",
    )
    yield (
        path,
        "namespaceSelector",
        "omitted" if namespace_selector is None else _selector(namespace_selector, output),
        "An empty selector selects all namespaces; namespace terms combine by union",
    )
    yield path, "topologyKey", _text(raw.get("topologyKey")), "Declared co-location topology"
    for field in ("matchLabelKeys", "mismatchLabelKeys"):
        if field in raw:
            yield (
                path,
                field,
                _strings(raw[field], output),
                "Declared label-key composition; not evaluated",
            )


def _affinity(spec: dict[str, Any], output: _Projection) -> Iterable[tuple[str, ...]]:
    affinity = spec.get("affinity", {})
    if not isinstance(affinity, dict):
        output.note(_UNKNOWN)
        yield "affinity", "declaration", "—", "Malformed affinity"
        return
    if not affinity:
        yield "affinity", "declaration", "omitted or empty", "No declared affinity"
    for kind in ("nodeAffinity", "podAffinity", "podAntiAffinity"):
        if kind not in affinity:
            continue
        rules = affinity[kind]
        if not isinstance(rules, dict):
            output.note(_UNKNOWN)
            yield kind, "declaration", "—", "Malformed affinity"
            continue
        for field, preferred in (
            ("requiredDuringSchedulingIgnoredDuringExecution", False),
            ("preferredDuringSchedulingIgnoredDuringExecution", True),
        ):
            if field not in rules:
                continue
            raw = rules[field]
            path = kind + (".preferred" if preferred else ".required")
            if kind == "nodeAffinity" and not preferred:
                raw = raw.get("nodeSelectorTerms") if isinstance(raw, dict) else None
            terms = output.items(raw)
            yield (
                path,
                "term count",
                str(len(raw)) if isinstance(raw, list) else "—",
                "Configured preference"
                if preferred
                else "Empty required node selector matches no nodes"
                if kind == "nodeAffinity" and terms == []
                else "Configured requirement",
            )
            for index, term in enumerate(terms or []):
                item_path = f"{path}[{index}]"
                if preferred:
                    entry = term if isinstance(term, dict) else {}
                    weight = entry.get("weight")
                    yield (
                        item_path,
                        "weight",
                        str(weight) if type(weight) is int and 1 <= weight <= 100 else "—",
                        "Declared preference, not placement proof",
                    )
                    term = entry.get("preference" if kind == "nodeAffinity" else "podAffinityTerm")
                if kind == "nodeAffinity":
                    yield from _node_term(term, item_path, output)
                else:
                    yield from _pod_term(term, item_path, output)


def _tolerations(spec: dict[str, Any], output: _Projection) -> Iterable[tuple[str, ...]]:
    entries = output.items(spec.get("tolerations", []))
    if entries == []:
        yield "—", "none declared", "—", "—", "—", "No scheduling or eviction verdict"
    for index, raw in enumerate(entries or []):
        if not isinstance(raw, dict):
            output.note(_UNKNOWN)
            yield str(index), "—", "—", "—", "—", "—"
            continue
        item = raw
        operator = item.get("operator", "Equal")
        key, value = item.get("key", ""), item.get("value", "")
        effect = item.get("effect", "")
        seconds = item.get("tolerationSeconds")
        yield (
            str(index),
            "all keys (Exists required)" if key == "" else _text(key),
            str(operator) if operator in ("Equal", "Exists", "Lt", "Gt") else "—",
            "empty value" if value == "" else _text(value),
            str(effect)
            if effect in ("NoSchedule", "PreferNoSchedule", "NoExecute")
            else "all effects"
            if effect == ""
            else "—",
            str(seconds)
            if type(seconds) is int and -(2**63) <= seconds < 2**63
            else "not set"
            if seconds is None
            else "—",
        )
    output.note(
        "Toleration operator defaults to Equal; Lt/Gt depend on serving feature gates. tolerationSeconds applies only to NoExecute; omitted means unbounded and zero/negative is treated as zero. A toleration never guarantees placement."
    )


def _taints(spec: dict[str, Any], output: _Projection) -> Iterable[tuple[str, ...]]:
    entries = output.items(spec.get("taints", []))
    if entries == []:
        yield "—", "none declared", "—", "—"
    for index, raw in enumerate(entries or []):
        if not isinstance(raw, dict):
            output.note(_UNKNOWN)
            yield str(index), "—", "—", "—"
            continue
        item = raw
        value = item.get("value", "")
        effect = item.get("effect")
        yield (
            str(index),
            _text(item.get("key")),
            "empty value" if value == "" else _text(value),
            str(effect) if effect in ("NoSchedule", "PreferNoSchedule", "NoExecute") else "—",
        )


def scheduling_declarations(manifest: dict[str, Any]) -> CuratedDetails | None:
    """Publish exact core-v1 Pod/Node declarations without clients, links or raw bodies."""
    kind = manifest.get("kind")
    if manifest.get("apiVersion") != "v1" or kind not in ("Pod", "Node"):
        return None
    output = _Projection()
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        output.note(_UNKNOWN)
        output.section("Scheduling declarations", ("Field", "Value"), (("spec", "—"),))
    elif kind == "Pod":
        output.section(
            "Scheduling identity (declared)",
            ("Field", "Value"),
            (
                (field, _text(spec.get(field)))
                for field in ("nodeName", "schedulerName", "priorityClassName", "runtimeClassName")
            ),
        )
        output.section(
            "Node selectors (declared)",
            ("Label", "Value", "Provenance"),
            _node_selectors(spec, output),
        )
        output.section(
            "Affinity declarations",
            ("Declaration", "Field", "Value", "Meaning"),
            _affinity(spec, output),
        )
        output.section(
            "Tolerations (declared)",
            ("Index", "Key", "Operator", "Value", "Effect", "Seconds"),
            _tolerations(spec, output),
        )
    else:
        unschedulable = spec.get("unschedulable", False)
        output.section(
            "Node scheduling (declared)",
            ("Field", "Value", "Provenance"),
            (
                (
                    "unschedulable",
                    str(unschedulable).lower() if type(unschedulable) is bool else "—",
                    "Declared" if "unschedulable" in spec else "API default: false",
                ),
            ),
        )
        output.section(
            "Node taints (declared)", ("Index", "Key", "Value", "Effect"), _taints(spec, output)
        )
    return CuratedDetails(tuple(output.sections), (), tuple(output.notices))
