"""Bounded declared policy, endpoint, quota and admission facts; no evaluation or I/O."""

import json
import re
from collections.abc import Iterable
from dataclasses import asdict
from decimal import Decimal, localcontext
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import namespace_name
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
    AllResources,
    CollectionDestination,
    CuratedLink,
    DeclaredObjectReference,
    IngressClassName,
    LabelsMatch,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.quantities import parse_quantity
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipRef,
    RelationshipSelector,
    endpoint_references,
    structured_selector,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment
from kuberich.domain.table_values import Column, Value
from kuberich.errors import AppError

_UNKNOWN = Value("—", None)
_ITEMS = MAX_CURATED_DETAIL_ROWS
_WEBHOOK_COLUMNS = tuple(
    Column(key, key in {"webhooks", "timeout-min", "timeout-max"})
    for key in (
        "webhooks",
        "review-versions",
        "failure-policies",
        "side-effects",
        "clients",
        "timeout-min",
        "timeout-max",
    )
)
FAMILIES = (
    CuratedFamily(
        "networking.k8s.io",
        "networkpolicies",
        "NetworkPolicy",
        True,
        frozenset({"v1"}),
        ("networkpolicy", "netpol"),
        tuple(
            Column(key, key.endswith("-rules"))
            for key in ("selector", "policy-types", "ingress-rules", "egress-rules")
        ),
    ),
    CuratedFamily(
        "discovery.k8s.io",
        "endpointslices",
        "EndpointSlice",
        True,
        frozenset({"v1"}),
        ("endpointslice",),
        tuple(
            Column(key, key in {"endpoints", "ready", "not-ready", "unspecified"})
            for key in (
                "address-type",
                "service",
                "endpoints",
                "ready",
                "not-ready",
                "unspecified",
                "ports",
            )
        ),
    ),
    CuratedFamily(
        "networking.k8s.io",
        "ingressclasses",
        "IngressClass",
        False,
        frozenset({"v1"}),
        ("ingressclass",),
        tuple(
            Column(key, key == "default")
            for key in ("controller", "default", "parameters-kind", "parameters-scope")
        ),
    ),
    CuratedFamily(
        "",
        "resourcequotas",
        "ResourceQuota",
        True,
        frozenset({"v1"}),
        ("resourcequota", "quota"),
        tuple(
            Column(key, key in {"resources", "exceeded"})
            for key in ("resources", "usage", "scopes", "exceeded")
        ),
    ),
    CuratedFamily(
        "",
        "limitranges",
        "LimitRange",
        True,
        frozenset({"v1"}),
        ("limitrange", "limits"),
        tuple(Column(key, key == "items") for key in ("types", "items", "defaults", "constraints")),
    ),
    CuratedFamily(
        "admissionregistration.k8s.io",
        "mutatingwebhookconfigurations",
        "MutatingWebhookConfiguration",
        False,
        frozenset({"v1"}),
        ("mutatingwebhookconfiguration",),
        _WEBHOOK_COLUMNS,
    ),
    CuratedFamily(
        "admissionregistration.k8s.io",
        "validatingwebhookconfigurations",
        "ValidatingWebhookConfiguration",
        False,
        frozenset({"v1"}),
        ("validatingwebhookconfiguration",),
        _WEBHOOK_COLUMNS,
    ),
)


