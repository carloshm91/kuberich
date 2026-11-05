"""Exact authorization questions, immutable evidence and fail-closed server decisions."""

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.authorization import (
    AccessReview,
    AuthorizationIntent,
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
    RbacObjectRef,
    RbacSnapshot,
    RbacSubject,
    RbacSubjectKind,
    ResourceAccess,
    ReviewDecision,
    RulesReview,
    canonical_resource_access,
    classify_access_review,
    rescope_intent,
)
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError

NS = AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "team")
ALL = AuthorizationScope(AuthorizationScopeKind.ALL_NAMESPACES, None)
CLUSTER = AuthorizationScope(AuthorizationScopeKind.CLUSTER, None)
USER = RbacSubject(RbacSubjectKind.USER, "alice", None)
INSTANT = datetime(2026, 11, 5, tzinfo=UTC)


def access(**changes):
    return replace(
        ResourceAccess("get", "", "v1", "pods", None, None, NS, ResourceQuery()), **changes
    )


def request(**changes):
    return AuthorizationRequest(
        SessionIdentity("synthetic", 1),
        1,
        AuthorizationIntent(AuthorizationMode.REVIEW, NS, access=access(**changes)),
    )


def test_publications_are_immutable_and_request_retains_exact_identity():
    question = request()
    identity = IdentityReview(
        question,
        CurrentIdentity("alice", "subject-uid", ("developers",)),
        EvidenceStatus.READY,
        (),
        INSTANT,
    )
    review = AccessReview(
        question,
        ReviewDecision.NO_ALLOW,
        EvidenceStatus.READY,
        "No authorizer allowed this request",
        (),
        INSTANT,
    )
    rules = RulesReview(question, (), True, EvidenceStatus.READY, ("Incomplete",), INSTANT)
    rbac = RbacSnapshot(question, (), (), (), (), 0, INSTANT)
    analysis = RbacAnalysis((), (), False, (), 0)
    snapshot = AuthorizationSnapshot(question, rbac, analysis, identity, review, rules, False)
    assert snapshot.identity.identity.groups == ("developers",)
    assert snapshot.review.decision == ReviewDecision.NO_ALLOW
    assert snapshot.rules.incomplete and snapshot.rbac.request == question
    assert not snapshot.collecting and not hasattr(snapshot, "__dict__")
    with pytest.raises(FrozenInstanceError):
        snapshot.review = None


@pytest.mark.parametrize(
    "kind,namespace",
    [
        ("namespace", "team"),
        (AuthorizationScopeKind.NAMESPACE, None),
        (AuthorizationScopeKind.NAMESPACE, 2),
        (AuthorizationScopeKind.NAMESPACE, "INVALID"),
        (AuthorizationScopeKind.CLUSTER, "team"),
        (AuthorizationScopeKind.ALL_NAMESPACES, "team"),
    ],
)
def test_scope_requires_a_namespace_only_for_namespace_scope(kind, namespace):
    with pytest.raises(AppError):
        AuthorizationScope(kind, namespace)


@pytest.mark.parametrize(
    "changes",
    [
        {"verb": "GET"},
        {"verb": 1},
        {"group": "bad/group"},
        {"version": "bad/version"},
        {"resource": "pods/log"},
        {"subresource": "bad/path"},
        {"name": "../bad"},
        {"scope": "team"},
        {"query": {}},
    ],
)
def test_resource_questions_reject_unsafe_or_unvalidated_components(changes):
    with pytest.raises(AppError):
        access(**changes)


def test_resource_question_keeps_discovered_group_version_and_subresource():
    item = access(
        group="apps",
        version="v1beta1",
        resource="deployments",
        subresource="scale",
        name="example",
        verb="patch",
    )
    assert item.group == "apps" and item.version == "v1beta1" and item.name == "example"
    assert access(verb="*").verb == "*"


@pytest.mark.parametrize(
    "path", ["healthz", "/healthz?token=x", "/healthz#fragment", "", "/healthz\x1b[31m"]
)
def test_nonresource_questions_require_literal_absolute_paths(path):
    with pytest.raises(AppError):
        NonResourceAccess("get", path)


def test_nonresource_literal_path_keeps_its_case():
    assert NonResourceAccess("get", "/Readyz").path == "/Readyz"


@pytest.mark.parametrize(
    "kind,name,namespace",
    [
        ("User", "alice", None),
        (RbacSubjectKind.SERVICE_ACCOUNT, "app", None),
        (RbacSubjectKind.SERVICE_ACCOUNT, "bad/path", "team"),
        (RbacSubjectKind.SERVICE_ACCOUNT, "app", "INVALID"),
        (RbacSubjectKind.USER, "alice", "team"),
        (RbacSubjectKind.GROUP, "developers", "team"),
        (RbacSubjectKind.USER, "", None),
    ],
)
def test_subject_identity_is_validated_without_inventing_namespaces(kind, name, namespace):
    with pytest.raises(AppError):
        RbacSubject(kind, name, namespace)


