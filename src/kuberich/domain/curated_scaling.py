"""Bounded, version-specific scaling and scheduling facts without inferred health."""

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, replace
from datetime import datetime
from itertools import islice
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.curated import (
    MAX_CURATED_CELL_CHARACTERS,
    MAX_CURATED_DETAIL_BYTES,
    MAX_CURATED_DETAIL_ROWS,
    CuratedCells,
    CuratedDetails,
    CuratedFamily,
    DetailSection,
    require_curated_record,
)
from kuberich.domain.curated_navigation import (
    CollectionDestination,
    CuratedLink,
    LabelsMatch,
    PodRuntimeClass,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.quantities import parse_quantity
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipRef,
    structured_selector,
)
from kuberich.domain.resources import (
    ApiResource,
    ResourceRecord,
    api_segment,
    split_api_version,
)
from kuberich.domain.table_values import Column, Value
from kuberich.errors import AppError

_UNKNOWN = Value("—", None)
_LIMIT = MAX_CURATED_DETAIL_ROWS
_CONDITIONS = frozenset(
    {
        "AbleToScale",
        "ScalingActive",
        "ScalingLimited",
        "RecommendationProvided",
        "LowConfidence",
        "NoPodsMatched",
        "FetchingHistory",
        "ConfigDeprecated",
        "ConfigUnsupported",
        "DisruptionAllowed",
    }
)


def _family(
    group: str,
    name: str,
    kind: str,
    namespaced: bool,
    versions: tuple[str, ...],
    aliases: tuple[str, ...],
    fields: tuple[tuple[str, bool], ...],
) -> CuratedFamily:
    return CuratedFamily(
        group,
        name,
        kind,
        namespaced,
        frozenset(versions),
        aliases,
        tuple(Column(key, numeric) for key, numeric in fields),
    )


FAMILIES = (
    _family(
        "autoscaling",
        "horizontalpodautoscalers",
        "HorizontalPodAutoscaler",
        True,
        ("v1", "v2"),
        ("hpa",),
        (
            ("target", False),
            ("min", True),
            ("max", True),
            ("current", True),
            ("desired", True),
            ("metrics", False),
            ("conditions", False),
        ),
    ),
    _family(
        "autoscaling.k8s.io",
        "verticalpodautoscalers",
        "VerticalPodAutoscaler",
        True,
        ("v1",),
        ("vpa",),
        (
            ("target", False),
            ("mode", False),
            ("recommended-containers", True),
            ("conditions", False),
        ),
    ),
    _family(
        "policy",
        "poddisruptionbudgets",
        "PodDisruptionBudget",
        True,
        ("v1",),
        ("pdb",),
        (
            ("min-available", True),
            ("max-unavailable", True),
            ("allowed", True),
            ("current-healthy", True),
            ("desired-healthy", True),
            ("expected-pods", True),
            ("status", False),
        ),
    ),
    _family(
        "scheduling.k8s.io",
        "priorityclasses",
        "PriorityClass",
        False,
        ("v1",),
        ("pc",),
        (("priority", True), ("global-default", False), ("preemption", False)),
    ),
    _family(
        "node.k8s.io",
        "runtimeclasses",
        "RuntimeClass",
        False,
        ("v1",),
        ("runtimeclass",),
        (
            ("handler", False),
            ("overhead-cpu", True),
            ("overhead-memory", True),
            ("node-selector", False),
            ("tolerations", True),
        ),
    ),
    _family(
        "coordination.k8s.io",
        "leases",
        "Lease",
        True,
        ("v1",),
        ("lease",),
        (
            ("holder", False),
            ("duration-seconds", True),
            ("renew-time", False),
            ("transitions", True),
        ),
    ),
)


