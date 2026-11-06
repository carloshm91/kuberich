"""Allowlisted access declarations; authorization remains owned by the RBAC workspace."""

import json
from collections.abc import Iterable
from dataclasses import asdict, replace
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
    RbacBinding,
    RbacObjectRef,
    RbacRole,
    RbacSubject,
    RbacSubjectKind,
)
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
    AuthorizationDestination,
    CuratedLink,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.rbac import parse_rbac_binding, parse_rbac_role
from kuberich.domain.relationships import (
    RelationshipMode,
    RelationshipRef,
    fact_list,
    fact_mapping,
    fact_name,
)
from kuberich.domain.resources import ApiResource, ResourceRecord, resource_record
from kuberich.domain.table_values import Column, Value
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

_GROUP = "rbac.authorization.k8s.io"
_INVALID = "Access declaration is malformed or exceeds parser bounds."
_DECLARED = "Declarations do not establish effective access or external group membership."
_ROLE_FIELDS = tuple(
    Column(key, True)
    for key in ("rules", "resource-rules", "nonresource-rules", "aggregation-selectors")
)
_BINDING_FIELDS = (
    Column("role-kind"),
    Column("role"),
    Column("service-accounts", True),
    Column("users", True),
    Column("groups", True),
)
FAMILIES = (
    CuratedFamily(
        "",
        "serviceaccounts",
        "ServiceAccount",
        True,
        frozenset({"v1"}),
        ("sa",),
        (Column("automount"), Column("secrets", True), Column("image-pull-secrets", True)),
    ),
    CuratedFamily(_GROUP, "roles", "Role", True, frozenset({"v1"}), ("role",), _ROLE_FIELDS),
    CuratedFamily(
        _GROUP,
        "clusterroles",
        "ClusterRole",
        False,
        frozenset({"v1"}),
        ("clusterrole",),
        _ROLE_FIELDS,
    ),
    CuratedFamily(
        _GROUP, "rolebindings", "RoleBinding", True, frozenset({"v1"}), ("rb",), _BINDING_FIELDS
    ),
    CuratedFamily(
        _GROUP,
        "clusterrolebindings",
        "ClusterRoleBinding",
        False,
        frozenset({"v1"}),
        ("crb",),
        _BINDING_FIELDS,
    ),
)


def _text(value: str) -> str:
    return sanitize_text(value)[:MAX_CURATED_CELL_CHARACTERS]


def _joined(values: tuple[str, ...]) -> str:
    return _text(
        ", ".join(value[:256] for value in values[:16]) + (" …" if len(values) > 16 else "")
    )


def _scope(namespace: str | None) -> AuthorizationScope:
    return AuthorizationScope(
        AuthorizationScopeKind.CLUSTER if namespace is None else AuthorizationScopeKind.NAMESPACE,
        namespace,
    )


def _array(manifest: dict[str, Any], field: str, notices: list[str]) -> list[Any]:
    if field not in manifest:
        notices.append(f"{field} not declared; no entries are declared.")
    return fact_list(manifest.get(field, []))


def _secret(value: Any, namespace: str | None, *, local: bool) -> RelationshipRef:
    data = fact_mapping(value)
    name = fact_name(data.get("name"))
    if (
        data.get("namespace", namespace) != namespace
        or data.get("kind", "Secret") != "Secret"
        or data.get("apiVersion", "v1") != "v1"
    ):
        raise AppError("Invalid Secret reference type or namespace.")
    uid = None if local else data.get("uid")
    if uid is not None:
        uid = validate_argument(uid)
    return RelationshipRef("v1", "Secret", namespace, name, uid, None)


def _rbac(
    resource: ApiResource, record: ResourceRecord, manifest: dict[str, Any]
) -> RbacRole | RbacBinding | None:
    try:
        if resource.kind in {"Role", "ClusterRole"}:
            return parse_rbac_role(resource, record)
        # The API defaults an omitted User/Group apiGroup; keep contradictory
        # explicit groups for the existing parser to reject.
        defaulted = False
        for subject in fact_list(manifest.get("subjects", [])):
            item = fact_mapping(subject)
            if item.get("kind") in {"User", "Group"} and "apiGroup" not in item:
                item["apiGroup"] = _GROUP
                defaulted = True
        return parse_rbac_binding(
            resource, resource_record(resource, manifest) if defaulted else record
        )
    except AppError:
        return None


