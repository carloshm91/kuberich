"""Bounded admission declarations and current-name links; no admission evaluation."""

import json
import re
from collections.abc import Iterable
from dataclasses import asdict
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
    CollectionDestination,
    CuratedLink,
    DeclaredObjectReference,
    PolicyBindingMatch,
    ReferenceDestination,
)
from kuberich.domain.relationships import structured_selector
from kuberich.domain.resources import ApiResource, ResourceRecord, api_segment, split_api_version
from kuberich.domain.table_values import Column, Value
from kuberich.errors import AppError

_GROUP = "admissionregistration.k8s.io"
_UNKNOWN = Value("—", None)
_UNAVAILABLE = "A declaration is missing, malformed, or exceeds its safe input bound."
_OMITTED = "Some declared detail rows or actions were omitted at the output bound."
_MAX_DECLARED_IDENTITY_CHARACTERS = 8192
_VERSIONS = frozenset({"v1", "v1beta1"})
_POLICY_BINDINGS = {
    "validatingadmissionpolicies": (
        "validatingadmissionpolicybindings",
        "ValidatingAdmissionPolicyBinding",
    ),
    "mutatingadmissionpolicies": (
        "mutatingadmissionpolicybindings",
        "MutatingAdmissionPolicyBinding",
    ),
}
_BINDING_POLICIES = {
    "validatingadmissionpolicybindings": "ValidatingAdmissionPolicy",
    "mutatingadmissionpolicybindings": "MutatingAdmissionPolicy",
}
FAMILIES = (
    CuratedFamily(
        _GROUP,
        "validatingadmissionpolicies",
        "ValidatingAdmissionPolicy",
        False,
        _VERSIONS,
        ("validatingadmissionpolicy", "vap"),
        tuple(
            Column(key, key in {"match-rules", "match-conditions", "validations"})
            for key in (
                "match-rules",
                "match-conditions",
                "failure-policy",
                "param-kind",
                "validations",
                "observation",
            )
        ),
    ),
    CuratedFamily(
        _GROUP,
        "validatingadmissionpolicybindings",
        "ValidatingAdmissionPolicyBinding",
        False,
        _VERSIONS,
        ("validatingadmissionpolicybinding", "vapb"),
        tuple(
            Column(key, key == "match-rules")
            for key in ("policy", "actions", "parameters", "match-rules")
        ),
    ),
    CuratedFamily(
        _GROUP,
        "mutatingadmissionpolicies",
        "MutatingAdmissionPolicy",
        False,
        _VERSIONS,
        ("mutatingadmissionpolicy", "map"),
        tuple(
            Column(key, key in {"match-rules", "match-conditions", "mutations"})
            for key in (
                "match-rules",
                "match-conditions",
                "failure-policy",
                "param-kind",
                "mutations",
                "reinvocation",
            )
        ),
    ),
    CuratedFamily(
        _GROUP,
        "mutatingadmissionpolicybindings",
        "MutatingAdmissionPolicyBinding",
        False,
        _VERSIONS,
        ("mutatingadmissionpolicybinding", "mapb"),
        tuple(Column(key, key == "match-rules") for key in ("policy", "parameters", "match-rules")),
    ),
)