def _map(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> Value:
    if not isinstance(value, str) or not value:
        return _UNKNOWN
    text = sanitize_text(value)[:MAX_CURATED_CELL_CHARACTERS]
    return Value(text, text.casefold())


def _number(value: object, *, signed: bool = False, maximum: int = 2**31 - 1) -> Value:
    lower = -(2**31) if signed else 0
    if type(value) is int and lower <= value <= maximum:
        return Value(str(value), value)
    return _UNKNOWN


def _quantity(value: object) -> Value:
    parsed = parse_quantity(value)
    return Value(str(value), parsed) if parsed is not None else _UNKNOWN


def _percent(value: object) -> Value:
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,3}%", value):
        number = int(value[:-1])
        if number <= 100:
            return Value(value, (1, float(number)))
    count = _number(value)
    return (
        Value(count.text, (0, float(value)))
        if type(value) is int and count.sort is not None
        else _UNKNOWN
    )


def _timestamp(value: object) -> Value:
    if (
        not isinstance(value, str)
        or len(value) > 64
        or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})",
            value,
        )
    ):
        return _UNKNOWN
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return Value(_text(value).text, parsed.timestamp())
    except (ValueError, OverflowError):
        return _UNKNOWN


def _count(value: object) -> Value:
    return _number(len(value)) if isinstance(value, list) else _UNKNOWN


def _condition_rows(status: dict[str, Any]) -> Iterable[tuple[str, ...]]:
    value = status.get("conditions")
    if isinstance(value, list):
        for condition in value[:_LIMIT]:
            item = _map(condition)
            kind = item.get("type")
            state = item.get("status")
            yield (
                kind if isinstance(kind, str) and kind in _CONDITIONS else "Other condition",
                state if state in ("True", "False", "Unknown") else "—",
            )


def _conditions(status: dict[str, Any]) -> Value:
    rows = tuple(_condition_rows(status))
    return _text(", ".join("=".join(row) for row in rows))


def _ref(raw: object, namespace: str | None, *, uid: bool = False) -> RelationshipRef:
    data = _map(raw)
    group, served = split_api_version(data.get("apiVersion"))
    version = f"{group}/{served}" if group else served
    name = api_segment(data.get("name"))
    kind = data.get("kind")
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind):
        raise AppError("Invalid declared reference kind.")
    identity = data.get("uid")
    if uid and (
        not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,253}", identity)
    ):
        raise AppError("A bounded owner UID is required.")
    return RelationshipRef(version, kind, namespace, name, identity if uid else None, None)


def _target(raw: object, namespace: str | None) -> Value:
    try:
        ref = _ref(raw, namespace)
        return _text(f"{ref.kind}/{ref.name}")
    except AppError:
        return _UNKNOWN


def _reference_link(
    key: str, label: str, raw: object, namespace: str | None, *, uid: bool = False
) -> CuratedLink:
    provenance = "Declared owner UID" if uid else "Declared reference; fresh target lookup required"
    try:
        destination = ReferenceDestination(_ref(raw, namespace, uid=uid), uid)
        return CuratedLink(key, label, provenance, destination)
    except AppError:
        return CuratedLink(
            key, label, provenance, None, "Reference is missing, invalid or over limit."
        )


def _mode(spec: dict[str, Any]) -> Value:
    return _text(_map(spec.get("updatePolicy")).get("updateMode", "Auto"))


def _pdb_status(data: dict[str, Any], status: dict[str, Any]) -> Value:
    generation = _number(_map(data.get("metadata")).get("generation"), maximum=2**63 - 1)
    observed = _number(status.get("observedGeneration"), maximum=2**63 - 1)
    if generation.sort is None or observed.sort is None:
        return _text("Unknown generation")
    return _text("Current generation" if generation.sort == observed.sort else "Stale generation")


def _selector_text(value: object) -> Value:
    try:
        selector = structured_selector(value, direct=True)
        return _text(
            ", ".join(f"{item.key}={item.values[0]}" for item in selector.requirements)
            or "All nodes (empty selector)"
        )
    except AppError:
        return _UNKNOWN


