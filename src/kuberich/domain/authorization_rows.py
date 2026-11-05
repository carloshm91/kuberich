"""Bounded native authorization presentation, without matching or transport work."""

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
    AuthorizationSnapshot,
    NonResourceAccess,
    RbacObjectRef,
    RbacRole,
    RbacRule,
    RbacSubject,
    ResourceAccess,
)

MAX_AUTHORIZATION_ROWS = 1024


@dataclass(frozen=True)
class AuthorizationRow:
    key: str
    label: str
    scope: str
    status: str
    details: tuple[str, ...]
    destination: AuthorizationIntent | None
    object_ref: RbacObjectRef | None


class _Rows(list[AuthorizationRow]):
    """Retain a bounded display prefix, including while a rule generator runs."""

    truncated = False

    def append(self, row: AuthorizationRow) -> None:
        if len(self) == MAX_AUTHORIZATION_ROWS:
            self.truncated = True
        else:
            super().append(row)

    def extend(self, rows: Iterable[AuthorizationRow]) -> None:
        for row in rows:
            if len(self) == MAX_AUTHORIZATION_ROWS:
                self.truncated = True
                break
            self.append(row)


def scope_label(scope: AuthorizationScope) -> str:
    return (
        f"namespace {scope.namespace}"
        if scope.kind is AuthorizationScopeKind.NAMESPACE
        else "all namespaces"
        if scope.kind is AuthorizationScopeKind.ALL_NAMESPACES
        else "cluster"
    )


def _key(prefix: str, *parts: str | int | None) -> str:
    return prefix + ":" + hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()


def _time(value: datetime | None) -> str:
    return (
        value.astimezone(UTC).isoformat(timespec="seconds") if value is not None else "unavailable"
    )


def _subject(subject: RbacSubject) -> str:
    return f"{subject.kind} {subject.namespace + '/' if subject.namespace is not None else ''}{subject.name}"


def _ref(ref: RbacObjectRef) -> str:
    return f"{ref.kind}/{ref.name}" + (
        f" · namespace {ref.namespace}" if ref.namespace is not None else " · cluster"
    )


def _object_key(ref: RbacObjectRef) -> tuple[str | None, ...]:
    return ref.kind, ref.namespace, ref.name, ref.uid


def _selected(ref: RbacObjectRef, expected: RbacObjectRef) -> bool:
    return _object_key(ref)[:3] == _object_key(expected)[:3] and (
        expected.uid is None or ref.uid == expected.uid
    )


def _subject_key(subject: RbacSubject) -> tuple[str | None, ...]:
    return str(subject.kind), subject.namespace, subject.name


def _rule(rule: RbacRule) -> tuple[str, ...]:
    return (
        "verbs: " + ", ".join(rule.verbs),
        "API groups: " + ", ".join(group or "core" for group in rule.api_groups),
        "resources: " + ", ".join(rule.resources),
        "resource names: " + (", ".join(rule.resource_names) or "unrestricted"),
        "non-resource URLs: " + (", ".join(rule.non_resource_urls) or "none"),
    )


def _question(access: ResourceAccess | NonResourceAccess) -> str:
    if isinstance(access, NonResourceAccess):
        return f"{access.verb} {access.path}"
    return (
        f"{access.verb} {access.resource}{'.' + access.group if access.group else ''}{'/' + access.subresource if access.subresource else ''}"
        + (f" · name {access.name}" if access.name is not None else " · unnamed request")
    )


def _role_destination(intent: AuthorizationIntent, ref: RbacObjectRef) -> AuthorizationIntent:
    return AuthorizationIntent(AuthorizationMode.ROLE, intent.scope, role=ref)


def _role_row(intent: AuthorizationIntent, role: RbacRole) -> AuthorizationRow:
    return AuthorizationRow(
        _key("role", *_object_key(role.ref)),
        _ref(role.ref),
        scope_label(intent.scope),
        "materialized aggregate" if role.aggregation_selectors else "declared role",
        (f"{len(role.rules)} observed rules", f"observed UID: {role.ref.uid or 'unavailable'}"),
        _role_destination(intent, role.ref),
        role.ref,
    )