def _literal(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "—"
    safe = sanitize_text(value)
    if len(safe) > MAX_CURATED_CELL_CHARACTERS:
        return safe[: MAX_CURATED_CELL_CHARACTERS - 1] + "…"
    return safe


def _text(value: object) -> Value:
    text = _literal(value)
    return _UNKNOWN if text == "—" else Value(text, text.casefold())


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> Value:
    return Value(str(value), value) if type(value) is int and 0 <= value < 2**63 else _UNKNOWN


class _Facts:
    def __init__(self) -> None:
        self.values: dict[str, Value] = {}
        self.sections: list[DetailSection] = []
        self.links: list[CuratedLink] = []
        self.notices: list[str] = []
        # Reserve all fixed headers, notices, cells and JSON escaping overhead.
        self.used = 16 * 1024
        self.rows = 0

    def note(self, text: str) -> None:
        if text not in self.notices:
            self.notices.append(text)

    def section(
        self, title: str, columns: tuple[str, ...], rows: Iterable[tuple[str, ...]]
    ) -> None:
        retained: list[tuple[str, ...]] = []
        omitted = 0
        for row in rows:
            safe = tuple(_literal(value) for value in row)
            size = len(json.dumps(safe, ensure_ascii=True).encode()) + 8
            if self.rows >= MAX_CURATED_DETAIL_ROWS or self.used + size > MAX_CURATED_DETAIL_BYTES:
                omitted += 1
                self.note(_OMITTED)
            else:
                retained.append(safe)
                self.used += size
                self.rows += 1
        self.sections.append(DetailSection(title, columns, tuple(retained), omitted))

    def link(self, link: CuratedLink) -> None:
        size = len(json.dumps(asdict(link), ensure_ascii=True).encode()) + 128
        if self.rows >= MAX_CURATED_DETAIL_ROWS or self.used + size > MAX_CURATED_DETAIL_BYTES:
            self.note(_OMITTED)
        else:
            self.links.append(link)
            self.rows += 1
            self.used += size

    def objects(self, value: object, *, maximum: int = 256) -> list[dict[str, Any]] | None:
        if (
            not isinstance(value, list)
            or len(value) > maximum
            or any(not isinstance(item, dict) for item in value)
        ):
            self.note(_UNAVAILABLE)
            return None
        return value


def _count(value: object, facts: _Facts, *, maximum: int = 256) -> Value:
    objects = facts.objects(value, maximum=maximum)
    return _number(len(objects)) if objects is not None else _UNKNOWN


def _named_count(value: object, identity: str, facts: _Facts, *, maximum: int = 256) -> Value:
    objects = facts.objects(value, maximum=maximum)
    if objects is None:
        return _UNKNOWN
    names = [item.get(identity) for item in objects]
    if any(
        not isinstance(name, str)
        or not name
        or len(name) > _MAX_DECLARED_IDENTITY_CHARACTERS
        or sanitize_text(name) != name
        for name in names
    ) or len(set(names)) != len(names):
        facts.note(
            "A named declaration has a missing, malformed, duplicate, or oversized identity; its count is unavailable."
        )
        return _UNKNOWN
    return _number(len(objects))


def _strings(
    value: object, facts: _Facts, *, empty: str = "none declared", core_group: bool = False
) -> str:
    if (
        not isinstance(value, list)
        or len(value) > 256
        or any(not isinstance(item, str) for item in value)
    ):
        facts.note(_UNAVAILABLE)
        return "—"
    if len(value) > 16:
        facts.note("String summary entries beyond the first 16 are omitted.")
    return (
        ", ".join("core" if core_group and item == "" else _literal(item) for item in value[:16])
        if value
        else empty
    )


def _enum(value: object, allowed: tuple[str, ...], facts: _Facts) -> str:
    if value not in allowed:
        facts.note(_UNAVAILABLE)
        return "—"
    return value


def _selector(value: object, facts: _Facts) -> str:
    try:
        parsed = structured_selector(value)
    except AppError:
        facts.note("A malformed selector cannot establish a selection.")
        return "—"
    return (
        "; ".join(
            f"{item.key} {item.operator} ({','.join(item.values)})" for item in parsed.requirements
        )
        or "empty selector (all within declared scope)"
    )


def _matching(value: object, facts: _Facts, *, binding: bool) -> None:
    label = "matchResources" if binding else "matchConstraints"
    facts.note(
        "Include rules are alternatives; exclusions take precedence. Binding and policy constraints both apply, followed by policy match conditions."
    )
    if value is None and binding:
        facts.values["match-rules"] = _number(0)
        facts.section(
            label + " (declared)",
            ("Field", "Value"),
            ((label, "omitted: no additional binding restriction"),),
        )
        return
    if not isinstance(value, dict):
        facts.values["match-rules"] = _UNKNOWN
        facts.note(
            "Malformed binding matchResources are unavailable, not an omitted restriction."
            if binding
            else "Policy matchConstraints are required; unavailable constraints are not unrestricted."
        )
        return
    included = facts.objects(
        value.get("resourceRules", []) if binding else value.get("resourceRules")
    )
    excluded = facts.objects(value.get("excludeResourceRules", []))
    facts.values["match-rules"] = _number(len(included)) if included is not None else _UNKNOWN
    if not binding and included == []:
        facts.note(
            "Policy resourceRules are required; no matching request is inferred from an empty declaration."
        )
    rows = [
        (
            "matchPolicy",
            _enum(value.get("matchPolicy", "Equivalent"), ("Exact", "Equivalent"), facts),
            "declared" if "matchPolicy" in value else "API default",
        ),
        *(
            (
                field,
                _selector(value.get(field, {}), facts),
                "declared" if field in value else "API default",
            )
            for field in ("namespaceSelector", "objectSelector")
        ),
    ]
    facts.section(label + " selectors", ("Field", "Value", "Origin"), rows)
    rules = []
    for mode, items in (("include", included), ("exclude", excluded)):
        for index, rule in enumerate(items or []):
            rules.append(
                (
                    mode,
                    str(index),
                    *(
                        _strings(rule.get(field, []), facts, empty="all names")
                        if field == "resourceNames"
                        else _strings(rule.get(field), facts, core_group=field == "apiGroups")
                        for field in (
                            "operations",
                            "apiGroups",
                            "apiVersions",
                            "resources",
                            "resourceNames",
                        )
                    ),
                    _enum(rule.get("scope", "*"), ("*", "Namespaced", "Cluster"), facts),
                )
            )
    facts.section(
        label + " rules (declared)",
        (
            "Mode",
            "Rule",
            "Operations",
            "API groups",
            "API versions",
            "Resources/subresources",
            "Resource names",
            "Scope",
        ),
        rules,
    )
    facts.note(
        "Namespace selectors use Namespace labels for Namespace requests and do not skip other cluster resources. Object selectors inspect request old/new labels; this view does not evaluate them."
    )


def _param_kind(spec: dict[str, Any], facts: _Facts) -> None:
    raw = spec.get("paramKind")
    if raw is None:
        facts.values["param-kind"] = _text("none declared")
        return
    item = _mapping(raw)
    try:
        group, version = split_api_version(item.get("apiVersion"))
        kind = item.get("kind")
        if not isinstance(kind, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind) is None:
            raise AppError("Invalid parameter kind.")
    except AppError:
        facts.values["param-kind"] = _UNKNOWN
        facts.note(_UNAVAILABLE)
    else:
        facts.values["param-kind"] = _text(f"{group + '/' if group else ''}{version} {kind}")
    facts.section(
        "Parameter kind (declared)",
        ("API version", "Kind"),
        ((_literal(item.get("apiVersion")), _literal(item.get("kind"))),),
    )
    facts.note(
        "Parameter kind is a declaration, not a lookup. Parameter values are never read by this view."
    )


def _parameters(spec: dict[str, Any], facts: _Facts) -> None:
    raw = spec.get("paramRef")
    if raw is None:
        facts.values["parameters"] = _text("none declared")
        facts.note("No paramRef is declared; this does not mean a parameter lookup failed.")
        return
    item = _mapping(raw)
    name, selector = item.get("name"), item.get("selector")
    mode, identity = "—", "—"
    try:
        if name not in (None, "") and selector is None:
            identity, mode = api_segment(name), "name"
        elif name in (None, "") and selector is not None:
            identity = _selector(selector, facts)
            mode = "selector" if identity != "—" else "—"
        else:
            raise AppError("Parameter name and selector must be exclusive.")
        namespace = item.get("namespace")
        if namespace not in (None, ""):
            namespace = namespace_name(namespace)
    except AppError:
        mode, identity, namespace = "—", "—", "—"
        facts.note(_UNAVAILABLE)
    action = _enum(item.get("parameterNotFoundAction"), ("Allow", "Deny"), facts)
    facts.values["parameters"] = _text(mode)
    facts.section(
        "Parameter reference (declared)",
        ("Mode", "Identity/selector", "Explicit namespace", "parameterNotFoundAction"),
        ((mode, identity, namespace or "omitted", action),),
    )
    facts.note(
        "For namespaced paramKind, omitted parameter namespace depends on the admission request namespace, never the header namespace. Cluster-scoped parameters require namespace omission."
    )
    facts.note(
        "Parameter values and lookup results are unavailable here; inspect the current named policy for its declared paramKind."
    )


def _observation(manifest: dict[str, Any], facts: _Facts) -> None:
    status = _mapping(manifest.get("status"))
    generation = _number(_mapping(manifest.get("metadata")).get("generation"))
    observed = _number(status.get("observedGeneration"))
    state = (
        "unknown generation"
        if generation.sort is None or observed.sort is None
        else "current generation"
        if generation.sort == observed.sort
        else "stale generation"
    )
    facts.values["observation"] = _text(state)
    checking = status.get("typeChecking")
    warnings = (
        _count(_mapping(checking).get("expressionWarnings", []), facts).text
        if isinstance(checking, dict)
        else "—"
    )
    facts.section(
        "Server-observed policy status",
        ("Generation", "Observed generation", "Provenance", "Type checking", "Warning count"),
        (
            (
                generation.text,
                observed.text,
                state,
                "reported" if isinstance(checking, dict) else "unavailable",
                warnings,
            ),
        ),
    )
    conditions = facts.objects(status.get("conditions", []))
    facts.section(
        "Server-observed conditions",
        ("Type", "Status", "Observed generation"),
        (
            (
                _literal(item.get("type")),
                _enum(item.get("status"), ("True", "False", "Unknown"), facts),
                _number(item.get("observedGeneration")).text,
            )
            for item in conditions or []
        ),
    )
    facts.note(
        "Conditions and type checking are server observations with generation provenance. No warnings does not prove that an admission request succeeds."
    )


def _policy(
    resource: ApiResource,
    record: ResourceRecord,
    manifest: dict[str, Any],
    spec: dict[str, Any],
    facts: _Facts,
) -> None:
    _matching(spec.get("matchConstraints"), facts, binding=False)
    _param_kind(spec, facts)
    failure = _enum(spec.get("failurePolicy", "Fail"), ("Fail", "Ignore"), facts)
    facts.values["failure-policy"] = _text(failure)
    facts.values["match-conditions"] = _named_count(
        spec.get("matchConditions", []), "name", facts, maximum=64
    )
    counts = [("variables", _named_count(spec.get("variables", []), "name", facts).text)]
    if resource.name == "validatingadmissionpolicies":
        facts.values["validations"] = _count(spec.get("validations", []), facts)
        counts.extend(
            (
                ("validations", facts.values["validations"].text),
                (
                    "auditAnnotations",
                    _named_count(spec.get("auditAnnotations", []), "key", facts).text,
                ),
            )
        )
        _observation(manifest, facts)
    else:
        facts.values["mutations"] = _count(spec.get("mutations"), facts)
        reinvocation = _enum(spec.get("reinvocationPolicy"), ("Never", "IfNeeded"), facts)
        facts.values["reinvocation"] = _text(reinvocation)
        counts.extend(
            (("mutations", facts.values["mutations"].text), ("reinvocationPolicy", reinvocation))
        )
        mutations = facts.objects(spec.get("mutations"))
        if mutations == []:
            facts.note(
                "Mutating policy mutations are required; an empty declaration is not an admission outcome."
            )
        facts.section(
            "Mutation declarations (payloads concealed)",
            ("Index", "Patch type", "Payload"),
            (
                (
                    str(index),
                    _enum(item.get("patchType"), ("ApplyConfiguration", "JSONPatch"), facts),
                    "concealed; never executed",
                )
                for index, item in enumerate(mutations or [])
            ),
        )
        facts.note(
            "reinvocationPolicy is required for mutating policies; no webhook Never default or validating-policy status is inferred."
        )
    facts.section(
        "Policy content (declared; payloads concealed)",
        ("Field", "Count/value", "Origin"),
        (
            ("failurePolicy", failure, "declared" if "failurePolicy" in spec else "API default"),
            ("matchConditions", facts.values["match-conditions"].text, "declared count"),
            *(
                (
                    field,
                    count,
                    "declared required field"
                    if field == "reinvocationPolicy"
                    else "declared count",
                )
                for field, count in counts
            ),
        ),
    )
    binding_plural, binding_kind = _POLICY_BINDINGS[resource.name]
    try:
        api_segment(record.name)
        predicate = PolicyBindingMatch(
            resource.api_version,
            binding_plural,
            binding_kind,
            record.name,
        )
    except AppError:
        destination = None
    else:
        destination = CollectionDestination(
            _GROUP,
            binding_plural,
            resource.version,
            "cluster",
            None,
            predicate,
        )
    facts.link(
        CuratedLink(
            "bindings",
            "Bindings declaring this policy",
            "Exact spec.policyName on discovered same-version bindings; current-name relation, not historical UID continuity.",
            destination,
            None if destination is not None else "Policy name is malformed.",
        )
    )


def _binding(resource: ApiResource, spec: dict[str, Any], facts: _Facts) -> None:
    _matching(spec.get("matchResources"), facts, binding=True)
    _parameters(spec, facts)
    if resource.name == "validatingadmissionpolicybindings":
        actions = spec.get("validationActions")
        if (
            not isinstance(actions, list)
            or not actions
            or any(item not in ("Deny", "Warn", "Audit") for item in actions)
            or len(set(actions)) != len(actions)
            or {"Deny", "Warn"}.issubset(actions)
        ):
            facts.values["actions"] = _UNKNOWN
            facts.note(
                "Validation actions are missing or malformed; no enforcement result is inferred."
            )
        else:
            facts.values["actions"] = _text(", ".join(sorted(actions)))
    try:
        name = api_segment(spec.get("policyName"))
    except AppError:
        facts.values["policy"] = _UNKNOWN
        destination = None
    else:
        facts.values["policy"] = _text(name)
        destination = ReferenceDestination(
            DeclaredObjectReference(
                _GROUP, resource.version, _BINDING_POLICIES[resource.name], None, name
            ),
            False,
        )
    facts.section(
        "Binding declaration",
        ("Policy name", "validationActions") if "actions" in facts.values else ("Policy name",),
        (
            (facts.values["policy"].text, facts.values["actions"].text)
            if "actions" in facts.values
            else (facts.values["policy"].text,),
        ),
    )
    facts.link(
        CuratedLink(
            "policy",
            "Current named policy",
            "Declared policyName resolved through actual discovery; this name-only reference does not assert historical UID continuity.",
            destination,
            None if destination is not None else "Policy name is missing or malformed.",
        )
    )


def _extract(resource: ApiResource, record: ResourceRecord) -> tuple[CuratedCells, CuratedDetails]:
    family, manifest = require_curated_record(resource, record, FAMILIES)
    facts = _Facts()
    spec = manifest.get("spec")
    if not isinstance(spec, dict):
        facts.note("Admission spec is unavailable; no omitted-field defaults are inferred.")
    elif family.resource in _POLICY_BINDINGS:
        _policy(resource, record, manifest, spec, facts)
    else:
        _binding(resource, spec, facts)
    facts.note(
        "Configured declarations are not an admission simulator or an enforcement verdict. Requests, user identity, conversion and CEL evaluation are not reconstructed."
    )
    facts.note(
        "CEL expressions, variables, patches, validation messages, audit values and type-check warning text remain concealed and are never executed."
    )
    return CuratedCells(
        tuple((field.key, facts.values.get(field.key, _UNKNOWN)) for field in family.fields),
        tuple(facts.notices),
    ), CuratedDetails(tuple(facts.sections), tuple(facts.links), tuple(facts.notices))


def cells(resource: ApiResource, record: ResourceRecord) -> CuratedCells:
    return _extract(resource, record)[0]


def details(resource: ApiResource, record: ResourceRecord) -> CuratedDetails:
    return _extract(resource, record)[1]