def test_subject_identity_preserves_case_and_serviceaccount_scope():
    assert RbacSubject(RbacSubjectKind.USER, "Alice", None) != USER
    assert RbacSubject(RbacSubjectKind.GROUP, "Team", None).name == "Team"
    assert RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "app", "team").namespace == "team"


@pytest.mark.parametrize(
    "kind,namespace",
    [
        ("Secret", None),
        ("Role", None),
        ("RoleBinding", 1),
        ("ClusterRole", "team"),
        ("ClusterRoleBinding", "team"),
    ],
)
def test_object_refs_require_the_actual_rbac_kind_and_scope(kind, namespace):
    with pytest.raises(AppError):
        RbacObjectRef(kind, "example", namespace, None)


def test_object_refs_pin_optional_uid_but_names_can_include_system_colons():
    assert RbacObjectRef("ClusterRole", "system:view", None, "uid").uid == "uid"
    assert RbacObjectRef("RoleBinding", "view", "team", None).namespace == "team"
    with pytest.raises(AppError):
        RbacObjectRef("Role", "bad/path", "team", None)


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "subjects"},
        {"scope": "team"},
        {"mode": AuthorizationMode.SUBJECT},
        {"mode": AuthorizationMode.SUBJECTS, "subject": USER},
        {"mode": AuthorizationMode.SUBJECT, "subject": "alice"},
        {"mode": AuthorizationMode.BINDING, "binding": RbacObjectRef("Role", "view", "team", None)},
        {"mode": AuthorizationMode.ROLE, "role": "view"},
        {"mode": AuthorizationMode.REVIEW, "access": {}},
        {"mode": AuthorizationMode.SELF_RULES, "scope": ALL},
    ],
)
def test_mode_selection_combinations_fail_before_collection(changes):
    fields = {"mode": AuthorizationMode.SUBJECTS, "scope": NS, **changes}
    with pytest.raises(AppError):
        AuthorizationIntent(**fields)


def test_modes_require_their_own_selection_and_exact_question_scope():
    role = RbacObjectRef("ClusterRole", "view", None, "uid")
    binding = RbacObjectRef("RoleBinding", "view", "team", "uid")
    assert AuthorizationIntent(AuthorizationMode.ROLE, NS, role=role).role == role
    assert AuthorizationIntent(AuthorizationMode.BINDING, NS, binding=binding).binding == binding
    assert AuthorizationIntent(AuthorizationMode.SELF_RULES, NS).scope == NS
    with pytest.raises(AppError, match="Non-resource"):
        AuthorizationIntent(
            AuthorizationMode.REVIEW, NS, access=NonResourceAccess("get", "/healthz")
        )
    with pytest.raises(AppError, match="scopes"):
        AuthorizationIntent(AuthorizationMode.WHO_CAN, ALL, access=access())


@pytest.mark.parametrize(
    "changes", [{"session": None}, {"revision": True}, {"revision": -1}, {"intent": {}}]
)
def test_request_requires_owned_session_revision_and_validated_intent(changes):
    with pytest.raises(AppError):
        replace(request(), **changes)


@pytest.mark.parametrize("verb", ["list", "watch"])
@pytest.mark.parametrize(
    "selector,name,expected",
    [
        ("metadata.name=example", None, "example"),
        ("metadata.name==example,metadata.name=example", None, "example"),
        ("metadata.name=example,status.phase!=Pending", "example", "example"),
        ("metadata.name=", None, None),
        ("metadata.name!=other", "explicit", "explicit"),
        ("status.phase=Running", None, None),
    ],
)
def test_canonical_name_uses_only_unambiguous_actual_field_equality(verb, selector, name, expected):
    query = ResourceQuery("app=api", selector)
    value = access(verb=verb, name=name, query=query)
    canonical = canonical_resource_access(value)
    assert canonical.name == expected and canonical.query == query
    assert canonical.query.field_selector == selector
    assert canonical_resource_access(canonical) == canonical
    assert request(verb=verb, name=name, query=query).intent.access == canonical


@pytest.mark.parametrize(
    "selector,name",
    [
        ("metadata.name=one,metadata.name=two", None),
        ("metadata.name=one", "two"),
        ("metadata.name=", "one"),
    ],
)
def test_conflicting_selector_or_explicit_names_cannot_bind_a_review(selector, name):
    value = access(verb="list", name=name, query=ResourceQuery(field_selector=selector))
    with pytest.raises(AppError, match=r"[Cc]onflict"):
        canonical_resource_access(value)
    with pytest.raises(AppError):
        request(verb="list", name=name, query=value.query)


@pytest.mark.parametrize("verb", ["get", "create", "delete", "deletecollection", "patch"])
def test_other_verbs_never_derive_or_override_name_from_selectors(verb):
    value = access(
        verb=verb, name="explicit", query=ResourceQuery(field_selector="metadata.name=other")
    )
    assert canonical_resource_access(value) is value
    assert canonical_resource_access(access(verb="list", name="explicit")).name == "explicit"


