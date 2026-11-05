"""Actual loopback review POSTs, bounded parsing, auth identity and fail-closed transport."""

import asyncio
import threading
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.adapters import kubernetes
from kuberich.domain.authorization import (
    AuthorizationMode,
    EvidenceStatus,
    NonResourceAccess,
    ReviewDecision,
)
from kuberich.domain.connections import ConnectionProblem, ConnectionState, HttpProblem
from kuberich.domain.resource_queries import ResourceQuery
from kuberich.errors import AppError
from kuberich.services.authorization import (
    ACCESS_PATH,
    IDENTITY_PATH,
    RULES_PATH,
    AuthorizationReader,
)
from tests.support.authorization import AuthorizationApi, auth_request, authorization_session

pytestmark = pytest.mark.fast


@pytest.mark.asyncio
async def test_exact_current_identity_resource_nonresource_and_rules_posts(tmp_path):
    api = AuthorizationApi()
    async with authorization_session(
        tmp_path,
        api,
        user={"token": "synthetic-token", "as": "selected-user", "as-groups": ["selected-group"]},
    ) as session:
        reviews = AuthorizationReader(session)
        request = auth_request()
        query = ResourceQuery(
            field_selector="metadata.name==one,spec.nodeName=node-a",
            label_selector="app in (api,web)",
            compact=True,
        )
        access = replace(request.intent.access, name=None, subresource="status", query=query)
        request = replace(request, intent=replace(request.intent, access=access))
        assert request.intent.access.name == "one"
        identity = await reviews.identity(request)
        assert identity.identity.username == "fixture-user"
        assert identity.identity.groups == ("fixture-group",)
        assert (await reviews.review(request)).decision is ReviewDecision.ALLOWED
        nonresource = auth_request(access=NonResourceAccess("get", "/healthz"))
        assert (await reviews.review(nonresource)).decision is ReviewDecision.ALLOWED
        rules = await reviews.rules(auth_request(AuthorizationMode.SELF_RULES))
        assert rules.status is EvidenceStatus.READY and not rules.incomplete
        assert rules.rules[0].resources == ("pods",)
        assert [(method, path) for method, path, _, _ in api.calls] == [
            ("POST", IDENTITY_PATH),
            ("POST", ACCESS_PATH),
            ("POST", ACCESS_PATH),
            ("POST", RULES_PATH),
        ]
        assert api.calls[0][3] == {
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "SelfSubjectReview",
            "spec": {},
        }
        assert api.calls[1][3]["spec"] == {
            "resourceAttributes": {
                "namespace": "team",
                "verb": "list",
                "group": "",
                "version": "v1",
                "resource": "pods",
                "name": "one",
                "subresource": "status",
                "fieldSelector": {"rawSelector": query.field_selector},
                "labelSelector": {"rawSelector": query.label_selector},
            }
        }
        assert api.calls[2][3]["spec"] == {
            "nonResourceAttributes": {"verb": "get", "path": "/healthz"}
        }
        assert api.calls[3][3]["spec"] == {"namespace": "team"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,decision,evidence",
    [
        (
            {"allowed": True, "evaluationError": "supplemental"},
            ReviewDecision.ALLOWED,
            EvidenceStatus.READY,
        ),
        ({"allowed": False, "denied": True}, ReviewDecision.DENIED, EvidenceStatus.READY),
        ({"allowed": False}, ReviewDecision.NO_ALLOW, EvidenceStatus.READY),
        ({"allowed": True, "denied": True}, ReviewDecision.UNKNOWN, EvidenceStatus.INVALID),
        ({"allowed": "true"}, ReviewDecision.UNKNOWN, EvidenceStatus.INVALID),
        ({}, ReviewDecision.UNKNOWN, EvidenceStatus.INVALID),
    ],
)
async def test_authoritative_decision_is_exact_strict_and_never_inferred(
    tmp_path, status, decision, evidence
):
    api = AuthorizationApi()
    api.status[ACCESS_PATH] = status
    async with authorization_session(tmp_path, api) as session:
        review = await AuthorizationReader(session).review(auth_request())
        assert (review.decision, review.status) == (decision, evidence)
        if "evaluationError" in status:
            assert review.warnings == ("supplemental",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,status",
    [
        (403, EvidenceStatus.FORBIDDEN),
        (404, EvidenceStatus.UNAVAILABLE),
        (405, EvidenceStatus.UNAVAILABLE),
        (500, EvidenceStatus.FAILED),
    ],
)
@pytest.mark.parametrize(
    "operation,path", [("identity", IDENTITY_PATH), ("review", ACCESS_PATH), ("rules", RULES_PATH)]
)
async def test_failed_reviews_preserve_unknown_provenance_and_omit_server_messages(
    tmp_path, code, status, operation, path
):
    async def handler(request):
        assert request.method == "POST" and request.path == path
        return web.json_response({"message": "PRIVATE server Bearer fixture-token"}, status=code)

    async with authorization_session(tmp_path, handler) as session:
        request = auth_request(
            AuthorizationMode.SELF_RULES if operation == "rules" else AuthorizationMode.REVIEW
        )
        result = await getattr(AuthorizationReader(session), operation)(request)
        assert result.status is status
        assert "PRIVATE" not in repr(result) and "fixture-token" not in repr(result)
        if operation == "review":
            assert result.decision is ReviewDecision.UNKNOWN


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,payload",
    [
        (IDENTITY_PATH, {"status": {}}),
        (IDENTITY_PATH, {"status": {"userInfo": {"username": "u", "groups": "bad"}}}),
        (IDENTITY_PATH, {"status": {"userInfo": {"username": 1}}}),
        (IDENTITY_PATH, {"status": {"userInfo": {"username": "u", "uid": 2}}}),
        (RULES_PATH, {"status": {"incomplete": "true"}}),
        (RULES_PATH, {"status": {"resourceRules": [{}]}}),
        (RULES_PATH, {"status": {"resourceRules": "bad"}}),
        (RULES_PATH, {"status": {"evaluationError": 3}}),
        (ACCESS_PATH, {"kind": "Other", "status": {"allowed": True}}),
        (ACCESS_PATH, {"status": []}),
    ],
)
async def test_malformed_review_payloads_are_invalid_evidence(tmp_path, path, payload):
    async def handler(request):
        body = await request.json()
        return web.json_response(
            {"apiVersion": body["apiVersion"], "kind": body["kind"], **payload}
        )

    async with authorization_session(tmp_path, handler) as session:
        reader = AuthorizationReader(session)
        request = auth_request(
            AuthorizationMode.SELF_RULES if path == RULES_PATH else AuthorizationMode.REVIEW
        )
        result = await (
            reader.rules(request)
            if path == RULES_PATH
            else reader.identity(request)
            if path == IDENTITY_PATH
            else reader.review(request)
        )
        assert result.status is EvidenceStatus.INVALID