def authorization_rows(snapshot: AuthorizationSnapshot | None) -> tuple[AuthorizationRow, ...]:
    """Project only observed DTOs; informational rows never become API targets."""
    if snapshot is None:
        return (
            AuthorizationRow(
                "summary:loading",
                "Authorization",
                "",
                "loading",
                ("Waiting for the current authorization request.",),
                None,
                None,
            ),
        )
    intent = snapshot.request.intent
    scope = scope_label(intent.scope)
    rows = _Rows(
        [
            AuthorizationRow(
                "summary:request",
                _question(intent.access)
                if intent.access is not None
                else "RBAC " + intent.mode.value.replace("_", " "),
                scope,
                "loading" if snapshot.collecting else "observed evidence",
                ("Informational evidence only; existing operation guards remain authoritative.",),
                None,
                None,
            )
        ]
    )
    warnings: list[str] = []
    if intent.mode is AuthorizationMode.WHO_CAN:
        warnings.append(
            "RBAC candidates only: external authorizers and unknown group members are not established by these declarations."
        )
    if intent.mode is AuthorizationMode.SUBJECT:
        warnings.append(
            "Observed RBAC declarations do not establish effective authorization. Review the current identity's exact request with :can-i."
        )
    if snapshot.rbac is not None:
        for source in snapshot.rbac.sources:
            collection = source.collection
            detail = (
                "collection N/A"
                if collection is None
                else "complete collection"
                if collection.complete
                else "INCOMPLETE collection"
            )
            rows.append(
                AuthorizationRow(
                    _key("source", source.family, source.scope.kind.value, source.scope.namespace),
                    "Source " + source.family,
                    scope_label(source.scope),
                    str(source.status),
                    (
                        detail,
                        f"observed: {_time(source.observed_at)}",
                        f"resource version: {source.resource_version or 'unavailable'}",
                        source.detail,
                    ),
                    None,
                    None,
                )
            )
    identity = snapshot.identity
    if identity is not None:
        current = identity.identity
        rows.append(
            AuthorizationRow(
                "identity:current",
                current.username if current is not None else "Current identity unavailable",
                scope,
                str(identity.status),
                (
                    f"observed: {_time(identity.observed_at)}",
                    *(("groups: " + ", ".join(current.groups),) if current is not None else ()),
                ),
                None,
                None,
            )
        )
        warnings.extend(identity.warnings)
    review = snapshot.review
    if review is not None and intent.access is not None:
        access = intent.access
        selectors = (
            (
                f"API version: {access.version}",
                f"label selector: {access.query.label_selector or 'none'}",
                f"field selector: {access.query.field_selector or 'none'}",
            )
            if isinstance(access, ResourceAccess)
            else ()
        )
        rows.append(
            AuthorizationRow(
                "review:decision",
                _question(access),
                scope,
                f"{review.decision} · {review.status}",
                (review.reason, f"observed: {_time(review.observed_at)}", *selectors),
                None,
                None,
            )
        )
        warnings.extend(review.warnings)
    rules = snapshot.rules
    if rules is not None:
        rows.append(
            AuthorizationRow(
                "review:rules",
                "Current identity rules",
                scope,
                str(rules.status),
                (
                    f"observed: {_time(rules.observed_at)}",
                    "INCOMPLETE rules; absence cannot establish denial."
                    if rules.incomplete
                    else "Observed rules; absence is not an access denial.",
                ),
                None,
                None,
            )
        )
        warnings.extend(rules.warnings)
        rows.extend(
            AuthorizationRow(
                _key("rule", "self", index),
                f"Rule {index + 1}",
                scope,
                "observed rules",
                _rule(rule),
                None,
                None,
            )
            for index, rule in enumerate(rules.rules)
        )
    rbac, analysis = snapshot.rbac, snapshot.analysis
    if analysis is not None:
        warnings.extend(analysis.warnings)
        if analysis.incomplete:
            warnings.append(
                "INCOMPLETE analysis: retained grants/contributors are a subset; absence is not proof of no access."
            )
    if rbac is not None:
        if intent.mode is AuthorizationMode.SUBJECTS:
            for evidence in rbac.subjects:
                subject = evidence.subject
                rows.append(
                    AuthorizationRow(
                        _key("subject", *_subject_key(subject)),
                        _subject(subject),
                        scope,
                        "observed subject",
                        tuple("origin: " + _ref(origin) for origin in evidence.origins)
                        or ("Listed ServiceAccount; no binding membership is implied.",),
                        AuthorizationIntent(
                            AuthorizationMode.SUBJECT, intent.scope, subject=subject
                        ),
                        None,
                    )
                )
        elif intent.mode in {AuthorizationMode.BINDINGS, AuthorizationMode.BINDING}:
            for binding in rbac.bindings:
                if intent.binding is not None and not _selected(binding.ref, intent.binding):
                    continue
                rows.append(
                    AuthorizationRow(
                        _key("binding", *_object_key(binding.ref)),
                        _ref(binding.ref),
                        scope,
                        "declared binding",
                        (
                            f"roleRef: {binding.role_kind}/{binding.role_name}",
                            f"observed UID: {binding.ref.uid or 'unavailable'}",
                        ),
                        AuthorizationIntent(
                            AuthorizationMode.BINDING, intent.scope, binding=binding.ref
                        )
                        if intent.mode is AuthorizationMode.BINDINGS
                        else None,
                        binding.ref,
                    )
                )
                if intent.mode is AuthorizationMode.BINDING:
                    role_ref = next(
                        (
                            role.ref
                            for role in rbac.roles
                            if role.ref.kind == binding.role_kind
                            and role.ref.name == binding.role_name
                            and role.ref.namespace
                            == (binding.ref.namespace if binding.role_kind == "Role" else None)
                        ),
                        RbacObjectRef(
                            binding.role_kind,
                            binding.role_name,
                            binding.ref.namespace if binding.role_kind == "Role" else None,
                            None,
                        ),
                    )
                    rows.append(
                        AuthorizationRow(
                            _key("role", *_object_key(role_ref)),
                            _ref(role_ref),
                            scope,
                            "observed role"
                            if role_ref.uid is not None
                            else "unresolved role reference",
                            (
                                "Role references resolve by name; object opening requires an observed UID.",
                            ),
                            _role_destination(intent, role_ref),
                            role_ref if role_ref.uid is not None else None,
                        )
                    )
                    rows.extend(
                        AuthorizationRow(
                            _key("subject", *_subject_key(subject)),
                            _subject(subject),
                            scope,
                            "declared subject",
                            (),
                            AuthorizationIntent(
                                AuthorizationMode.SUBJECT, intent.scope, subject=subject
                            ),
                            None,
                        )
                        for subject in dict.fromkeys(binding.subjects)
                    )
        elif intent.mode in {AuthorizationMode.ROLES, AuthorizationMode.ROLE}:
            for role in rbac.roles:
                if intent.role is not None and not _selected(role.ref, intent.role):
                    continue
                rows.append(_role_row(intent, role))
                if intent.mode is AuthorizationMode.ROLE:
                    rows.extend(
                        AuthorizationRow(
                            _key("rule", *_object_key(role.ref), index),
                            f"Rule {index + 1} · {_ref(role.ref)}",
                            scope,
                            "materialized" if role.aggregation_selectors else "declared",
                            _rule(rule),
                            None,
                            role.ref,
                        )
                        for index, rule in enumerate(role.rules)
                    )
        if (
            intent.mode in {AuthorizationMode.SUBJECT, AuthorizationMode.WHO_CAN}
            and analysis is not None
        ):
            for grant in analysis.grants:
                destination = (
                    AuthorizationIntent(
                        AuthorizationMode.BINDING, intent.scope, binding=grant.binding
                    )
                    if intent.mode is AuthorizationMode.SUBJECT
                    else AuthorizationIntent(
                        AuthorizationMode.SUBJECT, intent.scope, subject=grant.subject
                    )
                )
                rows.append(
                    AuthorizationRow(
                        _key(
                            "grant",
                            *_subject_key(grant.subject),
                            *_object_key(grant.binding),
                            *_object_key(grant.role),
                            grant.rule_index,
                            grant.via_group,
                        ),
                        _subject(grant.subject) + " · " + _ref(grant.binding),
                        scope_label(grant.scope),
                        f"RBAC candidate · {grant.evidence}",
                        (
                            f"role: {_ref(grant.role)} · rule {grant.rule_index + 1}",
                            f"via group: {grant.via_group or 'direct declaration'}",
                        ),
                        destination,
                        grant.binding,
                    )
                )
        if analysis is not None:
            for aggregate in analysis.aggregations:
                warnings.extend(aggregate.warnings)
                if aggregate.incomplete:
                    warnings.append("INCOMPLETE aggregate explanation for " + _ref(aggregate.role))
                rows.extend(
                    AuthorizationRow(
                        _key("contributor", *_object_key(aggregate.role), *_object_key(ref)),
                        "Contributor " + _ref(ref),
                        scope,
                        "inferred explanation",
                        (
                            "Selector-matched contributor; materialized aggregate rules remain the observed declaration.",
                        ),
                        _role_destination(intent, ref),
                        ref if ref.uid is not None else None,
                    )
                    for ref in aggregate.contributors
                )
        selected = intent.binding or intent.role
        if selected is not None and not any(
            row.object_ref is not None and _selected(row.object_ref, selected) for row in rows
        ):
            rows.append(
                AuthorizationRow(
                    "summary:missing",
                    _ref(selected),
                    scope,
                    "missing / unavailable",
                    (
                        "Selected object was not observed. Source evidence describes collection limits.",
                    ),
                    None,
                    None,
                )
            )
    warnings = list(dict.fromkeys(warnings))
    information = [
        row for row in rows if row.key.startswith(("summary:", "source:", "identity:", "review:"))
    ]
    information.extend(
        AuthorizationRow(
            _key("warning", warning), "Evidence limit", scope, "warning", (warning,), None, None
        )
        for warning in warnings
    )
    content = [row for row in rows if row not in information]
    result = information + content
    if rows.truncated or len(result) > MAX_AUTHORIZATION_ROWS:
        result = [
            *result[: MAX_AUTHORIZATION_ROWS - 1],
            AuthorizationRow(
                "summary:truncated",
                "Display row limit",
                scope,
                "truncated",
                (
                    "At most 1,024 evidence rows are displayed; retained source/analysis limits still apply.",
                ),
                None,
                None,
            ),
        ]
    return tuple(result)
