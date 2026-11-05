"""Literal authorization grammar and discovery resolution keep questions exact."""

from dataclasses import replace

import pytest

from kuberich.domain.authorization import (
    AuthorizationMode,
    AuthorizationScopeKind,
    NonResourceAccess,
    RbacSubjectKind,
)
from kuberich.domain.resources import ApiResource, Discovery
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.authorization_commands import authorization_command, authorization_intent
from kuberich.services.commands import CommandService, suggestions


def discovery():
    return Discovery(
        (
            ApiResource("", "v1", "pods", "Pod", True, frozenset({"get", "list"}), ("po",)),
            ApiResource("", "v1", "nodes", "Node", False, frozenset({"get", "list"}), ("no",)),
            ApiResource(
                "apps",
                "v1",
                "deployments",
                "Deployment",
                True,
                frozenset({"get", "list"}),
                ("deploy",),
            ),
        )
    )


@pytest.mark.parametrize(
    "text,mode",
    [
        ("rbac", AuthorizationMode.SUBJECTS),
        ("rbac subjects", AuthorizationMode.SUBJECTS),
        ("rbac bindings --all-namespaces", AuthorizationMode.BINDINGS),
        ("rbac roles --cluster", AuthorizationMode.ROLES),
        ("rules team", AuthorizationMode.SELF_RULES),
        ("can-i get po", AuthorizationMode.REVIEW),
        ("who-can get deployments.apps", AuthorizationMode.WHO_CAN),
    ],
)
def test_commands_are_informational_and_resolve_only_after_parsing(text, mode):
    parsed = authorization_command(text)
    assert parsed.mode is mode
    assert CommandService(AccessPolicy(True)).resolve(":" + text) == parsed
    intent = authorization_intent(parsed, discovery(), "team")
    assert intent.mode is mode
    if intent.access is not None:
        assert intent.access.version == "v1" and intent.access.query.empty
    assert authorization_intent(parsed, discovery(), None).mode is mode


@pytest.mark.parametrize(
    "text,kind,name,namespace",
    [
        (
            'rbac subject user "Alice Smith" --namespace team',
            RbacSubjectKind.USER,
            "Alice Smith",
            None,
        ),
        ("rbac subject group Operators --all-namespaces", RbacSubjectKind.GROUP, "Operators", None),
        (
            "rbac subject serviceaccount identity runner",
            RbacSubjectKind.SERVICE_ACCOUNT,
            "runner",
            "identity",
        ),
    ],
)
def test_subjects_remain_case_sensitive_and_serviceaccount_identity_keeps_its_namespace(
    text, kind, name, namespace
):
    parsed = authorization_command(text)
    assert parsed.subject.kind is kind and parsed.subject.name == name
    assert parsed.subject.namespace == namespace
    assert authorization_intent(parsed, discovery(), "other").subject == parsed.subject


@pytest.mark.parametrize(
    "text,namespace,kind,effective",
    [
        (
            "can-i get pods example --subresource log",
            "team",
            AuthorizationScopeKind.NAMESPACE,
            "team",
        ),
        ("can-i list pods --all-namespaces", "team", AuthorizationScopeKind.ALL_NAMESPACES, None),
        (
            "can-i get pods.core --namespace other",
            "team",
            AuthorizationScopeKind.NAMESPACE,
            "other",
        ),
        ("can-i get nodes", "team", AuthorizationScopeKind.CLUSTER, None),
        ("can-i get nodes --cluster", None, AuthorizationScopeKind.CLUSTER, None),
        ("who-can get pods", None, AuthorizationScopeKind.ALL_NAMESPACES, None),
    ],
)
def test_resource_questions_pin_the_served_descriptor_and_explicit_scope(
    text, namespace, kind, effective
):
    intent = authorization_intent(authorization_command(text), discovery(), namespace)
    assert intent.scope.kind is kind and intent.scope.namespace == effective
    assert intent.access.scope == intent.scope
    if "example" in text:
        assert intent.access.name == "example" and intent.access.subresource == "log"


@pytest.mark.parametrize("verb", ["can-i", "who-can"])
def test_non_resource_questions_use_literal_cluster_paths(verb):
    intent = authorization_intent(
        authorization_command(f"{verb} get --non-resource-url /healthz"), discovery(), "team"
    )
    assert intent.access == NonResourceAccess("get", "/healthz")
    assert intent.scope.kind is AuthorizationScopeKind.CLUSTER


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        ":rbac",
        "something",
        'rbac subject user "unfinished',
        "rbac --namespace",
        "rbac --namespace team --cluster",
        "rbac --all-namespaces --all-namespaces",
        "can-i get pods --subresource",
        "can-i get --non-resource-url",
        "rbac --unknown",
        "can-i get pods --subresource log --subresource status",
        "can-i get --non-resource-url /a --non-resource-url /b",
        "rbac --subresource log",
        "rbac --non-resource-url /healthz",
        "rbac invalid",
        "rbac subject user",
        "rbac subject machine example",
        "rbac subject user Alice extra",
        "rbac subject serviceaccount team",
        "rules",
        "rules team extra",
        "rules team --cluster",
        "rules team --subresource log",
        "rules team --non-resource-url /healthz",
        "can-i",
        "who-can",
        "can-i get",
        "can-i get pods one two",
        "can-i GET pods",
        "can-i get pods --non-resource-url /healthz",
        "can-i get --non-resource-url /healthz --cluster",
        "can-i get --non-resource-url /healthz --subresource log",
        "can-i get --non-resource-url relative",
        "can-i get pods/exec",
        "can-i get pods.",
        "can-i get pods --namespace INVALID",
        "rbac subject user bad\x1bname",
    ],
)
def test_invalid_grammar_is_rejected_without_discovery_or_transport(text):
    with pytest.raises(AppError):
        authorization_command(text)


@pytest.mark.parametrize(
    "text",
    [
        "can-i get pods --cluster",
        "can-i get nodes --namespace team",
        "can-i get nodes --all-namespaces",
        "can-i get unknown",
    ],
)
def test_resolution_never_broadens_an_incompatible_or_undiscovered_question(text):
    with pytest.raises(AppError):
        authorization_intent(authorization_command(text), discovery(), "team")


def test_incomplete_programmatic_question_is_rejected_and_ambiguous_alias_is_not_guessed():
    parsed = authorization_command("can-i get pods")
    for changed in (replace(parsed, verb=None), replace(parsed, resource_name=None)):
        with pytest.raises(AppError):
            authorization_intent(changed, discovery(), "team")
    ambiguous = Discovery(
        (*discovery().resources, replace(discovery().resources[0], group="other.test"))
    )
    with pytest.raises(AppError, match="ambiguous"):
        authorization_intent(parsed, ambiguous, "team")


def test_command_completion_keeps_existing_priorities_and_exposes_authorization_grammar():
    assert suggestions("c", (), ())[:3] == ("context", "contexts", "ctx")
    assert suggestions("rbac ", (), ())[:3] == (
        "rbac bindings",
        "rbac roles",
        "rbac subject group ",
    )
    assert suggestions("rules ", (), ("*", "team")) == ("rules team",)
    assert "can-i get " in suggestions("can-i ", (), ())
    assert "who-can list " in suggestions("who-can ", (), ())
