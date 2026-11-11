"""Finite Helm destination reads through an owned real HTTP Kubernetes session."""

import json
from contextlib import asynccontextmanager

import pytest
from aiohttp import web

from kuberich.adapters.helm_live import (
    live_objects,
    manifest_destinations,
    namespace_identity,
    require_release_ownership,
)
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.connections import ConnectionProblem, HttpProblem
from kuberich.domain.helm import HelmDriver, HelmProblem, HelmReleaseKey, HelmRequest, HelmScope
from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from tests.support.connections import catalog_fixture
from tests.support.history import history_http
from tests.support.resources import descriptor, legacy_roots

LIMIT = 8 * 1024 * 1024
NAMESPACE_PATH = "/api/v1/namespaces/team"
CONFIGMAPS = NAMESPACE_PATH + "/configmaps/"


def document(name="settings", *, namespace="team", api="v1", kind="ConfigMap"):
    metadata = {"name": name}
    if namespace is not None:
        metadata["namespace"] = namespace
    return {"apiVersion": api, "kind": kind, "metadata": metadata}


def observed(name="settings", *, namespace="team", api="v1", kind="ConfigMap", size=None):
    result = document(name, namespace=namespace, api=api, kind=kind)
    result["metadata"].update(
        uid="owned-" + name,
        resourceVersion="opaque/rv",
        labels={"app.kubernetes.io/managed-by": "Helm"},
        annotations={
            "meta.helm.sh/release-name": "owned-release",
            "meta.helm.sh/release-namespace": "team",
        },
    )
    result["data"] = {"private": "synthetic-private-value", "padding": ""}
    if size is not None:
        result["data"]["padding"] = "x" * (size - len(json.dumps(result).encode()))
        assert len(json.dumps(result).encode()) == size
    return result


class LiveApi:
    def __init__(self):
        self.routes = {path: {"body": body} for path, body in legacy_roots().items()}
        self.routes["/api/v1"]["body"]["resources"] = [
            descriptor("configmaps", kind="ConfigMap"),
            descriptor("nodes", kind="Node", namespaced=False),
            descriptor("namespaces", kind="Namespace", namespaced=False),
        ]
        self.routes["/apis"]["body"]["groups"] = [
            {
                "name": "apps",
                "versions": [{"groupVersion": "apps/v1", "version": "v1"}],
            }
        ]
        self.routes["/apis/apps/v1"] = {
            "body": {
                "kind": "APIResourceList",
                "groupVersion": "apps/v1",
                "resources": [descriptor("deployments", kind="Deployment")],
            }
        }
        self.routes[NAMESPACE_PATH] = {
            "body": {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {"name": "team", "uid": "owned-namespace", "resourceVersion": "1"},
                "status": {"phase": "Active"},
            }
        }
        self.requests = []
        self.valid = True
        self.invalidate_on = None

    async def handle(self, request):
        self.requests.append((request.method, request.path, dict(request.query)))
        if request.path == self.invalidate_on:
            self.valid = False
        route = self.routes.get(request.path, {"body": {}, "status": 404})
        return web.json_response(route["body"], status=route.get("status", 200))

    def guard(self):
        if not self.valid:
            raise AppError("Captured session is stale.")

    def body_reads(self):
        discovery = {"/api", "/apis", "/api/v1", "/apis/apps/v1"}
        return [path for _, path, _ in self.requests if path not in discovery]


@asynccontextmanager
async def live_source(directory, *, namespace="team"):
    api = LiveApi()
    async with history_http(api.handle) as origin:
        session = KubernetesSession(
            catalog_fixture(directory, origin).select("kuberich-test-one"), 3
        )
        await session.open()
        request = HelmRequest(
            HelmScope(SessionIdentity(session.context.name, 1), namespace, HelmDriver.SECRET), 1
        )
        try:
            yield api, session, request
        finally:
            await session.close()


@pytest.mark.asyncio
async def test_destinations_resolve_exact_named_scope_without_fetching_any_object_bodies(tmp_path):
    async with live_source(tmp_path) as (api, session, request):
        destinations = await manifest_destinations(
            session,
            request,
            (
                document(namespace=None),
                document("worker", namespace=None, kind="Node"),
                document("workload", namespace="other", api="apps/v1", kind="Deployment"),
            ),
            api.guard,
        )
        assert [item.path for item in destinations] == [
            CONFIGMAPS + "settings",
            "/api/v1/nodes/worker",
            "/apis/apps/v1/namespaces/other/deployments/workload",
        ]
        assert destinations[1].label == "v1/Node/(cluster)/worker"
        assert destinations[2].label == "apps/v1/Deployment/other/workload"
        assert api.body_reads() == []
        assert all(method == "GET" and not query for method, _, query in api.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, ""])
async def test_undeclared_namespace_uses_explicit_default_before_request_scope(tmp_path, declared):
    async with live_source(tmp_path) as (api, session, request):
        result = await manifest_destinations(
            session,
            request,
            (document(namespace=declared),),
            api.guard,
            default_namespace="captured-release",
        )
        assert result[0].path == "/api/v1/namespaces/captured-release/configmaps/settings"
        assert api.body_reads() == []


