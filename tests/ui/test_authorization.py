"""Actual native authorization commands and HTTP evidence in the shared App frame."""

import logging

import pytest

from kuberich.config.schema import Settings
from kuberich.domain.authorization import (
    AuthorizationMode,
    AuthorizationScopeKind,
    RbacSubject,
    RbacSubjectKind,
    ReviewDecision,
)
from kuberich.services.authorization_commands import authorization_command
from kuberich.ui.app import KubeRichApp
from tests.support.authorization_ui import GROUP, AuthorizationAPI, authorization_api
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for
from tests.ui.test_navigation import make_app


async def pods_ready(app, namespace="team"):
    await wait_for(
        lambda: (
            app.state.view_kind == "pods"
            and app.state.scope is not None
            and app.state.namespace == namespace
            and app.resources.row_count == 1
        )
    )


async def ready(app, mode):
    await wait_for(
        lambda: (
            app.state.view_kind == "authorization"
            and app.workspace.store.observation.authorization is not None
            and app.workspace.store.observation.authorization.request.intent.mode is mode
            and not app.workspace.store.observation.authorization.collecting
            and not app.workspace.authorization_collecting
            and app.authorization_table.request == app.workspace.authorization_request
            and "summary:request" in app.authorization_table.rows
            and app.authorization_table.get_cell("summary:request", "STATUS").plain
            == "observed evidence"
        )
    )


def rows(app):
    return tuple(
        app.authorization_table.row_at(item.key.value)
        for item in app.authorization_table.ordered_rows
    )