def _literal(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    safe = sanitize_text(value)
    return (
        safe
        if len(safe) <= MAX_CURATED_CELL_CHARACTERS
        else safe[: MAX_CURATED_CELL_CHARACTERS - 1] + "…"
    )


def _text(value: object) -> Value:
    text = _literal(value)
    return _UNKNOWN if text == "—" else Value(text, text.casefold())


def _number(value: object) -> Value:
    return Value(str(value), value) if type(value) is int and 0 <= value < 2**63 else _UNKNOWN


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class _Facts:
    def __init__(self) -> None:
        self.values: dict[str, Value] = {}
        self.sections: list[DetailSection] = []
        self.links: list[CuratedLink] = []
        self.notices: list[str] = []
        self.used = 4096  # Reserve headers, bounded notices, and omission metadata.
        self.count = 0

    def note(self, text: str) -> None:
        if text not in self.notices and len(self.notices) < 16:
            self.notices.append(text)

    def section(
        self,
        title: str,
        columns: tuple[str, ...],
        rows: Iterable[tuple[str, ...]],
        omitted: int = 0,
    ) -> None:
        retained = []
        self.used += len(title.encode()) + sum(len(value.encode()) for value in columns)
        for row in rows:
            safe = tuple(_literal(value) for value in row)
            size = len(json.dumps(safe, ensure_ascii=True).encode()) + 8
            if self.count >= _ITEMS or self.used + size > MAX_CURATED_DETAIL_BYTES:
                omitted += 1
            else:
                retained.append(safe)
                self.used += size
                self.count += 1
        if omitted:
            self.note("Some declared detail rows or actions were omitted at the output bound.")
        self.sections.append(DetailSection(title, columns, tuple(retained), omitted))

    def link(self, link: CuratedLink) -> None:
        size = len(json.dumps(asdict(link), ensure_ascii=True).encode()) + 128
        if size > MAX_CURATED_DETAIL_BYTES - 4096:
            link = CuratedLink(
                link.key,
                link.label,
                link.provenance,
                None,
                "Declared identity exceeds the action payload bound.",
            )
            size = len(json.dumps(asdict(link), ensure_ascii=True).encode()) + 128
        if self.count < _ITEMS and self.used + size <= MAX_CURATED_DETAIL_BYTES:
            self.links.append(link)
            self.used += size
            self.count += 1
        else:
            self.note("Some declared detail rows or actions were omitted at the output bound.")


def _list(value: object, facts: _Facts, *, limit: int = _ITEMS) -> list[Any] | None:
    if not isinstance(value, list) or len(value) > limit:
        facts.note("A declared collection is missing, malformed, or exceeds its safe input bound.")
        return None
    return value


def _strings(value: object, facts: _Facts) -> str:
    items = _list(value, facts)
    if items is None or any(not isinstance(item, str) for item in items):
        facts.note("A declared string collection is unavailable.")
        return "—"
    if len(items) > 16:
        facts.note("String summary entries beyond the first16 are omitted.")
    return (
        ", ".join(_literal(item) for item in items[:16])
        + (f" … +{len(items) - 16}" if len(items) > 16 else "")
        if items
        else "none"
    )


def _selector(
    value: object, facts: _Facts, *, empty_text: str = "empty selector (all within declared scope)"
) -> tuple[str, RelationshipSelector | None]:
    try:
        parsed = structured_selector(value)
    except AppError:
        facts.note("A malformed selector cannot establish a selection.")
        return "—", None
    parts = [
        f"{item.key} {item.operator} ({','.join(item.values)})" for item in parsed.requirements
    ]
    return "; ".join(parts) if parts else empty_text, parsed


def _namespace_links(record: ResourceRecord, facts: _Facts) -> None:
    assert record.namespace is not None
    facts.link(
        CuratedLink(
            "namespace",
            "Namespace",
            "Current named namespace; no accounting or admission verdict.",
            ReferenceDestination(
                RelationshipRef("v1", "Namespace", None, record.namespace, None, None), False
            ),
        )
    )


def _browse(facts: _Facts, record: ResourceRecord, resource: str, label: str) -> None:
    facts.link(
        CuratedLink(
            resource,
            label,
            "Namespace exploration only; not accounting, applicability, or enforcement proof.",
            CollectionDestination(
                "", resource, "v1", "object-namespace", record.namespace, AllResources()
            ),
        )
    )


def _namespace(value: object) -> str:
    if not isinstance(value, str):
        raise AppError("Invalid namespace identity.")
    return namespace_name(value)


def _service_link(
    facts: _Facts, key: str, namespace: object, name: object, provenance: str
) -> None:
    try:
        target_namespace, target_name = _namespace(namespace), api_segment(name)
    except AppError:
        facts.link(
            CuratedLink(
                key,
                "Declared Service",
                provenance,
                None,
                "Service name or namespace is missing or malformed.",
            )
        )
    else:
        facts.link(
            CuratedLink(
                key,
                "Declared Service",
                provenance,
                ReferenceDestination(
                    RelationshipRef("v1", "Service", target_namespace, target_name, None, None),
                    False,
                ),
            )
        )


def _network(manifest: dict[str, Any], record: ResourceRecord, facts: _Facts) -> None:
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        facts.note("NetworkPolicy spec is unavailable; no selector default is inferred.")
        return
    selector_text, selector = _selector(
        spec.get("podSelector", {}), facts, empty_text="all namespace Pods"
    )
    facts.values["selector"] = _text(selector_text)
    facts.link(
        CuratedLink(
            "selected-pods",
            "Selected namespace Pods",
            "Declared NetworkPolicy podSelector; omitted selector defaults to all Pods in its namespace.",
            CollectionDestination(
                "", "pods", "v1", "object-namespace", record.namespace, LabelsMatch(selector)
            )
            if selector is not None
            else None,
            None if selector is not None else "Pod selector is malformed.",
        )
    )
    ingress, egress = _list(spec.get("ingress", []), facts), _list(spec.get("egress", []), facts)
    types = spec.get("policyTypes", [])
    origin = "declared"
    if types == []:
        types = ["Ingress", *(["Egress"] if egress else [])] if egress is not None else None
        origin = "API default"
    if (
        not isinstance(types, list)
        or not types
        or any(item not in ("Ingress", "Egress") for item in types)
    ):
        facts.note("Policy types are unavailable; no network effect is inferred.")
        facts.values["policy-types"] = _UNKNOWN
    else:
        facts.values["policy-types"] = _text(", ".join(sorted(set(types))))
    facts.values.update(
        {
            "ingress-rules": _number(len(ingress)) if ingress is not None else _UNKNOWN,
            "egress-rules": _number(len(egress)) if egress is not None else _UNKNOWN,
        }
    )
    facts.section(
        "NetworkPolicy declaration",
        ("Selector", "Policy types", "Origin"),
        ((selector_text, facts.values["policy-types"].text, origin),),
    )
    for direction, rules, peer_key in (("Ingress", ingress, "from"), ("Egress", egress, "to")):
        rows = []
        for index, raw in enumerate(rules or []):
            if not isinstance(raw, dict):
                facts.note("A malformed policy rule has no interpreted allow semantics.")
                rows.append((str(index), "invalid rule", "—"))
                continue
            rule = _mapping(raw)
            peers, ports = _list(rule.get(peer_key, []), facts), _list(rule.get("ports", []), facts)
            peer_text = []
            for peer_raw in (peers or [])[:16]:
                peer = _mapping(peer_raw)
                parts = [
                    name + ": " + _selector(peer[name], facts)[0]
                    for name in ("podSelector", "namespaceSelector")
                    if name in peer
                ]
                if "ipBlock" in peer:
                    block = _mapping(peer["ipBlock"])
                    parts.append(
                        "CIDR "
                        + _literal(block.get("cidr"))
                        + "; except "
                        + _strings(block.get("except", []), facts)
                    )
                peer_text.append(" + ".join(parts) if parts else "invalid peer")
            port_text = []
            for port_raw in (ports or [])[:16]:
                port = _mapping(port_raw)
                value, end = port.get("port"), port.get("endPort")
                valid = isinstance(port_raw, dict) and (
                    value is None
                    or (type(value) is int and 1 <= value <= 65535)
                    or (
                        isinstance(value, str)
                        and re.fullmatch(r"[a-z][a-z0-9-]{0,14}", value) is not None
                    )
                )
                if end is not None:
                    valid = (
                        valid and type(value) is int and type(end) is int and value <= end <= 65535
                    )
                protocol = port.get("protocol", "TCP")
                valid = valid and protocol in ("TCP", "UDP", "SCTP")
                port_text.append(
                    (
                        f"{value if value is not None else '*'}"
                        + (f"-{end}" if end is not None else "")
                        + f"/{protocol}"
                    )
                    if valid
                    else "invalid port"
                )
            if (peers is not None and len(peers) > 16) or (ports is not None and len(ports) > 16):
                facts.note("Peer/port summary entries beyond the first16 are omitted.")
            rows.append(
                (
                    str(index),
                    "; ".join(peer_text) if peers else "all peers" if peers == [] else "—",
                    ", ".join(port_text) if ports else "all ports" if ports == [] else "—",
                )
            )
        facts.section(direction + " rules (declared)", ("Rule", "Peers", "Ports"), rows)
    facts.note("Declared selectors/rules do not prove CNI enforcement or network reachability.")


def _endpoints(
    resource: ApiResource, manifest: dict[str, Any], record: ResourceRecord, facts: _Facts
) -> None:
    # These two optional EndpointSlice/v1 lists encode their nil zero value as null.
    raw_endpoints, raw_ports = manifest.get("endpoints"), manifest.get("ports")
    endpoints, ports = (
        _list([] if raw_endpoints is None else raw_endpoints, facts, limit=1000),
        _list([] if raw_ports is None else raw_ports, facts, limit=100),
    )
    facts.values["address-type"] = _text(manifest.get("addressType"))
    if manifest.get("addressType") not in ("IPv4", "IPv6", "FQDN"):
        facts.note("Unknown address type has no inferred address or consumer semantics.")
    name = _mapping(_mapping(manifest.get("metadata")).get("labels")).get(
        "kubernetes.io/service-name"
    )
    facts.values["service"] = _text(name)
    if name is not None:
        _service_link(
            facts,
            "service",
            record.namespace,
            name,
            "Declared EndpointSlice Service label; current named object, not backend health proof.",
        )
    else:
        facts.note(
            "No Service association is declared; custom slices need not belong to a Service."
        )
    try:
        refs = (
            endpoint_references(resource, record)
            if endpoints is not None and ports is not None
            else ()
        )
    except AppError:
        refs = ()
        facts.note("Malformed endpoint metadata prevents target-reference navigation.")
    for index, endpoint in enumerate(refs[:_ITEMS]):
        ref = endpoint.target
        facts.link(
            CuratedLink(
                f"target-{index}",
                f"Endpoint {index} target",
                "Observed targetRef requires exact UID; IP addresses never establish object identity.",
                ReferenceDestination(ref, True) if ref is not None and ref.uid else None,
                None if ref is not None and ref.uid else "No UID-bearing targetRef is available.",
            )
        )
    counts = {True: 0, False: 0, None: 0}
    valid = endpoints is not None
    rows = []
    for index, raw in enumerate(endpoints or []):
        item = _mapping(raw)
        conditions = item.get("conditions", {})
        condition = _mapping(conditions).get("ready")
        if (
            not isinstance(raw, dict)
            or not isinstance(conditions, dict)
            or (condition is not None and type(condition) is not bool)
        ):
            valid = False
        else:
            counts[condition] += 1
        if index < _ITEMS:
            flags = tuple(
                "unspecified"
                if value is None
                else str(value).lower()
                if type(value) is bool
                else "invalid"
                for value in (
                    _mapping(conditions).get(field) for field in ("ready", "serving", "terminating")
                )
            )
            rows.append(
                (
                    str(index),
                    _strings(item.get("addresses"), facts),
                    *flags,
                    _literal(_mapping(item.get("targetRef")).get("name")),
                )
            )
    facts.values.update(
        {
            "endpoints": _number(len(endpoints)) if endpoints is not None else _UNKNOWN,
            "ready": _number(counts[True]) if valid else _UNKNOWN,
            "not-ready": _number(counts[False]) if valid else _UNKNOWN,
            "unspecified": _number(counts[None]) if valid else _UNKNOWN,
        }
    )
    port_rows = []
    for raw in ports or []:
        item = _mapping(raw)
        value, protocol = item.get("port"), item.get("protocol", "TCP")
        port_rows.append(
            (
                _literal(item.get("name")),
                "all ports"
                if value is None
                else str(value)
                if type(value) is int and 1 <= value <= 65535
                else "invalid",
                _literal(protocol) if protocol in ("TCP", "UDP", "SCTP") else "invalid",
            )
        )
    facts.values["ports"] = (
        _text(", ".join(f"{row[0]}:{row[1]}/{row[2]}" for row in port_rows) or "none declared")
        if ports is not None
        else _UNKNOWN
    )
    facts.section(
        "Observed endpoints",
        ("Entry", "Addresses", "Ready", "Serving", "Terminating", "Target name"),
        rows,
        max(0, len(endpoints or []) - _ITEMS),
    )
    facts.section("Declared ports", ("Name", "Port", "Protocol"), port_rows)
    facts.note(
        "Flags are observed tri-state facts, not Pod health. Consumers generally treat unspecified ready/serving as true and terminating as false."
    )
    facts.note(
        "Multiple addresses and dual-stack slices are not distinct Pod counts; a nil port means all ports, never port0."
    )


def _ingress(manifest: dict[str, Any], record: ResourceRecord, facts: _Facts) -> None:
    spec = _mapping(manifest.get("spec"))
    annotation = _mapping(_mapping(manifest.get("metadata")).get("annotations")).get(
        "ingressclass.kubernetes.io/is-default-class", "false"
    )
    facts.values["controller"] = _text(spec.get("controller"))
    facts.values["default"] = (
        Value(annotation, int(annotation == "true"))
        if annotation in ("true", "false")
        else _UNKNOWN
    )
    if facts.values["default"] is _UNKNOWN:
        facts.note(
            "The recognized default-class annotation is malformed; arbitrary annotations remain hidden."
        )
    try:
        predicate = IngressClassName(record.name)
    except AppError:
        facts.link(
            CuratedLink(
                "ingresses",
                "Ingresses using this class",
                "Exact spec.ingressClassName; legacy annotations are separate.",
                None,
                "Class name is invalid.",
            )
        )
    else:
        facts.link(
            CuratedLink(
                "ingresses",
                "Ingresses using this class",
                "Exact spec.ingressClassName; legacy annotations are separate.",
                CollectionDestination(
                    "networking.k8s.io", "ingresses", "v1", "selected-namespace", None, predicate
                ),
            )
        )
    parameters = spec.get("parameters")
    if parameters is not None:
        parameter = _mapping(parameters)
        scope = parameter.get("scope", "Cluster")
        facts.values.update(
            {"parameters-kind": _text(parameter.get("kind")), "parameters-scope": _text(scope)}
        )
        try:
            name = api_segment(parameter.get("name"))
            kind, group = parameter.get("kind"), parameter.get("apiGroup")
            if group is None:
                group = ""
            if (
                not isinstance(kind, str)
                or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind) is None
                or not isinstance(group, str)
            ):
                raise AppError("Invalid parameter identity.")
            if group:
                api_segment(group)
            namespace = _namespace(parameter.get("namespace")) if scope == "Namespace" else None
            if scope not in ("Namespace", "Cluster") or (
                scope == "Cluster" and parameter.get("namespace") is not None
            ):
                raise AppError("Invalid parameter scope.")
            destination = ReferenceDestination(
                DeclaredObjectReference(group, None, kind, namespace, name), False
            )
        except AppError:
            facts.link(
                CuratedLink(
                    "parameters",
                    "Declared parameters",
                    "Group/kind-only reference requires unique actual discovery; no guessed plural/version.",
                    None,
                    "Parameters identity or scope is malformed.",
                )
            )
        else:
            facts.link(
                CuratedLink(
                    "parameters",
                    "Declared parameters",
                    "Group/kind-only reference requires unique actual discovery; no guessed plural/version.",
                    destination,
                )
            )
        facts.section(
            "Declared parameters",
            ("Group", "Kind", "Name", "Scope", "Namespace"),
            (
                (
                    _literal(parameter.get("apiGroup")),
                    _literal(parameter.get("kind")),
                    _literal(parameter.get("name")),
                    _literal(scope),
                    _literal(parameter.get("namespace")),
                ),
            ),
        )
    else:
        facts.note("No parameters object is declared.")
    facts.section(
        "IngressClass",
        ("Controller", "Default class"),
        ((facts.values["controller"].text, facts.values["default"].text),),
    )