@pytest.mark.asyncio
async def test_empty_manifest_and_document_limit_do_not_contact_discovery_or_object_endpoints(
    tmp_path,
):
    async with live_source(tmp_path) as (api, session, request):
        assert await manifest_destinations(session, request, (), api.guard) == ()
        with pytest.raises(AppError, match="document limit"):
            await live_objects(
                session, request, tuple(document(str(i)) for i in range(257)), api.guard
            )
        assert api.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "target,scope",
    [
        (document(namespace=None), None),
        (document(namespace=42), "team"),
        (document("node", namespace="team", kind="Node"), "team"),
        (document("bad/name"), "team"),
        (document(namespace="../foreign"), "team"),
        ({"apiVersion": "v1", "kind": "ConfigMap", "metadata": None}, "team"),
        ({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"generateName": "job-"}}, "team"),
    ],
)
async def test_scope_and_concrete_identity_are_required_before_body_reads(tmp_path, target, scope):
    async with live_source(tmp_path, namespace=scope) as (api, session, request):
        with pytest.raises(AppError):
            await live_objects(session, request, (target,), api.guard)
        assert api.body_reads() == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", ["duplicate-destination", "duplicate-discovery", "unknown", "ambiguous", "no-get"]
)
async def test_discovery_must_uniquely_serve_a_readable_type(tmp_path, fault):
    async with live_source(tmp_path) as (api, session, request):
        docs = (document(),)
        if fault == "duplicate-destination":
            docs += (document(),)
        elif fault == "unknown":
            docs = (document(api="missing.example/v1", kind="Missing"),)
        elif fault == "ambiguous":
            api.routes["/api/v1"]["body"]["resources"].append(
                descriptor("otherconfigmaps", kind="ConfigMap")
            )
        elif fault == "duplicate-discovery":
            api.routes["/api/v1"]["body"]["resources"].append(
                descriptor("configmaps", kind="ConfigMap")
            )
        else:
            api.routes["/api/v1"]["body"]["resources"][0]["verbs"] = ["list", "watch"]
        with pytest.raises(AppError):
            await live_objects(session, request, docs, api.guard)
        assert api.body_reads() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 500])
async def test_unreadable_matching_discovery_cannot_be_treated_as_absence(tmp_path, status):
    async with live_source(tmp_path) as (api, session, request):
        api.routes["/api/v1"] = {"status": status, "body": {"message": "synthetic-private-value"}}
        with pytest.raises(AppError) as error:
            await live_objects(session, request, (document(),), api.guard)
        assert "synthetic-private-value" not in str(error.value)
        assert api.body_reads() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(403, "forbidden"), (500, "unavailable")])
async def test_named_get_rbac_or_server_failure_refuses_complete_review(tmp_path, status, expected):
    async with live_source(tmp_path) as (api, session, request):
        api.routes[CONFIGMAPS + "settings"] = {
            "status": status,
            "body": {"message": "synthetic-private-value"},
        }
        with pytest.raises(HelmProblem) as error:
            await live_objects(session, request, (document(),), api.guard)
        assert error.value.kind == expected
        assert "synthetic-private-value" not in str(error.value)
        assert api.body_reads() == [CONFIGMAPS + "settings"]


@pytest.mark.asyncio
async def test_only_actual_404_is_an_absent_live_destination(tmp_path):
    async with live_source(tmp_path) as (api, session, request):
        result = await live_objects(session, request, (document(),), api.guard)
        assert len(result) == 1
        assert (result[0].body, result[0].uid, result[0].resource_version) == (None, None, None)
        assert result[0].retained_bytes == 0
        require_release_ownership(result[0], HelmReleaseKey("team", "owned-release"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("apiVersion", "apps/v1"),
        ("kind", "Secret"),
        ("metadata", None),
        ("name", "foreign"),
        ("namespace", "foreign"),
        ("uid", None),
        ("uid", 123),
        ("uid", ""),
        ("uid", "control\nidentity"),
        ("resourceVersion", None),
        ("resourceVersion", 123),
        ("resourceVersion", ""),
    ],
)
async def test_named_response_must_match_identity_and_have_stable_uid_and_rv(
    tmp_path, field, value
):
    body = observed()
    if field in {"apiVersion", "kind", "metadata"}:
        body[field] = value
    else:
        body["metadata"][field] = value
    async with live_source(tmp_path) as (api, session, request):
        api.routes[CONFIGMAPS + "settings"] = {"body": body}
        with pytest.raises(AppError) as error:
            await live_objects(session, request, (document(),), api.guard)
        assert "synthetic-private-value" not in str(error.value)


