"""Real session ownership with controlled Helm producers at the workspace port."""

import asyncio

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.helm import (
    HelmDriver,
    HelmList,
    HelmProblem,
    HelmRelease,
    HelmReleaseKey,
    HelmScope,
)
from kuberich.domain.targets import SessionIdentity
from kuberich.domain.views import ResourceSelection, ViewStatus
from kuberich.errors import AppError
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.connections import catalog_fixture
from tests.support.resources import collection, item
from tests.support.workspace import wait_for, workspace_api


async def namespaces(_):
    return web.json_response(collection(*(item(ns, namespace=None) for ns in ("team", "default"))))


def release_list(namespace="team"):
    return HelmList(
        (
            HelmRelease(
                HelmReleaseKey(namespace, "demo"),
                1,
                "deployed",
                "owned-0.1.0",
                "1",
                "2026-11-09T00:00:00Z",
            ),
        ),
        True,
    )


class Producer:
    """A collection test double, separate from the actual CLI/storage contract tests."""

    def __init__(self, client, current, run=None):
        self.client, self.current, self.run = client, current, run
        self.invalidated = False
        self.closed = False
        self.close_saw_open_client = False
        self.requests = []

    def invalidate(self):
        self.invalidated = True

    async def close(self):
        self.invalidate()
        self.close_saw_open_client = self.client.api is not None
        self.closed = True

    async def list(self, request):
        self.requests.append(request)
        if self.run is not None:
            return await self.run(request)
        assert self.current(request)
        return release_list(request.scope.namespace or "team")


@pytest.mark.asyncio
async def test_optional_helm_is_lazy_and_namespace_refresh_reconnect_rebind_authority(tmp_path):
    producers = []

    def factory(client, current):
        producer = Producer(client, current)
        producers.append(producer)
        return producer

    async with workspace_api(namespaces) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            helm_factory=factory,
        )
        try:
            await owner.connect("kuberich-test-one")
            assert not producers
            identity = owner.sessions.observation.identity
            scope = HelmScope(identity, "team", HelmDriver.SECRET)
            await owner.select_helm(scope)
            await wait_for(
                lambda: (
                    owner.store.observation.helm is not None
                    and not owner.store.observation.helm.collecting
                )
            )
            first = owner.helm_request
            assert owner.helm_service is producers[0]
            assert owner.store.observation.scope is owner.store.observation.snapshot is None
            assert owner.store.observation.helm.listing == release_list()

            await owner.refresh_discovery()
            await wait_for(lambda: not owner.store.observation.helm.collecting)
            refreshed = owner.helm_request
            assert refreshed.generation > first.generation
            assert not producers[0].current(first)
            assert producers[0].closed and producers[0].close_saw_open_client

            task = owner.select_namespace("default")
            assert producers[1].invalidated
            assert not producers[1].current(refreshed)
            await task
            await wait_for(lambda: not owner.store.observation.helm.collecting)
            changed = owner.helm_request
            assert changed.scope.namespace == "default"
            assert changed.scope.session != refreshed.scope.session
            assert changed.scope.session == owner.sessions.observation.identity
            assert owner.store.observation.helm.listing == release_list("default")

            previous = producers[-1]
            await owner.connect("kuberich-test-Two")
            await wait_for(
                lambda: (
                    owner.store.observation.helm is not None
                    and not owner.store.observation.helm.collecting
                )
            )
            assert previous.closed and previous.close_saw_open_client
            assert not previous.current(changed)
            assert owner.helm_request.scope.session.context == "kuberich-test-Two"
            assert owner.helm_request.scope.session == owner.sessions.observation.identity
        finally:
            await owner.close()
            await owner.close()
        assert all(producer.closed and producer.close_saw_open_client for producer in producers)
        assert owner.ownership.helm_count == 0
        assert owner.sessions.client is None
        assert owner.store.observation.status is ViewStatus.DISCONNECTED


