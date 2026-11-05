"""RBAC declaration parsing, exact request semantics and bounded provenance."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationRequest,
    AuthorizationScope,
    AuthorizationScopeKind,
    AuthorizationSnapshot,
    CurrentIdentity,
    EvidenceStatus,
    NonResourceAccess,
    RbacAnalysis,
    RbacBinding,
    RbacEvidenceKind,
    RbacObjectRef,
    RbacRole,
    RbacRule,
    RbacSnapshot,
    RbacSource,
    RbacSubject,
    RbacSubjectEvidence,
    RbacSubjectKind,
    ResourceAccess,
)
from kuberich.domain.authorization_rows import authorization_rows
from kuberich.domain.rbac import (
    aggregation_contributors,
    binding_applies,
    parse_rbac_binding,
    parse_rbac_role,
    resolve_role,
    rule_matches,
    subject_grants,
    who_can,
)
from kuberich.domain.relationships import LabelRequirement, RelationshipSelector
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from tests.support.relationships import descriptor, record

GROUP = "rbac.authorization.k8s.io"
ROLES = descriptor("roles", "Role", GROUP)
CLUSTERROLES = descriptor("clusterroles", "ClusterRole", GROUP, namespaced=False)
BINDINGS = descriptor("rolebindings", "RoleBinding", GROUP)
CLUSTERBINDINGS = descriptor("clusterrolebindings", "ClusterRoleBinding", GROUP, namespaced=False)
NS = AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "team")
ALL = AuthorizationScope(AuthorizationScopeKind.ALL_NAMESPACES, None)
CLUSTER = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
ALICE = RbacSubject(RbacSubjectKind.USER, "alice", None)
DEVELOPERS = RbacSubject(RbacSubjectKind.GROUP, "developers", None)
SA = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "app", "team")
INSTANT = datetime(2026, 11, 5, tzinfo=UTC)


def rule(**changes):
    return replace(RbacRule(("get",), ("",), ("pods",), (), ()), **changes)


def access(**changes):
    return replace(
        ResourceAccess("get", "", "v1", "pods", None, None, NS, ResourceQuery()), **changes
    )


def role(name="view", *, namespace="team", rules=None, labels=(), selectors=()):
    return RbacRole(
        RbacObjectRef(
            "Role" if namespace is not None else "ClusterRole", name, namespace, name + "-uid"
        ),
        (rule(),) if rules is None else rules,
        labels,
        selectors,
    )


def binding(
    name="view", *, namespace="team", subjects=(ALICE,), role_kind="Role", role_name="view"
):
    return RbacBinding(
        RbacObjectRef(
            "RoleBinding" if namespace is not None else "ClusterRoleBinding",
            name,
            namespace,
            name + "-uid",
        ),
        subjects,
        role_kind,
        role_name,
    )


def snapshot(*, bindings=None, roles=None, sources=(), scope=NS):
    request = AuthorizationRequest(
        SessionIdentity("synthetic", 1), 1, AuthorizationIntent(AuthorizationMode.SUBJECTS, scope)
    )
    return RbacSnapshot(
        request,
        (RbacSubjectEvidence(ALICE, ()),),
        (binding(),) if bindings is None else bindings,
        (role(),) if roles is None else roles,
        sources,
        1,
        INSTANT,
    )


def selector(key="part", *values):
    return RelationshipSelector((LabelRequirement(key, "In", values or ("leaf",)),))


def raw_rule(**changes):
    return {"verbs": ["get"], "apiGroups": [""], "resources": ["pods"], **changes}


def raw_subject(kind="User", name="alice", **changes):
    return {
        "kind": kind,
        "name": name,
        "apiGroup": "" if kind == "ServiceAccount" else GROUP,
        **changes,
    }


def binding_record(resource=BINDINGS, **changes):
    return record(
        resource,
        roleRef={
            "apiGroup": GROUP,
            "kind": "Role" if resource.namespaced else "ClusterRole",
            "name": "view",
        },
        subjects=[raw_subject()],
        **changes,
    )


def test_role_parser_preserves_materialized_rules_raw_case_labels_and_aggregations():
    source = record(
        CLUSTERROLES,
        name="aggregate",
        rules=[
            raw_rule(verbs=["*"], resourceNames=["Named"]),
            {"verbs": ["get"], "nonResourceURLs": ["/healthz", "/ready*"]},
        ],
        metadata={"labels": {"tier": "control"}},
        aggregationRule={
            "clusterRoleSelectors": [
                {"matchLabels": {"part": "leaf"}},
                {
                    "matchExpressions": [
                        {"key": "part", "operator": "In", "values": ["leaf", ""]},
                        {"key": "blocked", "operator": "DoesNotExist"},
                    ]
                },
            ]
        },
    )
    parsed = parse_rbac_role(CLUSTERROLES, source)
    assert parsed.ref.name == "aggregate" and parsed.ref.uid == "example-uid"
    assert parsed.rules[0].resource_names == ("Named",)
    assert parsed.rules[1].non_resource_urls == ("/healthz", "/ready*")
    assert parsed.labels == (("tier", "control"),)
    assert len(parsed.aggregation_selectors) == 2
    assert parsed.aggregation_selectors[1].requirements[0].values == ("leaf", "")
    assert parse_rbac_role(ROLES, record(ROLES)).rules == ()
    assert (
        parse_rbac_role(
            CLUSTERROLES, record(CLUSTERROLES, aggregationRule={})
        ).aggregation_selectors
        == ()
    )


@pytest.mark.parametrize(
    "resource",
    [
        replace(ROLES, group="other"),
        replace(ROLES, kind="Secret"),
        replace(ROLES, namespaced=False),
    ],
)
def test_parser_requires_the_exact_discovered_rbac_family(resource):
    with pytest.raises(AppError):
        parse_rbac_role(resource, record(ROLES))
    with pytest.raises(AppError):
        parse_rbac_binding(resource, binding_record())


@pytest.mark.parametrize(
    "value",
    [
        None,
        {"verbs": []},
        raw_rule(apiGroups=[]),
        raw_rule(nonResourceURLs=["/healthz"]),
        {"verbs": ["get"], "nonResourceURLs": ["/healthz"], "apiGroups": [""]},
        {"verbs": ["get"], "nonResourceURLs": ["/healthz"], "resourceNames": ["one"]},
        raw_rule(verbs=[1]),
        raw_rule(resources=[""]),
        raw_rule(resourceNames="one"),
        raw_rule(verbs=["x" * 8193]),
    ],
)
def test_invalid_or_excessive_rules_cannot_create_grants(value):
    with pytest.raises(AppError):
        parse_rbac_role(ROLES, record(ROLES, rules=[value]))


@pytest.mark.parametrize(
    "value",
    [
        {"other": {}},
        {"matchLabels": {"bad key": "value"}},
        {"matchExpressions": [{"key": "part", "operator": "Unknown", "values": []}]},
        {"matchExpressions": [{"key": "part", "operator": [], "values": []}]},
        {"matchExpressions": [{"key": "part", "operator": "In", "values": []}]},
        {"matchExpressions": [{"key": "part", "operator": "Exists", "values": ["leaf"]}]},
        {"matchExpressions": [{"key": "bad key", "operator": "Exists"}]},
        {"matchExpressions": [{"key": "part", "operator": "In", "values": ["bad value"]}]},
        {"matchExpressions": [{"key": "part", "operator": "In", "values": ["leaf"] * 10000}]},
    ],
)
def test_invalid_aggregation_selectors_are_unknown_evidence(value):
    with pytest.raises(AppError):
        parse_rbac_role(
            CLUSTERROLES, record(CLUSTERROLES, aggregationRule={"clusterRoleSelectors": [value]})
        )


def test_aggregations_require_clusterroles_and_full_bounded_manifests():
    with pytest.raises(AppError, match="Only ClusterRoles"):
        parse_rbac_role(ROLES, record(ROLES, aggregationRule={}))
    with pytest.raises(AppError, match="Incomplete"):
        parse_rbac_role(ROLES, replace(record(ROLES), metadata_only=True))


def test_binding_parser_preserves_subjects_and_defaults_only_omitted_namespaced_sa_scope():
    source = record(
        BINDINGS,
        roleRef={"apiGroup": GROUP, "kind": "ClusterRole", "name": "system:view"},
        subjects=[
            raw_subject("User", "Alice"),
            raw_subject("Group", "Developers"),
            raw_subject("ServiceAccount", "app"),
            raw_subject("ServiceAccount", "other", namespace="other"),
        ],
    )
    parsed = parse_rbac_binding(BINDINGS, source)
    assert parsed.role_kind == "ClusterRole" and parsed.role_name == "system:view"
    assert parsed.subjects[0].name == "Alice" and parsed.subjects[1].name == "Developers"
    assert parsed.subjects[2].namespace == "team" and parsed.subjects[3].namespace == "other"
    cluster = parse_rbac_binding(
        CLUSTERBINDINGS,
        record(
            CLUSTERBINDINGS,
            roleRef={"apiGroup": GROUP, "kind": "ClusterRole", "name": "view"},
            subjects=[raw_subject("ServiceAccount", "app", namespace="team")],
        ),
    )
    assert cluster.subjects == (SA,)
    assert parse_rbac_binding(BINDINGS, binding_record()).subjects == (ALICE,)
    assert (
        parse_rbac_binding(
            BINDINGS, record(BINDINGS, roleRef={"apiGroup": GROUP, "kind": "Role", "name": "view"})
        ).subjects
        == ()
    )


@pytest.mark.parametrize(
    "role_ref",
    [
        None,
        {"apiGroup": "other", "kind": "Role", "name": "view"},
        {"apiGroup": GROUP, "kind": "User", "name": "view"},
        {"apiGroup": GROUP, "kind": [], "name": "view"},
        {"apiGroup": GROUP, "kind": "Role", "name": "../view"},
    ],
)
def test_role_references_require_rbac_group_supported_kind_and_safe_name(role_ref):
    with pytest.raises(AppError):
        parse_rbac_binding(BINDINGS, record(BINDINGS, roleRef=role_ref))


@pytest.mark.parametrize(
    "subject",
    [
        raw_subject("Unknown"),
        raw_subject(apiGroup="other"),
        raw_subject("ServiceAccount", "app", apiGroup=GROUP),
        raw_subject("ServiceAccount", "app", namespace=""),
        raw_subject(namespace="team"),
        raw_subject(name=""),
        None,
    ],
)
def test_malformed_subjects_do_not_become_users_or_groups(subject):
    with pytest.raises(AppError):
        parse_rbac_binding(
            BINDINGS,
            record(
                BINDINGS,
                roleRef={"apiGroup": GROUP, "kind": "Role", "name": "view"},
                subjects=[subject],
            ),
        )


def test_clusterbindings_cannot_default_sa_namespace_or_reference_namespaced_role():
    with pytest.raises(AppError):
        parse_rbac_binding(
            CLUSTERBINDINGS,
            record(
                CLUSTERBINDINGS,
                roleRef={"apiGroup": GROUP, "kind": "ClusterRole", "name": "view"},
                subjects=[raw_subject("ServiceAccount", "app")],
            ),
        )
    with pytest.raises(AppError):
        parse_rbac_binding(
            CLUSTERBINDINGS,
            record(CLUSTERBINDINGS, roleRef={"apiGroup": GROUP, "kind": "Role", "name": "view"}),
        )


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({}, True),
        ({"verb": "delete"}, False),
        ({"group": "apps"}, False),
        ({"resource": "secrets"}, False),
        ({"subresource": "log"}, False),
        ({"version": "v9"}, True),
    ],
)
def test_resource_rule_matches_literals_and_ignores_api_version(changes, expected):
    assert rule_matches(rule(), access(**changes)) is expected


@pytest.mark.parametrize(
    "resources,subresource,expected",
    [
        (("*",), None, True),
        (("*",), "log", True),
        (("pods/log",), "log", True),
        (("*/log",), "log", True),
        (("*/scale",), "log", False),
        (("pods/*",), "log", False),
        (("pods/*",), None, False),
        (("pods/log",), None, False),
    ],
)
def test_resource_wildcards_follow_kubernetes_subresource_rules(resources, subresource, expected):
    assert (
        rule_matches(
            rule(verbs=("*",), api_groups=("*",), resources=resources),
            access(subresource=subresource),
        )
        is expected
    )


@pytest.mark.parametrize(
    "name,expected", [(None, False), ("one", True), ("One", False), ("two", False)]
)
def test_resource_names_are_exact_and_an_unnamed_request_is_not_allowed(name, expected):
    assert rule_matches(rule(resource_names=("one",)), access(name=name)) is expected


def test_named_list_watch_selector_is_canonical_and_unfiltered_request_stays_unnamed():
    named = rule(verbs=("list", "watch"), resource_names=("one",))
    assert rule_matches(
        named, access(verb="list", query=ResourceQuery(field_selector="metadata.name==one"))
    )
    assert not rule_matches(
        named, access(verb="list", query=ResourceQuery(label_selector="metadata.name=one"))
    )
    assert not rule_matches(
        named, access(verb="watch", query=ResourceQuery(field_selector="metadata.name!=one"))
    )
    with pytest.raises(AppError):
        rule_matches(
            named,
            access(
                verb="list", name="two", query=ResourceQuery(field_selector="metadata.name=one")
            ),
        )


@pytest.mark.parametrize(
    "urls,path,expected",
    [
        (("/readyz",), "/readyz", True),
        (("/readyz",), "/readyz/verbose", False),
        (("/ready*",), "/readyz/verbose", True),
        (("/read*yz",), "/readyz", False),
        (("*",), "/anything", True),
        ((), "/healthz", False),
        (("/other*", "/healthz"), "/healthz", True),
    ],
)
def test_nonresource_urls_match_exact_or_trailing_wildcard_only(urls, path, expected):
    assert (
        rule_matches(
            rule(resources=(), api_groups=(), non_resource_urls=urls),
            NonResourceAccess("get", path),
        )
        is expected
    )


def test_namespaced_bindings_never_grant_cluster_cross_namespace_or_nonresource_requests():
    local = binding()
    assert binding_applies(local, NS)
    for scope in (ALL, CLUSTER, AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "other")):
        assert not binding_applies(local, scope)
    cluster = binding(namespace=None, role_kind="ClusterRole")
    assert all(binding_applies(cluster, scope) for scope in (NS, ALL, CLUSTER))
    assert not binding_applies(replace(cluster, role_kind="Role"), CLUSTER)
    assert not binding_applies(replace(local, ref=RbacObjectRef("Role", "view", "team", None)), NS)
    source = snapshot(
        roles=(
            role(
                rules=(
                    rule(verbs=("*",), resources=("*",)),
                    rule(verbs=("get",), resources=(), api_groups=(), non_resource_urls=("*",)),
                )
            ),
        )
    )
    assert who_can(source, access(scope=CLUSTER, resource="nodes")).grants == ()
    assert who_can(source, access(scope=ALL)).grants == ()
    assert who_can(source, NonResourceAccess("get", "/healthz")).grants == ()


def test_role_ref_resolution_uses_name_scope_and_kind_but_not_old_uid():
    original = role()
    changed_uid = replace(original, ref=replace(original.ref, uid="replacement"))
    candidates = (role("other"), role(namespace="other"), role(namespace=None), changed_uid)
    assert resolve_role(binding(), candidates) == changed_uid
    assert resolve_role(binding(role_kind="ClusterRole"), candidates) == candidates[2]
    assert resolve_role(binding(), ()) is None


def test_subject_rules_expand_only_the_exact_reviewed_identity_groups():
    source = snapshot(bindings=(binding(subjects=(ALICE, DEVELOPERS, SA)),))
    assert len(subject_grants(source, ALICE).grants) == 1
    identity = CurrentIdentity("alice", None, ("developers",))
    grants = subject_grants(source, ALICE, identity).grants
    assert [item.via_group for item in grants] == [None, "developers"]
    assert all(item.subject == ALICE for item in grants)
    assert len(subject_grants(source, ALICE, replace(identity, username="bob")).grants) == 1
    assert len(subject_grants(source, ALICE, replace(identity, groups=("other",))).grants) == 1
    group = subject_grants(source, DEVELOPERS, identity)
    assert len(group.grants) == 1 and group.grants[0].subject == DEVELOPERS
    assert not subject_grants(source, RbacSubject(RbacSubjectKind.GROUP, "other", None)).grants
    assert not subject_grants(source, RbacSubject(RbacSubjectKind.USER, "Alice", None)).grants
    assert any("external authorizers" in value for value in group.warnings)
    assert any("membership" in value for value in group.warnings)


def test_serviceaccount_username_and_namespaces_are_exact_and_current_groups_are_supplemental():
    system_user = RbacSubject(RbacSubjectKind.USER, "system:serviceaccount:team:app", None)
    source = snapshot(bindings=(binding(subjects=(SA, system_user, DEVELOPERS)),))
    identity = CurrentIdentity(system_user.name, None, ("developers",))
    grants = subject_grants(source, SA, identity).grants
    assert [grant.via_group for grant in grants] == [None, "developers"]
    assert len(subject_grants(source, system_user).grants) == 1
    assert not subject_grants(source, replace(SA, namespace="other")).grants


def test_who_can_retains_declared_groups_and_original_binding_role_provenance():
    aggregate = role(namespace=None, selectors=(selector(),), rules=(rule(),))
    source = snapshot(
        bindings=(
            binding(subjects=(ALICE, DEVELOPERS), role_kind="ClusterRole"),
            binding("global", namespace=None, subjects=(SA,), role_kind="ClusterRole"),
        ),
        roles=(aggregate,),
    )
    result = who_can(source, access())
    assert [item.subject for item in result.grants] == [ALICE, DEVELOPERS, SA]
    assert all(item.evidence == RbacEvidenceKind.MATERIALIZED for item in result.grants)
    assert result.grants[0].scope == NS and result.grants[-1].scope == CLUSTER
    assert result.grants[0].binding.uid == "view-uid" and result.grants[0].role.uid == "view-uid"
    assert all(item.rule_index == 0 and item.via_group is None for item in result.grants)
    assert not result.incomplete


def test_all_namespaces_subject_browse_retains_local_grants_without_unioning_request_permission():
    source = snapshot(
        scope=ALL,
        bindings=(binding(), binding("other", namespace="other")),
        roles=(role(), role(namespace="other")),
    )
    assert {item.scope.namespace for item in subject_grants(source, ALICE).grants} == {
        "team",
        "other",
    }
    assert who_can(source, access(scope=ALL)).grants == ()
    assert (
        subject_grants(
            replace(
                source,
                request=replace(
                    source.request, intent=AuthorizationIntent(AuthorizationMode.SUBJECTS, CLUSTER)
                ),
            ),
            ALICE,
        ).grants
        == ()
    )


def test_inferred_contributor_rules_never_replace_observed_aggregate_rules():
    aggregate = role(namespace=None, rules=(), selectors=(selector(),))
    leaf = role("leaf", namespace=None, labels=(("part", "leaf"),))
    source = snapshot(bindings=(binding(role_kind="ClusterRole"),), roles=(aggregate, leaf))
    assert aggregation_contributors(aggregate, (aggregate, leaf)).contributors == (leaf.ref,)
    assert who_can(source, access()).grants == ()


def test_partial_sources_and_missing_roles_remain_visible_even_with_zero_matches():
    sources = (
        RbacSource("roles", NS, EvidenceStatus.FORBIDDEN, None, None, "Denied", INSTANT),
        RbacSource("roles", NS, EvidenceStatus.FORBIDDEN, None, None, "Denied", INSTANT),
        RbacSource(
            "rolebindings",
            NS,
            EvidenceStatus.READY,
            CollectionState(False, True, 1, 10),
            "1",
            "Partial",
            INSTANT,
        ),
        RbacSource("accounts", NS, EvidenceStatus.READY, None, None, "Observed", INSTANT),
        RbacSource(
            "clusterroles",
            CLUSTER,
            EvidenceStatus.READY,
            CollectionState(),
            "1",
            "Observed",
            INSTANT,
        ),
    )
    result = who_can(snapshot(roles=(), sources=sources), access())
    assert result.incomplete and result.grants == ()
    assert sum("roles." in value and "source" in value for value in result.warnings) == 1
    assert any("missing" in value for value in result.warnings)
    assert subject_grants(snapshot(bindings=(binding(subjects=()),)), ALICE).grants == ()
    assert subject_grants(snapshot(bindings=()), ALICE).comparisons_used == 0
    assert who_can(snapshot(roles=(role(rules=(rule(verbs=("delete",)),)),)), access()).grants == ()


@pytest.mark.parametrize("budget", range(7))
def test_comparison_exhaustion_retains_deterministic_prefixes_and_never_overruns(budget):
    source = snapshot(bindings=(binding(), binding("second")))
    complete = subject_grants(source, ALICE)
    result = subject_grants(source, ALICE, max_comparisons=budget)
    assert result.comparisons_used <= budget
    assert result.grants == complete.grants[: len(result.grants)]
    assert result.incomplete and any("comparison budget" in value for value in result.warnings)


@pytest.mark.parametrize("limit", [0, 1, 2])
def test_result_budget_retains_only_real_grant_prefix_and_reports_exhaustion(limit):
    source = snapshot(roles=(role(rules=(rule(), rule(), rule())),))
    result = subject_grants(source, ALICE, max_results=limit)
    assert len(result.grants) == limit and result.incomplete
    assert any("result budget" in value for value in result.warnings)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_comparisons": -1},
        {"max_comparisons": True},
        {"max_results": -1},
        {"max_results": False},
    ],
)
def test_invalid_budget_configuration_is_rejected(changes):
    with pytest.raises(AppError):
        subject_grants(snapshot(), ALICE, **changes)


def test_callers_cannot_raise_global_comparison_and_result_caps():
    source = snapshot(roles=(role(rules=(rule(),) * 1025),))
    result = subject_grants(source, ALICE, max_results=999999)
    assert len(result.grants) == 1024 and result.incomplete
    many = snapshot(
        bindings=(binding(),) * 101, roles=tuple(role(str(index)) for index in range(1000))
    )
    limited = who_can(many, access(), max_comparisons=999999)
    assert limited.comparisons_used == 100000 and limited.incomplete


def test_aggregation_explanations_walk_transitively_deduplicate_and_skip_namespaced_roles():
    root = role("root", namespace=None, selectors=(selector("part", "middle", "leaf"),))
    middle = role("middle", namespace=None, labels=(("part", "middle"),), selectors=(selector(),))
    leaf = role("leaf", namespace=None, labels=(("part", "leaf"),))
    unrelated = role("other", namespace=None, labels=(("part", "other"),))
    result = aggregation_contributors(root, (role(), root, middle, leaf, unrelated))
    assert result.contributors == (middle.ref, leaf.ref)
    assert not result.incomplete and result.comparisons_used > 0
    assert aggregation_contributors(leaf, (root, middle, leaf)).comparisons_used == 0
    assert aggregation_contributors(root, ()).contributors == ()


def test_aggregation_cycles_and_invalid_selectors_do_not_replace_materialized_rules():
    root = role("root", namespace=None, labels=(("part", "leaf"),), selectors=(selector(),))
    cyclic = aggregation_contributors(root, (root,))
    assert cyclic.incomplete and cyclic.contributors == ()
    assert any("cycle" in value for value in cyclic.warnings)
    bad = replace(
        root,
        aggregation_selectors=(
            RelationshipSelector((LabelRequirement("part", "Unknown", ()),)),
            selector(),
        ),
    )
    invalid = aggregation_contributors(bad, (root,))
    assert invalid.incomplete and any("Invalid" in value for value in invalid.warnings)
    assert any("cycle" in value for value in invalid.warnings)


@pytest.mark.parametrize("comparisons", range(5))
def test_aggregation_budget_charges_selectors_and_traversal_edges_before_work(comparisons):
    root = role("root", namespace=None, selectors=(selector(),))
    leaf = role("leaf", namespace=None, labels=(("part", "leaf"),))
    result = aggregation_contributors(root, (root, leaf), max_comparisons=comparisons)
    assert result.comparisons_used <= comparisons
    if comparisons < 3:
        assert result.incomplete and result.contributors == ()
    else:
        assert result.contributors == (leaf.ref,) and not result.incomplete


def test_aggregation_results_and_depth_are_bounded_with_retained_prefixes():
    root = role("root", namespace=None, selectors=(selector(),))
    leaves = tuple(
        role(str(index), namespace=None, labels=(("part", "leaf"),)) for index in range(2)
    )
    result = aggregation_contributors(root, leaves, max_results=1)
    assert result.incomplete and result.contributors == (leaves[0].ref,)
    assert aggregation_contributors(root, leaves, max_results=0).contributors == ()
    chain = tuple(
        role(
            str(index),
            namespace=None,
            labels=(("part", str(index)),),
            selectors=(selector("part", str(index + 1)),),
        )
        for index in range(10)
    )
    deep = aggregation_contributors(chain[0], chain)
    assert deep.incomplete and len(deep.contributors) == 8
    assert any("depth" in value for value in deep.warnings)


def test_resource_record_cannot_be_relabelled_as_a_different_rbac_api_family():
    with pytest.raises(AppError):
        parse_rbac_role(ROLES, record(BINDINGS))
    with pytest.raises(AppError):
        parse_rbac_role(replace(ROLES, version="v2"), record(ROLES))


def test_nested_aggregation_budget_exhaustion_propagates_with_retained_contributor():
    root = role("root", namespace=None, selectors=(selector("part", "middle"),))
    middle = role("middle", namespace=None, labels=(("part", "middle"),), selectors=(selector(),))
    leaf = role("leaf", namespace=None, labels=(("part", "leaf"),))
    result = aggregation_contributors(root, (root, middle, leaf), max_comparisons=3)
    assert result.incomplete and result.contributors == (middle.ref,)
    assert result.comparisons_used == 3
    assert any("comparison budget" in value for value in result.warnings)


def test_named_list_matching_revalidates_question_and_limits_its_http_claim():
    source = snapshot(roles=(role(rules=(rule(verbs=("list",), resource_names=("one",)),)),))
    result = who_can(source, access(verb="list", name="one"))
    assert len(result.grants) == 1
    assert any("unfiltered" in value for value in result.warnings)
    unnamed = who_can(source, access(verb="list"))
    assert not unnamed.grants and not any("unfiltered" in value for value in unnamed.warnings)
    with pytest.raises(AppError):
        rule_matches(
            rule(),
            access(
                verb="list", name="one", query=ResourceQuery(field_selector="metadata.name=other")
            ),
        )


@pytest.mark.parametrize("selected_kind", [RbacSubjectKind.SERVICE_ACCOUNT, RbacSubjectKind.USER])
def test_equivalent_subject_declarations_produce_unique_grant_row_keys(selected_kind):
    canonical_user = RbacSubject(RbacSubjectKind.USER, "system:serviceaccount:team:app", None)
    selected = SA if selected_kind is RbacSubjectKind.SERVICE_ACCOUNT else canonical_user
    operators = RbacSubject(RbacSubjectKind.GROUP, "operators", None)
    declarations = (SA, canonical_user, SA, DEVELOPERS, DEVELOPERS, operators)
    source = snapshot(bindings=(binding(subjects=declarations),))
    request = replace(
        source.request, intent=AuthorizationIntent(AuthorizationMode.SUBJECT, NS, subject=selected)
    )
    source = replace(source, request=request)
    identity = CurrentIdentity(canonical_user.name, None, ("developers", "operators"))
    result = subject_grants(source, selected, identity)
    analysis = RbacAnalysis(
        result.grants, (), result.incomplete, result.warnings, result.comparisons_used
    )
    publication = AuthorizationSnapshot(request, source, analysis, None, None, None, False)
    rows = authorization_rows(publication)
    grant_keys = [row.key for row in rows if row.key.startswith("grant:")]
    assert len(grant_keys) == len(set(grant_keys)), (
        "Equivalent declarations generated duplicate native row keys."
    )
    assert [grant.via_group for grant in result.grants] == [None, "developers", "operators"]
    assert len(grant_keys) == 3 and not result.incomplete


@pytest.mark.parametrize("max_results", [2, 3])
def test_duplicate_subjects_consume_comparisons_but_only_unique_grant_slots(max_results):
    canonical_user = RbacSubject(RbacSubjectKind.USER, "system:serviceaccount:team:app", None)
    operators = RbacSubject(RbacSubjectKind.GROUP, "operators", None)
    declarations = (SA, canonical_user, SA, DEVELOPERS, DEVELOPERS, operators)
    source = snapshot(bindings=(binding(subjects=declarations),))
    identity = CurrentIdentity(canonical_user.name, None, ("developers", "operators"))
    result = subject_grants(source, SA, identity, max_results=max_results)
    assert [grant.via_group for grant in result.grants] == [None, "developers", "operators"][
        :max_results
    ]
    assert result.comparisons_used == 1 + len(declarations) + 1 + 1
    assert result.incomplete is (max_results < 3)
    assert any("result budget" in warning for warning in result.warnings) is (max_results < 3)


def test_who_can_keeps_declared_user_serviceaccount_aliases_and_unique_group_subjects():
    canonical_user = RbacSubject(RbacSubjectKind.USER, "system:serviceaccount:team:app", None)
    source = snapshot(
        bindings=(binding(subjects=(SA, canonical_user, SA, DEVELOPERS, DEVELOPERS)),)
    )
    result = who_can(source, access(), max_results=3)
    assert [grant.subject for grant in result.grants] == [SA, canonical_user, DEVELOPERS]
    assert not result.incomplete and all(grant.via_group is None for grant in result.grants)


def test_equivalent_subject_deduplication_preserves_binding_scope_and_rule_provenance():
    canonical_user = RbacSubject(RbacSubjectKind.USER, "system:serviceaccount:team:app", None)
    declarations = (SA, canonical_user)
    source = snapshot(
        scope=ALL,
        bindings=(
            binding(subjects=declarations),
            binding("second", subjects=declarations),
            binding(namespace="other", subjects=declarations),
        ),
        roles=(role(rules=(rule(), rule())), role(namespace="other", rules=(rule(), rule()))),
    )
    result = subject_grants(source, SA, max_results=6)
    assert [
        (grant.binding.name, grant.scope.namespace, grant.rule_index) for grant in result.grants
    ] == [
        ("view", "team", 0),
        ("view", "team", 1),
        ("second", "team", 0),
        ("second", "team", 1),
        ("view", "other", 0),
        ("view", "other", 1),
    ]
    assert len(set(result.grants)) == 6 and not result.incomplete