def select(app, predicate):
    row = next(row for row in rows(app) if predicate(row))
    app.authorization_table.move_cursor(row=app.authorization_table.get_row_index(row.key))
    app.authorization_table.focus()
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,plural,name,namespace",
    [
        ("RoleBinding", "rolebindings", "readers", "team"),
        ("ClusterRoleBinding", "clusterrolebindings", "cluster-readers", None),
    ],
)
async def test_repeated_binding_subjects_render_unique_native_rows_and_remain_navigable(
    tmp_path, kind, plural, name, namespace
):
    api = AuthorizationAPI()
    user = {"kind": "User", "apiGroup": GROUP, "name": "Alice"}
    group = {"kind": "Group", "apiGroup": GROUP, "name": "Operators"}
    account = {"kind": "ServiceAccount", "name": "runner", "namespace": "identity"}
    api.objects[(GROUP, plural, namespace, name)]["subjects"] = [
        user,
        dict(user),
        group,
        account,
        dict(group),
        {**user, "kind": "Group"},
        dict(account),
        {**account, "namespace": "other"},
    ]
    expected = (
        RbacSubject(RbacSubjectKind.USER, "Alice", None),
        RbacSubject(RbacSubjectKind.GROUP, "Operators", None),
        RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "runner", "identity"),
        RbacSubject(RbacSubjectKind.GROUP, "Alice", None),
        RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "runner", "other"),
    )
    async with authorization_api(api) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.getLogger("binding-subjects"),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test(size=(80, 20)) as pilot:
            await pods_ready(app)
            await app.run_command("rbac bindings")
            await ready(app, AuthorizationMode.BINDINGS)
            selected = select(
                app,
                lambda row: (
                    row.object_ref is not None
                    and row.object_ref.kind == kind
                    and row.object_ref.name == name
                ),
            )
            await pilot.press("enter")
            panel = app.query_one("#view-error")
            await wait_for(
                lambda: (
                    panel.has_class("failed")
                    or (
                        app.authorization_table.request == app.workspace.authorization_request
                        and any(row.status == "declared subject" for row in rows(app))
                    )
                )
            )
            assert not panel.has_class("failed"), (
                "Binding detail must render legal repeated subjects"
            )
            await ready(app, AuthorizationMode.BINDING)
            subjects = tuple(row for row in rows(app) if row.status == "declared subject")
            assert tuple(row.destination.subject for row in subjects) == expected
            assert len({row.key for row in rows(app)}) == app.authorization_table.row_count
            assert all(row.object_ref is None for row in subjects)
            assert {row.label for row in subjects} == {
                "User Alice",
                "Group Operators",
                "Group Alice",
                "ServiceAccount identity/runner",
                "ServiceAccount other/runner",
            }
            assert app.workspace.authorization_request.intent.binding == selected.object_ref
            select(app, lambda row: row.label == "Group Operators")
            await pilot.press("enter")
            await ready(app, AuthorizationMode.SUBJECT)
            grants = tuple(row for row in rows(app) if row.key.startswith("grant:"))
            matching = tuple(row for row in grants if row.object_ref == selected.object_ref)
            assert len(matching) == 1
            assert matching[0].destination.binding == selected.object_ref
            assert "via group: direct declaration" in matching[0].details
            assert f"{kind}/{name}" in matching[0].label
            assert (f"namespace {namespace}" if namespace is not None else "cluster") in matching[
                0
            ].label
            assert not panel.has_class("failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 30)])
async def test_subject_binding_role_drilldowns_preserve_native_frame_and_observed_uid_open(
    tmp_path, size
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=size) as pilot:
            await pods_ready(app)
            frame = app.query_one("#resource-view").region
            await app.run_command("rbac subjects")
            await ready(app, AuthorizationMode.SUBJECTS)
            assert app.query_one("#resource-view").region == frame and len(app.screen_stack) == 1
            assert app.state.scope is None
            assert not app.check_action("review_delete", ()) and not app.check_action(
                "inspect_yaml", ()
            )
            select(app, lambda row: row.label == "User Alice")
            await pilot.press("enter")
            await ready(app, AuthorizationMode.SUBJECT)
            assert any("effective authorization" in " ".join(row.details) for row in rows(app))
            select(
                app,
                lambda row: row.key.startswith("grant:") and row.object_ref.kind == "RoleBinding",
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.BINDING)
            select(
                app,
                lambda row: (
                    row.destination is not None and row.destination.mode is AuthorizationMode.ROLE
                ),
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.ROLE)
            assert any(
                row.status == "declared" and "resources: pods" in row.details for row in rows(app)
            )
            role = select(
                app, lambda row: row.object_ref is not None and row.object_ref.kind == "Role"
            )
            await app.run_command("open")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == "roles"
                    and app.custom_table.row_count == 1
                )
            )
            assert app.views.expected_uid == role.object_ref.uid
            assert app.state.selected == role.object_ref.uid
            assert app.state.scope.resource.group == GROUP
            await pilot.press("escape")
            await ready(app, AuthorizationMode.ROLE)
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None and app.workspace.ownership.authorization_count == 0


