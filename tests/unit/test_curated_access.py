"""Access facts reuse exact RBAC declarations, identities and bounded safe projections."""

import json
from dataclasses import asdict, replace

import pytest

from kuberich.domain.authorization import AuthorizationMode, AuthorizationScopeKind, RbacSubjectKind
from kuberich.domain.curated_access import FAMILIES, cells, details
from kuberich.domain.curated_navigation import (
    AuthorizationDestination,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.resources import resource_record
from kuberich.errors import AppError
from tests.support.curated_access import (
    CANARY,
    KINDS,
    access_manifest,
    access_record,
    access_resource,
)


def values(kind="ServiceAccount", **changes):
    return dict(cells(access_resource(kind), access_record(kind, **changes)).values)


@pytest.mark.parametrize("kind", KINDS)
def test_family_columns_typed_values_distinct_rows_and_canary_allowlist(kind):
    resource = access_resource(kind)
    first, second = (
        cells(resource, access_record(kind)),
        cells(resource, access_record(kind, variant=1)),
    )
    profile = next(item for item in FAMILIES if item.kind == kind)
    expected = (
        ("automount", "secrets", "image-pull-secrets")
        if kind == "ServiceAccount"
        else ("rules", "resource-rules", "nonresource-rules", "aggregation-selectors")
        if kind in {"Role", "ClusterRole"}
        else ("role-kind", "role", "service-accounts", "users", "groups")
    )
    assert (
        tuple(key for key, _ in first.values)
        == tuple(item.key for item in profile.fields)
        == expected
    )
    assert first.values != second.values
    for record in (access_record(kind), access_record(kind, variant=1)):
        result = details(resource, record)
        assert CANARY not in repr(cells(resource, record)) + repr(result)
        assert result.links and all(
            len(value.text) <= 256 for _, value in cells(resource, record).values
        )
        assert any(isinstance(link.destination, AuthorizationDestination) for link in result.links)
        assert "effective access" in " ".join(result.notices)
    for field, value in second.values:
        assert type(value.sort) is (int if field not in {"automount", "role-kind", "role"} else str)


@pytest.mark.parametrize(
    "mount,expected",
    [(None, "inherited"), (True, "true"), (False, "false"), ("false", "unknown"), (0, "unknown")],
)
def test_automount_inherited_explicit_and_malformed(mount, expected):
    result = values(automountServiceAccountToken=mount)
    assert result["automount"].text == expected


@pytest.mark.parametrize(
    "kind,field",
    [
        ("ServiceAccount", "secrets"),
        ("ServiceAccount", "imagePullSecrets"),
        ("Role", "rules"),
        ("ClusterRole", "rules"),
        ("RoleBinding", "subjects"),
        ("ClusterRoleBinding", "subjects"),
    ],
)
def test_optional_absent_arrays_are_no_declared_entries_while_null_is_unknown(kind, field):
    resource = access_resource(kind)
    manifest = access_manifest(kind)
    manifest.pop(field)
    absent = cells(resource, resource_record(resource, manifest))
    assert any("not declared" in notice for notice in absent.notices)
    assert any(value.sort == 0 for _, value in absent.values)
    explicit = cells(resource, access_record(kind, **{field: []}))
    assert not explicit.notices
    invalid = cells(resource, access_record(kind, **{field: None}))
    assert invalid.notices and any(value.sort is None for _, value in invalid.values)
    assert details(resource, access_record(kind, **{field: None})).notices


def test_role_rule_classes_aggregation_and_existing_role_intent():
    result = values("ClusterRole", variant=1)
    assert [value.sort for value in result.values()] == [2, 1, 1, 1]
    publication = details(access_resource("ClusterRole"), access_record("ClusterRole", variant=1))
    intent = publication.links[0].destination.intent
    assert intent.mode is AuthorizationMode.ROLE and intent.role.uid == "owned-uid-1"
    assert intent.scope.kind is AuthorizationScopeKind.CLUSTER
    assert publication.sections[0].rows[1][-1] == "/healthz"
    assert publication.sections[1].rows
    assert publication.sections[1].rows[0] == ("1", "owned-part", "In", "readers")
    empty = details(
        access_resource("ClusterRole"),
        access_record("ClusterRole", aggregationRule={"clusterRoleSelectors": [{}]}),
    )
    assert empty.sections[1].rows == (("1", "all ClusterRoles", "empty selector", ""),)


@pytest.mark.parametrize("kind", ["RoleBinding", "ClusterRoleBinding"])
def test_binding_subjects_preserve_grant_scope_and_declared_subject_namespace(kind):
    record = access_record(kind, variant=1)
    original = record.manifest
    result = values(kind, variant=1)
    assert [result[key].sort for key in ("service-accounts", "users", "groups")] == [1, 2, 1]
    publication = details(access_resource(kind), record)
    destinations = [link.destination for link in publication.links]
    assert all(isinstance(item, AuthorizationDestination) for item in destinations)
    intents = [item.intent for item in destinations]
    assert intents[0].mode is AuthorizationMode.BINDING
    assert intents[1].role.kind == "ClusterRole" and intents[1].role.namespace is None
    assert intents[0].scope.namespace == ("team" if kind == "RoleBinding" else None)
    assert intents[2].subject.namespace == ("team" if kind == "RoleBinding" else "other")
    assert intents[-1].subject.kind is RbacSubjectKind.GROUP
    assert record.manifest == original


@pytest.mark.parametrize(
    "kind,changes",
    [
        ("Role", {"rules": [{}]}),
        ("Role", {"aggregationRule": {}}),
        ("ClusterRole", {"aggregationRule": None}),
        ("RoleBinding", {"roleRef": {}}),
        ("RoleBinding", {"subjects": [{"kind": "Unknown", "name": "x"}]}),
        ("RoleBinding", {"subjects": [{"kind": "User", "name": "x", "apiGroup": "wrong"}]}),
        (
            "ClusterRoleBinding",
            {"roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": "x"}},
        ),
    ],
)
def test_parser_rejections_are_unknown_and_disabled_without_raw_payload(kind, changes):
    record = access_record(kind, **changes)
    assert all(value.sort is None for _, value in cells(access_resource(kind), record).values)
    result = details(access_resource(kind), record)
    assert len(result.links) == 1 and result.links[0].destination is None
    assert result.links[0].unavailable_reason and CANARY not in repr(result)


