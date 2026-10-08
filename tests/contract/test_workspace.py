"""Actual clients plus controlled races qualify view ownership and bounded delivery."""

import asyncio
import threading
import weakref
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.config.catalog import Entry, KubeCatalog
from kuberich.domain.connections import (
    ConnectionRequest,
    ConnectionState,
    HttpProblem,
)
from kuberich.domain.resources import ResourceSnapshot, resource_record
from kuberich.domain.views import ResourceSelection, ViewObservation, ViewStatus
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.errors import AppError
from kuberich.services import workspace as module
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.watches import ListWatch
from kuberich.services.workspace import MAX_SUBSCRIPTIONS, WorkspaceService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, item, pod_resource
from tests.support.watches import bookmark, error_event, frame
from tests.support.workspace import stable_watch, wait_for, workspace_api


def make_snapshot(resource=None, namespace="team", version="opaque-snapshot"):
    resource = resource or pod_resource()
    record = resource_record(resource, item(namespace=namespace), namespace)
    return ResourceSnapshot(resource, namespace, version, (record,))


def assert_closed(workspace):
    assert workspace.sessions.client is None
    assert workspace._watch is None and workspace._operation is None
    assert workspace.task is None or workspace.task.done()
    assert workspace._closing.done()
    assert workspace._discovery is None and not workspace._subscriptions
    assert workspace.store.observation.status is ViewStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_real_scopes_alias_resource_switch_and_context_replacement_use_only_current_client(
    tmp_path,
):
    reads = []

    async def namespace_handler(request):
        values = [item(name, namespace=None) for name in ("default", "team")]
        return web.json_response(collection(*values, rv="namespace-version"))

    async def resources(request):
        reads.append((request.path, request.query.get("watch"), request.headers["Authorization"]))
        if "watch" in request.query:
            return await stable_watch(request, bookmark("owned-bookmark"))
        namespace = request.path.split("/")[4] if "/namespaces/" in request.path else None
        return web.json_response(collection(item(namespace=namespace or "team")))

    async with workspace_api(namespace_handler, resources) as url:
        catalog = catalog_fixture(tmp_path, url)
        catalog.users["second"] = Entry({"token": "second-synthetic"}, tmp_path)
        catalog.contexts["kuberich-test-Two"].data["user"] = "second"
        before = (tmp_path / "fixture-config").read_bytes()
        owner = WorkspaceService(SessionService(catalog, ConnectionRequest()))
        subscription = owner.subscribe()
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            first = owner.store.observation
            api = owner.sessions.client.api
            directory = Path(owner.sessions.client.directory.name)
            assert first.snapshot.items[0].namespace == "team"
            await owner.select_namespace("default")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            second = owner.store.observation
            assert second.scope.namespace == "default" and second.revision > first.revision
            assert second.scope.session.connection_id == first.scope.session.connection_id
            assert second.scope.session.generation > first.scope.session.generation
            await owner.select_resource(ResourceSelection("namespaces"))
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            cluster = owner.store.observation
            assert cluster.scope.namespace is None and cluster.connection.namespace == "default"
            assert all(record.namespace is None for record in cluster.snapshot.items)
            await owner.select_namespace(None)
            await owner.select_resource(ResourceSelection("po"))
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.scope.namespace is None
            assert owner.store.observation.scope.resource.name == "pods"
            old_watch = owner._watch
            await owner.connect("kuberich-test-Two")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            last = owner.store.observation
            assert (
                old_watch.done() and api.rest_client.pool_manager.closed and not directory.exists()
            )
            assert last.scope.session.connection_id != first.scope.session.connection_id
            assert last.scope.namespace == "default"
            assert reads[-1][2] == "Bearer second-synthetic"
            assert (await anext(subscription)) is last
            assert (tmp_path / "fixture-config").read_bytes() == before
        finally:
            await owner.close()
        assert_closed(owner)