@pytest.mark.asyncio
async def test_materialized_aggregate_rules_and_inferred_contributors_are_separate(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("rbac roles")
            await ready(app, AuthorizationMode.ROLES)
            select(
                app, lambda row: row.object_ref is not None and row.object_ref.name == "aggregate"
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.ROLE)
            assert any(
                row.status == "materialized" and "resources: pods" in row.details
                for row in rows(app)
            )
            contributor = select(app, lambda row: row.key.startswith("contributor:"))
            assert (
                contributor.status == "inferred explanation"
                and contributor.destination.role.name == "contributor"
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.ROLE)
            assert app.workspace.authorization_request.intent.role.name == "contributor"
            assert any("resources: pods/log" in row.details for row in rows(app))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "allowed,denied,http,decision",
    [
        (True, False, 201, ReviewDecision.ALLOWED),
        (False, True, 201, ReviewDecision.DENIED),
        (False, False, 201, ReviewDecision.NO_ALLOW),
        (False, False, 403, ReviewDecision.UNKNOWN),
    ],
)
async def test_authoritative_review_decisions_and_warnings_do_not_change_operation_guards(
    tmp_path, allowed, denied, http, decision
):
    api = AuthorizationAPI()
    api.allowed, api.denied, api.review_status = allowed, denied, http
    api.reason = "[bold]literal\x1b[31m reason"
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("can-i list pods example --subresource log --namespace other")
            await ready(app, AuthorizationMode.REVIEW)
            snapshot = app.workspace.store.observation.authorization
            assert snapshot.review.decision is decision
            assert (
                app.state.namespace == "team" and snapshot.request.intent.scope.namespace == "other"
            )
            question = next(
                body for path, body in api.reviews if path.endswith("/selfsubjectaccessreviews")
            )
            assert question["spec"]["resourceAttributes"] == {
                "verb": "list",
                "group": "",
                "version": "v1",
                "resource": "pods",
                "subresource": "log",
                "name": "example",
                "namespace": "other",
            }
            assert any(
                row.key == "review:decision" and row.status.startswith(decision.value)
                for row in rows(app)
            )
            if allowed:
                assert any(
                    "named list/watch" in " ".join(row.details).lower()
                    or "unfiltered" in " ".join(row.details).lower()
                    for row in rows(app)
                )
                detail = app.authorization_table.get_cell("review:decision", "DETAIL / OBSERVATION")
                assert (
                    "[bold]literal" in detail.plain
                    and "\x1b" not in detail.plain
                    and not detail.spans
                )
            before = len(api.reviews)
            await app.run_command("")
            assert len(api.reviews) == before
            await pilot.press("slash")
            app.filter_input.value = "matches-nothing"
            await pilot.press("enter")
            await wait_for(lambda: all(row.destination is None for row in rows(app)))
            assert any(row.key == "review:decision" for row in rows(app))
            assert len(api.reviews) == before
            await app.run_command("annotate")
            assert "Read-only" in str(app.status.content)
            assert len(app.screen_stack) == 1 and not app.check_action("review_delete", ())
            assert all(
                path.endswith(("selfsubjectreviews", "selfsubjectaccessreviews"))
                for path, _ in api.reviews
            )


@pytest.mark.asyncio
async def test_who_can_and_denied_sources_preserve_uncertainty_when_filter_matches_nothing(
    tmp_path,
):
    api = AuthorizationAPI()
    api.forbidden.add("rolebindings")
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("who-can get pods example")
            await ready(app, AuthorizationMode.WHO_CAN)
            assert any(row.status == "forbidden" for row in rows(app))
            assert any("external authorizers" in " ".join(row.details) for row in rows(app))
            assert any(
                "Group Operators" in row.label and row.key.startswith("grant:") for row in rows(app)
            )
            await pilot.press("slash")
            app.filter_input.value = "matches-nothing"
            await pilot.press("enter")
            await wait_for(lambda: not any(row.key.startswith("grant:") for row in rows(app)))
            assert any(row.status == "forbidden" for row in rows(app))
            assert any("external authorizers" in " ".join(row.details) for row in rows(app))
            assert not any("/users" in path or "/groups" in path for path, _ in api.reads)