def cells(resource: ApiResource, record: ResourceRecord) -> CuratedCells:
    """Extract only the frozen columns; absent reported observations remain unknown."""
    family, data = require_curated_record(resource, record, FAMILIES)
    spec, status = _map(data.get("spec")), _map(data.get("status"))
    overhead = _map(_map(data.get("overhead")).get("podFixed"))
    scheduling = _map(data.get("scheduling"))
    values: dict[str, Value]
    match family.kind:
        case "HorizontalPodAutoscaler":
            metrics = (
                _count(spec.get("metrics"))
                if resource.version == "v2"
                else _number(spec.get("targetCPUUtilizationPercentage"))
            )
            values = {
                "target": _target(spec.get("scaleTargetRef"), record.namespace),
                "min": _number(spec.get("minReplicas", 1)),
                "max": _number(spec.get("maxReplicas")),
                "current": _number(status.get("currentReplicas")),
                "desired": _number(status.get("desiredReplicas")),
                "metrics": metrics,
                "conditions": _conditions(status),
            }
        case "VerticalPodAutoscaler":
            recommendations = _map(status.get("recommendation")).get("containerRecommendations")
            values = {
                "target": _target(spec.get("targetRef"), record.namespace),
                "mode": _mode(spec),
                "recommended-containers": _count(recommendations),
                "conditions": _conditions(status),
            }
        case "PodDisruptionBudget":
            values = {
                "min-available": _percent(spec.get("minAvailable")),
                "max-unavailable": _percent(spec.get("maxUnavailable")),
                "allowed": _number(status.get("disruptionsAllowed")),
                "current-healthy": _number(status.get("currentHealthy")),
                "desired-healthy": _number(status.get("desiredHealthy")),
                "expected-pods": _number(status.get("expectedPods")),
                "status": _pdb_status(data, status),
            }
        case "PriorityClass":
            default = data.get("globalDefault", False)
            boolean = (
                Value(str(default).lower(), int(default)) if type(default) is bool else _UNKNOWN
            )
            values = {
                "priority": _number(data.get("value"), signed=True),
                "global-default": boolean,
                "preemption": _text(data.get("preemptionPolicy", "PreemptLowerPriority")),
            }
        case "RuntimeClass":
            values = {
                "handler": _text(data.get("handler")),
                "overhead-cpu": _quantity(overhead.get("cpu")),
                "overhead-memory": _quantity(overhead.get("memory")),
                "node-selector": _selector_text(scheduling.get("nodeSelector")),
                "tolerations": _count(scheduling.get("tolerations")),
            }
        case _:  # The descriptor gate makes Lease the only remaining family.
            values = {
                "holder": _text(spec.get("holderIdentity")),
                "duration-seconds": _number(spec.get("leaseDurationSeconds")),
                "renew-time": _timestamp(spec.get("renewTime")),
                "transitions": _number(spec.get("leaseTransitions")),
            }
    return CuratedCells(tuple((field.key, values[field.key]) for field in family.fields))


class _Details:
    """Share row and UTF-8 budgets across sections, including their headings."""

    def __init__(self) -> None:
        self.sections: list[DetailSection] = []
        self.rows = 0
        self.bytes = 0

    def section(
        self, title: str, columns: tuple[str, ...], rows: Iterable[tuple[str, ...]]
    ) -> None:
        accepted: list[tuple[str, ...]] = []
        omitted = 0
        self.bytes += len((title + "".join(columns)).encode())
        for row in rows:
            safe = tuple(_text(value).text for value in row)
            size = sum(len(value.encode()) for value in safe)
            if self.rows < _LIMIT and self.bytes + size <= MAX_CURATED_DETAIL_BYTES:
                accepted.append(safe)
                self.rows += 1
                self.bytes += size
            else:
                omitted += 1
        self.sections.append(DetailSection(title, columns, tuple(accepted), omitted))