def test_serviceaccount_declared_secret_uid_and_current_named_reference_identity():
    record = access_record(variant=1)
    result = details(access_resource(), record)
    assert isinstance(result.links[1].destination, RelationshipDestination)
    refs = [
        link.destination
        for link in result.links
        if isinstance(link.destination, ReferenceDestination)
    ]
    assert refs[0].ref.uid == "declared-secret-uid" and refs[0].require_uid
    assert refs[1].ref.uid is None and not refs[1].require_uid
    assert all(item.ref.namespace == "team" and item.ref.kind == "Secret" for item in refs)
    assert refs[2].ref.name == "owned-registry"


@pytest.mark.parametrize(
    "ref",
    [
        None,
        {},
        {"name": "x", "namespace": "other"},
        {"name": "x", "kind": "Pod"},
        {"name": "x", "apiVersion": "bad/v1"},
        {"name": "x", "uid": True},
        {"name": "bad/name"},
        {"name": "x" * 254},
    ],
)
def test_invalid_secret_identity_disables_link_and_never_matches_a_clipped_name(ref):
    record = access_record(secrets=[ref])
    assert values(secrets=[ref])["secrets"].sort is None
    result = details(access_resource(), record)
    link = next(link for link in result.links if link.key == "secrets:0")
    assert link.destination is None and link.unavailable_reason