@pytest.mark.asyncio
async def test_rapid_switches_coalesce_and_cancel_once_while_old_watch_finishes_cleanup(
    tmp_path, monkeypatch
):
    started, cleaning, release, ended = (asyncio.Event() for _ in range(4))
    scopes, cancellations = [], []

    async def controlled(self, resource, namespace, sink):
        scopes.append((resource.name, namespace))
        await sink(SyncUpdate(SyncStatus.LIVE, make_snapshot(resource, namespace)))
        if len(scopes) == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellations.append(asyncio.current_task().cancelling())
                # A noncooperative adapter finishing an old event must not publish it.
                await sink(SyncUpdate(SyncStatus.LIVE, make_snapshot(resource, namespace, "late")))
                cleaning.set()
                await release.wait()
                assert not self.reader.session.api.rest_client.pool_manager.closed
                ended.set()
                return
        await asyncio.Event().wait()

    monkeypatch.setattr(ListWatch, "run", controlled)

    async def handler(request):
        return namespaces("team", "default")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await started.wait()
            old_watch = owner._watch
            first_driver = owner.select_namespace("default")
            await cleaning.wait()
            assert owner.store.observation.snapshot is None
            for index in range(30):
                assert owner.select_namespace(f"scope-{index}") is first_driver
            owner.select_namespace(None)
            assert owner.select_resource(ResourceSelection("namespaces")) is first_driver
            assert cancellations == [1] and not ended.is_set()
            assert owner.store.observation.snapshot is None and len(scopes) == 1
            release.set()
            await first_driver
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert ended.is_set() and old_watch.done()
            assert scopes == [("pods", "team"), ("namespaces", None)]
            assert owner.sessions.observation.namespace is None
            assert owner.store.observation.scope.resource.name == "namespaces"
            assert owner.store.observation.snapshot.resource_version != "late"
        finally:
            release.set()
            await owner.close()
        assert_closed(owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("late_failure", [False, True])
async def test_old_discovery_ignoring_cancellation_is_not_cached_or_bound_to_new_context(
    tmp_path, monkeypatch, late_failure
):
    started, release = asyncio.Event(), asyncio.Event()
    original = ResourceReader.discover
    calls = []

    async def delayed(self):
        result = await original(self)
        calls.append(self.session)
        if len(calls) == 1:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                if late_failure:
                    raise HttpProblem(500) from None
                return result
        return result

    monkeypatch.setattr(ResourceReader, "discover", delayed)

    async def handler(request):
        return namespaces("team", "default")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            first = owner.connect("kuberich-test-one")
            await started.wait()
            api = owner.sessions.client.api
            assert owner.connect("kuberich-test-Two") is first
            release.set()
            await first
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert api.rest_client.pool_manager.closed
            assert owner.store.observation.context == "kuberich-test-Two"
            assert owner._discovery[0] is owner.sessions.client is calls[1]
            assert len(calls) == 2
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_switch_cancels_real_paginated_read_before_a_late_second_page(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()
    paths = []

    async def handler(request):
        return namespaces("team", "default")

    async def resources(request):
        paths.append(request.path)
        namespace = request.path.split("/")[4]
        if "watch" in request.query:
            return await stable_watch(request)
        if namespace == "team":
            if not request.query["continue"]:
                return web.json_response(collection(item("old-page-one"), token="owned-next"))
            started.set()
            await release.wait()
            return web.json_response(collection(item("old-page-two")))
        return web.json_response(collection(item("current", namespace=namespace)))

    async with workspace_api(handler, resources) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await started.wait()
            old = owner._watch
            transition = owner.select_namespace("default")
            assert owner.store.observation.snapshot is None
            release.set()
            await transition
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert old.done()
            assert [value.name for value in owner.store.observation.snapshot.items] == ["current"]
            assert paths[-1] == "/api/v1/namespaces/default/pods"
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
async def test_context_switch_cancels_reconnect_backoff_and_clears_old_stale_snapshot(
    tmp_path, monkeypatch
):
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def retry_sleep(delay):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(module, "ListWatch", lambda reader: ListWatch(reader, sleep=retry_sleep))

    async def handler(request):
        return namespaces("team", "default")

    async def resources(request):
        namespace = request.path.split("/")[4]
        if "watch" in request.query:
            if namespace == "team":
                return web.Response(status=503, text="opaque-sensitive-body")
            return await stable_watch(request)
        return web.json_response(collection(item(namespace=namespace)))

    async with workspace_api(handler, resources) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await started.wait()
            stale = owner.store.observation
            assert stale.status is ViewStatus.STALE and stale.snapshot
            assert (
                "Stale resource data" in stale.message and "opaque-sensitive" not in stale.message
            )
            transition = owner.connect("kuberich-test-Two")
            assert owner.store.observation.snapshot is None
            await transition
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert cancelled.is_set()
            assert owner.store.observation.scope.namespace == "default"
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_real_410_discards_current_snapshot_and_recovery_replaces_it(tmp_path, monkeypatch):
    calls, version = [], "before-expiration"
    relisting, release = asyncio.Event(), asyncio.Event()

    async def sleep(delay):
        relisting.set()
        await release.wait()

    monkeypatch.setattr(module, "ListWatch", lambda reader: ListWatch(reader, sleep=sleep))

    async def handler(request):
        return namespaces("team")

    async def resources(request):
        nonlocal version
        if "watch" not in request.query:
            calls.append(True)
            return web.json_response(collection(item(version), rv=version))
        if len(calls) == 1:
            response = web.StreamResponse()
            await response.prepare(request)
            await response.write(frame(error_event(410)))
            version = "after-relist"
            return response
        return await stable_watch(request)

    async with workspace_api(handler, resources) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await relisting.wait()
            assert owner.store.observation.status is ViewStatus.RELISTING
            assert owner.store.observation.snapshot is None
            release.set()
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.snapshot.resource_version == "after-relist"
            assert owner.store.observation.snapshot.items[0].name == "after-relist"
            assert len(calls) == 2
        finally:
            release.set()
            await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404])
