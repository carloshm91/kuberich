"""Bounded RBAC declarations and explanations; never an authorization decision."""

from dataclasses import dataclass, field
from typing import Any

from kuberich.domain.authorization import (
    MAX_AGGREGATION_DEPTH,
    MAX_AUTHORIZATION_COMPARISONS,
    MAX_AUTHORIZATION_RESULTS,
    AuthorizationScope,
    AuthorizationScopeKind,
    CurrentIdentity,
    EvidenceStatus,
    NonResourceAccess,
    RbacAggregation,
    RbacBinding,
    RbacEvidenceKind,
    RbacGrant,
    RbacMatchResult,
    RbacObjectRef,
    RbacRole,
    RbacRule,
    RbacSnapshot,
    RbacSubject,
    RbacSubjectKind,
    ResourceAccess,
    canonical_resource_access,
)
from kuberich.domain.relationships import (
    LabelRequirement,
    RelationshipSelector,
    fact_list,
    fact_mapping,
    relationship_manifest,
    resource_labels,
    selector_matches,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_name
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

_RBAC_GROUP = "rbac.authorization.k8s.io"
_EXTERNAL_WARNING = "RBAC declarations do not account for external authorizers; use a current SelfSubjectAccessReview for an authoritative answer."
_GROUP_WARNING = "Group membership is unknown except for the reviewed current identity; declared groups do not enumerate their members."
_COMPARISON_WARNING = "RBAC comparison budget exhausted; this is a deterministic partial result."
_RESULT_WARNING = "RBAC result budget exhausted; this is a deterministic partial result."


def _strings(value: Any, *, empty: bool = False) -> tuple[str, ...]:
    result = []
    for item in fact_list(value):
        if item == "" and empty:
            result.append("")
        else:
            result.append(validate_argument(item))
    return tuple(result)


def _rule(value: Any) -> RbacRule:
    data = fact_mapping(value)
    verbs = _strings(data.get("verbs"))
    groups = _strings(data.get("apiGroups", []), empty=True)
    resources = _strings(data.get("resources", []))
    names = _strings(data.get("resourceNames", []))
    urls = _strings(data.get("nonResourceURLs", []))
    if (
        not verbs
        or bool(resources) == bool(urls)
        or (resources and not groups)
        or (urls and (groups or names))
    ):
        raise AppError("Invalid RBAC rule shape.")
    return RbacRule(verbs, groups, resources, names, urls)


def _object_ref(
    resource: ApiResource, record: ResourceRecord, manifest: dict[str, Any], *, binding: bool
) -> RbacObjectRef:
    families = (
        {"rolebindings": "RoleBinding", "clusterrolebindings": "ClusterRoleBinding"}
        if binding
        else {"roles": "Role", "clusterroles": "ClusterRole"}
    )
    if (
        manifest.get("apiVersion") != resource.api_version
        or manifest.get("kind") != resource.kind
        or resource.group != _RBAC_GROUP
        or families.get(resource.name) != resource.kind
        or resource.namespaced != (resource.kind in {"Role", "RoleBinding"})
    ):
        raise AppError("RBAC facts require the discovered RBAC resource family.")
    return RbacObjectRef(resource.kind, record.name, record.namespace, record.uid)


def _selector(value: Any) -> RelationshipSelector:
    data = fact_mapping(value)
    if set(data) - {"matchLabels", "matchExpressions"}:
        raise AppError("Invalid RBAC aggregation selector fields.")
    labels = fact_mapping(data.get("matchLabels", {}))
    selector_matches(RelationshipSelector(()), labels)
    requirements = [LabelRequirement(key, "In", (value,)) for key, value in labels.items()]
    values_used = len(requirements)
    for raw in fact_list(data.get("matchExpressions", [])):
        item = fact_mapping(raw)
        key, operator = validate_argument(item.get("key", "")), item.get("operator")
        values = _strings(item.get("values", []), empty=True)
        values_used += len(values) + 1
        if values_used > 10000:
            raise AppError("Excessive RBAC aggregation selector.")
        selector_matches(RelationshipSelector(()), {key: ""})
        for value in values:
            selector_matches(RelationshipSelector(()), {"value": value})
        if (
            not isinstance(operator, str)
            or operator not in {"In", "NotIn", "Exists", "DoesNotExist"}
            or ((operator in {"In", "NotIn"}) != bool(values))
        ):
            raise AppError("Invalid RBAC aggregation selector expression.")
        requirements.append(LabelRequirement(key, operator, values))
    return RelationshipSelector(tuple(requirements))


def parse_rbac_role(resource: ApiResource, record: ResourceRecord) -> RbacRole:
    manifest = relationship_manifest(record)
    ref = _object_ref(resource, record, manifest, binding=False)
    rules = tuple(_rule(value) for value in fact_list(manifest.get("rules", [])))
    selectors: tuple[RelationshipSelector, ...] = ()
    if "aggregationRule" in manifest:
        if ref.kind != "ClusterRole":
            raise AppError("Only ClusterRoles can aggregate roles.")
        aggregation = fact_mapping(manifest["aggregationRule"])
        selectors = tuple(
            _selector(value) for value in fact_list(aggregation.get("clusterRoleSelectors", []))
        )
    return RbacRole(ref, rules, resource_labels(record), selectors)


def parse_rbac_binding(resource: ApiResource, record: ResourceRecord) -> RbacBinding:
    manifest = relationship_manifest(record)
    ref = _object_ref(resource, record, manifest, binding=True)
    role = fact_mapping(manifest.get("roleRef"))
    role_kind = role.get("kind")
    if (
        role.get("apiGroup") != _RBAC_GROUP
        or not isinstance(role_kind, str)
        or role_kind not in {"Role", "ClusterRole"}
        or (ref.kind == "ClusterRoleBinding" and role_kind != "ClusterRole")
    ):
        raise AppError("Invalid RBAC roleRef group or kind.")
    role_name = resource_name(role.get("name"))
    subjects = []
    for raw in fact_list(manifest.get("subjects", [])):
        item = fact_mapping(raw)
        try:
            kind = RbacSubjectKind(validate_argument(item.get("kind", "")))
        except ValueError:
            raise AppError("Unsupported RBAC subject kind.") from None
        group = "" if kind == RbacSubjectKind.SERVICE_ACCOUNT else _RBAC_GROUP
        if item.get("apiGroup", "") != group:
            raise AppError("Invalid RBAC subject API group.")
        namespace = item.get(
            "namespace", ref.namespace if kind == RbacSubjectKind.SERVICE_ACCOUNT else None
        )
        subjects.append(RbacSubject(kind, validate_argument(item.get("name", "")), namespace))
    return RbacBinding(ref, tuple(subjects), role_kind, role_name)


def rule_matches(rule: RbacRule, access: ResourceAccess | NonResourceAccess) -> bool:
    if isinstance(access, ResourceAccess):
        access = canonical_resource_access(access)
    if "*" not in rule.verbs and access.verb not in rule.verbs:
        return False
    if isinstance(access, NonResourceAccess):
        return any(
            url == access.path or (url.endswith("*") and access.path.startswith(url[:-1]))
            for url in rule.non_resource_urls
        )
    if "*" not in rule.api_groups and access.group not in rule.api_groups:
        return False
    target = access.resource + ("/" + access.subresource if access.subresource is not None else "")
    if not any(
        value == "*"
        or value == target
        or (access.subresource is not None and value == "*/" + access.subresource)
        for value in rule.resources
    ):
        return False
    return not rule.resource_names or (
        access.name is not None and access.name in rule.resource_names
    )


def binding_applies(binding: RbacBinding, scope: AuthorizationScope) -> bool:
    if binding.ref.kind == "ClusterRoleBinding":
        return binding.role_kind == "ClusterRole"
    return (
        binding.ref.kind == "RoleBinding"
        and scope.kind == AuthorizationScopeKind.NAMESPACE
        and scope.namespace == binding.ref.namespace
    )


def resolve_role(binding: RbacBinding, roles: tuple[RbacRole, ...]) -> RbacRole | None:
    namespace = binding.ref.namespace if binding.role_kind == "Role" else None
    return next(
        (
            role
            for role in roles
            if role.ref.kind == binding.role_kind
            and role.ref.name == binding.role_name
            and role.ref.namespace == namespace
        ),
        None,
    )


@dataclass(slots=True)
class _Budget:
    comparisons: int
    results: int
    used: int = 0
    incomplete: bool = False
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if (
            type(self.comparisons) is not int
            or self.comparisons < 0
            or type(self.results) is not int
            or self.results < 0
        ):
            raise AppError("RBAC budgets must be nonnegative integers.")
        self.comparisons = min(self.comparisons, MAX_AUTHORIZATION_COMPARISONS)
        self.results = min(self.results, MAX_AUTHORIZATION_RESULTS)

    def warn(self, warning: str, *, incomplete: bool = True) -> None:
        self.incomplete |= incomplete
        if warning not in self.warnings:
            self.warnings.append(warning)

    def charge(self) -> bool:
        if self.used >= self.comparisons:
            self.warn(_COMPARISON_WARNING)
            return False
        self.used += 1
        return True

    def retain(self, size: int) -> bool:
        if size >= self.results:
            self.warn(_RESULT_WARNING)
            return False
        return True


def _source_warnings(snapshot: RbacSnapshot, budget: _Budget) -> None:
    budget.warn(_EXTERNAL_WARNING, incomplete=False)
    for source in snapshot.sources:
        if source.status != EvidenceStatus.READY or (
            source.collection is not None and not source.collection.complete
        ):
            budget.warn("RBAC source evidence is incomplete: " + source.family + ".")


def _lookup(
    binding: RbacBinding, roles: tuple[RbacRole, ...], budget: _Budget
) -> tuple[RbacRole | None, bool]:
    for role in roles:
        if not budget.charge():
            return None, False
        if resolve_role(binding, (role,)) is not None:
            return role, True
    budget.warn("Referenced RBAC role is missing or unavailable.")
    return None, True


def _username(subject: RbacSubject) -> str:
    if subject.kind == RbacSubjectKind.SERVICE_ACCOUNT:
        return f"system:serviceaccount:{subject.namespace}:{subject.name}"
    return subject.name


def _subject_matches(
    declared: RbacSubject, selected: RbacSubject, identity: CurrentIdentity | None
) -> tuple[bool, str | None]:
    if declared.kind == RbacSubjectKind.GROUP:
        if selected.kind == RbacSubjectKind.GROUP:
            return declared.name == selected.name, None
        if (
            identity is not None
            and identity.username == _username(selected)
            and declared.name in identity.groups
        ):
            return True, declared.name
        return False, None
    return selected.kind != RbacSubjectKind.GROUP and _username(declared) == _username(
        selected
    ), None


def _grant_scope(binding: RbacBinding) -> AuthorizationScope:
    return (
        AuthorizationScope(AuthorizationScopeKind.NAMESPACE, binding.ref.namespace)
        if binding.ref.namespace is not None
        else AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
    )


def _match(
    snapshot: RbacSnapshot,
    subject: RbacSubject | None,
    identity: CurrentIdentity | None,
    access: ResourceAccess | NonResourceAccess | None,
    budget: _Budget,
) -> RbacMatchResult:
    _source_warnings(snapshot, budget)
    budget.warn(_GROUP_WARNING, incomplete=False)
    grants: list[RbacGrant] = []
    scope = snapshot.request.intent.scope
    if isinstance(access, ResourceAccess):
        access = canonical_resource_access(access)
        scope = access.scope
        if access.verb in {"list", "watch"} and access.name is not None:
            budget.warn(
                "Named list/watch evidence does not establish permission for an unfiltered HTTP request.",
                incomplete=False,
            )
    elif isinstance(access, NonResourceAccess):
        scope = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
    for binding in snapshot.bindings:
        if not budget.charge():
            break
        applicable = binding_applies(binding, scope)
        if subject is not None and scope.kind == AuthorizationScopeKind.ALL_NAMESPACES:
            applicable = True
        if not applicable:
            continue
        matches: list[tuple[RbacSubject, str | None]] = []
        seen_matches: set[tuple[RbacSubject, str | None]] = set()
        for declared in binding.subjects:
            if not budget.charge():
                return RbacMatchResult(
                    tuple(grants), budget.incomplete, tuple(budget.warnings), budget.used
                )
            matched, via = (
                (True, None) if subject is None else _subject_matches(declared, subject, identity)
            )
            if matched:
                match = (declared if subject is None else subject, via)
                if match not in seen_matches:
                    seen_matches.add(match)
                    matches.append(match)
        if not matches:
            continue
        role, continuing = _lookup(binding, snapshot.roles, budget)
        if not continuing:
            break
        if role is None:
            continue
        for index, rule in enumerate(role.rules):
            if not budget.charge():
                return RbacMatchResult(
                    tuple(grants), budget.incomplete, tuple(budget.warnings), budget.used
                )
            if access is not None and not rule_matches(rule, access):
                continue
            for selected, via in matches:
                if not budget.retain(len(grants)):
                    return RbacMatchResult(
                        tuple(grants), budget.incomplete, tuple(budget.warnings), budget.used
                    )
                grants.append(
                    RbacGrant(
                        selected,
                        binding.ref,
                        role.ref,
                        index,
                        _grant_scope(binding),
                        RbacEvidenceKind.MATERIALIZED
                        if role.aggregation_selectors
                        else RbacEvidenceKind.DECLARED,
                        via,
                    )
                )
    return RbacMatchResult(tuple(grants), budget.incomplete, tuple(budget.warnings), budget.used)


def subject_grants(
    snapshot: RbacSnapshot,
    subject: RbacSubject,
    identity: CurrentIdentity | None = None,
    *,
    max_comparisons: int = MAX_AUTHORIZATION_COMPARISONS,
    max_results: int = MAX_AUTHORIZATION_RESULTS,
) -> RbacMatchResult:
    """Declared subject rules, expanding only reviewed groups for that exact identity."""
    return _match(snapshot, subject, identity, None, _Budget(max_comparisons, max_results))


def who_can(
    snapshot: RbacSnapshot,
    access: ResourceAccess | NonResourceAccess,
    *,
    max_comparisons: int = MAX_AUTHORIZATION_COMPARISONS,
    max_results: int = MAX_AUTHORIZATION_RESULTS,
) -> RbacMatchResult:
    """Match declared subjects, never infer the members of a declared group."""
    return _match(snapshot, None, None, access, _Budget(max_comparisons, max_results))


def aggregation_contributors(
    role: RbacRole,
    roles: tuple[RbacRole, ...],
    *,
    max_comparisons: int = MAX_AUTHORIZATION_COMPARISONS,
    max_results: int = MAX_AUTHORIZATION_RESULTS,
) -> RbacAggregation:
    """Explain selected aggregate contributors without substituting inferred rules."""
    budget = _Budget(max_comparisons, max_results)
    contributors: list[RbacObjectRef] = []
    seen: set[RbacObjectRef] = set()

    def visit(parent: RbacRole, ancestors: tuple[RbacObjectRef, ...], depth: int) -> bool:
        if not parent.aggregation_selectors:
            return True
        if depth >= MAX_AGGREGATION_DEPTH:
            budget.warn("RBAC aggregation depth limit reached.")
            return True
        for candidate in roles:
            if candidate.ref.kind != "ClusterRole":
                continue
            matched = False
            for selector in parent.aggregation_selectors:
                if not budget.charge():
                    return False
                try:
                    matched = selector_matches(selector, dict(candidate.labels))
                except AppError:
                    budget.warn("Invalid RBAC aggregation selector or labels.")
                    continue
                if matched:
                    break
            if not matched:
                continue
            if not budget.charge():
                return False
            if candidate.ref in ancestors:
                budget.warn("RBAC aggregation cycle detected.")
                continue
            if candidate.ref in seen:
                continue
            if not budget.retain(len(contributors)):
                return False
            contributors.append(candidate.ref)
            seen.add(candidate.ref)
            if not visit(candidate, (*ancestors, candidate.ref), depth + 1):
                return False
        return True

    visit(role, (role.ref,), 0)
    return RbacAggregation(
        role.ref, tuple(contributors), budget.incomplete, tuple(budget.warnings), budget.used
    )