def _encoded(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _finish(result: _Details, links: list[CuratedLink], notices: list[str]) -> CuratedDetails:
    """Account for complete action identities and JSON structure, reserving omission notices."""
    sections = [replace(section, rows=()) for section in result.sections]
    base = CuratedDetails(tuple(sections), (), tuple(notices))
    # The fixed reserve covers the two authored omission notices and changed count widths.
    size = _encoded(asdict(base)) + 512
    used = 0
    for index, original in enumerate(result.sections):
        accepted: list[tuple[str, ...]] = []
        omitted = original.omitted_rows
        for row in original.rows:
            added = _encoded(row) + 1
            if used < _LIMIT and size + added <= MAX_CURATED_DETAIL_BYTES:
                accepted.append(row)
                used += 1
                size += added
            else:
                omitted += 1
        sections[index] = replace(original, rows=tuple(accepted), omitted_rows=omitted)
    selected: list[CuratedLink] = []
    for link in links:
        added = _encoded(asdict(link)) + 1
        if used < _LIMIT and size + added <= MAX_CURATED_DETAIL_BYTES:
            selected.append(link)
            used += 1
            size += added
    omitted_links = len(links) - len(selected)
    if omitted_links:
        notices.append(
            f"Links omitted: {omitted_links}; complete identities exceed the row/link or byte budget."
        )
    if any(section.omitted_rows for section in sections):
        notices.append(
            "Detail row or UTF-8 byte budget reached; omitted row counts are shown per section."
        )
    return CuratedDetails(tuple(sections), tuple(selected), tuple(notices))


def _metric_identity(raw: object) -> tuple[str, dict[str, Any]]:
    item = _map(raw)
    kind = item.get("type")
    keys = {
        "Resource": "resource",
        "ContainerResource": "containerResource",
        "Pods": "pods",
        "Object": "object",
        "External": "external",
    }
    if not isinstance(kind, str) or kind not in keys:
        raise AppError("Unsupported metric source.")
    body = _map(item.get(keys[kind]))
    identity: dict[str, Any] = {"type": kind}
    if kind in {"Resource", "ContainerResource"}:
        identity["name"] = api_segment(body.get("name"))
        if kind == "ContainerResource":
            identity["container"] = api_segment(body.get("container"))
    else:
        metric = _map(body.get("metric"))
        name = metric.get("name")
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z_:][A-Za-z0-9_:./-]{0,252}", name
        ):
            raise AppError("Invalid metric identity.")
        selector = structured_selector(metric.get("selector", {}))
        identity["metric"] = name
        identity["selector"] = sorted(
            (entry.key, entry.operator, sorted(entry.values)) for entry in selector.requirements
        )
        if kind == "Object":
            ref = _ref(body.get("describedObject"), None)
            identity["object"] = (ref.api_version, ref.kind, ref.name)
    return json.dumps(identity, sort_keys=True), body


def _metric_value(raw: object, *, target: bool = False) -> str:
    data = _map(raw)
    if target:
        field = {
            "Utilization": "averageUtilization",
            "Value": "value",
            "AverageValue": "averageValue",
        }.get(str(data.get("type")))
        if field is None:
            return "Unknown target type"
        data = {field: data.get(field)}
    values = (
        ("utilization", _number(data.get("averageUtilization")), "%"),
        ("value", _quantity(data.get("value")), ""),
        ("average", _quantity(data.get("averageValue")), ""),
    )
    return (
        ", ".join(
            f"{key}={value.text}{suffix}" for key, value, suffix in values if value.sort is not None
        )
        or "—"
    )