async def test_denied_watch_surfaces_failure_without_hot_retries_or_fake_empty_state(
    tmp_path, status
):
    watches = []

    async def handler(request):
        return namespaces("team")

    async def resources(request):
        if "watch" in request.query:
            watches.append(True)
            return web.Response(status=status, text="opaque-private-response")
        return web.json_response(collection(item()))

    async with workspace_api(handler, resources) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.FAILED)
            assert isinstance(owner.store.observation.problem, HttpProblem)
            assert owner.store.observation.problem.status == status
            assert owner.store.observation.snapshot.items
            assert owner._watch.done() and len(watches) == 1
            assert "opaque-private" not in owner.store.observation.message
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_closed_and_disconnected_scope_admission_and_bounded_subscriptions():
    owner = WorkspaceService(SessionService(KubeCatalog(), ConnectionRequest()))
    subscriptions = [owner.subscribe() for _ in range(MAX_SUBSCRIPTIONS)]
    with pytest.raises(AppError, match="Too many"):
        owner.subscribe()
    for operation in (
        lambda: owner.select_namespace("default"),
        lambda: owner.select_resource(ResourceSelection()),
    ):
        with pytest.raises(AppError, match="Connect"):
            operation()
    with pytest.raises(AppError):
        owner.connect("invalid\ncontext")
    subscriptions[0].close()
    subscriptions[0].close()
    subscriptions.append(owner.subscribe())
    assert len(owner._subscriptions) == MAX_SUBSCRIPTIONS
    reader = subscriptions[-1]
    assert (await anext(reader)).status is ViewStatus.DISCONNECTED
    waiting = asyncio.create_task(anext(reader))
    await asyncio.sleep(0)
    await owner.close()
    with pytest.raises(StopAsyncIteration):
        await waiting
    reader.offer(ViewObservation())
    await owner.close()
    assert_closed(owner)
    for operation in (
        owner.subscribe,
        lambda: owner.connect("owned"),
        lambda: owner.select_namespace(None),
    ):
        with pytest.raises(AppError, match="closed"):
            operation()