def _quantity(value: object, facts: _Facts) -> tuple[str, Decimal | None]:
    parsed = parse_quantity(value)
    if parsed is None:
        facts.note(
            "Missing or malformed quantities remain unknown; resource dimensions are never totalled."
        )
    return (_literal(value) if parsed is not None else "—", parsed)


def _quota(manifest: dict[str, Any], record: ResourceRecord, facts: _Facts) -> None:
    spec, status = _mapping(manifest.get("spec")), _mapping(manifest.get("status"))
    raw_maps = (spec.get("hard"), status.get("hard"), status.get("used"))
    maps = [_mapping(value) for value in raw_maps]
    keys = sorted({key for value in maps for key in value if isinstance(key, str)})
    facts.values["resources"] = (
        _number(len(keys)) if any(isinstance(value, dict) for value in raw_maps) else _UNKNOWN
    )
    exceeded, complete, rows, usage = (
        0,
        all(isinstance(value, dict) for value in raw_maps[1:]),
        [],
        [],
    )
    for key in keys[:_ITEMS]:
        desired, hard, used = (_quantity(value.get(key), facts) for value in maps)
        remaining = percent = "—"
        if hard[1] is None or used[1] is None:
            complete = False
        else:
            with localcontext() as context:
                context.prec = 100
                remaining = str(hard[1] - used[1])
                percent = str(used[1] * 100 / hard[1]) + "%" if hard[1] else "undefined (hard=0)"
                exceeded += used[1] > hard[1]
        usage.append(f"{key}: {used[0]}/{hard[0]}")
        rows.append((key, desired[0], hard[0], used[0], remaining, percent))
    facts.values.update(
        {
            "usage": _text("; ".join(usage)) if keys else _UNKNOWN,
            "scopes": _text(_strings(spec.get("scopes", []), facts)),
            "exceeded": _number(exceeded) if complete and len(keys) <= _ITEMS else _UNKNOWN,
        }
    )
    _namespace_links(record, facts)
    _browse(facts, record, "resourcequotas", "Namespace quotas")
    _browse(facts, record, "limitranges", "Namespace limits")
    _browse(facts, record, "pods", "Namespace Pods (exploration)")
    facts.section(
        "Quota per resource",
        (
            "Resource",
            "Desired spec.hard",
            "Enforced status.hard",
            "Used",
            "Remaining (base units)",
            "Utilization of enforced hard",
        ),
        rows,
        max(0, len(keys) - _ITEMS),
    )
    scope_rows = (
        [(value, "declared", "—") for value in spec.get("scopes", [])[:_ITEMS]]
        if isinstance(spec.get("scopes", []), list)
        else []
    )
    scope_count = len(scope_rows)
    selector = spec.get("scopeSelector")
    expressions = _list(_mapping(selector).get("matchExpressions", []), facts)
    if (selector is not None and not isinstance(selector, dict)) or expressions is None:
        facts.values["scopes"] = _UNKNOWN
        facts.note("Malformed quota scope declarations are not interpreted as no restriction.")
    for raw in expressions or []:
        item = _mapping(raw)
        scope_rows.append(
            (
                _literal(item.get("scopeName")),
                _literal(item.get("operator")),
                _strings(item.get("values", []), facts),
            )
        )
    if expressions and facts.values["scopes"].sort is not None:
        base = facts.values["scopes"].text
        summary = "; ".join(" ".join(row) for row in scope_rows[scope_count:])
        facts.values["scopes"] = _text((base + "; " if base != "none" else "") + summary)
    facts.section("Quota scope declarations", ("Scope", "Operator", "Values"), scope_rows)
    facts.note(
        "Usage compares each resource only with enforced status.hard; desired spec.hard is separate. Browsing does not reconstruct quota accounting."
    )


