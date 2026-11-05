"""Owned review transport and bounded, explicitly partial RBAC evidence collection."""

import asyncio
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from typing import Any

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.authorization import (
    MAX_AUTHORIZATION_COMPARISONS,
    MAX_AUTHORIZATION_RESULTS,
    AccessReview,
    AuthorizationMode,
    AuthorizationRequest,
    AuthorizationScope,
    AuthorizationScopeKind,
    AuthorizationSnapshot,
    CurrentIdentity,
    EvidenceStatus,
    IdentityReview,
    NonResourceAccess,
    RbacAnalysis,
    RbacBinding,
    RbacObjectRef,
    RbacRole,
    RbacSnapshot,
    RbacSource,
    RbacSubject,
    RbacSubjectEvidence,
    RbacSubjectKind,
    ResourceAccess,
    ReviewDecision,
    RulesReview,
    canonical_resource_access,
    classify_access_review,
)
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.rbac import (
    aggregation_contributors,
    parse_rbac_binding,
    parse_rbac_role,
    subject_grants,
    who_can,
)
from kuberich.domain.read_budget import ReadBudget, ReadBudgetExceeded
from kuberich.domain.resources import (
    ApiResource,
    CollectionState,
    Discovery,
    ResourceRecord,
    ResourceSnapshot,
    api_resource,
    resource_record,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.services.resources import ResourceReader, parse_owned

ACCESS_PATH = "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"
RULES_PATH = "/apis/authorization.k8s.io/v1/selfsubjectrulesreviews"
IDENTITY_PATH = "/apis/authentication.k8s.io/v1/selfsubjectreviews"
MAX_COLLECTION_SECONDS = 30.0
MAX_OBJECTS = 10000
MAX_FACT_BYTES = 16 * 1024 * 1024
RBAC_GROUP = "rbac.authorization.k8s.io"


def _failure(
    problem: ConnectionProblem | AppError | ReadBudgetExceeded,
) -> tuple[EvidenceStatus, str]:
    if isinstance(problem, ReadBudgetExceeded):
        return EvidenceStatus.TRUNCATED, "Shared logical read budget exhausted."
    if isinstance(problem, HttpProblem):
        status = {
            403: EvidenceStatus.FORBIDDEN,
            404: EvidenceStatus.UNAVAILABLE,
            405: EvidenceStatus.UNAVAILABLE,
        }.get(problem.status, EvidenceStatus.FAILED)
        return status, f"Review/read HTTP {problem.status}; server message omitted."
    if isinstance(problem, AppError) or (
        isinstance(problem, ConnectionProblem) and problem.state is ConnectionState.API_ERROR
    ):
        return EvidenceStatus.INVALID, "Invalid or excessive authorization evidence."
    return EvidenceStatus.FAILED, "Authorization evidence could not be read."


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AppError("Expected an authorization response object.")
    return value


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_OBJECTS:
        raise AppError("Invalid or excessive review strings.")
    return tuple(_text(item) for item in value)


def _text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 8192:
        raise AppError("Invalid review string.")
    return validate_argument(value)


def _status(payload: object, kind: str, version: str) -> dict[str, Any]:
    data = _mapping(payload)
    if data.get("kind") != kind or data.get("apiVersion") != version:
        raise AppError("Review response does not match the requested API.")
    return _mapping(data.get("status"))


def _identity(request: AuthorizationRequest, payload: object) -> IdentityReview:
    status = _status(payload, "SelfSubjectReview", "authentication.k8s.io/v1")
    info = _mapping(status.get("userInfo"))
    username = _text(info.get("username"))
    uid = None if info.get("uid") in (None, "") else _text(info["uid"])
    groups = _strings(info.get("groups", []))
    return IdentityReview(
        request, CurrentIdentity(username, uid, groups), EvidenceStatus.READY, (), datetime.now(UTC)
    )


def _rules(request: AuthorizationRequest, payload: object) -> RulesReview:
    status = _status(payload, "SelfSubjectRulesReview", "authorization.k8s.io/v1")
    incomplete = status.get("incomplete", False)
    error = status.get("evaluationError", "")
    if type(incomplete) is not bool or not isinstance(error, str) or len(error) > 8192:
        raise AppError("Invalid rules review completeness.")
    rules: list[Any] = []
    for key in ("resourceRules", "nonResourceRules"):
        values = status.get(key, [])
        if not isinstance(values, list) or len(values) + len(rules) > MAX_OBJECTS:
            raise AppError("Invalid or excessive review rules.")
        rules.extend(values)
    # Reuse the public policy-rule parser; no synthetic object is published.
    resource = api_resource(
        RBAC_GROUP + "/v1",
        {"name": "clusterroles", "kind": "ClusterRole", "namespaced": False, "verbs": ["get"]},
    )
    record = resource_record(
        resource,
        {
            "apiVersion": resource.api_version,
            "kind": resource.kind,
            "metadata": {"name": "review-rules"},
            "rules": rules,
        },
    )
    parsed = parse_rbac_role(resource, record)
    warnings = ((sanitize_text(error),) if error else ()) + (
        ("Rules review is incomplete and cannot establish denial.",) if incomplete else ()
    )
    return RulesReview(
        request, parsed.rules, incomplete, EvidenceStatus.READY, warnings, datetime.now(UTC)
    )


class AuthorizationReader:
    """Only the three current-effective-identity review APIs; no subject impersonation."""

    def __init__(self, session: KubernetesSession) -> None:
        self.session = session

    async def identity(self, request: AuthorizationRequest) -> IdentityReview:
        try:
            payload = await self.session.review_json(
                IDENTITY_PATH,
                {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview", "spec": {}},
            )
            return await parse_owned(partial(_identity, request, payload))
        except (ConnectionProblem, AppError) as problem:
            status, detail = _failure(problem)
            return IdentityReview(request, None, status, (detail,), datetime.now(UTC))

    async def review(self, request: AuthorizationRequest) -> AccessReview:
        access = request.intent.access
        if isinstance(access, ResourceAccess):
            access = canonical_resource_access(access)
            attributes: dict[str, Any] = {
                "namespace": access.scope.namespace or "",
                "verb": access.verb,
                "group": access.group,
                "version": access.version,
                "resource": access.resource,
            }
            for key, value in (("name", access.name), ("subresource", access.subresource)):
                if value is not None:
                    attributes[key] = value
            for key, value in (
                ("fieldSelector", access.query.field_selector),
                ("labelSelector", access.query.label_selector),
            ):
                if value is not None:
                    attributes[key] = {"rawSelector": value}
            spec = {"resourceAttributes": attributes}
        elif isinstance(access, NonResourceAccess):
            spec = {"nonResourceAttributes": {"verb": access.verb, "path": access.path}}
        else:
            raise AppError("An access review requires an exact access question.")
        try:
            payload = await self.session.review_json(
                ACCESS_PATH,
                {
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SelfSubjectAccessReview",
                    "spec": spec,
                },
            )
            raw_status = await parse_owned(
                partial(_status, payload, "SelfSubjectAccessReview", "authorization.k8s.io/v1")
            )
            return await parse_owned(
                partial(classify_access_review, request, raw_status, datetime.now(UTC))
            )
        except (ConnectionProblem, AppError) as problem:
            status, detail = _failure(problem)
            return AccessReview(
                request,
                ReviewDecision.UNKNOWN,
                status,
                "No authoritative answer.",
                (detail,),
                datetime.now(UTC),
            )

    async def rules(self, request: AuthorizationRequest) -> RulesReview:
        namespace = request.intent.scope.namespace
        if namespace is None:
            raise AppError("Rules review requires a namespace.")
        try:
            payload = await self.session.review_json(
                RULES_PATH,
                {
                    "apiVersion": "authorization.k8s.io/v1",
                    "kind": "SelfSubjectRulesReview",
                    "spec": {"namespace": namespace},
                },
            )
            return await parse_owned(partial(_rules, request, payload))
        except (ConnectionProblem, AppError) as problem:
            status, detail = _failure(problem)
            return RulesReview(request, (), True, status, (detail,), datetime.now(UTC))


def _facts(
    resource: ApiResource, records: tuple[ResourceRecord, ...]
) -> tuple[tuple[RbacRole, ...], tuple[RbacBinding, ...], tuple[RbacSubject, ...], bool]:
    roles, bindings, subjects = [], [], []
    invalid = False
    for record in records:
        try:
            if resource.name in {"roles", "clusterroles"}:
                roles.append(parse_rbac_role(resource, record))
            elif resource.name in {"rolebindings", "clusterrolebindings"}:
                bindings.append(parse_rbac_binding(resource, record))
            else:
                subjects.append(
                    RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, record.name, record.namespace)
                )
        except AppError:
            invalid = True
    return tuple(roles), tuple(bindings), tuple(subjects), invalid


def _selected(expected: RbacObjectRef, observed: RbacObjectRef) -> bool:
    return (expected.kind, expected.name, expected.namespace) == (
        observed.kind,
        observed.name,
        observed.namespace,
    ) and (expected.uid is None or expected.uid == observed.uid)


def _analyze(snapshot: RbacSnapshot, identity: CurrentIdentity | None) -> RbacAnalysis:
    intent = snapshot.request.intent
    warnings: tuple[str, ...] = ()
    incomplete, comparisons, retained = False, 0, 0
    if intent.subject is not None:
        result = subject_grants(snapshot, intent.subject, identity)
    elif intent.access is not None:
        result = who_can(snapshot, intent.access)
    else:
        # The selected role still needs explicit partial/external-authorizer warnings.
        result = who_can(
            replace(snapshot, bindings=()), NonResourceAccess("get", "/__kuberich_explanation__")
        )
    grants = result.grants
    warnings, incomplete, comparisons = result.warnings, result.incomplete, result.comparisons_used
    retained = len(grants)
    refs = {grant.role for grant in grants}
    if intent.role is not None:
        refs.update(role.ref for role in snapshot.roles if _selected(intent.role, role.ref))
    aggregations = []
    for role in snapshot.roles:
        if role.ref not in refs or not role.aggregation_selectors:
            continue
        aggregation = aggregation_contributors(
            role,
            snapshot.roles,
            max_comparisons=MAX_AUTHORIZATION_COMPARISONS - comparisons,
            max_results=MAX_AUTHORIZATION_RESULTS - retained,
        )
        aggregations.append(aggregation)
        comparisons += aggregation.comparisons_used
        retained += len(aggregation.contributors)
        incomplete |= aggregation.incomplete
        warnings += aggregation.warnings
    return RbacAnalysis(
        grants, tuple(aggregations), incomplete, tuple(dict.fromkeys(warnings)), comparisons
    )


class AuthorizationService:
    def __init__(
        self,
        reader: ResourceReader,
        reviews: AuthorizationReader,
        discovery: Discovery,
        session: SessionIdentity,
        current: Callable[[AuthorizationRequest], bool],
    ) -> None:
        if reader.session is not reviews.session:
            raise AppError("Authorization readers must share an owned client.")
        self.budget = ReadBudget()
        self.reader = ResourceReader(reader.session, tables=False, budget=self.budget)
        self.reviews, self.discovery, self.session, self.current = (
            reviews,
            discovery,
            session,
            current,
        )
        self._client = reader.session

    def _check(self, request: AuthorizationRequest) -> None:
        if (
            request.session != self.session
            or self.reader.session is not self._client
            or self.reviews.session is not self._client
            or not self.current(request)
        ):
            raise asyncio.CancelledError

    async def review(self, request: AuthorizationRequest) -> AccessReview:
        self._check(request)
        try:
            self.budget.charge()
            result = await self.reviews.review(request)
        except ReadBudgetExceeded as problem:
            status, detail = _failure(problem)
            result = AccessReview(
                request,
                ReviewDecision.UNKNOWN,
                status,
                "No authoritative answer.",
                (detail,),
                datetime.now(UTC),
            )
        self._check(request)
        return result

    async def _scan(
        self,
        request: AuthorizationRequest,
        resource: ApiResource,
        scope: AuthorizationScope,
        count: int,
        size: int,
    ) -> tuple[ResourceSnapshot | None, EvidenceStatus, str]:
        latest = None

        async def progress(value: ResourceSnapshot) -> None:
            nonlocal latest
            self._check(request)
            latest = value

        try:
            latest = await self.reader.list(
                resource,
                scope.namespace,
                max_items=MAX_OBJECTS - count,
                max_retained_bytes=MAX_FACT_BYTES - size,
                progress=progress,
            )
            self._check(request)
            status = (
                EvidenceStatus.READY
                if latest.collection.complete and not latest.collection.limited
                else EvidenceStatus.TRUNCATED
            )
            return latest, status, "Observed collection."
        except (ConnectionProblem, AppError, ReadBudgetExceeded) as problem:
            self._check(request)
            status, detail = _failure(problem)
            return latest, status, detail

    async def collect(
        self, request: AuthorizationRequest, publish: Callable[[AuthorizationSnapshot], None]
    ) -> AuthorizationSnapshot:
        self._check(request)
        snapshot = AuthorizationSnapshot(request, None, None, None, None, None, True)
        sources: list[RbacSource] = []
        roles: list[RbacRole] = []
        bindings: list[RbacBinding] = []
        accounts: list[RbacSubject] = []
        count = size = 0

        def emit() -> AuthorizationSnapshot:
            self._check(request)
            publish(snapshot)
            self._check(request)
            return snapshot

        def rbac() -> RbacSnapshot:
            origins: dict[RbacSubject, list[RbacObjectRef]] = {subject: [] for subject in accounts}
            for binding in bindings:
                for subject in binding.subjects:
                    origins.setdefault(subject, []).append(binding.ref)
            return RbacSnapshot(
                request,
                tuple(
                    RbacSubjectEvidence(subject, tuple(dict.fromkeys(refs)))
                    for subject, refs in origins.items()
                ),
                tuple(bindings),
                tuple(roles),
                tuple(sources),
                self.budget.used,
                datetime.now(UTC),
            )

        emit()
        try:
            async with asyncio.timeout(MAX_COLLECTION_SECONDS):
                if request.intent.mode == AuthorizationMode.REVIEW:
                    snapshot = replace(snapshot, review=await self.review(request))
                    emit()
                self.budget.charge()
                identity = await self.reviews.identity(request)
                self._check(request)
                snapshot = replace(snapshot, identity=identity)
                emit()
                if request.intent.mode == AuthorizationMode.SELF_RULES:
                    self.budget.charge()
                    rules_review = await self.reviews.rules(request)
                    self._check(request)
                    snapshot = replace(snapshot, rules=rules_review)
                elif request.intent.mode != AuthorizationMode.REVIEW:
                    families = [(RBAC_GROUP, "clusterroles"), (RBAC_GROUP, "clusterrolebindings")]
                    if request.intent.scope.kind != AuthorizationScopeKind.CLUSTER:
                        families += [
                            (RBAC_GROUP, "roles"),
                            (RBAC_GROUP, "rolebindings"),
                            ("", "serviceaccounts"),
                        ]
                    for group, name in families:
                        self._check(request)
                        scope = (
                            AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
                            if name.startswith("cluster")
                            else request.intent.scope
                        )
                        resource = None
                        try:
                            resource = self.discovery.find(name, group=group)
                            collection, status, detail = await self._scan(
                                request, resource, scope, count, size
                            )
                            if collection is not None:
                                (
                                    parsed_roles,
                                    parsed_bindings,
                                    parsed_accounts,
                                    invalid,
                                ) = await parse_owned(partial(_facts, resource, collection.items))
                                self._check(request)
                                count += len(collection.items)
                                size += collection.collection.retained_bytes
                                roles.extend(parsed_roles)
                                bindings.extend(parsed_bindings)
                                accounts.extend(parsed_accounts)
                                if invalid and status is EvidenceStatus.READY:
                                    status = EvidenceStatus.INVALID
                                    detail = "Some supported declarations were invalid."
                            source = RbacSource(
                                name,
                                scope,
                                status,
                                collection.collection if collection is not None else None,
                                collection.resource_version if collection is not None else None,
                                detail,
                                datetime.now(UTC),
                            )
                        except (ConnectionProblem, AppError, ReadBudgetExceeded) as problem:
                            status, detail = _failure(problem)
                            if resource is None:
                                status = EvidenceStatus.UNAVAILABLE
                            source = RbacSource(
                                name, scope, status, None, None, detail, datetime.now(UTC)
                            )
                        sources.append(source)
                        snapshot = replace(snapshot, rbac=await parse_owned(rbac))
                        emit()
                    # Name-based roleRef semantics may resolve despite a forbidden/partial LIST.
                    missing = {
                        (
                            binding.role_kind,
                            binding.role_name,
                            binding.ref.namespace if binding.role_kind == "Role" else None,
                        )
                        for binding in bindings
                    }
                    selected = request.intent.role
                    if selected is not None:
                        missing.add((selected.kind, selected.name, selected.namespace))
                    observed_roles = {
                        (role.ref.kind, role.ref.name, role.ref.namespace) for role in roles
                    }
                    for kind, name, namespace in sorted(missing, key=repr):
                        if (kind, name, namespace) in observed_roles:
                            continue
                        scope = (
                            AuthorizationScope(AuthorizationScopeKind.NAMESPACE, namespace)
                            if namespace is not None
                            else AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
                        )
                        family = ("roles" if kind == "Role" else "clusterroles") + "/" + name
                        named_resource = None
                        try:
                            if count >= MAX_OBJECTS or size >= MAX_FACT_BYTES:
                                raise ReadBudgetExceeded
                            named_resource = self.discovery.find(
                                "roles" if kind == "Role" else "clusterroles", group=RBAC_GROUP
                            )
                            record = await self.reader.get(named_resource, name, namespace)
                            self._check(request)
                            count += 1
                            size += record.size_bytes
                            if size > MAX_FACT_BYTES:
                                raise ReadBudgetExceeded
                            role = await parse_owned(
                                partial(parse_rbac_role, named_resource, record)
                            )
                            self._check(request)
                            roles.append(role)
                            sources.append(
                                RbacSource(
                                    family,
                                    scope,
                                    EvidenceStatus.READY,
                                    None,
                                    record.resource_version,
                                    "Observed referenced role by name.",
                                    datetime.now(UTC),
                                )
                            )
                        except (ConnectionProblem, AppError, ReadBudgetExceeded) as problem:
                            status, detail = _failure(problem)
                            if named_resource is None and not isinstance(
                                problem, ReadBudgetExceeded
                            ):
                                status = EvidenceStatus.UNAVAILABLE
                            if isinstance(problem, HttpProblem) and problem.status == 404:
                                status = EvidenceStatus.MISSING
                            sources.append(
                                RbacSource(
                                    family, scope, status, None, None, detail, datetime.now(UTC)
                                )
                            )
                            if isinstance(problem, ReadBudgetExceeded):
                                break
                    for ref in (request.intent.role, request.intent.binding):
                        if ref is not None and not any(
                            _selected(ref, observed)
                            for observed in [role.ref for role in roles]
                            + [binding.ref for binding in bindings]
                        ):
                            family = {
                                "Role": "roles",
                                "ClusterRole": "clusterroles",
                                "RoleBinding": "rolebindings",
                                "ClusterRoleBinding": "clusterrolebindings",
                            }[ref.kind]
                            selected_source = next(
                                (
                                    source
                                    for source in reversed(sources)
                                    if source.family in {family, family + "/" + ref.name}
                                ),
                                None,
                            )
                            replaced = any(
                                (observed.kind, observed.name, observed.namespace)
                                == (ref.kind, ref.name, ref.namespace)
                                for observed in [role.ref for role in roles]
                                + [binding.ref for binding in bindings]
                            )
                            status = (
                                EvidenceStatus.MISSING
                                if replaced
                                or (
                                    selected_source is not None
                                    and selected_source.status is EvidenceStatus.READY
                                )
                                else selected_source.status
                                if selected_source is not None
                                else EvidenceStatus.UNAVAILABLE
                            )
                            sources.append(
                                RbacSource(
                                    "selected/" + ref.kind,
                                    request.intent.scope,
                                    status,
                                    None,
                                    None,
                                    "Selected UID is missing or replaced; replacement evidence is not the selected object."
                                    if status is EvidenceStatus.MISSING
                                    else "Selected UID was not observed; source evidence is incomplete or unavailable.",
                                    datetime.now(UTC),
                                )
                            )
                    final_rbac = await parse_owned(rbac)
                    snapshot = replace(snapshot, rbac=final_rbac)
                    if request.intent.mode in {
                        AuthorizationMode.SUBJECT,
                        AuthorizationMode.WHO_CAN,
                        AuthorizationMode.ROLE,
                    }:
                        analysis = await parse_owned(
                            partial(_analyze, final_rbac, identity.identity)
                        )
                        self._check(request)
                        snapshot = replace(snapshot, analysis=analysis)
        except (TimeoutError, ReadBudgetExceeded):
            self._check(request)
            detail = "Authorization collection deadline or shared read budget exhausted."
            if request.intent.mode == AuthorizationMode.REVIEW and snapshot.review is None:
                snapshot = replace(
                    snapshot,
                    review=AccessReview(
                        request,
                        ReviewDecision.UNKNOWN,
                        EvidenceStatus.TRUNCATED,
                        "No authoritative answer.",
                        (detail,),
                        datetime.now(UTC),
                    ),
                )
            elif request.intent.mode == AuthorizationMode.SELF_RULES:
                snapshot = replace(
                    snapshot,
                    rules=RulesReview(
                        request, (), True, EvidenceStatus.TRUNCATED, (detail,), datetime.now(UTC)
                    ),
                )
            elif request.intent.mode != AuthorizationMode.REVIEW:
                sources.append(
                    RbacSource(
                        "collection",
                        request.intent.scope,
                        EvidenceStatus.TRUNCATED,
                        CollectionState(False, True),
                        None,
                        detail,
                        datetime.now(UTC),
                    )
                )
                snapshot = replace(snapshot, rbac=await parse_owned(rbac))
                if request.intent.mode in {
                    AuthorizationMode.SUBJECT,
                    AuthorizationMode.WHO_CAN,
                    AuthorizationMode.ROLE,
                }:
                    snapshot = replace(snapshot, analysis=RbacAnalysis((), (), True, (detail,), 0))
        snapshot = replace(snapshot, collecting=False)
        return emit()