@pytest.mark.asyncio
async def test_slow_subscriber_coalesces_pending_updates_and_releases_superseded_snapshots():
    owner = WorkspaceService(SessionService(KubeCatalog(), ConnectionRequest()))
    subscription = owner.subscribe()
    first = make_snapshot()
    reference = weakref.ref(first)
    subscription.offer(ViewObservation(snapshot=first))
    del first
    for revision in range(1000):
        latest = ViewObservation(revision=revision, snapshot=make_snapshot(version=str(revision)))
        subscription.offer(latest)
    assert reference() is None
    assert (await anext(subscription)) is latest
    assert subscription._pending is None and not subscription._ready.is_set()
    await owner.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_client_preparation_and_cancelled_close_wait_for_worker(
    tmp_path, monkeypatch
):
    from kuberich.adapters import kubernetes

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = kubernetes._prepare

    def controlled(context, directory):
        started.set()
        release.wait(timeout=5)
        try:
            return original(context, directory)
        finally:
            finished.set()

    monkeypatch.setattr(kubernetes, "_prepare", controlled)

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        task = owner.connect("kuberich-test-one")
        await asyncio.to_thread(started.wait, 5)
        directory = Path(owner.sessions.client.directory.name)
        for _ in range(10):
            assert owner.connect("kuberich-test-Two") is task
            await asyncio.sleep(0)
        closing = asyncio.create_task(owner.close())
        await asyncio.sleep(0)
        for _ in range(3):
            closing.cancel()
            await asyncio.sleep(0)
            assert not finished.is_set() and directory.exists() and not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert finished.is_set() and not directory.exists()
        assert_closed(owner)


@pytest.mark.asyncio
async def test_repeated_open_close_leaves_no_owned_tasks_or_sessions(tmp_path):
    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        identities = set()
        for _ in range(3):
            owner = WorkspaceService(
                SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
            )
            await owner.connect("kuberich-test-one")
            await wait_for(lambda owner=owner: owner.store.observation.status is ViewStatus.LIVE)
            identity = owner.store.observation.scope.session.connection_id
            assert identity not in identities
            identities.add(identity)
            api = owner.sessions.client.api
            task = owner._watch
            directory = Path(owner.sessions.client.directory.name)
            await owner.close()
            assert task.done() and api.rest_client.pool_manager.closed and not directory.exists()
            assert_closed(owner)
            assert not [
                task
                for task in asyncio.all_tasks()
                if task.get_name() in {"kuberich-workspace", "kuberich-resource-watch"}
            ]