def _limits(manifest: dict[str, Any], record: ResourceRecord, facts: _Facts) -> None:
    items = _list(_mapping(manifest.get("spec")).get("limits"), facts)
    facts.values["items"] = _number(len(items)) if items is not None else _UNKNOWN
    types, defaults, constraints = [], [], []
    rows: list[tuple[str, ...]] = []
    valid_items, omitted = items is not None, 0
    for index, raw in enumerate(items or []):
        item = _mapping(raw)
        kind = _literal(item.get("type"))
        if (
            not isinstance(raw, dict)
            or kind not in ("Container", "Pod", "PersistentVolumeClaim")
            or any(
                not isinstance(item.get(field, {}), dict)
                for field in ("min", "max", "default", "defaultRequest", "maxLimitRequestRatio")
            )
        ):
            valid_items = False
            facts.note(
                "A malformed or unknown LimitRange item has no inferred defaults or constraints."
            )
        types.append(kind)
        maps = [
            _mapping(item.get(field, {}))
            for field in ("min", "max", "default", "defaultRequest", "maxLimitRequestRatio")
        ]
        keys = sorted({key for value in maps for key in value if isinstance(key, str)})
        remaining = max(0, _ITEMS - len(rows))
        omitted += max(0, len(keys) - remaining)
        for key in keys[:remaining]:
            values = tuple(_quantity(value.get(key), facts)[0] for value in maps)
            rows.append((str(index), kind, key, *values))
            defaults.append(f"#{index} {kind}/{key}: {values[2]}/{values[3]}")
            constraints.append(
                f"#{index} {kind}/{key}: {values[0]}..{values[1]}; ratio {values[4]}"
            )
    facts.values.update(
        {
            "types": _text(", ".join(sorted(set(types)))) if items is not None else _UNKNOWN,
            "defaults": _text("; ".join(defaults) or "none declared") if valid_items else _UNKNOWN,
            "constraints": _text("; ".join(constraints) or "none declared")
            if valid_items
            else _UNKNOWN,
        }
    )
    _namespace_links(record, facts)
    if {"Container", "Pod"}.intersection(types):
        _browse(facts, record, "pods", "Namespace Pods (exploration)")
    if "PersistentVolumeClaim" in types:
        _browse(facts, record, "persistentvolumeclaims", "Namespace PVCs (exploration)")
    facts.section(
        "LimitRange declarations",
        (
            "Item",
            "Type",
            "Resource",
            "Min",
            "Max",
            "Default limit",
            "Default request",
            "Max limit/request ratio (dimensionless)",
        ),
        rows,
        omitted,
    )
    facts.note(
        "Each item/type/resource is separate. Namespace browsing does not prove admission decisions or changes to existing objects."
    )


