"""Bounded literal authorization rows preserve evidence limits and navigation identity."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

import kuberich.domain.authorization as a
from kuberich.domain.authorization_rows import (
    MAX_AUTHORIZATION_ROWS,
    authorization_rows,
    scope_label,
)
from kuberich.domain.relationships import RelationshipSelector
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.resources import CollectionState
from kuberich.domain.targets import SessionIdentity

NOW = datetime(2026, 11, 5, tzinfo=UTC)
SCOPE = a.AuthorizationScope(a.AuthorizationScopeKind.NAMESPACE, "team")
USER = a.RbacSubject(a.RbacSubjectKind.USER, "Alice", None)
GROUP = a.RbacSubject(a.RbacSubjectKind.GROUP, "Operators", None)
ACCOUNT = a.RbacSubject(a.RbacSubjectKind.SERVICE_ACCOUNT, "runner", "identity")
ROLE = a.RbacObjectRef("Role", "reader", "team", "role-uid")
CLUSTER_ROLE = a.RbacObjectRef("ClusterRole", "aggregate", None, "cluster-role-uid")
BINDING = a.RbacObjectRef("RoleBinding", "readers", "team", "binding-uid")
RULE = a.RbacRule(("get", "list"), ("",), ("pods",), (), ())


def observed(mode=a.AuthorizationMode.SUBJECTS, *, selected=None, access=None, complete=True):
    intent = a.AuthorizationIntent(
        mode, SCOPE, **({selected[0]: selected[1]} if selected else {}), access=access
    )
    request = a.AuthorizationRequest(SessionIdentity("owned", 0), 1, intent)
    roles = (
        a.RbacRole(ROLE, (RULE,), (), ()),
        a.RbacRole(
            CLUSTER_ROLE,
            (a.RbacRule(("*",), ("apps",), ("deployments/scale",), ("example",), ("/healthz*",)),),
            (),
            (RelationshipSelector(()),),
        ),
    )
    bindings = (a.RbacBinding(BINDING, (USER, GROUP, ACCOUNT), "Role", ROLE.name),)
    sources = (
        a.RbacSource(
            "roles",
            SCOPE,
            a.EvidenceStatus.READY,
            CollectionState() if complete else CollectionState(complete=False, limited=True),
            "7",
            "source declaration",
            NOW,
        ),
        a.RbacSource(
            "clusterroles",
            a.AuthorizationScope(a.AuthorizationScopeKind.CLUSTER, None),
            a.EvidenceStatus.FORBIDDEN,
            None,
            None,
            "Denied",
            None,
        ),
    )
    rbac = a.RbacSnapshot(
        request,
        (a.RbacSubjectEvidence(USER, (BINDING,)), a.RbacSubjectEvidence(ACCOUNT, ())),
        bindings,
        roles,
        sources,
        3,
        NOW,
    )
    grant = a.RbacGrant(USER, BINDING, ROLE, 0, SCOPE, a.RbacEvidenceKind.DECLARED, None)
    aggregate = a.RbacAggregation(
        CLUSTER_ROLE, (ROLE, replace(ROLE, uid=None)), not complete, ("aggregation warning",), 2
    )
    analysis = a.RbacAnalysis((grant,), (aggregate,), not complete, ("analysis warning",), 3)
    return a.AuthorizationSnapshot(request, rbac, analysis, None, None, None, False)


@pytest.mark.parametrize(
    "scope,label",
    [
        (SCOPE, "namespace team"),
        (a.AuthorizationScope(a.AuthorizationScopeKind.ALL_NAMESPACES, None), "all namespaces"),
        (a.AuthorizationScope(a.AuthorizationScopeKind.CLUSTER, None), "cluster"),
    ],
)
def test_scope_labels_do_not_confuse_namespace_and_cluster_requests(scope, label):
    assert scope_label(scope) == label


def test_loading_and_completed_empty_snapshots_stay_informational():
    assert authorization_rows(None)[0].status == "loading"
    snapshot = observed()
    empty = replace(snapshot, rbac=None, analysis=None, collecting=True)
    rows = authorization_rows(empty)
    assert len(rows) == 1 and rows[0].status == "loading"
    assert rows[0].destination is rows[0].object_ref is None
    assert authorization_rows(replace(empty, collecting=False))[0].status == "observed evidence"


def test_subject_rows_keep_observed_origins_and_actual_serviceaccount_namespace():
    rows = authorization_rows(observed())
    subjects = [row for row in rows if row.key.startswith("subject:")]
    assert subjects[0].destination.subject == USER
    assert "origin: RoleBinding/readers" in subjects[0].details[0]
    assert "identity/runner" in subjects[1].label
    assert "no binding membership" in subjects[1].details[0]
    assert all(row.object_ref is None for row in subjects)
    sources = [row for row in rows if row.key.startswith("source:")]
    assert sources[0].status == "ready" and "complete collection" in sources[0].details
    assert "observed: unavailable" in sources[1].details


def test_subject_browsing_without_analysis_still_exposes_subjects_and_denied_sources():
    rows = authorization_rows(replace(observed(), analysis=None))
    assert any(row.destination is not None and row.destination.subject == USER for row in rows)
    assert any(row.status == "forbidden" and row.key.startswith("source:") for row in rows)
    assert not any(row.key.startswith("contributor:") for row in rows)


@pytest.mark.parametrize("mode", [a.AuthorizationMode.BINDINGS, a.AuthorizationMode.BINDING])
def test_binding_drilldowns_follow_observed_subjects_and_resolved_role(mode):
    snapshot = observed(
        mode, selected=("binding", BINDING) if mode is a.AuthorizationMode.BINDING else None
    )
    rows = authorization_rows(snapshot)
    binding = next(row for row in rows if row.object_ref == BINDING)
    assert (
        binding.destination is None
        if mode is a.AuthorizationMode.BINDING
        else binding.destination.binding == BINDING
    )
    if mode is a.AuthorizationMode.BINDING:
        role = next(row for row in rows if row.object_ref == ROLE)
        assert role.destination.role == ROLE
        assert {row.destination.subject for row in rows if row.key.startswith("subject:")} == {
            USER,
            GROUP,
            ACCOUNT,
        }


@pytest.mark.parametrize("kind", ["RoleBinding", "ClusterRoleBinding"])
def test_binding_repeated_subjects_keep_one_row_per_full_identity_in_declaration_order(kind):
    binding_ref = replace(BINDING, kind=kind, namespace="team" if kind == "RoleBinding" else None)
    snapshot = observed(a.AuthorizationMode.BINDING, selected=("binding", binding_ref))
    distinct = (
        USER,
        GROUP,
        ACCOUNT,
        replace(USER, kind=a.RbacSubjectKind.GROUP),
        replace(ACCOUNT, namespace="other"),
    )
    declarations = (
        USER,
        replace(USER),
        GROUP,
        ACCOUNT,
        replace(GROUP),
        distinct[3],
        replace(ACCOUNT),
        distinct[4],
    )
    binding = replace(
        snapshot.rbac.bindings[0],
        ref=binding_ref,
        subjects=declarations,
        role_kind="Role" if kind == "RoleBinding" else "ClusterRole",
        role_name=ROLE.name if kind == "RoleBinding" else CLUSTER_ROLE.name,
    )
    snapshot = replace(snapshot, rbac=replace(snapshot.rbac, bindings=(binding,)))

    rows = authorization_rows(snapshot)
    subjects = tuple(row for row in rows if row.key.startswith("subject:"))
    assert tuple(row.destination.subject for row in subjects) == distinct
    assert len({row.key for row in rows}) == len(rows)
    assert all(row.object_ref is None and row.destination.scope == SCOPE for row in subjects)
    assert subjects[0].label == "User Alice" and subjects[3].label == "Group Alice"
    assert subjects[2].label == "ServiceAccount identity/runner"
    assert subjects[4].label == "ServiceAccount other/runner"
    assert snapshot.rbac.bindings[0].subjects == declarations


def test_repeated_role_rule_declarations_keep_distinct_rule_indices():
    snapshot = observed(a.AuthorizationMode.ROLE, selected=("role", ROLE))
    role = replace(snapshot.rbac.roles[0], rules=(RULE, RULE))
    snapshot = replace(snapshot, rbac=replace(snapshot.rbac, roles=(role,)))
    rules = tuple(row for row in authorization_rows(snapshot) if row.key.startswith("rule:"))
    assert len(rules) == 2 and rules[0].key != rules[1].key
    assert rules[0].details == rules[1].details
    assert rules[0].label.startswith("Rule 1") and rules[1].label.startswith("Rule 2")


@pytest.mark.parametrize("kind", ["Role", "ClusterRole"])
def test_binding_missing_role_stays_navigable_evidence_without_an_object_target(kind):
    snapshot = observed(a.AuthorizationMode.BINDING, selected=("binding", BINDING))
    binding = replace(snapshot.rbac.bindings[0], role_kind=kind, role_name="gone")
    snapshot = replace(snapshot, rbac=replace(snapshot.rbac, bindings=(binding,)))
    row = next(row for row in authorization_rows(snapshot) if row.label.startswith(kind + "/gone"))
    assert row.object_ref is None and row.destination.role.uid is None
    assert row.destination.role.namespace == ("team" if kind == "Role" else None)


def test_binding_resolves_a_cluster_role_without_importing_its_namespace():
    snapshot = observed(a.AuthorizationMode.BINDING, selected=("binding", BINDING))
    snapshot = replace(
        snapshot,
        rbac=replace(
            snapshot.rbac,
            bindings=(
                replace(
                    snapshot.rbac.bindings[0], role_kind="ClusterRole", role_name=CLUSTER_ROLE.name
                ),
            ),
        ),
    )
    assert any(
        row.destination is not None and row.destination.role == CLUSTER_ROLE
        for row in authorization_rows(snapshot)
    )


@pytest.mark.parametrize("selected", [ROLE, CLUSTER_ROLE, replace(ROLE, name="gone")])
def test_role_rules_show_observed_materialized_or_declared_provenance(selected):
    rows = authorization_rows(observed(a.AuthorizationMode.ROLE, selected=("role", selected)))
    rules = [row for row in rows if row.key.startswith("rule:")]
    if selected.name == "gone":
        assert not rules
        assert any(row.key == "summary:missing" and row.object_ref is None for row in rows)
    else:
        assert rules and rules[0].object_ref == selected
        assert rules[0].status == ("materialized" if selected.kind == "ClusterRole" else "declared")
        assert any("resource names:" in line for line in rules[0].details)


def test_roles_browse_does_not_replace_materialized_aggregate_rules_with_contributors():
    rows = authorization_rows(observed(a.AuthorizationMode.ROLES))
    roles = [row for row in rows if row.key.startswith("role:")]
    assert len(roles) == 2 and all(
        row.destination.mode is a.AuthorizationMode.ROLE for row in roles
    )
    contributors = [row for row in rows if row.key.startswith("contributor:")]
    assert contributors and all(row.status == "inferred explanation" for row in contributors)
    assert contributors[1].object_ref is None


@pytest.mark.parametrize("mode", [a.AuthorizationMode.SUBJECT, a.AuthorizationMode.WHO_CAN])
def test_grants_are_candidates_with_exact_navigation_and_explicit_authorizer_limits(mode):
    access = (
        a.ResourceAccess("get", "", "v1", "pods", None, None, SCOPE, ResourceQuery())
        if mode is a.AuthorizationMode.WHO_CAN
        else None
    )
    snapshot = observed(
        mode,
        selected=("subject", USER) if mode is a.AuthorizationMode.SUBJECT else None,
        access=access,
        complete=False,
    )
    grant = replace(snapshot.analysis.grants[0], via_group="Operators")
    snapshot = replace(snapshot, analysis=replace(snapshot.analysis, grants=(grant,)))
    rows = authorization_rows(snapshot)
    candidate = next(row for row in rows if row.key.startswith("grant:"))
    assert candidate.status == "RBAC candidate · declared"
    assert "via group: Operators" in candidate.details
    assert candidate.destination.mode is (
        a.AuthorizationMode.BINDING
        if mode is a.AuthorizationMode.SUBJECT
        else a.AuthorizationMode.SUBJECT
    )
    warning = " ".join(
        line for row in rows if row.key.startswith("warning:") for line in row.details
    )
    assert "INCOMPLETE analysis" in warning and "aggregation warning" in warning
    assert "INCOMPLETE aggregate" in warning
    assert (
        ("external authorizers" in warning)
        if mode is a.AuthorizationMode.WHO_CAN
        else ("effective authorization" in warning)
    )


@pytest.mark.parametrize("nonresource", [False, True])
def test_reviews_keep_authoritative_decisions_and_all_warnings_visible(nonresource):
    access = (
        a.NonResourceAccess("get", "/healthz")
        if nonresource
        else a.ResourceAccess(
            "list", "apps", "v1", "deployments", "scale", "example", SCOPE, ResourceQuery()
        )
    )
    scope = a.AuthorizationScope(a.AuthorizationScopeKind.CLUSTER, None) if nonresource else SCOPE
    request = a.AuthorizationRequest(
        SessionIdentity("owned", 0),
        1,
        a.AuthorizationIntent(a.AuthorizationMode.REVIEW, scope, access=access),
    )
    review = a.AccessReview(
        request,
        a.ReviewDecision.ALLOWED,
        a.EvidenceStatus.READY,
        "Server allowed this exact question",
        ("named list is hypothetical without equality",),
        NOW,
    )
    identity = a.IdentityReview(
        request,
        a.CurrentIdentity("Alice", None, ("Operators",)),
        a.EvidenceStatus.READY,
        ("identity warning",),
        NOW,
    )
    rows = authorization_rows(
        a.AuthorizationSnapshot(request, None, None, identity, review, None, False)
    )
    decision = next(row for row in rows if row.key == "review:decision")
    assert decision.status == "allowed · ready" and decision.object_ref is None
    assert "Server allowed" in decision.details[0]
    assert any("hypothetical" in line for row in rows for line in row.details)
    assert any(row.label == "Alice" and "groups: Operators" in row.details for row in rows)


@pytest.mark.parametrize("incomplete", [False, True])
def test_self_rules_and_missing_identity_never_turn_absent_rules_into_denial(incomplete):
    snapshot = observed(a.AuthorizationMode.SELF_RULES)
    rules = a.RulesReview(
        snapshot.request, (RULE,), incomplete, a.EvidenceStatus.READY, ("rules warning",), NOW
    )
    identity = a.IdentityReview(snapshot.request, None, a.EvidenceStatus.FORBIDDEN, (), NOW)
    rows = authorization_rows(
        replace(snapshot, rbac=None, analysis=None, identity=identity, rules=rules)
    )
    assert any(row.label == "Current identity unavailable" for row in rows)
    assert any(row.key == "review:rules" and "denial" in " ".join(row.details) for row in rows)
    assert any(row.key.startswith("rule:") for row in rows)


def test_current_binding_selection_does_not_show_other_bindings_or_reuse_a_missing_target():
    snapshot = observed(
        a.AuthorizationMode.BINDING, selected=("binding", replace(BINDING, name="gone"))
    )
    rows = authorization_rows(snapshot)
    assert not any(row.key.startswith("binding:") for row in rows)
    assert any(row.key == "summary:missing" and row.object_ref is None for row in rows)


@pytest.mark.parametrize(
    "mode,field,ref",
    [
        (a.AuthorizationMode.ROLE, "role", ROLE),
        (a.AuthorizationMode.BINDING, "binding", BINDING),
    ],
)
def test_detail_selection_pins_known_uid_but_unresolved_role_references_resolve_by_name(
    mode, field, ref
):
    analysis = a.RbacAnalysis((), (), False, (), 0) if mode is a.AuthorizationMode.ROLE else None
    replaced = replace(
        observed(mode, selected=(field, replace(ref, uid="prior-object-uid"))), analysis=analysis
    )
    rows = authorization_rows(replaced)
    assert any(row.key == "summary:missing" for row in rows)
    assert not any(row.object_ref == ref for row in rows)
    unresolved = replace(
        observed(mode, selected=(field, replace(ref, uid=None))), analysis=analysis
    )
    rows = authorization_rows(unresolved)
    assert any(row.object_ref == ref for row in rows)
    assert not any(row.key == "summary:missing" for row in rows)


@pytest.mark.parametrize(
    "mode", [a.AuthorizationMode.SUBJECTS, a.AuthorizationMode.ROLE, a.AuthorizationMode.SELF_RULES]
)
def test_display_budget_is_bounded_during_appends_and_rule_expansion_and_keeps_warning(mode):
    snapshot = observed(mode, selected=("role", ROLE) if mode is a.AuthorizationMode.ROLE else None)
    if mode is a.AuthorizationMode.SUBJECTS:
        subjects = tuple(
            a.RbacSubjectEvidence(a.RbacSubject(a.RbacSubjectKind.USER, f"user-{index}", None), ())
            for index in range(MAX_AUTHORIZATION_ROWS + 1)
        )
        snapshot = replace(snapshot, rbac=replace(snapshot.rbac, subjects=subjects))
    elif mode is a.AuthorizationMode.ROLE:
        role = replace(snapshot.rbac.roles[0], rules=(RULE,) * (MAX_AUTHORIZATION_ROWS + 1))
        snapshot = replace(snapshot, rbac=replace(snapshot.rbac, roles=(role,)))
    else:
        rules = a.RulesReview(
            snapshot.request,
            (RULE,) * MAX_AUTHORIZATION_ROWS,
            True,
            a.EvidenceStatus.READY,
            tuple(f"warning-{index}" for index in range(20)),
            NOW,
        )
        snapshot = replace(snapshot, rules=rules)
    rows = authorization_rows(snapshot)
    assert len(rows) == MAX_AUTHORIZATION_ROWS
    assert rows[-1].key == "summary:truncated" and rows[-1].object_ref is None
    assert any(row.key.startswith("source:") for row in rows)


def test_stable_keys_distinguish_recreated_roles_and_subject_case():
    snapshot = observed(a.AuthorizationMode.ROLES)
    first = authorization_rows(snapshot)
    assert first == authorization_rows(snapshot)
    changed = replace(
        snapshot,
        rbac=replace(
            snapshot.rbac,
            roles=(replace(snapshot.rbac.roles[0], ref=replace(ROLE, uid="replacement")),),
        ),
    )
    before = next(row.key for row in first if row.object_ref == ROLE)
    assert all(row.key != before for row in authorization_rows(changed))
