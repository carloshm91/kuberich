"""Real loopback graph ownership, revision invalidation, cache and client retirement."""

import asyncio
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.relationships import RelationshipMode, RelationshipStatus
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.views import ResourceSelection, ViewStatus
from kuberich.errors import AppError
from kuberich.services import relationships
from kuberich.services.relationships import RelationshipService
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, descriptor, item, legacy_roots
from tests.support.workspace import stable_watch, wait_for, workspace_api

pytestmark = pytest.mark.fast


def roots():
    values = legacy_roots()
    values["/api/v1"]["resources"].append(descriptor("configmaps", kind="ConfigMap"))
    values["/apis"]["groups"] = [
        {
            "name": "owned.example.test",
            "versions": [{"groupVersion": "owned.example.test/v1", "version": "v1"}],
            "preferredVersion": {"groupVersion": "owned.example.test/v1", "version": "v1"},
        }
    ]
    values["/apis/owned.example.test/v1"] = {
        "groupVersion": "owned.example.test/v1",
        "resources": [descriptor("widgets", kind="Widget")],
    }
    return values


def pod(namespace="team", *, uid="owned-one"):
    value = item(namespace=namespace, uid=uid)
    value["metadata"]["ownerReferences"] = [
        {
            "apiVersion": "owned.example.test/v1",
            "kind": "Widget",
            "name": "first",
            "uid": "owned-first",
            "controller": True,
        }
    ]
    return value


def widget(name):
    value = {**item(name), "apiVersion": "owned.example.test/v1", "kind": "Widget"}
    if name == "first":
        value["metadata"]["ownerReferences"] = [
            {
                "apiVersion": "owned.example.test/v1",
                "kind": "Widget",
                "name": "second",
                "uid": "owned-second",
            }
        ]
    return value


async def namespace_handler(request):
    return namespaces("team", "default")


class Api:
    def __init__(self):
        self.calls = []
        self.watchers = 0
        self.root_uid = "owned-one"
        self.hold = False
        self.held = asyncio.Event()
        self.release = asyncio.Event()

    async def __call__(self, request):
        self.calls.append((request.path, dict(request.query)))
        if "watch" in request.query:
            self.watchers += 1
            try:
                return await stable_watch(request)
            finally:
                self.watchers -= 1
        if "/widgets/" in request.path:
            return web.json_response(widget(request.path.rsplit("/", 1)[-1]))
        if request.path.endswith("/pods/one"):
            if self.hold:
                self.held.set()
                await self.release.wait()
            return web.json_response(pod(uid=self.root_uid))
        namespace = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        if request.path.endswith("/pods"):
            return web.json_response(collection(pod(namespace)))
        if request.path.endswith("/configmaps/one"):
            return web.json_response(
                {**item(), "kind": "ConfigMap", "data": {"key": "PRIVATE-fixture-value"}}
            )
        return web.json_response(collection())


def target(owner):
    observation = owner.store.observation
    record = observation.snapshot.items[0]
    return ResourceTarget(
        observation.connection.identity,
        observation.scope.resource.group,
        observation.scope.resource.name,
        record.namespace,
        record.name,
        record.uid,
    ), observation.scope.resource


def ready(owner, *, name="first"):
    snapshot = owner.store.observation.relationships
    return (
        snapshot is not None
        and not owner.relationship_collecting
        and owner.store.observation.status is ViewStatus.LIVE
        and any(row.ref.name == name for row in snapshot.rows)
    )


