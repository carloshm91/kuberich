"""Immutable authorization questions and evidence, independent of transport and navigation."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connections import namespace_name
from kuberich.domain.relationships import RelationshipSelector
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState, api_segment, resource_name
from kuberich.domain.selectors import selectors
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_AUTHORIZATION_COMPARISONS = 100000
MAX_AUTHORIZATION_RESULTS = 1024
MAX_AGGREGATION_DEPTH = 8


class AuthorizationScopeKind(StrEnum):
    NAMESPACE = "namespace"
    ALL_NAMESPACES = "all_namespaces"
    CLUSTER = "cluster"


class AuthorizationMode(StrEnum):
    SUBJECTS = "subjects"
    BINDINGS = "bindings"
    ROLES = "roles"
    SUBJECT = "subject"
    BINDING = "binding"
    ROLE = "role"
    REVIEW = "review"
    SELF_RULES = "self_rules"
    WHO_CAN = "who_can"


class ReviewDecision(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    NO_ALLOW = "no_allow"
    UNKNOWN = "unknown"


class EvidenceStatus(StrEnum):
    LOADING = "loading"
    READY = "ready"
    FORBIDDEN = "forbidden"
    MISSING = "missing"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"
    FAILED = "failed"
    TRUNCATED = "truncated"


class RbacSubjectKind(StrEnum):
    USER = "User"
    GROUP = "Group"
    SERVICE_ACCOUNT = "ServiceAccount"


class RbacEvidenceKind(StrEnum):
    DECLARED = "declared"
    MATERIALIZED = "materialized"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class AuthorizationScope:
    kind: AuthorizationScopeKind
    namespace: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AuthorizationScopeKind):
            raise AppError("Authorization scope requires an explicit kind.")
        if self.kind == AuthorizationScopeKind.NAMESPACE:
            if not isinstance(self.namespace, str):
                raise AppError("A namespace authorization scope requires a namespace.")
            namespace_name(self.namespace)
        elif self.namespace is not None:
            raise AppError("Cluster and all-namespace scopes cannot name a namespace.")


@dataclass(frozen=True, slots=True)
class ResourceAccess:
    verb: str
    group: str
    version: str
    resource: str
    subresource: str | None
    name: str | None
    scope: AuthorizationScope
    query: ResourceQuery

    def __post_init__(self) -> None:
        _verb(self.verb)
        if self.group != "":
            api_segment(self.group)
        for value in (self.version, self.resource):
            api_segment(value)
        if self.subresource is not None:
            api_segment(self.subresource)
        if self.name is not None:
            resource_name(self.name)
        if not isinstance(self.scope, AuthorizationScope) or not isinstance(
            self.query, ResourceQuery
        ):
            raise AppError("Resource access requires validated scope and server selectors.")


@dataclass(frozen=True, slots=True)
class NonResourceAccess:
    verb: str
    path: str

    def __post_init__(self) -> None:
        _verb(self.verb)
        validate_argument(self.path)
        if not self.path.startswith("/") or "?" in self.path or "#" in self.path:
            raise AppError("Non-resource access requires an absolute URL path without a query.")


def _verb(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9]*|\*", value):
        raise AppError("Authorization verbs require a literal lowercase verb or wildcard.")


@dataclass(frozen=True, slots=True)
class RbacSubject:
    kind: RbacSubjectKind
    name: str
    namespace: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, RbacSubjectKind):
            raise AppError("RBAC subjects require a supported kind.")
        validate_argument(self.name)
        if self.kind == RbacSubjectKind.SERVICE_ACCOUNT:
            resource_name(self.name)
            if not isinstance(self.namespace, str):
                raise AppError("ServiceAccount subjects require an explicit namespace.")
            namespace_name(self.namespace)
        elif self.namespace is not None:
            raise AppError("User and Group subjects cannot have a namespace.")


@dataclass(frozen=True, slots=True)
class RbacObjectRef:
    kind: str
    name: str
    namespace: str | None
    uid: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"Role", "ClusterRole", "RoleBinding", "ClusterRoleBinding"}:
            raise AppError("Invalid RBAC object kind.")
        resource_name(self.name)
        if self.kind in {"Role", "RoleBinding"}:
            if not isinstance(self.namespace, str):
                raise AppError("Namespaced RBAC objects require a namespace.")
            namespace_name(self.namespace)
        elif self.namespace is not None:
            raise AppError("Cluster RBAC objects cannot have a namespace.")
        if self.uid is not None:
            validate_argument(self.uid)


@dataclass(frozen=True, slots=True)
class AuthorizationIntent:
    mode: AuthorizationMode
    scope: AuthorizationScope
    subject: RbacSubject | None = None
    binding: RbacObjectRef | None = None
    role: RbacObjectRef | None = None
    access: ResourceAccess | NonResourceAccess | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, AuthorizationMode) or not isinstance(
            self.scope, AuthorizationScope
        ):
            raise AppError("Authorization intent requires a validated mode and scope.")
        selected = (
            self.subject is not None,
            self.binding is not None,
            self.role is not None,
            self.access is not None,
        )
        expected = {
            AuthorizationMode.SUBJECT: (True, False, False, False),
            AuthorizationMode.BINDING: (False, True, False, False),
            AuthorizationMode.ROLE: (False, False, True, False),
            AuthorizationMode.REVIEW: (False, False, False, True),
            AuthorizationMode.WHO_CAN: (False, False, False, True),
        }.get(self.mode, (False, False, False, False))
        if selected != expected:
            raise AppError("Authorization mode and selected evidence do not agree.")
        if self.subject is not None and not isinstance(self.subject, RbacSubject):
            raise AppError("Authorization subject must be a validated subject.")
        for ref, kinds in (
            (self.binding, {"RoleBinding", "ClusterRoleBinding"}),
            (self.role, {"Role", "ClusterRole"}),
        ):
            if ref is not None and (not isinstance(ref, RbacObjectRef) or ref.kind not in kinds):
                raise AppError("Authorization selection has the wrong RBAC object kind.")
        if self.access is not None and not isinstance(
            self.access, (ResourceAccess, NonResourceAccess)
        ):
            raise AppError("Authorization request requires one validated access variant.")
        if (
            isinstance(self.access, NonResourceAccess)
            and self.scope.kind != AuthorizationScopeKind.CLUSTER
        ):
            raise AppError("Non-resource questions require cluster scope.")
        if isinstance(self.access, ResourceAccess) and self.scope != self.access.scope:
            raise AppError("Resource question and access scopes must agree.")
        if (
            self.mode == AuthorizationMode.SELF_RULES
            and self.scope.kind != AuthorizationScopeKind.NAMESPACE
        ):
            raise AppError("SelfSubjectRulesReview requires a namespace.")


@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    session: SessionIdentity
    revision: int
    intent: AuthorizationIntent

    def __post_init__(self) -> None:
        if (
            not isinstance(self.session, SessionIdentity)
            or type(self.revision) is not int
            or self.revision < 0
        ):
            raise AppError(
                "Authorization requests require an owned session and nonnegative revision."
            )
        if not isinstance(self.intent, AuthorizationIntent):
            raise AppError("Authorization requests require a validated intent.")
        if isinstance(self.intent.access, ResourceAccess):
            object.__setattr__(
                self,
                "intent",
                replace(self.intent, access=canonical_resource_access(self.intent.access)),
            )


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    username: str
    uid: str | None
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IdentityReview:
    request: AuthorizationRequest
    identity: CurrentIdentity | None
    status: EvidenceStatus
    warnings: tuple[str, ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AccessReview:
    request: AuthorizationRequest
    decision: ReviewDecision
    status: EvidenceStatus
    reason: str
    warnings: tuple[str, ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class RbacRule:
    verbs: tuple[str, ...]
    api_groups: tuple[str, ...]
    resources: tuple[str, ...]
    resource_names: tuple[str, ...]
    non_resource_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RulesReview:
    request: AuthorizationRequest
    rules: tuple[RbacRule, ...]
    incomplete: bool
    status: EvidenceStatus
    warnings: tuple[str, ...]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class RbacRole:
    ref: RbacObjectRef
    rules: tuple[RbacRule, ...]
    labels: tuple[tuple[str, str], ...]
    aggregation_selectors: tuple[RelationshipSelector, ...]


@dataclass(frozen=True, slots=True)
class RbacBinding:
    ref: RbacObjectRef
    subjects: tuple[RbacSubject, ...]
    role_kind: str
    role_name: str


@dataclass(frozen=True, slots=True)
class RbacSubjectEvidence:
    subject: RbacSubject
    origins: tuple[RbacObjectRef, ...]


@dataclass(frozen=True, slots=True)
class RbacSource:
    family: str
    scope: AuthorizationScope
    status: EvidenceStatus
    collection: CollectionState | None
    resource_version: str | None
    detail: str
    observed_at: datetime | None


@dataclass(frozen=True, slots=True)
class RbacGrant:
    subject: RbacSubject
    binding: RbacObjectRef
    role: RbacObjectRef
    rule_index: int
    scope: AuthorizationScope
    evidence: RbacEvidenceKind
    via_group: str | None


@dataclass(frozen=True, slots=True)
class RbacMatchResult:
    grants: tuple[RbacGrant, ...]
    incomplete: bool
    warnings: tuple[str, ...]
    comparisons_used: int


@dataclass(frozen=True, slots=True)
class RbacAggregation:
    role: RbacObjectRef
    contributors: tuple[RbacObjectRef, ...]
    incomplete: bool
    warnings: tuple[str, ...]
    comparisons_used: int


@dataclass(frozen=True, slots=True)
class RbacAnalysis:
    grants: tuple[RbacGrant, ...]
    aggregations: tuple[RbacAggregation, ...]
    incomplete: bool
    warnings: tuple[str, ...]
    comparisons_used: int


@dataclass(frozen=True, slots=True)
class RbacSnapshot:
    request: AuthorizationRequest
    subjects: tuple[RbacSubjectEvidence, ...]
    bindings: tuple[RbacBinding, ...]
    roles: tuple[RbacRole, ...]
    sources: tuple[RbacSource, ...]
    requests_used: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AuthorizationSnapshot:
    request: AuthorizationRequest
    rbac: RbacSnapshot | None
    analysis: RbacAnalysis | None
    identity: IdentityReview | None
    review: AccessReview | None
    rules: RulesReview | None
    collecting: bool


def canonical_resource_access(access: ResourceAccess) -> ResourceAccess:
    """Mirror requestinfo list/watch name extraction while preserving literal selectors."""
    field_selector = access.query.field_selector
    if field_selector is not None and any(character.isspace() for character in field_selector):
        raise AppError("Authorization requires literal field selectors without whitespace.")
    if access.verb not in {"list", "watch"} or field_selector is None:
        return access
    names = {
        item.values[0]
        for item in selectors(field_selector, field=True)
        if item.key == "metadata.name" and item.operator in {"=", "=="}
    }
    if len(names) > 1:
        raise AppError("Conflicting metadata.name equalities cannot define an access request.")
    if not names:
        return access
    derived = next(iter(names)) or None
    if access.name is not None and access.name != derived:
        raise AppError("Explicit access name conflicts with its metadata.name equality.")
    return replace(access, name=derived)


def rescope_intent(intent: AuthorizationIntent, namespace: str | None) -> AuthorizationIntent:
    """Apply one explicit browsing scope change without changing a selected subject."""
    if intent.mode in {AuthorizationMode.REVIEW, AuthorizationMode.WHO_CAN} and (
        isinstance(intent.access, NonResourceAccess)
        or (
            isinstance(intent.access, ResourceAccess)
            and intent.access.scope.kind == AuthorizationScopeKind.CLUSTER
        )
    ):
        return intent
    scope = AuthorizationScope(
        AuthorizationScopeKind.NAMESPACE
        if namespace is not None
        else AuthorizationScopeKind.ALL_NAMESPACES,
        namespace,
    )
    if intent.mode == AuthorizationMode.SELF_RULES and namespace is None:
        return AuthorizationIntent(AuthorizationMode.SUBJECTS, scope)
    for ref, fallback in (
        (intent.binding, AuthorizationMode.BINDINGS),
        (intent.role, AuthorizationMode.ROLES),
    ):
        if (
            ref is not None
            and ref.namespace is not None
            and namespace is not None
            and ref.namespace != namespace
        ):
            return AuthorizationIntent(fallback, scope)
    access = intent.access
    if isinstance(access, ResourceAccess) and access.scope.kind != AuthorizationScopeKind.CLUSTER:
        access = replace(access, scope=scope)
    return replace(intent, scope=scope, access=access)


def classify_access_review(
    request: AuthorizationRequest, status: object, observed_at: datetime
) -> AccessReview:
    """Only a structurally valid server review can report an authoritative decision."""
    if not isinstance(status, dict):
        return AccessReview(
            request,
            ReviewDecision.UNKNOWN,
            EvidenceStatus.INVALID,
            "Invalid access review status.",
            (),
            observed_at,
        )
    allowed, denied = status.get("allowed"), status.get("denied", False)
    reason, error = status.get("reason", ""), status.get("evaluationError", "")
    if (
        type(allowed) is not bool
        or type(denied) is not bool
        or (allowed and denied)
        or not isinstance(reason, str)
        or not isinstance(error, str)
    ):
        return AccessReview(
            request,
            ReviewDecision.UNKNOWN,
            EvidenceStatus.INVALID,
            "Invalid access review status.",
            (),
            observed_at,
        )
    warnings: tuple[str, ...] = (sanitize_text(error[:8192]),) if error else ()
    access = request.intent.access
    if (
        isinstance(access, ResourceAccess)
        and access.verb in {"list", "watch"}
        and access.name is not None
    ):
        warnings += (
            "Named list/watch evidence does not establish permission for an unfiltered HTTP request.",
        )
    decision = (
        ReviewDecision.ALLOWED
        if allowed
        else ReviewDecision.DENIED
        if denied
        else ReviewDecision.NO_ALLOW
    )
    return AccessReview(
        request, decision, EvidenceStatus.READY, sanitize_text(reason[:8192]), warnings, observed_at
    )