@pytest.mark.asyncio
async def test_rules_all_namespace_transition_and_namespace_picker_use_one_atomic_question(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("rules team")
            await ready(app, AuthorizationMode.SELF_RULES)
            assert any("INCOMPLETE rules" in " ".join(row.details) for row in rows(app))
            await pilot.press("slash")
            app.filter_input.value = "does-not-match-a-rule"
            await pilot.press("enter")
            await app.run_command("ns *")
            await ready(app, AuthorizationMode.SUBJECTS)
            assert app.state.namespace is None
            assert "Rules require one namespace" in str(app.status.content)
            await app.run_command("rbac bindings --namespace team")
            await ready(app, AuthorizationMode.BINDINGS)
            select(
                app, lambda row: row.object_ref is not None and row.object_ref.kind == "RoleBinding"
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.BINDING)
            await app.run_command("ns")
            await wait_for(
                lambda: app.state.view_kind == "namespaces" and app.namespace_table.row_count == 3
            )
            assert app.workspace.authorization_request is None
            app.namespace_table.move_cursor(
                row=app.namespace_table.get_row_index("namespace-default")
            )
            await pilot.press("enter")
            await ready(app, AuthorizationMode.BINDINGS)
            assert app.state.namespace == "default"
            assert app.workspace.authorization_request.intent.scope.namespace == "default"
            assert app.workspace.authorization_request.intent.binding is None


@pytest.mark.asyncio
async def test_cluster_non_resource_question_keeps_its_scope_when_header_namespace_changes(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("can-i get --non-resource-url /healthz")
            await ready(app, AuthorizationMode.REVIEW)
            intent = app.workspace.authorization_request.intent
            await app.run_command("ns other")
            await ready(app, AuthorizationMode.REVIEW)
            assert app.state.namespace == "other"
            assert app.workspace.authorization_request.intent == intent
            assert intent.scope.kind is AuthorizationScopeKind.CLUSTER


@pytest.mark.asyncio
async def test_cross_context_history_recollects_review_and_preserves_independent_scopes(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("can-i get pods example --namespace other")
            await ready(app, AuthorizationMode.REVIEW)
            original = app.workspace.authorization_request
            assert (
                app.workspace.store.observation.authorization.review.decision
                is ReviewDecision.ALLOWED
            )
            await app.run_command("ctx kuberich-test-Two")
            await pods_ready(app, "default")
            api.allowed, api.denied = False, True
            before = sum(path.endswith("/selfsubjectaccessreviews") for path, _ in api.reviews)
            await pilot.press("alt+left")
            await ready(app, AuthorizationMode.REVIEW)
            restored = app.workspace.authorization_request
            assert restored.session != original.session
            assert restored.session == app.sessions.observation.identity
            assert restored.intent == original.intent and app.state.namespace == "team"
            assert restored.intent.scope.namespace == "other"
            assert (
                app.workspace.store.observation.authorization.review.decision
                is ReviewDecision.DENIED
            )
            assert (
                sum(path.endswith("/selfsubjectaccessreviews") for path, _ in api.reviews)
                == before + 1
            )


@pytest.mark.asyncio
async def test_object_open_from_question_namespace_restores_header_scope_and_exact_viewport(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 24)) as pilot:
            await pods_ready(app)
            await app.run_command("rbac roles --namespace other")
            await ready(app, AuthorizationMode.ROLES)
            original = app.workspace.authorization_request
            assert app.state.namespace == "team" and original.intent.scope.namespace == "other"
            role = select(
                app, lambda row: row.object_ref is not None and row.object_ref.kind == "Role"
            )
            assert role.object_ref.namespace == "other"
            await pilot.pause()
            app.authorization_table.scroll_to(x=9, animate=False, immediate=True, force=True)
            await pilot.pause()
            viewport = app.authorization_table.capture_viewport()
            assert viewport.x == 9
            await app.run_command("open")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == "roles"
                    and app.custom_table.row_count == 1
                )
            )
            assert app.state.namespace == app.state.scope.namespace == "other"
            assert app.state.selected == app.views.expected_uid == role.object_ref.uid
            await pilot.press("escape")
            await ready(app, AuthorizationMode.ROLES)
            await pilot.pause()
            restored = app.workspace.authorization_request
            assert app.state.namespace == "team" and restored.intent.scope.namespace == "other"
            assert restored.session.generation > original.session.generation
            assert restored.session.connection_id == original.session.connection_id
            assert app.authorization_table.capture_viewport() == viewport
            assert sum(path.endswith("/selfsubjectreviews") for path, _ in api.reviews) == 2