def _hpa_metrics(spec: dict[str, Any], status: dict[str, Any]) -> Iterable[tuple[str, ...]]:
    desired = spec.get("metrics")
    current = status.get("currentMetrics")
    desired = desired if isinstance(desired, list) else []
    current = current if isinstance(current, list) else []
    truncated = len(desired) > _LIMIT or len(current) > _LIMIT
    indexed: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    for item in current[:_LIMIT]:
        try:
            identity, body = _metric_identity(item)
            indexed.setdefault(identity, []).append(body)
        except AppError:
            invalid += 1
    targets: dict[str, int] = {}
    for item in desired[:_LIMIT]:
        try:
            identity, _ = _metric_identity(item)
            targets[identity] = targets.get(identity, 0) + 1
        except AppError:
            pass
    for item in desired[:_LIMIT]:
        try:
            identity, body = _metric_identity(item)
            matches = indexed.pop(identity, [])
            unique = not truncated and len(matches) == 1 and targets[identity] == 1
            observation = _metric_value(matches[0].get("current")) if unique else "Unpaired"
            evidence = (
                "Pairing uncertain: metric input collection truncated"
                if truncated
                else (
                    "Matched complete identity"
                    if unique
                    else "Missing or ambiguous current identity"
                )
            )
            yield identity, _metric_value(body.get("target"), target=True), observation, evidence
        except AppError:
            yield "Invalid metric identity", "—", "Unpaired", "Unsupported or invalid source"
    for identity, matches in indexed.items():
        yield identity, "—", "Unpaired", f"{len(matches)} status entries without unique target"
    if invalid:
        yield "Invalid status metrics", "—", "Unpaired", str(invalid)
    excess = max(0, len(desired) - _LIMIT) + max(0, len(current) - _LIMIT)
    if excess:
        yield "Metric entries omitted", str(excess), "—", "Input collection limit"


def _resource_rows(value: object, prefix: tuple[str, ...] = ()) -> Iterable[tuple[str, ...]]:
    data = _map(value)
    for key, quantity in islice(data.items(), _LIMIT):
        yield (*prefix, _text(key).text, _quantity(quantity).text)
    if len(data) > _LIMIT:
        yield (*prefix, "Resources omitted", str(len(data) - _LIMIT))