@pytest.mark.asyncio
async def test_workspace_expansion_cache_shared_budget_refresh_and_ordinary_watch_retirement(
    tmp_path,
):
    api = Api()
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        subscription = owner.subscribe()
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            assert owner.ownership.watch_count == 1
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await wait_for(lambda: ready(owner))
            await wait_for(lambda: api.watchers == 0)
            first = owner.store.observation
            graph = first.relationships
            assert graph.requests_used == 2
            assert not owner.relationship_collecting
            assert owner.ownership.relationships_count == 1
            assert (
                owner.ownership.watch_count
                == owner.ownership.metrics_count
                == owner.ownership.pulse_count
                == 0
            )
            assert (await anext(subscription)) is first
            child = next(row for row in graph.rows if row.ref.name == "first")
            child_source = next(
                source for source in graph.sources if source.family.endswith("/first")
            )
            operation = owner.set_relationship_expanded(child.path, True)
            assert owner.relationship_request.revision > graph.request.revision
            assert owner.store.observation.relationships.request == owner.relationship_request
            assert not owner.store.apply_relationships(first.revision, graph)
            await operation
            await wait_for(lambda: ready(owner, name="second"))
            second = owner.store.observation.relationships
            assert second.requests_used == 4
            assert (
                next(
                    source for source in second.sources if source.family.endswith("/first")
                ).observed_at
                == child_source.observed_at
            )
            await owner.set_relationship_expanded(child.path, False)
            await wait_for(
                lambda: ready(owner) and owner.store.observation.relationships.requests_used == 5
            )
            assert not any(
                row.ref.name == "second" for row in owner.store.observation.relationships.rows
            )
            await owner.set_relationship_expanded(child.path, True)
            await wait_for(
                lambda: (
                    ready(owner, name="second")
                    and owner.store.observation.relationships.requests_used == 6
                )
            )
            assert sum(path.endswith("/widgets/second") for path, _ in api.calls) == 1
            await owner.refresh_relationships()
            await wait_for(
                lambda: (
                    ready(owner, name="second")
                    and owner.store.observation.relationships.requests_used == 3
                )
            )
            assert sum(path.endswith("/widgets/second") for path, _ in api.calls) == 2
            await owner.refresh_discovery()
            await wait_for(
                lambda: (
                    ready(owner, name="second")
                    and owner.store.observation.relationships.requests_used == 3
                )
            )
            assert sum(path.endswith("/widgets/second") for path, _ in api.calls) == 3
            await owner.select_resource(ResourceSelection())
            await wait_for(
                lambda: (
                    owner.store.observation.status is ViewStatus.LIVE
                    and owner.store.observation.snapshot is not None
                )
            )
            assert (
                owner.relationship_request is None and owner.store.observation.relationships is None
            )
            assert owner.ownership.relationships_count == 0 and owner.ownership.watch_count == 1
        finally:
            await owner.close()
        assert (
            owner.ownership.close_complete
            and owner.ownership.relationships_count
            == owner.ownership.watch_count
            == owner.ownership.subscription_count
            == 0
        )
        assert owner.sessions.client is None
        assert not owner.relationship_collecting


@pytest.mark.asyncio
async def test_pending_root_context_switch_rejects_stale_snapshot_and_retires_captured_client(
    tmp_path,
):
    api = Api()
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            captured = owner.sessions.client
            private = Path(captured.directory.name)
            api.hold = True
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await asyncio.wait_for(api.held.wait(), 5)
            assert owner.relationship_collecting
            previous = owner.store.observation
            pending = owner.connect("kuberich-test-Two")
            assert (
                owner.relationship_request is None and owner.store.observation.relationships is None
            )
            assert not owner.store.apply_relationships(previous.revision, previous.relationships)
            await pending
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            api.release.set()
            assert (
                owner.sessions.client is not captured
                and captured.api is None
                and not private.exists()
            )
            assert owner.store.observation.context == "kuberich-test-Two"
            assert owner.store.observation.relationships is None
            assert owner.ownership.relationships_count == 0 and owner.ownership.watch_count == 1
            with pytest.raises(AppError, match="obsolete connection"):
                owner.select_relationships(root, resource, RelationshipMode.XRAY)
        finally:
            api.release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_retry_same_context_rebinds_session_preserves_root_uid_and_detects_replacement(
    tmp_path,
):
    api = Api()
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await wait_for(lambda: ready(owner))
            original = owner.store.observation.relationships
            captured = owner.sessions.client
            api.root_uid = "recreated-root"
            await owner.connect("kuberich-test-one")
            await wait_for(
                lambda: (
                    owner.store.observation.relationships is not None
                    and not owner.relationship_collecting
                    and owner.store.observation.relationships.rows
                    and owner.store.observation.relationships.rows[0].status
                    is RelationshipStatus.REPLACED
                )
            )
            replaced = owner.store.observation.relationships
            assert (
                replaced.request.scope.root.uid == root.uid
                and replaced.rows[0].observed_uid == "recreated-root"
            )
            assert replaced.request.scope.root.session != original.request.scope.root.session
            assert captured.api is None and owner.sessions.client is not captured
            assert replaced.requests_used == 1
            api.root_uid = root.uid
            await owner.refresh_relationships()
            await wait_for(lambda: ready(owner))
            assert owner.store.observation.relationships.requests_used == 2
            assert not owner.store.apply_relationships(owner.store.observation.revision, original)
        finally:
            await owner.close()
        with pytest.raises(AppError, match="closed"):
            owner.select_relationships(root, resource, RelationshipMode.XRAY)
        with pytest.raises(AppError):
            owner.refresh_relationships()
        with pytest.raises(AppError):
            owner.set_relationship_expanded((), True)