@pytest.mark.asyncio
async def test_context_switch_cancels_pending_review_and_rejects_late_allow(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test() as pilot:
                await pods_ready(app)
                api.hold_path = "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"
                await app.run_command("can-i get pods example")
                await wait_for(api.started.is_set)
                request = app.workspace.authorization_request
                await app.run_command("ctx kuberich-test-Two")
                await pods_ready(app, "default")
                api.release.set()
                await pilot.pause()
                assert app.workspace.authorization_request is None
                assert app.workspace.store.observation.authorization is None
                assert (
                    app.state.view_kind == "pods"
                    and app.sessions.observation.identity != request.session
                )
                assert app.workspace.ownership.authorization_count == 0
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_startup_command_waits_for_discovery_and_new_context_discards_it(tmp_path):
    api = AuthorizationAPI()
    api.hold_path = "/api"
    async with authorization_api(api) as url:
        app = make_app(
            catalog_fixture(tmp_path, url), initial=authorization_command("can-i get pods example")
        )
        try:
            async with app.run_test() as pilot:
                await wait_for(api.started.is_set)
                assert app.state.view_kind == "authorization"
                await app.run_command("ctx kuberich-test-Two")
                api.release.set()
                await pods_ready(app, "default")
                await pilot.pause()
                assert not api.reviews
                assert app.workspace.authorization_request is None
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_opened_rbac_uid_does_not_select_a_same_name_list_replacement(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("rbac roles")
            await ready(app, AuthorizationMode.ROLES)
            row = select(
                app, lambda row: row.object_ref is not None and row.object_ref.kind == "Role"
            )
            api.list_replacements[(GROUP, "roles", "team", row.object_ref.name)] = "replacement-uid"
            await pilot.press("o")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == "roles"
                    and app.state.status.name == "LIVE"
                )
            )
            assert app.views.expected_uid == row.object_ref.uid
            assert app.custom_table.row_count == 0 and app.state.selected is None