@pytest.mark.asyncio
async def test_namespaced_and_cluster_live_objects_preserve_identity_and_release_ownership(
    tmp_path,
):
    async with live_source(tmp_path) as (api, session, request):
        api.routes[CONFIGMAPS + "settings"] = {"body": observed()}
        api.routes["/api/v1/nodes/worker"] = {
            "body": observed("worker", namespace=None, kind="Node")
        }
        result = await live_objects(
            session,
            request,
            (document(), document("worker", namespace="", kind="Node")),
            api.guard,
        )
        assert result[0].uid == "owned-settings" and result[0].resource_version == "opaque/rv"
        assert result[1].namespace is None and result[1].uid == "owned-worker"
        assert "synthetic-private-value" not in repr(result)
        for live in result:
            require_release_ownership(live, HelmReleaseKey("team", "owned-release"))
            with pytest.raises(AppError, match="ownership"):
                require_release_ownership(live, HelmReleaseKey("team", "foreign"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("apiVersion", "foreign/v1"),
        ("kind", "ConfigMap"),
        ("metadata", None),
        ("name", "foreign"),
        ("deletionTimestamp", "2026-11-11T00:00:00Z"),
        ("status", None),
        ("phase", "Terminating"),
        ("uid", None),
    ],
)
async def test_namespace_identity_requires_matching_existing_active_namespace(
    tmp_path, field, value
):
    async with live_source(tmp_path) as (api, session, _request):
        body = api.routes[NAMESPACE_PATH]["body"]
        if field in {"apiVersion", "kind", "metadata", "status"}:
            body[field] = value
        elif field == "phase":
            body["status"][field] = value
        else:
            body["metadata"][field] = value
        with pytest.raises(AppError):
            await namespace_identity(session, "team", api.guard)
        assert api.body_reads() == [NAMESPACE_PATH]


@pytest.mark.asyncio
async def test_absent_namespace_is_not_created_or_replaced_by_another_selection(tmp_path):
    async with live_source(tmp_path) as (api, session, _request):
        api.routes[NAMESPACE_PATH] = {"body": {}, "status": 404}
        with pytest.raises(HttpProblem) as error:
            await namespace_identity(session, "team", api.guard)
        assert error.value.status == 404
        assert api.requests == [("GET", NAMESPACE_PATH, {})]


@pytest.mark.asyncio
async def test_captured_generation_guards_run_before_and_after_owned_reads(tmp_path):
    async with live_source(tmp_path) as (api, session, request):
        assert await namespace_identity(session, "team", api.guard) == "owned-namespace"
        api.requests.clear()
        api.valid = False
        with pytest.raises(AppError, match="stale"):
            await live_objects(session, request, (document(),), api.guard)
        assert api.requests == []
        api.valid, api.invalidate_on = True, NAMESPACE_PATH
        with pytest.raises(AppError, match="stale"):
            await namespace_identity(session, "team", api.guard)
        api.valid, api.invalidate_on = True, "/api/v1"
        with pytest.raises(AppError, match="stale"):
            await live_objects(session, request, (document(),), api.guard)
        assert CONFIGMAPS + "settings" not in api.body_reads()
        api.valid, api.invalidate_on = True, CONFIGMAPS + "settings"
        with pytest.raises(AppError, match="stale"):
            await live_objects(session, request, (document(),), api.guard)


@pytest.mark.asyncio
async def test_combined_desired_old_reads_reuse_exact_paths_and_charge_only_new_destinations(
    tmp_path,
):
    async with live_source(tmp_path) as (api, session, request):
        desired = await live_objects(
            session, request, tuple(document(f"cm-{i}") for i in range(128)), api.guard
        )
        old = await live_objects(
            session,
            request,
            tuple(document(f"cm-{i}") for i in range(64, 256)),
            api.guard,
            known=desired,
        )
        assert len(old) == 192 and old[0] is desired[64]
        assert len(api.body_reads()) == len(set(api.body_reads())) == 256
        before = list(api.body_reads())
        with pytest.raises(AppError, match="combined document limit"):
            await live_objects(
                session, request, (document("cm-256"),), api.guard, known=desired + old[64:]
            )
        assert api.body_reads() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("excess", [-1, 0, 1])
async def test_combined_byte_budget_includes_known_desired_bodies(tmp_path, excess):
    async with live_source(tmp_path) as (api, session, request):
        first_size = 1024 * 1024
        api.routes[CONFIGMAPS + "desired"] = {"body": observed("desired", size=first_size)}
        api.routes[CONFIGMAPS + "old"] = {"body": observed("old", size=LIMIT - first_size + excess)}
        known = await live_objects(session, request, (document("desired"),), api.guard)
        assert known[0].retained_bytes == first_size
        if excess == -1:
            result = await live_objects(
                session,
                request,
                (document("desired"), document("old")),
                api.guard,
                known=known,
            )
            assert result[0] is known[0]
            assert sum(item.retained_bytes for item in result) == LIMIT - 1
        else:
            with pytest.raises((AppError, ConnectionProblem)):
                await live_objects(session, request, (document("old"),), api.guard, known=known)
        assert api.body_reads() == [CONFIGMAPS + "desired", CONFIGMAPS + "old"]