def _webhooks(manifest: dict[str, Any], record: ResourceRecord, facts: _Facts) -> None:
    hooks = _list(manifest.get("webhooks"), facts)
    facts.values["webhooks"] = _number(len(hooks)) if hooks is not None else _UNKNOWN
    reviews, failures, effects, clients, timeouts, rows = [], [], [], [], [], []
    rules: list[tuple[str, ...]] = []
    valid_timeouts = hooks is not None
    omitted_rules = 0
    for index, raw in enumerate(hooks or []):
        item = _mapping(raw)
        reviews.append(_strings(item.get("admissionReviewVersions"), facts))
        failures.append(
            _literal(item.get("failurePolicy", "Fail") if isinstance(raw, dict) else None)
        )
        effects.append(_literal(item.get("sideEffects")))
        if (
            failures[-1] not in ("Fail", "Ignore")
            or effects[-1] not in ("None", "NoneOnDryRun")
            or item.get("matchPolicy", "Equivalent") not in ("Exact", "Equivalent")
        ):
            facts.note(
                "An unknown webhook capability is displayed only as a declaration, not a trust or admission verdict."
            )
        timeout = item.get("timeoutSeconds", 10) if isinstance(raw, dict) else None
        if type(timeout) is int and 1 <= timeout <= 30:
            timeouts.append(timeout)
        else:
            valid_timeouts = False
            facts.note("A webhook timeout is unavailable; no zero timeout is inferred.")
        client = _mapping(item.get("clientConfig"))
        service, url = client.get("service"), client.get("url")
        classification = (
            "Service"
            if isinstance(service, dict) and url is None
            else "URL (not fetched)"
            if isinstance(url, str) and url and service is None
            else "invalid client"
        )
        clients.append(classification)
        if isinstance(service, dict) and classification == "Service":
            _service_link(
                facts,
                f"service-{index}",
                service.get("namespace"),
                service.get("name"),
                "Declared webhook Service in its explicit namespace; no trust or availability claim.",
            )
        else:
            facts.link(
                CuratedLink(
                    f"client-{index}",
                    f"Webhook {index} client",
                    "URL clients are classified only; URL userinfo/path/query are never exposed or fetched.",
                    None,
                    "No unambiguous declared Service reference.",
                )
            )
        ca = client.get("caBundle")
        ca_state = (
            "unknown CA source"
            if not isinstance(item.get("clientConfig"), dict)
            else "system roots (declared default)"
            if ca in (None, "")
            else "configured public CA (bytes concealed)"
            if isinstance(ca, str)
            else "malformed CA declaration (concealed)"
        )
        selector_parts = []
        for field in ("namespaceSelector", "objectSelector"):
            selector_parts.append(field + ": " + _selector(item.get(field, {}), facts)[0])
        rows.append(
            (
                str(index),
                _literal(item.get("name")),
                classification,
                ca_state,
                reviews[-1],
                failures[-1],
                effects[-1],
                str(timeout) if type(timeout) is int and 1 <= timeout <= 30 else "—",
                _literal(item.get("matchPolicy", "Equivalent")),
                "; ".join(selector_parts),
            )
        )
        hook_rules = _list(item.get("rules", []), facts) or []
        remaining = max(0, _ITEMS - len(rules))
        omitted_rules += max(0, len(hook_rules) - remaining)
        for raw_rule in hook_rules[:remaining]:
            rule = _mapping(raw_rule)
            rules.append(
                (
                    str(index),
                    _strings(rule.get("operations"), facts),
                    _strings(rule.get("apiGroups"), facts),
                    _strings(rule.get("apiVersions"), facts),
                    _strings(rule.get("resources"), facts),
                    _literal(rule.get("scope", "*")),
                )
            )
    for key, values in (
        ("review-versions", reviews),
        ("failure-policies", failures),
        ("side-effects", effects),
        ("clients", clients),
    ):
        facts.values[key] = (
            _text(", ".join(sorted(set(values))) or "none") if hooks is not None else _UNKNOWN
        )
    facts.values.update(
        {
            "timeout-min": _number(min(timeouts)) if timeouts and valid_timeouts else _UNKNOWN,
            "timeout-max": _number(max(timeouts)) if timeouts and valid_timeouts else _UNKNOWN,
        }
    )
    facts.link(
        CuratedLink(
            "owners",
            "Declared owners and references",
            "Existing relationship traversal, not admission simulation.",
            RelationshipDestination(RelationshipMode.XRAY),
        )
    )
    facts.section(
        "Webhook declarations",
        (
            "Index",
            "Name",
            "Client",
            "CA source",
            "Review versions",
            "Failure policy",
            "Side effects",
            "Timeout seconds",
            "Match policy",
            "Selectors",
        ),
        rows,
    )
    facts.section(
        "Declared webhook rules",
        ("Webhook", "Operations", "API groups", "API versions", "Resources", "Scope"),
        rules,
        omitted_rules,
    )
    facts.note(
        "Declarations are capabilities, not admission, trust, enforcement or reachability verdicts. CA bytes and URL payloads remain concealed."
    )


