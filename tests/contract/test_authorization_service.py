"""Bounded real HTTP RBAC sources, exact requests and honest local explanations."""

import asyncio
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
    EvidenceStatus,
    RbacObjectRef,
    RbacSubject,
    RbacSubjectKind,
    ReviewDecision,
)
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError
from kuberich.services import authorization
from kuberich.services.authorization import (
    ACCESS_PATH,
    IDENTITY_PATH,
    RBAC_GROUP,
    AuthorizationReader,
    AuthorizationService,
)
from kuberich.services.resources import ResourceReader
from tests.support.authorization import (
    AuthorizationApi,
    auth_request,
    auth_resources,
    authorization_session,
    policy_rule,
    rbac_object,
)
from tests.support.resources import collection

pytestmark = pytest.mark.fast
PREFIX = "/apis/" + RBAC_GROUP + "/v1"


def seeded_api():
    api = AuthorizationApi()
    api.values[PREFIX + "/namespaces/team/roles"] = [rbac_object(rules=[policy_rule()])]
    api.values[PREFIX + "/namespaces/team/rolebindings"] = [
        rbac_object(
            "RoleBinding",
            "bind",
            roleRef={"apiGroup": RBAC_GROUP, "kind": "Role", "name": "reader"},
            subjects=[
                {"kind": "User", "name": "fixture-user", "apiGroup": RBAC_GROUP},
                {"kind": "Group", "name": "fixture-group", "apiGroup": RBAC_GROUP},
                {"kind": "ServiceAccount", "name": "local"},
            ],
        )
    ]
    api.values["/api/v1/namespaces/team/serviceaccounts"] = [
        {
            "apiVersion": "v1",
            "kind": "ServiceAccount",
            "metadata": {
                "name": "listed",
                "namespace": "team",
                "uid": "uid-listed",
                "resourceVersion": "rv-listed",
            },
            "secrets": [{"name": "PRIVATE-not-retained"}],
        }
    ]
    return api