@pytest.mark.asyncio
async def test_incomplete_rules_retain_safe_evaluation_warning_and_nonresource_rules(tmp_path):
    api = AuthorizationApi()
    api.status[RULES_PATH] = {
        "incomplete": True,
        "evaluationError": "Bearer abc123\u001b[31m detail",
        "nonResourceRules": [{"verbs": ["get"], "nonResourceURLs": ["/healthz*"]}],
    }
    async with authorization_session(tmp_path, api) as session:
        result = await AuthorizationReader(session).rules(
            auth_request(AuthorizationMode.SELF_RULES)
        )
        assert result.incomplete and result.status is EvidenceStatus.READY
        assert result.rules[0].non_resource_urls == ("/healthz*",)
        assert "abc123" not in repr(result) and "\u001b" not in repr(result)
        assert any("cannot establish denial" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_post_preserves_auth_and_impersonation_and_tokenfile_single_retry(tmp_path):
    token = tmp_path / "token"
    token.write_text("first-token")
    calls = []

    async def handler(request):
        calls.append((dict(request.headers), await request.json()))
        if len(calls) == 1:
            token.write_text("second-token")
            return web.json_response({}, status=401)
        return web.json_response({"ok": True}, status=202)

    async with authorization_session(
        tmp_path,
        handler,
        user={"tokenFile": str(token), "as": "effective-user", "as-groups": ["effective-group"]},
    ) as session:
        body = {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview", "spec": {}}
        assert await session.review_json(IDENTITY_PATH, body) == {"ok": True}
        assert [headers["Authorization"] for headers, _ in calls] == [
            "Bearer first-token",
            "Bearer second-token",
        ]
        assert all(
            headers["Impersonate-User"] == "effective-user"
            and headers["Impersonate-Group"] == "effective-group"
            for headers, _ in calls
        )
        assert calls[0][1] == calls[1][1] == body
        assert all(
            headers["Content-Type"] == "application/json"
            and headers["Accept-Encoding"] == "identity"
            for headers, _ in calls
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "path",
        "querypath",
        "kind",
        "version",
        "metadata",
        "spec",
        "sar",
        "namespace",
        "selector",
        "structured",
        "empty",
        "maximum",
        "maximum-bool",
        "both",
        "unknown",
    ],
)
async def test_fixed_post_port_rejects_unsupported_inputs_before_any_io(tmp_path, change):
    api = AuthorizationApi()
    path, maximum = ACCESS_PATH, 1048576
    body = {
        "apiVersion": "authorization.k8s.io/v1",
        "kind": "SelfSubjectAccessReview",
        "spec": {
            "resourceAttributes": {
                "namespace": "team",
                "verb": "list",
                "group": "",
                "version": "v1",
                "resource": "pods",
            }
        },
    }
    attrs = body["spec"]["resourceAttributes"]
    if change == "path":
        path = "/api/v1/namespaces/team/pods"
    elif change == "querypath":
        path += "?x=1"
    elif change == "kind":
        body["kind"] = "SubjectAccessReview"
    elif change == "version":
        body["apiVersion"] = "authorization.k8s.io/v1beta1"
    elif change == "metadata":
        body["metadata"] = {"name": "extra"}
    elif change == "spec":
        body["spec"] = []
    elif change == "sar":
        body["spec"]["user"] = "other"
    elif change == "namespace":
        attrs["namespace"] = "INVALID"
    elif change == "selector":
        attrs["fieldSelector"] = {"rawSelector": "metadata.name in (a,b)"}
    elif change == "structured":
        attrs["labelSelector"] = {"requirements": []}
    elif change == "empty":
        attrs["resource"] = ""
    elif change == "maximum":
        maximum = 1048577
    elif change == "maximum-bool":
        maximum = True
    elif change == "both":
        body["spec"]["nonResourceAttributes"] = {"verb": "get", "path": "/healthz"}
    else:
        attrs["unexpected"] = "bad"
    async with authorization_session(tmp_path, api) as session:
        with pytest.raises(AppError):
            await session.review_json(path, body, max_bytes=maximum)
        assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response,state",
    [
        (b"{bad", ConnectionState.API_ERROR),
        (b"[]", ConnectionState.API_ERROR),
        (b'{"large":"' + b"x" * 100 + b'"}', ConnectionState.API_ERROR),
    ],
)
async def test_review_response_bytes_and_shape_are_bounded(tmp_path, response, state):
    async def handler(request):
        return web.Response(body=response, content_type="application/json")

    async with authorization_session(tmp_path, handler) as session:
        with pytest.raises(ConnectionProblem) as error:
            await session.review_json(
                IDENTITY_PATH,
                {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview", "spec": {}},
                max_bytes=32,
            )
        assert error.value.state is state


@pytest.mark.asyncio
async def test_redirect_is_not_followed_and_http_failure_is_typed(tmp_path):
    called = []

    async def handler(request):
        called.append(request.path)
        return web.Response(status=307, headers={"Location": "/forbidden-target"})

    async with authorization_session(tmp_path, handler) as session:
        with pytest.raises(HttpProblem) as error:
            await session.review_json(
                IDENTITY_PATH,
                {"apiVersion": "authentication.k8s.io/v1", "kind": "SelfSubjectReview", "spec": {}},
            )
        assert error.value.status == 307 and called == [IDENTITY_PATH]


@pytest.mark.asyncio
async def test_review_cancellation_drains_actual_owned_json_decoder(tmp_path, monkeypatch):
    api = AuthorizationApi()
    entered, release = threading.Event(), threading.Event()
    decode = kubernetes.decode_json

    def held(data):
        entered.set()
        release.wait(5)
        return decode(data)

    monkeypatch.setattr(kubernetes, "decode_json", held)
    async with authorization_session(tmp_path, api) as session:
        task = asyncio.create_task(AuthorizationReader(session).review(auth_request()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0.01)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_direct_wrong_mode_review_rejects_without_io(tmp_path):
    api = AuthorizationApi()
    async with authorization_session(tmp_path, api) as session:
        reader = AuthorizationReader(session)
        with pytest.raises(AppError):
            await reader.review(auth_request(AuthorizationMode.SUBJECTS))
        with pytest.raises(AppError):
            await reader.rules(auth_request(AuthorizationMode.SUBJECTS, namespace=None))
        assert api.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selector", ["metadata.name =demo", " metadata.name=demo", "metadata.name=demo "]
)
async def test_literal_field_selector_cannot_be_normalized_into_a_different_review(
    tmp_path, selector
):
    api = AuthorizationApi()
    async with authorization_session(tmp_path, api) as session:
        access = replace(auth_request().intent.access, query=ResourceQuery(field_selector=selector))
        with pytest.raises(AppError):
            await AuthorizationReader(session).review(auth_request(access=access))
        assert api.calls == []


@pytest.mark.asyncio
async def test_actual_review_timeout_is_unknown_and_cancellation_does_not_become_denial(tmp_path):
    api = AuthorizationApi()
    api.held_path = ACCESS_PATH
    async with authorization_session(tmp_path, api, timeout=0.03) as session:
        try:
            result = await AuthorizationReader(session).review(auth_request())
            assert (
                result.decision is ReviewDecision.UNKNOWN and result.status is EvidenceStatus.FAILED
            )
        finally:
            api.release.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("trusted", [True, False])
async def test_review_post_uses_verified_tls_and_owned_proxy_without_exposing_credentials(
    tmp_path, owned_test_proxies, trusted
):
    from kuberich.adapters.kubernetes import KubernetesSession
    from tests.support.authorization import authorization_api
    from tests.support.connections import catalog_fixture, certificate
    from tests.support.http_proxy import http_proxy

    api = AuthorizationApi()
    tls, material = certificate(tmp_path)
    async with authorization_api(api, tls=tls) as url, http_proxy(url) as (proxy, witness):
        owned_test_proxies.add(proxy)
        cluster = {"proxy-url": proxy}
        if trusted:
            cluster["certificate-authority-data"] = material["certificate-authority-data"]
        session = KubernetesSession(
            catalog_fixture(tmp_path, url, cluster=cluster).select("kuberich-test-one"), 2
        )
        try:
            await session.open()
            result = await AuthorizationReader(session).review(auth_request())
            if trusted:
                assert result.decision is ReviewDecision.ALLOWED
                assert api.calls[0][:2] == ("POST", ACCESS_PATH)
            else:
                assert (
                    result.decision is ReviewDecision.UNKNOWN
                    and result.status is EvidenceStatus.FAILED
                )
                assert api.calls == []
            assert witness.requests and witness.requests[0][0] == "CONNECT"
        finally:
            await session.close()
    assert not witness.active