@pytest.mark.asyncio
async def test_all_namespaces_capture_keeps_actual_root_namespace_and_usedby_scan_scope(tmp_path):
    api = Api()
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest(all_namespaces=True))
        )
        try:
            with pytest.raises(AppError):
                owner.refresh_relationships()
            with pytest.raises(AppError):
                owner.set_relationship_expanded((), True)
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            original, _ = target(owner)
            resource = owner.discovery.find("configmaps")
            root = replace(original, resource="configmaps")
            await owner.select_relationships(
                root, resource, RelationshipMode.USED_BY, expanded=frozenset({()})
            )
            await wait_for(
                lambda: (
                    owner.store.observation.status is ViewStatus.LIVE
                    and not owner.relationship_collecting
                    and owner.store.observation.relationships is not None
                )
            )
            assert owner.relationship_request.scope.namespace is None
            assert owner.relationship_request.scope.root.namespace == "team"
            calls = len(api.calls)
            await owner.select_namespace("default")
            await wait_for(
                lambda: (
                    owner.store.observation.status is ViewStatus.LIVE
                    and not owner.relationship_collecting
                    and owner.relationship_request.scope.namespace == "default"
                )
            )
            assert owner.relationship_request.scope.root.namespace == "team"
            assert (
                owner.relationship_request.scope.root.session == owner.sessions.observation.identity
            )
            new_paths = [path for path, _ in api.calls[calls:]]
            assert "/api/v1/namespaces/team/configmaps/one" in new_paths
            assert "/api/v1/namespaces/team/pods" in new_paths
            assert "/api/v1/namespaces/default/pods" not in new_paths
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_latest_expansion_is_installed_before_parser_cancellation_and_no_late_old_result(
    tmp_path, monkeypatch
):
    api = Api()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = relationships.declared_references
    block = [True]

    def declarations(resource, record):
        if record.name == "one" and block[0]:
            block[0] = False
            started.set()
            release.wait(5)
            finished.set()
        return original(resource, record)

    monkeypatch.setattr(relationships, "declared_references", declarations)
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await wait_for(started.is_set)
            previous = owner.store.observation
            owner.set_relationship_expanded((), False)
            operation = owner.set_relationship_expanded((), True)
            newest = owner.relationship_request
            assert newest.revision > previous.relationships.request.revision
            assert owner.store.observation.relationships.request == newest
            await asyncio.sleep(0.01)
            assert not operation.done() and owner.ownership.relationships_count == 1
            release.set()
            await operation
            await wait_for(lambda: ready(owner))
            assert finished.is_set() and owner.store.observation.relationships.request == newest
            assert not owner.store.apply_relationships(previous.revision, previous.relationships)
            assert sum(path.endswith("/pods/one") for path, _ in api.calls) == 2
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_context_change_and_repeated_close_cancellation_drain_parser_before_client_retirement(
    tmp_path, monkeypatch
):
    api = Api()
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = relationships.declared_references

    def declarations(resource, record):
        started.set()
        release.wait(5)
        try:
            return original(resource, record)
        finally:
            finished.set()

    monkeypatch.setattr(relationships, "declared_references", declarations)
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        closing = None
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            captured = owner.sessions.client
            private = Path(captured.directory.name)
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await wait_for(started.is_set)
            switching = owner.connect("kuberich-test-Two")
            await asyncio.sleep(0.01)
            assert not switching.done() and captured.api is not None and private.exists()
            closing = asyncio.create_task(owner.close())
            await asyncio.sleep(0.01)
            closing.cancel()
            closing.cancel()
            assert owner.store.observation.relationships is None
            assert (
                captured.api is not None
                and private.exists()
                and owner.ownership.relationships_count == 1
            )
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await closing
            await owner.close()
            assert finished.is_set() and captured.api is None and not private.exists()
            assert owner.sessions.client is None and owner.ownership.close_complete
            assert (
                owner.ownership.relationships_count
                == owner.ownership.watch_count
                == owner.ownership.operation_count
                == 0
            )
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await owner.close()


@pytest.mark.asyncio
async def test_failed_collection_retry_and_outer_revision_guard_do_not_publish_obsolete_work(
    tmp_path, monkeypatch
):
    api = Api()
    errors = []
    fail = [True]
    original = RelationshipService.collect

    async def collect(service, request, publish):
        if fail[0]:
            fail[0] = False
            raise RuntimeError("PRIVATE-unexpected-error")
        return await original(service, request, publish)

    monkeypatch.setattr(RelationshipService, "collect", collect)
    async with workspace_api(namespace_handler, api, discovery_roots=roots) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            on_error=errors.append,
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            root, resource = target(owner)
            await owner.select_relationships(
                root, resource, RelationshipMode.XRAY, expanded=frozenset({()})
            )
            await wait_for(
                lambda: (
                    owner.store.observation.status is ViewStatus.FAILED
                    and not owner.relationship_collecting
                )
            )
            assert len(errors) == 1 and owner.relationship_request is not None
            assert "PRIVATE" not in str(owner.store.observation.problem)
            await owner.refresh_relationships()
            await wait_for(lambda: ready(owner))
            assert owner.store.observation.relationships.requests_used == 2
            api.hold = True
            await owner.refresh_relationships()
            await asyncio.wait_for(api.held.wait(), 5)
            previous = owner.store.observation
            current_request = owner.relationship_request
            revised = owner.store.begin(previous.context, previous.connection)
            assert owner.store.bind_relationships(revised, current_request)
            before = len(api.calls)
            api.release.set()
            await wait_for(lambda: not owner.relationship_collecting)
            assert len(api.calls) == before
            assert not owner.store.apply_relationships(previous.revision, previous.relationships)
            assert owner.store.observation.relationships.rows == ()
        finally:
            api.release.set()
            await owner.close()