def service(session, request, *, discovery=None, current=lambda _: True):
    return AuthorizationService(
        ResourceReader(session),
        AuthorizationReader(session),
        discovery if discovery is not None else auth_resources(),
        request.session,
        current,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        AuthorizationMode.SUBJECTS,
        AuthorizationMode.BINDINGS,
        AuthorizationMode.ROLES,
        AuthorizationMode.SUBJECT,
        AuthorizationMode.BINDING,
        AuthorizationMode.ROLE,
        AuthorizationMode.WHO_CAN,
    ],
)
async def test_real_five_family_sources_subject_origins_and_analysis_modes(tmp_path, mode):
    api = seeded_api()
    kwargs = {}
    if mode == AuthorizationMode.SUBJECT:
        kwargs["subject"] = RbacSubject(RbacSubjectKind.USER, "fixture-user", None)
    elif mode == AuthorizationMode.ROLE:
        kwargs["role"] = RbacObjectRef("Role", "reader", "team", "uid-reader")
    elif mode == AuthorizationMode.BINDING:
        kwargs["binding"] = RbacObjectRef("RoleBinding", "bind", "team", "uid-bind")
    request = auth_request(mode, **kwargs)
    publications = []
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, publications.append)
        assert not result.collecting and publications[-1] == result
        assert result.rbac.requests_used == 6
        assert [(method, path) for method, path, _, _ in api.calls] == [
            ("POST", IDENTITY_PATH),
            ("GET", PREFIX + "/clusterroles"),
            ("GET", PREFIX + "/clusterrolebindings"),
            ("GET", PREFIX + "/namespaces/team/roles"),
            ("GET", PREFIX + "/namespaces/team/rolebindings"),
            ("GET", "/api/v1/namespaces/team/serviceaccounts"),
        ]
        assert all(
            source.status is EvidenceStatus.READY
            and source.collection.complete
            and source.observed_at
            for source in result.rbac.sources
        )
        assert result.rbac.roles[0].ref.uid == "uid-reader"
        subjects = result.rbac.subjects
        assert {value.subject.name for value in subjects} == {
            "fixture-user",
            "fixture-group",
            "local",
            "listed",
        }
        assert next(value for value in subjects if value.subject.name == "listed").origins == ()
        assert (
            next(value for value in subjects if value.subject.name == "local").subject.namespace
            == "team"
        )
        assert (
            next(value for value in subjects if value.subject.name == "fixture-user").origins[0].uid
            == "uid-bind"
        )
        assert "PRIVATE" not in repr(result)
        assert all(value.request == request for value in publications)
        if mode in {AuthorizationMode.SUBJECT, AuthorizationMode.WHO_CAN, AuthorizationMode.ROLE}:
            assert result.analysis is not None
            assert result.analysis.comparisons_used <= 100000
            assert any("external authorizers" in warning for warning in result.analysis.warnings)
            assert len(result.analysis.grants) == (
                2
                if mode == AuthorizationMode.SUBJECT
                else 3
                if mode == AuthorizationMode.WHO_CAN
                else 0
            )
        else:
            assert result.analysis is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,paths",
    [
        (
            AuthorizationScope(AuthorizationScopeKind.ALL_NAMESPACES, None),
            [PREFIX + "/roles", PREFIX + "/rolebindings", "/api/v1/serviceaccounts"],
        ),
        (AuthorizationScope(AuthorizationScopeKind.CLUSTER, None), []),
    ],
)
async def test_scope_uses_actual_allnamespace_or_cluster_paths_without_namespace_union(
    tmp_path, scope, paths
):
    api = AuthorizationApi()
    request = replace(
        auth_request(AuthorizationMode.SUBJECTS),
        intent=AuthorizationIntent(AuthorizationMode.SUBJECTS, scope),
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert [path for method, path, _, _ in api.calls if method == "GET"] == [
            PREFIX + "/clusterroles",
            PREFIX + "/clusterrolebindings",
            *paths,
        ]
        assert len(result.rbac.sources) == 2 + len(paths)


@pytest.mark.asyncio
async def test_forbidden_role_list_named_get_resolves_recreated_role_by_name_and_retains_failure(
    tmp_path,
):
    api = seeded_api()
    api.denied.add(PREFIX + "/namespaces/team/roles")
    request = auth_request(
        AuthorizationMode.SUBJECT, subject=RbacSubject(RbacSubjectKind.USER, "fixture-user", None)
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert result.rbac.sources[2].status is EvidenceStatus.FORBIDDEN
        assert result.rbac.sources[-1].family == "roles/reader"
        assert result.rbac.sources[-1].status is EvidenceStatus.READY
        assert result.rbac.requests_used == 7
        assert result.analysis.incomplete and len(result.analysis.grants) == 2
        assert "PRIVATE" not in repr(result)


@pytest.mark.asyncio
async def test_missing_discovery_roles_unresolved_refs_and_selected_replacement_are_visible(
    tmp_path,
):
    api = seeded_api()
    request = auth_request(
        AuthorizationMode.ROLE, role=RbacObjectRef("Role", "reader", "team", "old-uid")
    )
    discovery = Discovery(
        tuple(resource for resource in auth_resources().resources if resource.name != "roles")
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request, discovery=discovery).collect(
            request, lambda _: None
        )
        assert result.analysis.incomplete
        assert (
            next(value for value in result.rbac.sources if value.family == "roles").status
            is EvidenceStatus.UNAVAILABLE
        )
        assert (
            next(value for value in result.rbac.sources if value.family == "selected/Role").status
            is EvidenceStatus.UNAVAILABLE
        )
        assert all(
            not path.endswith("/roles") and not path.endswith("/roles/reader")
            for _, path, _, _ in api.calls
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_family", ["roles", "rolebindings", "serviceaccounts"])
async def test_invalid_source_record_retains_valid_prefix_and_marks_source_invalid(
    tmp_path, bad_family
):
    api = seeded_api()
    path = (
        "/api/v1/namespaces/team/serviceaccounts"
        if bad_family == "serviceaccounts"
        else PREFIX + "/namespaces/team/" + bad_family
    )
    bad = rbac_object("RoleBinding" if bad_family == "rolebindings" else "Role", "invalid")
    if bad_family == "roles":
        bad["rules"] = [{}]
    elif bad_family == "serviceaccounts":
        bad = {
            "metadata": {
                "name": "invalid",
                "namespace": "INVALID",
                "uid": "bad",
                "resourceVersion": "bad",
            }
        }
    api.values[path].append(bad)
    request = auth_request(AuthorizationMode.WHO_CAN)
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert (
            next(value for value in result.rbac.sources if value.family == bad_family).status
            is EvidenceStatus.INVALID
        )
        assert result.analysis.incomplete
        assert len(result.rbac.roles) == 1 and len(result.rbac.bindings) == 1


@pytest.mark.asyncio
async def test_pagination_budget_preserves_partial_facts_and_never_exceeds64_logical_reads(
    tmp_path,
):
    api = AuthorizationApi()
    path = PREFIX + "/clusterroles"

    async def handler(request):
        if request.path == path:
            index = int(request.query.get("continue") or "0")
            api.calls.append((request.method, request.path, dict(request.query), None))
            return web.json_response(
                {
                    **collection(
                        rbac_object("ClusterRole", f"role-{index}", None, rules=[policy_rule()]),
                        token=str(index + 1),
                    ),
                    "apiVersion": RBAC_GROUP + "/v1",
                }
            )
        return await api(request)

    request = auth_request(AuthorizationMode.WHO_CAN)
    async with authorization_session(tmp_path, handler) as session:
        collector = service(session, request)
        result = await collector.collect(request, lambda _: None)
        assert len(api.calls) == result.rbac.requests_used == 64
        assert len(result.rbac.roles) == 63
        assert all(value.status is EvidenceStatus.TRUNCATED for value in result.rbac.sources)
        assert result.rbac.sources[0].collection.pages == 63
        assert not result.rbac.sources[0].collection.complete
        assert result.analysis.incomplete
        review = await collector.review(replace(auth_request(), session=request.session))
        assert (
            review.decision is ReviewDecision.UNKNOWN and review.status is EvidenceStatus.TRUNCATED
        )
        assert len(api.calls) == 64


@pytest.mark.asyncio
async def test_real_materialized_aggregate_and_inferred_contributors_share_analysis_budget(
    tmp_path,
):
    api = AuthorizationApi()
    aggregate = rbac_object(
        "ClusterRole",
        "aggregate",
        None,
        rules=[policy_rule()],
        aggregationRule={"clusterRoleSelectors": [{"matchLabels": {"contributes": "yes"}}]},
    )
    contributor = rbac_object("ClusterRole", "leaf", None, rules=[policy_rule(verbs=["delete"])])
    contributor["metadata"]["labels"] = {"contributes": "yes"}
    api.values[PREFIX + "/clusterroles"] = [aggregate, contributor]
    api.values[PREFIX + "/clusterrolebindings"] = [
        rbac_object(
            "ClusterRoleBinding",
            "bind",
            None,
            roleRef={"apiGroup": RBAC_GROUP, "kind": "ClusterRole", "name": "aggregate"},
            subjects=[{"apiGroup": RBAC_GROUP, "kind": "User", "name": "fixture-user"}],
        )
    ]
    request = auth_request(AuthorizationMode.WHO_CAN)
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert result.analysis.grants[0].role.uid == "uid-aggregate"
        assert result.analysis.aggregations[0].contributors[0].uid == "uid-leaf"
        assert 0 < result.analysis.comparisons_used < 100000
        assert not result.analysis.incomplete
        assert (
            len(result.analysis.grants)
            + sum(len(value.contributors) for value in result.analysis.aggregations)
            <= 1024
        )


@pytest.mark.asyncio
async def test_review_authority_is_published_before_supplemental_identity_and_refresh_is_fresh(
    tmp_path,
):
    api = AuthorizationApi()
    api.denied.add(IDENTITY_PATH)
    request = auth_request()
    publications = []
    async with authorization_session(tmp_path, api) as session:
        collector = service(session, request)
        first = await collector.collect(request, publications.append)
        assert first.review.decision is ReviewDecision.ALLOWED
        assert first.identity.status is EvidenceStatus.FORBIDDEN
        assert [path for _, path, _, _ in api.calls] == [ACCESS_PATH, IDENTITY_PATH]
        assert any(value.collecting and value.review is not None for value in publications)
        api.status[ACCESS_PATH] = {"allowed": False, "denied": True}
        second = await collector.collect(replace(request, revision=2), lambda _: None)
        assert second.review.decision is ReviewDecision.DENIED
        assert len(api.calls) == 4


@pytest.mark.asyncio
async def test_rules_mode_and_deadline_keep_explicit_incomplete_evidence(tmp_path, monkeypatch):
    api = AuthorizationApi()
    request = auth_request(AuthorizationMode.SELF_RULES)
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert result.rules.rules and result.rbac is None and result.review is None
        api.held_path = IDENTITY_PATH
        monkeypatch.setattr(authorization, "MAX_COLLECTION_SECONDS", 0.03)
        try:
            result = await service(session, request).collect(request, lambda _: None)
            assert result.rules.status is EvidenceStatus.TRUNCATED and result.rules.incomplete
        finally:
            api.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [AuthorizationMode.REVIEW, AuthorizationMode.WHO_CAN])
async def test_deadline_failure_retains_unknown_or_incomplete_analysis(tmp_path, monkeypatch, mode):
    api = AuthorizationApi()
    api.held_path = ACCESS_PATH if mode == AuthorizationMode.REVIEW else IDENTITY_PATH
    request = auth_request(mode)
    monkeypatch.setattr(authorization, "MAX_COLLECTION_SECONDS", 0.03)
    async with authorization_session(tmp_path, api) as session:
        try:
            result = await service(session, request).collect(request, lambda _: None)
            assert not result.collecting
            if mode == AuthorizationMode.REVIEW:
                assert (
                    result.review.decision is ReviewDecision.UNKNOWN
                    and result.review.status is EvidenceStatus.TRUNCATED
                )
            else:
                assert (
                    result.analysis.incomplete
                    and result.rbac.sources[0].status is EvidenceStatus.TRUNCATED
                )
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_stale_request_and_client_checks_before_after_await_and_publication(tmp_path):
    api = AuthorizationApi()
    request = auth_request()
    current = True
    async with authorization_session(tmp_path, api) as session:
        collector = service(session, request, current=lambda _: current)
        current = False
        with pytest.raises(asyncio.CancelledError):
            await collector.collect(request, lambda _: None)
        assert api.calls == []
        current = True
        api.held_path = ACCESS_PATH
        publications = []
        task = asyncio.create_task(collector.collect(request, publications.append))
        await api.held.wait()
        current = False
        api.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(publications) == 1 and publications[0].review is None
        current = True

        def publish(snapshot):
            nonlocal current
            current = False

        with pytest.raises(asyncio.CancelledError):
            await collector.collect(request, publish)


@pytest.mark.asyncio
async def test_readers_cannot_mix_captured_clients(tmp_path):
    api = AuthorizationApi()
    async with (
        authorization_session(tmp_path, api) as first,
        authorization_session(tmp_path, api) as second,
    ):
        request = auth_request()
        with pytest.raises(AppError):
            AuthorizationService(
                ResourceReader(first),
                AuthorizationReader(second),
                auth_resources(),
                request.session,
                lambda _: True,
            )


@pytest.mark.asyncio
async def test_failed_second_page_retains_first_page_and_actual_forbidden_provenance(tmp_path):
    api = AuthorizationApi()

    async def handler(request):
        if request.path == PREFIX + "/clusterroles":
            if request.query.get("continue"):
                return web.json_response({"message": "PRIVATE denied continuation"}, status=403)
            return web.json_response(
                {
                    **collection(
                        rbac_object("ClusterRole", "prefix", None, rules=[policy_rule()]),
                        token="next",
                    ),
                    "apiVersion": RBAC_GROUP + "/v1",
                }
            )
        return await api(request)

    request = auth_request(AuthorizationMode.WHO_CAN)
    async with authorization_session(tmp_path, handler) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert result.rbac.roles[0].ref.uid == "uid-prefix"
        assert result.rbac.sources[0].status is EvidenceStatus.FORBIDDEN
        assert (
            result.rbac.sources[0].collection.pages == 1
            and not result.rbac.sources[0].collection.complete
        )
        assert result.analysis.incomplete and "PRIVATE" not in repr(result)


@pytest.mark.asyncio
async def test_authoritative_review_survives_only_supplemental_identity_deadline(
    tmp_path, monkeypatch
):
    api = AuthorizationApi()
    api.held_path = IDENTITY_PATH
    monkeypatch.setattr(authorization, "MAX_COLLECTION_SECONDS", 0.03)
    request = auth_request()
    async with authorization_session(tmp_path, api) as session:
        try:
            result = await service(session, request).collect(request, lambda _: None)
            assert result.review.decision is ReviewDecision.ALLOWED and not result.collecting
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_object_retention_exhaustion_prevents_named_recovery_reads(tmp_path, monkeypatch):
    api = AuthorizationApi()
    api.values[PREFIX + "/clusterroles"] = [rbac_object("ClusterRole", "first", None)]
    request = auth_request(
        AuthorizationMode.ROLE, role=RbacObjectRef("Role", "unobserved", "team", "old")
    )
    monkeypatch.setattr(authorization, "MAX_OBJECTS", 1)
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert len(api.calls) == 2
        assert (
            next(
                source for source in result.rbac.sources if source.family == "roles/unobserved"
            ).status
            is EvidenceStatus.TRUNCATED
        )
        assert result.analysis.incomplete


@pytest.mark.asyncio
async def test_named_role_cannot_overrun_shared_retained_bytes(tmp_path, monkeypatch):
    api = AuthorizationApi()
    binding = rbac_object(
        "ClusterRoleBinding",
        "bind",
        None,
        roleRef={"apiGroup": RBAC_GROUP, "kind": "ClusterRole", "name": "huge"},
    )
    api.values[PREFIX + "/clusterrolebindings"] = [binding]
    huge = rbac_object(
        "ClusterRole", "huge", None, rules=[policy_rule(resourceNames=["value" * 100])]
    )

    async def handler(request):
        if request.path.endswith("/clusterroles/huge"):
            return web.json_response(huge)
        return await api(request)

    monkeypatch.setattr(authorization, "MAX_FACT_BYTES", 500)
    request = auth_request(AuthorizationMode.WHO_CAN)
    async with authorization_session(tmp_path, handler) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert not result.rbac.roles
        assert (
            next(
                source for source in result.rbac.sources if source.family == "clusterroles/huge"
            ).status
            is EvidenceStatus.TRUNCATED
        )
        assert result.analysis.incomplete


@pytest.mark.asyncio
async def test_selected_missing_role_get_is_missing_and_not_a_false_allow(tmp_path):
    api = AuthorizationApi()
    request = auth_request(
        AuthorizationMode.ROLE, role=RbacObjectRef("Role", "gone", "team", "old-uid")
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert (
            next(source for source in result.rbac.sources if source.family == "roles/gone").status
            is EvidenceStatus.MISSING
        )
        assert result.analysis.incomplete and not result.analysis.grants


@pytest.mark.asyncio
async def test_current_identity_groups_are_not_invented_after_forbidden_identity_review(tmp_path):
    api = seeded_api()
    api.denied.add(IDENTITY_PATH)
    request = auth_request(
        AuthorizationMode.SUBJECT, subject=RbacSubject(RbacSubjectKind.USER, "fixture-user", None)
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert result.identity.status is EvidenceStatus.FORBIDDEN
        assert len(result.analysis.grants) == 1 and result.analysis.grants[0].via_group is None
        assert any("Group membership is unknown" in warning for warning in result.analysis.warnings)


@pytest.mark.asyncio
@pytest.mark.parametrize("uid,contributors", [(None, 1), ("uid-aggregate", 1), ("old-uid", 0)])
async def test_role_reference_name_resolution_and_pinned_inspection_use_distinct_uid_semantics(
    tmp_path, uid, contributors
):
    api = AuthorizationApi()
    aggregate = rbac_object(
        "ClusterRole",
        "aggregate",
        None,
        rules=[policy_rule()],
        aggregationRule={"clusterRoleSelectors": [{"matchLabels": {"contributes": "yes"}}]},
    )
    leaf = rbac_object("ClusterRole", "leaf", None)
    leaf["metadata"]["labels"] = {"contributes": "yes"}
    api.values[PREFIX + "/clusterroles"] = [aggregate, leaf]
    request = auth_request(
        AuthorizationMode.ROLE, role=RbacObjectRef("ClusterRole", "aggregate", None, uid)
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert (
            sum(len(value.contributors) for value in result.analysis.aggregations) == contributors
        )
        assert any(
            value.family == "selected/ClusterRole" and value.status is EvidenceStatus.MISSING
            for value in result.rbac.sources
        ) == (uid == "old-uid")


@pytest.mark.asyncio
async def test_selected_binding_hidden_by_forbidden_list_is_not_falsely_reported_missing(tmp_path):
    api = AuthorizationApi()
    api.denied.add(PREFIX + "/namespaces/team/rolebindings")
    request = auth_request(
        AuthorizationMode.BINDING,
        binding=RbacObjectRef("RoleBinding", "hidden", "team", "uid-hidden"),
    )
    async with authorization_session(tmp_path, api) as session:
        result = await service(session, request).collect(request, lambda _: None)
        assert (
            next(
                source for source in result.rbac.sources if source.family == "selected/RoleBinding"
            ).status
            is EvidenceStatus.FORBIDDEN
        )