def _items(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _recommendation_rows(recommendations: list[Any]) -> Iterable[tuple[str, ...]]:
    for raw in recommendations[:_LIMIT]:
        item = _map(raw)
        for bound in ("target", "lowerBound", "upperBound", "uncappedTarget"):
            yield from _resource_rows(
                item.get(bound), (_text(item.get("containerName")).text, bound)
            )


def _policy_rows(policies: list[Any]) -> Iterable[tuple[str, ...]]:
    for raw in policies[:_LIMIT]:
        item = _map(raw)
        container = _text(item.get("containerName")).text
        yield container, "mode", "—", _text(item.get("mode", "Auto")).text
        yield (
            container,
            "controlledValues",
            "—",
            _text(item.get("controlledValues", "RequestsAndLimits")).text,
        )
        yield from _resource_rows(item.get("minAllowed"), (container, "minAllowed"))
        yield from _resource_rows(item.get("maxAllowed"), (container, "maxAllowed"))
        resources = _items(item.get("controlledResources"))
        for resource in resources[:_LIMIT]:
            yield container, "controlledResource", _text(resource).text, "Declared"
        if len(resources) > _LIMIT:
            yield container, "Controlled resources omitted", "—", str(len(resources) - _LIMIT)


def details(resource: ApiResource, record: ResourceRecord) -> CuratedDetails:
    """Publish declared facts and literal links, never controller/leader health claims."""
    family, data = require_curated_record(resource, record, FAMILIES)
    spec, status = _map(data.get("spec")), _map(data.get("status"))
    result = _Details()
    values = cells(resource, record).values
    result.section("Summary", ("Field", "Value"), ((key, value.text) for key, value in values))
    links: list[CuratedLink] = []
    notices: list[str] = []
    match family.kind:
        case "HorizontalPodAutoscaler":
            links.append(
                _reference_link(
                    "target", "Scale target", spec.get("scaleTargetRef"), record.namespace
                )
            )
            result.section(
                "Observation",
                ("Field", "Value"),
                (
                    (
                        "Observed generation",
                        _number(status.get("observedGeneration"), maximum=2**63 - 1).text,
                    ),
                    (
                        "Minimum replicas provenance",
                        "Declared" if "minReplicas" in spec else "API default: 1",
                    ),
                ),
            )
            if resource.version == "v1":
                result.section(
                    "CPU metric (v1)",
                    ("Target percent", "Current percent"),
                    (
                        (
                            _number(spec.get("targetCPUUtilizationPercentage")).text,
                            _number(status.get("currentCPUUtilizationPercentage")).text,
                        ),
                    ),
                )
            else:
                if (
                    len(_items(spec.get("metrics"))) > _LIMIT
                    or len(_items(status.get("currentMetrics"))) > _LIMIT
                ):
                    notices.append(
                        "Metric pairing uncertain: input collection limit prevents proving identity uniqueness."
                    )
                result.section(
                    "Metrics (v2)",
                    ("Complete identity", "Target", "Current", "Evidence"),
                    _hpa_metrics(spec, status),
                )
        case "VerticalPodAutoscaler":
            links.append(
                _reference_link("target", "Target", spec.get("targetRef"), record.namespace)
            )
            policy = _map(spec.get("updatePolicy"))
            result.section(
                "Update policy",
                ("Field", "Value"),
                (
                    (
                        "Mode provenance",
                        "Declared" if "updateMode" in policy else "API default: Auto",
                    ),
                ),
            )
            recommendations = _items(
                _map(status.get("recommendation")).get("containerRecommendations")
            )
            result.section(
                "Recommendations",
                ("Container", "Bound", "Resource", "Quantity"),
                _recommendation_rows(recommendations),
            )
            notices.append(
                f"Recommendation containers omitted: {max(0, len(recommendations) - _LIMIT)}."
            )
            policies = _items(_map(spec.get("resourcePolicy")).get("containerPolicies"))
            result.section(
                "Resource policies",
                ("Container", "Field", "Resource", "Value"),
                _policy_rows(policies),
            )
            notices.append(f"Container policies omitted: {max(0, len(policies) - _LIMIT)}.")
        case "PodDisruptionBudget":
            raw = spec.get("selector")
            try:
                selector = structured_selector(
                    {} if raw is None else raw, empty_matches=raw is not None
                )
                destination = CollectionDestination(
                    "", "pods", "v1", "object-namespace", record.namespace, LabelsMatch(selector)
                )
                links.append(
                    CuratedLink("pods", "Matching Pods", "Declared policy/v1 selector", destination)
                )
                semantics = (
                    "No Pods (null or absent selector)"
                    if raw is None
                    else (
                        "All Pods in object namespace (empty selector)"
                        if not selector.requirements
                        else "Declared selector requirements"
                    )
                )
                result.section(
                    "Selector",
                    ("Field", "Value"),
                    (
                        ("Semantics", semantics),
                        *(
                            (entry.key, f"{entry.operator}: {', '.join(entry.values)}")
                            for entry in selector.requirements[:_LIMIT]
                        ),
                    ),
                )
                notices.append(
                    f"Selector requirements omitted: {max(0, len(selector.requirements) - _LIMIT)}."
                )
            except AppError:
                links.append(
                    CuratedLink(
                        "pods",
                        "Matching Pods",
                        "Declared policy/v1 selector",
                        None,
                        "Selector is invalid or over limit.",
                    )
                )
                result.section(
                    "Selector",
                    ("Field", "Value"),
                    (("Semantics", "Invalid selector; selection disabled"),),
                )
            result.section(
                "Status provenance",
                ("Field", "Value"),
                (
                    (
                        "Observed generation",
                        _number(status.get("observedGeneration"), maximum=2**63 - 1).text,
                    ),
                    (
                        "Unhealthy Pod eviction policy",
                        _text(spec.get("unhealthyPodEvictionPolicy", "IfHealthyBudget")).text,
                    ),
                    (
                        "Eviction policy provenance",
                        "Declared"
                        if "unhealthyPodEvictionPolicy" in spec
                        else "API default: IfHealthyBudget",
                    ),
                ),
            )
        case "PriorityClass":
            result.section(
                "Defaults and description",
                ("Field", "Value"),
                (
                    (
                        "Global default provenance",
                        "Declared" if "globalDefault" in data else "API default: false",
                    ),
                    (
                        "Preemption provenance",
                        "Declared"
                        if "preemptionPolicy" in data
                        else "API default: PreemptLowerPriority",
                    ),
                    (
                        "Description",
                        "Configured; free text concealed"
                        if "description" in data
                        else "Not declared",
                    ),
                ),
            )
            links.append(
                CuratedLink(
                    "usedby",
                    "Used by",
                    "Existing relationship analysis; selected search scope",
                    RelationshipDestination(RelationshipMode.USED_BY),
                )
            )
        case "RuntimeClass":
            result.section(
                "Pod overhead",
                ("Resource", "Quantity"),
                _resource_rows(_map(data.get("overhead")).get("podFixed")),
            )
            scheduling = _map(data.get("scheduling"))
            try:
                selector = structured_selector(scheduling.get("nodeSelector", {}), direct=True)
                selector_rows = tuple(
                    (entry.key, entry.values[0]) for entry in selector.requirements[:_LIMIT]
                )
                notices.append(
                    f"Node selector requirements omitted: {max(0, len(selector.requirements) - _LIMIT)}."
                )
            except AppError:
                selector_rows = (("Selector", "Invalid; no inferred scheduling result"),)
            result.section("Declared node selector", ("Label", "Value"), selector_rows)
            tolerations = _items(scheduling.get("tolerations"))
            result.section(
                "Declared tolerations",
                ("Key", "Operator", "Value", "Effect", "Seconds"),
                (
                    (
                        _text(item.get("key")).text,
                        _text(item.get("operator", "Equal")).text,
                        _text(item.get("value")).text,
                        _text(item.get("effect")).text,
                        _number(item.get("tolerationSeconds"), maximum=2**63 - 1).text,
                    )
                    for item in map(_map, tolerations[:_LIMIT])
                ),
            )
            notices.append(
                f"Tolerations omitted: {max(0, len(tolerations) - _LIMIT)}. Handler is declared configuration, not runtime health."
            )
            try:
                destination = CollectionDestination(
                    "", "pods", "v1", "selected-namespace", None, PodRuntimeClass(record.name)
                )
                links.append(
                    CuratedLink(
                        "pods",
                        "Pods using RuntimeClass",
                        "Exact declared spec.runtimeClassName; selected search scope",
                        destination,
                    )
                )
            except AppError:
                links.append(
                    CuratedLink(
                        "pods",
                        "Pods using RuntimeClass",
                        "Declared runtime class name",
                        None,
                        "RuntimeClass name is invalid or over limit.",
                    )
                )
        case _:
            result.section(
                "Reported Lease observations",
                ("Field", "Value"),
                (
                    ("Acquire time", _timestamp(spec.get("acquireTime")).text),
                    (
                        "Renew time provenance",
                        "Reported timestamp; no local-clock expiry or leadership inference",
                    ),
                    ("Strategy", _text(spec.get("strategy")).text),
                    ("Preferred holder", _text(spec.get("preferredHolder")).text),
                ),
            )
            owners = _items(_map(data.get("metadata")).get("ownerReferences"))
            links.extend(
                _reference_link(
                    f"owner-{index}", f"Owner {index + 1}", owner, record.namespace, uid=True
                )
                for index, owner in enumerate(owners[:_LIMIT])
            )
            if not owners:
                notices.append(
                    "No explicit owner references; holder identity is not an object reference."
                )
            notices.append(f"Owner references omitted: {max(0, len(owners) - _LIMIT)}.")
            links.append(
                _reference_link(
                    "namespace",
                    "Namespace",
                    {"apiVersion": "v1", "kind": "Namespace", "name": record.namespace},
                    None,
                )
            )
    result.section("Reported conditions", ("Type", "Status"), _condition_rows(status))
    conditions = _items(status.get("conditions"))
    notices.append(f"Condition entries omitted: {max(0, len(conditions) - _LIMIT)}.")
    return _finish(result, links, notices)
