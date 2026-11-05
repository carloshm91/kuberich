"""Real loopback authorization task ownership, atomic scopes and revision retirement."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
    RbacSubject,
    RbacSubjectKind,
    ReviewDecision,
)
from kuberich.domain.connections import ConnectionRequest, ConnectionState, SessionObservation
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.views import ResourceSelection, ViewStatus
from kuberich.errors import AppError
from kuberich.services import authorization
from kuberich.services.authorization import ACCESS_PATH
from kuberich.services.authorization_workspace import AuthorizationWorkspace
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.contract.test_authorization_service import seeded_api
from tests.support.authorization import AuthorizationApi, auth_request, authorization_api
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for

pytestmark = pytest.mark.fast


def settled(owner):
    return (
        owner.store.observation.authorization is not None
        and not owner.authorization_collecting
        and not owner.store.observation.authorization.collecting
    )


def owner_for(tmp_path, url):
    return WorkspaceService(SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()))


@pytest.mark.asyncio
async def test_enter_retire_watch_publish_current_and_refresh_never_caches_allow(tmp_path):
    api = AuthorizationApi()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.ownership.watch_count == 1
            await owner.select_authorization(auth_request().intent)
            await wait_for(lambda: settled(owner))
            await wait_for(lambda: api.watchers == 0)
            first = owner.store.observation
            request = owner.authorization_request
            assert first.authorization.review.decision is ReviewDecision.ALLOWED
            assert owner.ownership.authorization_count == 1
            assert (
                owner.ownership.watch_count
                == owner.ownership.metrics_count
                == owner.ownership.pulse_count
                == owner.ownership.relationships_count
                == 0
            )
            api.status[ACCESS_PATH] = {"allowed": False, "denied": True}
            refresh = owner.refresh_authorization()
            assert owner.authorization_request.revision > request.revision
            assert owner.store.observation.authorization.review is None
            assert not owner.store.apply_authorization(first.revision, first.authorization)
            await refresh
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.authorization.review.decision is ReviewDecision.DENIED
            await owner.select_resource(ResourceSelection())
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert (
                owner.authorization_request is None
                and owner.store.observation.authorization is None
            )
            assert owner.ownership.authorization_count == 0 and owner.ownership.watch_count == 1
        finally:
            await owner.close()
        assert owner.ownership.close_complete and owner.sessions.client is None


@pytest.mark.asyncio
async def test_independent_header_question_scope_explicit_rescope_and_history_restore(tmp_path):
    api = AuthorizationApi()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            question = auth_request(namespace="other").intent
            await owner.select_authorization(question)
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.connection.namespace == "team"
            assert owner.authorization_request.intent.scope.namespace == "other"
            original = owner.authorization_request.intent
            await owner.select_namespace("default")
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.connection.namespace == "default"
            assert owner.authorization_request.intent.scope.namespace == "default"
            assert owner.authorization_request.intent.access.scope.namespace == "default"
            await owner.select_authorization(
                original, scope=NamespaceChoice("team"), preserve_intent=True
            )
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.connection.namespace == "team"
            assert owner.authorization_request.intent == original
            with pytest.raises(AppError):
                owner.select_authorization(original, preserve_intent=True)
            await owner.refresh_discovery()
            await wait_for(lambda: settled(owner))
            assert owner.authorization_request.intent == original
            assert owner.authorization_request.session == owner.sessions.observation.identity
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_sa_identity_allnamespace_selfrules_and_cluster_question_scope_are_preserved(
    tmp_path,
):
    api = AuthorizationApi()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            subject = RbacSubject(RbacSubjectKind.SERVICE_ACCOUNT, "account", "identity-ns")
            intent = AuthorizationIntent(
                AuthorizationMode.SUBJECT, auth_request().intent.scope, subject=subject
            )
            await owner.select_authorization(intent, scope=NamespaceChoice("other"))
            await wait_for(lambda: settled(owner))
            assert owner.authorization_request.intent.subject == subject
            assert owner.authorization_request.intent.scope.namespace == "other"
            await owner.select_authorization(auth_request(AuthorizationMode.SELF_RULES).intent)
            await wait_for(lambda: settled(owner))
            await owner.select_namespace(None)
            await wait_for(lambda: settled(owner))
            assert owner.authorization_request.intent.mode is AuthorizationMode.SUBJECTS
            assert (
                owner.authorization_request.intent.scope.kind
                is AuthorizationScopeKind.ALL_NAMESPACES
            )
            access = replace(
                auth_request().intent.access,
                scope=AuthorizationScope(AuthorizationScopeKind.CLUSTER, None),
                resource="nodes",
            )
            cluster = auth_request(access=access).intent
            await owner.select_authorization(cluster, scope=NamespaceChoice("team"))
            await wait_for(lambda: settled(owner))
            assert owner.authorization_request.intent == cluster
            assert owner.store.observation.connection.namespace == "team"
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_midpost_cancel_revision_context_and_samecontext_retry_are_owned(tmp_path):
    api = AuthorizationApi()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            api.held_path = ACCESS_PATH
            await owner.select_authorization(auth_request(namespace="other").intent)
            await api.held.wait()
            old = owner.authorization_request
            assert owner.authorization_collecting
            await owner.connect("kuberich-test-one")
            assert owner.authorization_request.intent == old.intent
            assert owner.authorization_request.session != old.session
            api.release.set()
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.authorization.request == owner.authorization_request
            await owner.connect("kuberich-test-Two")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert (
                owner.authorization_request is None
                and owner.store.observation.authorization is None
            )
            assert owner.ownership.authorization_count == 0
        finally:
            api.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_owned_matching_parser_is_drained_before_context_client_disposal(
    tmp_path, monkeypatch
):
    api = seeded_api()
    entered, release = threading.Event(), threading.Event()
    parse = authorization.parse_rbac_role

    def held(resource, record):
        entered.set()
        release.wait(5)
        return parse(resource, record)

    monkeypatch.setattr(authorization, "parse_rbac_role", held)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        await owner.connect("kuberich-test-one")
        await owner.select_authorization(auth_request(AuthorizationMode.ROLES).intent)
        closing = None
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            client = owner.sessions.client
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0.02)
            closing.cancel()
            await asyncio.sleep(0.01)
            assert not closing.done()
            assert owner.sessions.client is client
            assert owner.store.observation.authorization is None
            assert owner.authorization_request is None
            assert owner.ownership.authorization_count == 1
        finally:
            release.set()
            if closing is not None:
                with pytest.raises(asyncio.CancelledError):
                    await closing
            await owner.close()
        assert owner.sessions.client is None and owner.ownership.authorization_count == 0


@pytest.mark.asyncio
async def test_explicit_stop_clears_answer_and_close_or_unselected_actions_fail(tmp_path):
    api = AuthorizationApi()
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        with pytest.raises(AppError):
            owner.select_authorization(auth_request().intent)
        with pytest.raises(AppError):
            owner.refresh_authorization()
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_authorization(auth_request().intent)
            await wait_for(lambda: settled(owner))
            await owner.stop_authorization()
            assert (
                owner.authorization_request is None
                and owner.store.observation.authorization is None
            )
            assert owner.ownership.authorization_count == 0
            await owner.stop_authorization()
            await owner.select_authorization(auth_request().intent)
            await wait_for(lambda: settled(owner))
            await owner.select_pulse()
            await wait_for(lambda: owner.store.observation.pulse is not None)
            assert (
                owner.authorization_request is None
                and owner.store.observation.authorization is None
            )
        finally:
            await owner.close()
        with pytest.raises(AppError):
            owner.select_authorization(auth_request().intent)


@pytest.mark.asyncio
async def test_second_navigation_interrupt_drains_prior_parser_before_new_collection(
    tmp_path, monkeypatch
):
    api = seeded_api()
    entered, release = threading.Event(), threading.Event()
    parser = authorization.parse_rbac_role

    def held(resource, record):
        entered.set()
        release.wait(5)
        return parser(resource, record)

    monkeypatch.setattr(authorization, "parse_rbac_role", held)
    async with authorization_api(api) as url:
        owner = owner_for(tmp_path, url)
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_authorization(auth_request(AuthorizationMode.ROLES).intent)
            assert await asyncio.to_thread(entered.wait, 2)
            owner.select_namespace("other")
            await asyncio.sleep(0.02)
            operation = owner.select_authorization(auth_request().intent)
            await asyncio.sleep(0.02)
            assert (
                owner.authorization_collecting
                and owner.store.observation.authorization.review is None
            )
            release.set()
            await operation
            await wait_for(lambda: settled(owner))
            assert owner.store.observation.authorization.review.decision is ReviewDecision.ALLOWED
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_scoped_owner_reports_callback_failure_and_drops_stale_callback_before_publish(
    tmp_path,
):
    from kuberich.domain.views import ViewStore
    from tests.support.authorization import auth_resources, authorization_session

    api = AuthorizationApi()
    async with authorization_session(tmp_path, api) as session:
        request = auth_request()
        store = ViewStore()
        revision = store.begin(request.session.context)
        connection = SessionObservation(
            ConnectionState.CONNECTED, "Connected", request.session, "team"
        )
        store.connected(revision, connection)
        scoped = AuthorizationWorkspace()
        errors = []

        def fail():
            raise RuntimeError("owned publication failed")

        scoped.start(
            request,
            ResourceReader(session),
            auth_resources(),
            revision,
            store,
            lambda _: True,
            fail,
            lambda rev, error: errors.append((rev, str(error))),
        )
        await scoped.task
        assert errors == [(revision, "owned publication failed")]
        await scoped.stop()
        calls = 0

        def current(candidate):
            nonlocal calls
            calls += 1
            return calls < 3

        scoped.start(
            request,
            ResourceReader(session),
            auth_resources(),
            revision,
            store,
            current,
            lambda: errors.append("unexpected publication"),
            lambda *_: errors.append("unexpected failure"),
        )
        with pytest.raises(asyncio.CancelledError):
            await scoped.task
        assert errors == [(revision, "owned publication failed")]
        await scoped.stop()
        assert api.calls == []