def cells(resource: ApiResource, record: ResourceRecord) -> CuratedCells:
    profile, manifest = require_curated_record(resource, record, FAMILIES)
    notices: list[str] = []
    if profile.kind == "ServiceAccount":
        mount = manifest.get("automountServiceAccountToken")
        values = [
            Value("inherited", "inherited")
            if mount is None
            else Value(str(mount).lower(), str(mount).lower())
            if type(mount) is bool
            else Value("unknown", None)
        ]
        if mount is not None and type(mount) is not bool:
            notices.append("Automount policy is malformed; effective Pod policy is unknown.")
        for field in ("secrets", "imagePullSecrets"):
            try:
                references = _array(manifest, field, notices)
                for reference in references:
                    _secret(reference, record.namespace, local=field == "imagePullSecrets")
                values.append(Value(str(len(references)), len(references)))
            except AppError:
                values.append(Value("unknown", None))
                notices.append(_INVALID)
    else:
        parsed = _rbac(resource, record, manifest)
        if parsed is None:
            return CuratedCells(
                tuple((field.key, Value("unknown", None)) for field in profile.fields), (_INVALID,)
            )
        if isinstance(parsed, RbacRole):
            _array(manifest, "rules", notices)
            counts = (
                len(parsed.rules),
                sum(bool(rule.resources) for rule in parsed.rules),
                sum(bool(rule.non_resource_urls) for rule in parsed.rules),
                len(parsed.aggregation_selectors),
            )
            values = [Value(str(count), count) for count in counts]
        else:
            _array(manifest, "subjects", notices)
            values = [
                Value(parsed.role_kind, parsed.role_kind),
                Value(_text(parsed.role_name), parsed.role_name),
            ]
            for kind in (
                RbacSubjectKind.SERVICE_ACCOUNT,
                RbacSubjectKind.USER,
                RbacSubjectKind.GROUP,
            ):
                count = sum(subject.kind == kind for subject in parsed.subjects)
                values.append(Value(str(count), count))
    return CuratedCells(
        tuple((field.key, value) for field, value in zip(profile.fields, values, strict=True)),
        tuple(dict.fromkeys(notices)),
    )


class _Details:
    def __init__(self) -> None:
        self.sections: list[DetailSection] = []
        self.links: list[CuratedLink] = []
        self.notices = [_DECLARED]
        self.remaining = MAX_CURATED_DETAIL_ROWS
        self.bytes = MAX_CURATED_DETAIL_BYTES - 4096
        self.omitted_links = 0

    def link(self, value: CuratedLink) -> None:
        size = len(repr(value).encode("utf-8")) + 256
        if self.remaining and size <= self.bytes:
            self.links.append(value)
            self.remaining -= 1
            self.bytes -= size
        else:
            self.omitted_links += 1

    def section(
        self, title: str, columns: tuple[str, ...], rows: Iterable[tuple[str, ...]]
    ) -> None:
        retained, omitted = [], 0
        for row in rows:
            display = tuple(_text(cell) for cell in row)
            size = sum(len(cell.encode("utf-8")) for cell in display) + 256
            if self.remaining and size <= self.bytes:
                retained.append(display)
                self.remaining -= 1
                self.bytes -= size
            else:
                omitted += 1
        self.sections.append(DetailSection(title, columns, tuple(retained), omitted))

    def finish(self) -> CuratedDetails:
        # Reaccount the complete serialized presentation and action identities.
        # A raw UTF-8 estimate cannot account for JSON quote/control escaping.
        notices = list(dict.fromkeys(self.notices))
        sections = [replace(section, rows=()) for section in self.sections]
        size = _encoded(asdict(CuratedDetails(tuple(sections), (), tuple(notices)))) + 512
        selected = []
        used = 0
        omitted_links = self.omitted_links
        for link in self.links:
            added = _encoded(asdict(link)) + 1
            if used < MAX_CURATED_DETAIL_ROWS and size + added <= MAX_CURATED_DETAIL_BYTES:
                selected.append(link)
                size += added
                used += 1
            else:
                omitted_links += 1
        for index, original in enumerate(self.sections):
            retained = []
            omitted = original.omitted_rows
            for row in original.rows:
                added = _encoded(row) + 1
                if used < MAX_CURATED_DETAIL_ROWS and size + added <= MAX_CURATED_DETAIL_BYTES:
                    retained.append(row)
                    size += added
                    used += 1
                else:
                    omitted += 1
            sections[index] = replace(original, rows=tuple(retained), omitted_rows=omitted)
        if omitted_links:
            notices.append(f"{omitted_links} links omitted by the combined detail limit.")
        if any(section.omitted_rows for section in sections):
            notices.append("Detail row or serialized byte limit reached; omitted counts are shown.")
        return CuratedDetails(tuple(sections), tuple(selected), tuple(notices))