def test_full_valid_subject_identity_survives_display_clipping_and_output_is_bounded():
    name = "owned-" + "x" * 500
    record = access_record("RoleBinding", subjects=[{"kind": "User", "name": name}])
    result = details(access_resource("RoleBinding"), record)
    link = result.links[2]
    assert len(link.label) == 256 and link.destination.intent.subject.name == name
    large = access_record(
        "RoleBinding",
        subjects=[{"kind": "User", "name": str(index) + "x" * 8000} for index in range(300)],
    )
    result = details(access_resource("RoleBinding"), large)
    assert len(result.links) + sum(len(section.rows) for section in result.sections) <= 256
    assert len(repr(result).encode()) < 65536
    assert any(section.omitted_rows for section in result.sections)
    assert any("omitted" in notice for notice in result.notices)


def test_row_bound_omissions_and_long_rule_summary():
    rules = [{"verbs": ["get"] * 20, "apiGroups": [""], "resources": ["pods"]} for _ in range(400)]
    result = details(access_resource("Role"), access_record("Role", rules=rules))
    assert result.sections[0].omitted_rows > 0
    assert "…" in result.sections[0].rows[0][0]
    assert len(result.links) + sum(len(section.rows) for section in result.sections) <= 256
    assert len(repr(result).encode()) < 65536


def test_serialized_detail_budget_includes_json_escaping_and_complete_link_identity():
    literal = '\\"' * 128
    rule = {
        "verbs": [literal],
        "apiGroups": [literal],
        "resources": [literal],
        "resourceNames": [literal],
    }
    result = details(access_resource("Role"), access_record("Role", rules=[rule] * 80))
    encoded = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= 65536, len(encoded)
    assert len(result.links) + sum(len(section.rows) for section in result.sections) <= 256
    assert result.sections[0].omitted_rows > 0
    assert result.links[0].destination.intent.role.uid == "owned-uid-0"


def test_serialized_link_budget_preserves_full_identity_or_omits_the_whole_link():
    names = [str(index) + '\\"' * 4000 for index in range(20)]
    record = access_record(
        "RoleBinding", subjects=[{"kind": "User", "name": name} for name in names]
    )
    result = details(access_resource("RoleBinding"), record)
    encoded = json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":")).encode()
    assert len(encoded) <= 65536
    retained = [link.destination.intent.subject.name for link in result.links[2:]]
    assert retained and retained == names[: len(retained)]
    assert len(retained) < len(names) and any(
        "links omitted" in notice for notice in result.notices
    )
    assert all(len(link.label) <= 256 for link in result.links)


@pytest.mark.parametrize(
    "dimension,value",
    [
        ("group", "wrong"),
        ("version", "v2"),
        ("kind", "Pod"),
        ("namespaced", False),
        ("name", "pods"),
    ],
)
def test_exact_descriptor_and_metadata_only_rejection(dimension, value):
    resource = access_resource()
    invalid = replace(resource, **{dimension: value})
    for operation in (cells, details):
        with pytest.raises(AppError):
            operation(invalid, access_record())
        with pytest.raises(AppError):
            operation(resource, replace(access_record(), metadata_only=True))


@pytest.mark.parametrize("kind", KINDS)
def test_missing_types_are_normalized_by_actual_descriptor_and_explicit_contradictions_refuse(kind):
    resource = access_resource(kind)
    manifest = access_manifest(kind)
    del manifest["kind"], manifest["apiVersion"]
    record = resource_record(resource, manifest)
    assert cells(resource, record).values and details(resource, record).links
    for field, value in (("kind", "Wrong"), ("apiVersion", "wrong/v1")):
        with pytest.raises(AppError):
            resource_record(resource, {**manifest, field: value})


def test_malformed_array_parser_bound_and_invalid_subject_source_remain_safe():
    assert values(secrets="not a list")["secrets"].sort is None
    assert values("Role", rules=[{}] * 10001)["rules"].sort is None
    record = replace(access_record(), name="")
    with pytest.raises(AppError):
        details(access_resource(), record)