def test_rescope_namespaced_questions_and_browsing_without_changing_subject_identity():
    intent = request().intent
    changed = rescope_intent(intent, "other")
    assert changed.scope.namespace == changed.access.scope.namespace == "other"
    assert rescope_intent(changed, None).access.scope == ALL
    sa = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "app", "team")
    subject = rescope_intent(
        AuthorizationIntent(AuthorizationMode.SUBJECT, NS, subject=sa), "other"
    )
    assert subject.scope.namespace == "other" and subject.subject == sa
    assert (
        rescope_intent(AuthorizationIntent(AuthorizationMode.SELF_RULES, NS), None).mode
        == AuthorizationMode.SUBJECTS
    )
    assert (
        rescope_intent(
            AuthorizationIntent(AuthorizationMode.SELF_RULES, NS), "other"
        ).scope.namespace
        == "other"
    )


@pytest.mark.parametrize("mode", [AuthorizationMode.REVIEW, AuthorizationMode.WHO_CAN])
def test_explicit_header_changes_preserve_cluster_and_nonresource_questions(mode):
    for question in (access(resource="nodes", scope=CLUSTER), NonResourceAccess("get", "/readyz")):
        intent = AuthorizationIntent(mode, CLUSTER, access=question)
        assert rescope_intent(intent, "other") == intent
        assert rescope_intent(intent, None) == intent


@pytest.mark.parametrize(
    "mode,kind,fallback",
    [
        (AuthorizationMode.ROLE, "Role", AuthorizationMode.ROLES),
        (AuthorizationMode.BINDING, "RoleBinding", AuthorizationMode.BINDINGS),
    ],
)
def test_scope_change_drops_only_a_namespaced_selection_excluded_from_new_scope(
    mode, kind, fallback
):
    ref = RbacObjectRef(kind, "view", "team", "uid")
    intent = AuthorizationIntent(
        mode, NS, **({"role": ref} if mode == AuthorizationMode.ROLE else {"binding": ref})
    )
    assert rescope_intent(intent, "other").mode == fallback
    assert rescope_intent(intent, None).mode == mode
    assert rescope_intent(intent, "team").mode == mode
    cluster_ref = RbacObjectRef("ClusterRole", "view", None, "uid")
    assert (
        rescope_intent(
            AuthorizationIntent(AuthorizationMode.ROLE, NS, role=cluster_ref), "other"
        ).role
        == cluster_ref
    )


@pytest.mark.parametrize(
    "status,decision",
    [
        ({"allowed": True}, ReviewDecision.ALLOWED),
        ({"allowed": False, "denied": True}, ReviewDecision.DENIED),
        ({"allowed": False}, ReviewDecision.NO_ALLOW),
        ({"allowed": True, "denied": False}, ReviewDecision.ALLOWED),
    ],
)
def test_only_strict_server_booleans_classify_authoritative_review(status, decision):
    review = classify_access_review(request(), status, INSTANT)
    assert review.decision == decision and review.status == EvidenceStatus.READY
    assert review.observed_at == INSTANT


@pytest.mark.parametrize(
    "status",
    [
        None,
        [],
        {},
        {"allowed": None},
        {"allowed": 1},
        {"allowed": "true"},
        {"allowed": True, "denied": True},
        {"allowed": False, "denied": 0},
        {"allowed": True, "reason": []},
        {"allowed": False, "evaluationError": None},
    ],
)
def test_invalid_review_status_is_unknown_never_denied_or_allowed(status):
    review = classify_access_review(request(), status, INSTANT)
    assert review.decision == ReviewDecision.UNKNOWN and review.status == EvidenceStatus.INVALID


def test_evaluation_error_is_retained_even_for_allow_and_credentials_controls_are_sanitized():
    review = classify_access_review(
        request(),
        {
            "allowed": True,
            "reason": "Bearer secret-token\x1b[31m",
            "evaluationError": "partial authorizer failure\nmore",
        },
        INSTANT,
    )
    assert review.decision == ReviewDecision.ALLOWED
    assert "secret-token" not in review.reason and "\x1b" not in review.reason
    assert review.warnings == ("partial authorizer failure\\u000amore",)
    bounded = classify_access_review(
        request(), {"allowed": False, "reason": "r" * 9000, "evaluationError": "e" * 9000}, INSTANT
    )
    assert len(bounded.reason) == len(bounded.warnings[0]) == 8192


def test_named_list_review_does_not_claim_permission_for_unfiltered_http_request():
    review = classify_access_review(request(verb="list", name="one"), {"allowed": True}, INSTANT)
    assert review.decision == ReviewDecision.ALLOWED
    assert any("unfiltered" in value for value in review.warnings)
    nonresource = AuthorizationRequest(
        SessionIdentity("synthetic", 1),
        1,
        AuthorizationIntent(
            AuthorizationMode.REVIEW, CLUSTER, access=NonResourceAccess("get", "/readyz")
        ),
    )
    assert classify_access_review(nonresource, {"allowed": True}, INSTANT).warnings == ()
    assert classify_access_review(request(verb="list"), {"allowed": False}, INSTANT).warnings == ()