def _extract(resource: ApiResource, record: ResourceRecord) -> tuple[CuratedCells, CuratedDetails]:
    family, manifest = require_curated_record(resource, record, FAMILIES)
    facts = _Facts()
    if family.resource == "networkpolicies":
        _network(manifest, record, facts)
    elif family.resource == "endpointslices":
        _endpoints(resource, manifest, record, facts)
    elif family.resource == "ingressclasses":
        _ingress(manifest, record, facts)
    elif family.resource == "resourcequotas":
        _quota(manifest, record, facts)
    elif family.resource == "limitranges":
        _limits(manifest, record, facts)
    else:
        _webhooks(manifest, record, facts)
    if any(facts.values.get(field.key, _UNKNOWN).sort is None for field in family.fields):
        facts.note("Some curated fields are unavailable; missing or malformed values are not zero.")
    return CuratedCells(
        tuple((field.key, facts.values.get(field.key, _UNKNOWN)) for field in family.fields),
        tuple(facts.notices),
    ), CuratedDetails(tuple(facts.sections), tuple(facts.links), tuple(facts.notices))


def cells(resource: ApiResource, record: ResourceRecord) -> CuratedCells:
    return _extract(resource, record)[0]


def details(resource: ApiResource, record: ResourceRecord) -> CuratedDetails:
    return _extract(resource, record)[1]