@pytest.mark.asyncio
async def test_refresh_preserves_exact_intent_and_viewport_and_informational_rows_cannot_open(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            app.authorization.open_object()
            assert "evidence changed" in str(app.status.content)
            await app.run_command("rules team")
            await ready(app, AuthorizationMode.SELF_RULES)
            await app.run_command("ns *")
            await ready(app, AuthorizationMode.SUBJECTS)
            original = app.workspace.authorization_request
            viewport = app.authorization_table.capture_viewport()
            await app.run_command("refresh")
            await ready(app, AuthorizationMode.SUBJECTS)
            await pilot.pause()
            assert app.workspace.authorization_request.intent == original.intent
            assert app.workspace.authorization_request.revision > original.revision
            assert app.authorization_table.capture_viewport() == viewport
            assert "Rules require" not in str(app.status.content)
            select(app, lambda row: row.key == "summary:request")
            await pilot.press("enter")
            assert "informational evidence" in str(app.status.content)
            await pilot.press("o")
            assert "requires an observed RBAC object UID" in str(app.status.content)
            app.authorization.selected("expired-row-key")
            assert "Select an authorization evidence row" in str(app.status.content)


@pytest.mark.asyncio
async def test_startup_authorization_command_resolves_after_current_discovery(tmp_path):
    api = AuthorizationAPI()
    api.hold_path = "/api"
    async with authorization_api(api) as url:
        app = make_app(
            catalog_fixture(tmp_path, url), initial=authorization_command("can-i get pods example")
        )
        try:
            async with app.run_test():
                await wait_for(api.started.is_set)
                assert not api.reviews
                api.release.set()
                await ready(app, AuthorizationMode.REVIEW)
                assert (
                    app.workspace.store.observation.authorization.review.decision
                    is ReviewDecision.ALLOWED
                )
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_invalid_deferred_question_and_offline_question_retain_clear_native_notices(tmp_path):
    offline = make_app()
    async with offline.run_test():
        await offline.run_command("rbac")
        assert "Connect to a context" in str(offline.status.content)
    api = AuthorizationAPI()
    api.hold_path = "/api"
    async with authorization_api(api) as url:
        app = make_app(
            catalog_fixture(tmp_path, url), initial=authorization_command("can-i get absent")
        )
        try:
            async with app.run_test():
                await wait_for(api.started.is_set)
                api.release.set()
                await wait_for(lambda: "not discovered" in str(app.status.content))
                assert not api.reviews and app.state.view_kind == "authorization"
                await app.run_command("rbac")
                await ready(app, AuthorizationMode.SUBJECTS)
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_direct_context_navigation_remembers_authorization_before_resetting_route(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("rbac subjects")
            await ready(app, AuthorizationMode.SUBJECTS)
            original = app.workspace.authorization_request
            app.navigator.connect("kuberich-test-Two")
            await pods_ready(app, "default")
            await pilot.press("alt+left")
            await ready(app, AuthorizationMode.SUBJECTS)
            assert app.workspace.authorization_request.intent == original.intent
            assert app.workspace.authorization_request.session != original.session


@pytest.mark.asyncio
async def test_pending_question_does_not_cross_a_service_session_replacement(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test():
                await pods_ready(app)
                await app.run_command("rbac roles")
                await ready(app, AuthorizationMode.ROLES)
                original = app.workspace.authorization_request
                api.hold_path = "/api"
                app.workspace.refresh_discovery()
                await wait_for(api.started.is_set)
                await app.run_command("can-i get pods example")
                app.workspace.connect(app.state.context)
                api.release.set()
                await ready(app, AuthorizationMode.ROLES)
                assert app.workspace.authorization_request.session != original.session
                assert not any(
                    path.endswith("/selfsubjectaccessreviews") for path, _ in api.reviews
                )
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_same_context_back_waits_for_discovery_then_restores_captured_authorization(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test() as pilot:
                await pods_ready(app)
                await app.run_command("rbac roles")
                await ready(app, AuthorizationMode.ROLES)
                selected = select(
                    app, lambda row: row.object_ref is not None and row.object_ref.kind == "Role"
                )
                await pilot.press("o")
                await wait_for(
                    lambda: app.state.scope is not None and app.custom_table.row_count == 1
                )
                api.hold_path = "/api"
                await app.run_command("refresh")
                await wait_for(api.started.is_set)
                await app.run_command("back")
                assert app.state.view_kind == "authorization"
                api.release.set()
                await ready(app, AuthorizationMode.ROLES)
                await pilot.pause()
                assert app.authorization_table.selected_key() == selected.key
        finally:
            api.release.set()


@pytest.mark.asyncio
async def test_namespace_picker_discards_authorization_parent_after_service_context_replacement(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("rbac roles --namespace other")
            await ready(app, AuthorizationMode.ROLES)
            original = app.workspace.authorization_request
            await app.run_command("ns")
            await wait_for(
                lambda: app.state.view_kind == "namespaces" and app.namespace_table.row_count == 3
            )
            app.workspace.connect("kuberich-test-Two")
            await wait_for(
                lambda: (
                    app.state.context == "kuberich-test-Two"
                    and app.state.status.name == "LIVE"
                    and app.state.scope is not None
                    and app.state.scope.session == app.sessions.observation.identity
                    and "namespace-default" in app.namespace_table.rows
                )
            )
            app.namespace_table.move_cursor(
                row=app.namespace_table.get_row_index("namespace-default")
            )
            await pilot.press("enter")
            await pods_ready(app, "default")
            assert app.state.context == "kuberich-test-Two"
            assert app.workspace.authorization_request is None
            assert app.sessions.observation.identity != original.session


@pytest.mark.asyncio
async def test_same_context_reconnection_recollects_informational_review_without_cached_allow(
    tmp_path,
):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test():
            await pods_ready(app)
            await app.run_command("can-i get pods example")
            await ready(app, AuthorizationMode.REVIEW)
            original = app.workspace.authorization_request
            api.allowed, api.denied = False, True
            app.navigator.connect(app.state.context, remember=False)
            await ready(app, AuthorizationMode.REVIEW)
            assert app.workspace.authorization_request.session != original.session
            assert app.workspace.authorization_request.intent == original.intent
            assert (
                app.workspace.store.observation.authorization.review.decision
                is ReviewDecision.DENIED
            )


@pytest.mark.asyncio
async def test_ordinary_namespace_picker_remains_an_ordinary_pod_navigation(tmp_path):
    api = AuthorizationAPI()
    async with authorization_api(api) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("ns")
            await wait_for(
                lambda: app.namespace_table.row_count == 3 and app.state.view_kind == "namespaces"
            )
            app.namespace_table.move_cursor(
                row=app.namespace_table.get_row_index("namespace-default")
            )
            await pilot.press("enter")
            await pods_ready(app, "default")
            assert app.workspace.authorization_request is None