def _encoded(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _authorization(key: str, label: str, intent: AuthorizationIntent) -> CuratedLink:
    return CuratedLink(
        key,
        label,
        "Declared RBAC evidence; not an authorization decision",
        AuthorizationDestination(intent),
    )


def _aggregation_rows(role: RbacRole) -> Iterable[tuple[str, ...]]:
    for index, selector in enumerate(role.aggregation_selectors):
        if not selector.requirements:
            yield (str(index + 1), "all ClusterRoles", "empty selector", "")
        for requirement in selector.requirements:
            yield (
                str(index + 1),
                requirement.key,
                requirement.operator,
                _joined(requirement.values),
            )


def details(resource: ApiResource, record: ResourceRecord) -> CuratedDetails:
    profile, manifest = require_curated_record(resource, record, FAMILIES)
    output = _Details()
    if profile.kind == "ServiceAccount":
        subject = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, record.name, record.namespace)
        output.link(
            _authorization(
                "authorization",
                "Explain ServiceAccount grants",
                AuthorizationIntent(
                    AuthorizationMode.SUBJECT, _scope(record.namespace), subject=subject
                ),
            )
        )
        output.link(
            CuratedLink(
                "usedby",
                "Used by",
                "Observed references; no effective-access claim",
                RelationshipDestination(RelationshipMode.USED_BY),
            )
        )
        facts = cells(resource, record)
        output.notices.extend(facts.notices)
        output.section(
            "ServiceAccount policy",
            ("Fact", "Declaration"),
            ((key, value.text) for key, value in facts.values),
        )
        output.notices.append(
            "Automount is the ServiceAccount declaration; Pod policy can override it. Secret contents and tokens are never read."
        )
        for field in ("secrets", "imagePullSecrets"):
            rows = []
            try:
                references = _array(manifest, field, output.notices)
            except AppError:
                references = []
                output.notices.append(_INVALID)
            for index, raw in enumerate(references):
                try:
                    ref = _secret(raw, record.namespace, local=field == "imagePullSecrets")
                    output.link(
                        CuratedLink(
                            f"{field}:{index}",
                            _text(ref.name),
                            "Declared reference; fresh current named Secret, not token or historical identity",
                            ReferenceDestination(ref, ref.uid is not None),
                        )
                    )
                    rows.append((ref.name, ref.namespace or "", ref.uid or "not declared"))
                except AppError:
                    output.link(
                        CuratedLink(
                            f"{field}:{index}",
                            "Invalid Secret reference",
                            "Declared reference",
                            None,
                            "Secret reference identity, type or namespace is invalid.",
                        )
                    )
                    rows.append(("invalid reference", "unknown", "unknown"))
            output.section(field, ("Name", "Namespace", "Declared UID"), rows)
        return output.finish()
    parsed = _rbac(resource, record, manifest)
    if parsed is None:
        output.notices.append(_INVALID)
        output.link(
            CuratedLink("authorization", "Explain declaration", "RBAC declaration", None, _INVALID)
        )
        return output.finish()
    scope = _scope(record.namespace)
    if isinstance(parsed, RbacRole):
        output.link(
            _authorization(
                "authorization",
                "Explain role and aggregation",
                AuthorizationIntent(AuthorizationMode.ROLE, scope, role=parsed.ref),
            )
        )
        output.section(
            "Rules",
            ("Verbs", "API groups", "Resources", "Resource names", "Nonresource paths"),
            (
                (
                    _joined(rule.verbs),
                    _joined(rule.api_groups),
                    _joined(rule.resources),
                    _joined(rule.resource_names),
                    _joined(rule.non_resource_urls),
                )
                for rule in parsed.rules
            ),
        )
        output.section(
            "Aggregation declarations",
            ("Selector", "Key", "Operator", "Values"),
            _aggregation_rows(parsed),
        )
    else:
        output.link(
            _authorization(
                "authorization",
                "Explain binding",
                AuthorizationIntent(AuthorizationMode.BINDING, scope, binding=parsed.ref),
            )
        )
        role = RbacObjectRef(
            parsed.role_kind,
            parsed.role_name,
            record.namespace if parsed.role_kind == "Role" else None,
            None,
        )
        output.link(
            _authorization(
                "role",
                "Explain declared role",
                AuthorizationIntent(AuthorizationMode.ROLE, scope, role=role),
            )
        )
        for index, subject in enumerate(parsed.subjects):
            output.link(
                _authorization(
                    f"subject:{index}",
                    _text(str(subject.kind) + " " + subject.name),
                    AuthorizationIntent(AuthorizationMode.SUBJECT, scope, subject=subject),
                )
            )
        output.section(
            "Role reference",
            ("Kind", "Name", "Grant scope"),
            ((parsed.role_kind, parsed.role_name, record.namespace or "cluster"),),
        )
        output.section(
            "Subjects",
            ("Kind", "Name", "Namespace"),
            (
                (str(subject.kind), subject.name, subject.namespace or "not applicable")
                for subject in parsed.subjects
            ),
        )
        output.notices.append(
            "Role reference has no declared UID; explaining it resolves current named role evidence. Group membership remains unknown."
        )
    _array(manifest, "rules" if isinstance(parsed, RbacRole) else "subjects", output.notices)
    return output.finish()