@pytest.mark.asyncio
async def test_late_callbacks_cannot_publish_after_namespace_or_client_replacement(
    tmp_path, monkeypatch
):
    callbacks = []

    async def controlled(self, resource, namespace, sink):
        callbacks.append((sink, make_snapshot(resource, namespace)))
        await sink(SyncUpdate(SyncStatus.LIVE, callbacks[-1][1]))
        await asyncio.Event().wait()

    monkeypatch.setattr(ListWatch, "run", controlled)

    async def handler(request):
        return namespaces("team", "default")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: len(callbacks) == 1)
            await owner.select_namespace("default")
            await wait_for(lambda: len(callbacks) == 2)
            current = owner.store.observation
            await callbacks[0][0](SyncUpdate(SyncStatus.LIVE, callbacks[0][1]))
            assert owner.store.observation is current
            await owner.connect("kuberich-test-Two")
            await wait_for(lambda: len(callbacks) == 3)
            current = owner.store.observation
            await callbacks[1][0](SyncUpdate(SyncStatus.LIVE, callbacks[1][1]))
            assert owner.store.observation is current
            owner.sessions.select_namespace("externally-changed")
            with pytest.raises(AppError, match="Connect"):
                owner.select_resource(ResourceSelection())
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_unknown_resource_failure_can_recover_using_the_same_client_discovery_cache(tmp_path):
    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            cache = owner._discovery
            await owner.select_resource(ResourceSelection("absent"))
            assert owner.store.observation.status is ViewStatus.FAILED
            assert (
                owner.store.observation.scope is None and owner.store.observation.snapshot is None
            )
            assert owner._watch is None
            await owner.select_resource(ResourceSelection("pods"))
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner._discovery is cache
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_discovery_denial_is_distinct_from_connection_and_retry_uses_a_fresh_client(
    tmp_path, monkeypatch
):
    original, calls = ResourceReader.discover, []

    async def denied_once(self):
        calls.append(self.session)
        if len(calls) == 1:
            raise HttpProblem(403)
        return await original(self)

    monkeypatch.setattr(ResourceReader, "discover", denied_once)

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            failed = owner.store.observation
            assert failed.connection.state is ConnectionState.CONNECTED
            assert failed.status is ViewStatus.FAILED and failed.problem.status == 403
            assert owner._watch is None and owner._discovery is None
            api = owner.sessions.client.api
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert calls[0] is not calls[1] and api.rest_client.pool_manager.closed
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_namespace_list_denial_does_not_prevent_an_allowed_manual_scope(tmp_path):
    async def handler(request):
        return web.Response(status=403)

    async def resources(request):
        if "/allowed/" not in request.path:
            return web.Response(status=403)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(item(namespace="allowed")))

    async with workspace_api(handler, resources) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.FAILED)
            assert owner.store.observation.connection.state is ConnectionState.LIMITED
            await owner.select_namespace("allowed")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.snapshot.items[0].namespace == "allowed"
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_authentication_failure_remains_visible_without_resource_tasks(tmp_path):
    async def handler(request):
        return web.Response(status=401)

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            assert owner.store.observation.connection.state is ConnectionState.AUTH_ERROR
            assert owner.store.observation.status is ViewStatus.FAILED
            assert owner.sessions.client is None and owner._watch is None
            assert "401" in owner.store.observation.message
        finally:
            await owner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [AppError("opaque-sensitive-value"), RuntimeError("opaque-sensitive-value")]
)
async def test_watch_protocol_or_unexpected_failure_is_owned_and_propagates_programming_errors(
    tmp_path, monkeypatch, failure
):
    async def broken(self, resource, namespace, sink):
        raise failure

    monkeypatch.setattr(ListWatch, "run", broken)

    async def handler(request):
        return namespaces("team")

    async with workspace_api(handler) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner._watch.done())
            if isinstance(failure, RuntimeError):
                with pytest.raises(RuntimeError, match="opaque-sensitive"):
                    await owner._watch
            assert owner.store.observation.status is ViewStatus.FAILED
            assert "opaque-sensitive" not in owner.store.observation.message
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_unexpected_connection_failure_reaches_caller_and_cleanup_is_still_owned(monkeypatch):
    async def broken(context):
        raise RuntimeError("opaque-programming-error")

    owner = WorkspaceService(SessionService(KubeCatalog(), ConnectionRequest()))
    monkeypatch.setattr(owner.sessions, "connect", broken)
    with pytest.raises(RuntimeError, match="opaque-programming"):
        await owner.connect("owned")
    assert owner.store.observation.status is ViewStatus.FAILED
    assert "opaque-programming" not in owner.store.observation.message
    await owner.close()
    assert_closed(owner)


@pytest.mark.asyncio
async def test_unexpected_client_close_failure_is_not_suppressed_and_subscribers_are_closed(
    monkeypatch,
):
    owner = WorkspaceService(SessionService(KubeCatalog(), ConnectionRequest()))
    subscription = owner.subscribe()
    original = owner.sessions.close

    async def failed_close():
        await original()
        raise RuntimeError("owned-close-error")

    monkeypatch.setattr(owner.sessions, "close", failed_close)
    with pytest.raises(RuntimeError, match="owned-close"):
        await owner.close()
    assert subscription._closed and not owner._subscriptions
    with pytest.raises(RuntimeError, match="owned-close"):
        await owner.close()