@pytest.mark.asyncio
async def test_failed_refresh_keeps_prior_rows_stale_without_disconnecting(tmp_path):
    producers = []

    async def fail(_):
        raise HelmProblem("timeout", "Helm read timed out; refresh to retry.")

    def factory(client, current):
        producer = Producer(client, current, fail if producers else None)
        producers.append(producer)
        return producer

    async with workspace_api(namespaces) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            helm_factory=factory,
        )
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_helm(
                HelmScope(owner.sessions.observation.identity, "team", HelmDriver.SECRET)
            )
            await wait_for(lambda: not owner.store.observation.helm.collecting)
            retained = owner.store.observation.helm.listing
            await owner.refresh_helm()
            await wait_for(lambda: not owner.store.observation.helm.collecting)
            snapshot = owner.store.observation.helm
            assert snapshot.listing is retained
            assert snapshot.problem.kind == "timeout"
            assert owner.store.observation.status is ViewStatus.STALE
            assert "Stale releases" in owner.store.observation.message
            assert owner.helm_service is producers[-1]
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_departure_invalidates_before_await_and_drains_a_late_collection(tmp_path):
    started, cancelled, permit_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    producers = []

    async def late(_):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await permit_cleanup.wait()
        return release_list()

    def factory(client, current):
        producer = Producer(client, current, late)
        producers.append(producer)
        return producer

    async with workspace_api(namespaces) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            helm_factory=factory,
        )
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_helm(
                HelmScope(owner.sessions.observation.identity, "team", HelmDriver.SECRET)
            )
            await asyncio.wait_for(started.wait(), 5)
            request = owner.helm_request
            task = owner.select_resource(ResourceSelection())
            assert producers[0].invalidated and not producers[0].current(request)
            assert owner.helm_request is owner.helm_service is None
            assert owner.store.observation.helm is None
            await asyncio.wait_for(cancelled.wait(), 5)
            assert not task.done()
            permit_cleanup.set()
            await asyncio.wait_for(task, 5)
            assert producers[0].closed
            assert owner.store.observation.helm is None
            assert owner.store.observation.scope.resource.name == "pods"
        finally:
            permit_cleanup.set()
            await owner.close()


@pytest.mark.asyncio
async def test_unconfigured_helm_is_a_feature_error_and_invalid_scopes_do_not_replace_the_view(
    tmp_path,
):
    async with workspace_api(namespaces) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            with pytest.raises(AppError, match="Connect"):
                owner.select_helm(HelmScope(SessionIdentity("owned", 1), "team", HelmDriver.SECRET))
            await owner.connect("kuberich-test-one")
            identity = owner.sessions.observation.identity
            before = owner.store.observation
            with pytest.raises(AppError, match="header namespace"):
                owner.select_helm(HelmScope(identity, None, HelmDriver.SECRET))
            assert owner.store.observation is before
            await owner.select_helm(HelmScope(identity, "team", HelmDriver.SECRET))
            await wait_for(lambda: not owner.store.observation.helm.collecting)
            assert owner.store.observation.helm.problem.kind == "unavailable"
            assert owner.helm_service is None
            assert owner.store.observation.problem is None
            assert owner.sessions.client is not None
        finally:
            await owner.close()


@pytest.mark.asyncio
async def test_unexpected_collection_failure_stops_loading_and_reports_to_the_owner(tmp_path):
    errors, producers = [], []

    async def broken(_):
        raise RuntimeError("Synthetic producer failure")

    def factory(client, current):
        producer = Producer(client, current, broken)
        producers.append(producer)
        return producer

    async with workspace_api(namespaces) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest()),
            helm_factory=factory,
            on_error=errors.append,
        )
        try:
            await owner.connect("kuberich-test-one")
            await owner.select_helm(
                HelmScope(owner.sessions.observation.identity, "team", HelmDriver.SECRET)
            )
            await wait_for(lambda: bool(errors))
            assert type(errors[0]) is RuntimeError
            assert owner.store.observation.status is ViewStatus.FAILED
            assert not owner.store.observation.helm.collecting
            assert owner.store.observation.helm.problem.kind == "unavailable"
            assert owner.helm_request is owner.helm_service is None
            assert owner.sessions.client is not None
        finally:
            await owner.close()
        assert producers[0].closed
