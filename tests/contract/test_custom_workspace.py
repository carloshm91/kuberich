"""Owned real-HTTP catalogue refresh, version changes and context-generation guards."""

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.views import ViewStatus
from kuberich.errors import AppError
from kuberich.services.sessions import SessionService
from kuberich.services.workspace import WorkspaceService
from tests.support.connections import catalog_fixture, namespaces
from tests.support.resources import collection, descriptor, item, legacy_roots
from tests.support.tables import custom_item, server_table
from tests.support.workspace import stable_watch, wait_for, workspace_api


def roots(installed, preferred):
    values = legacy_roots()
    if installed:
        group = "owned.example.test"
        values["/apis"]["groups"] = [
            {
                "name": group,
                "versions": [
                    {"groupVersion": group + "/" + v, "version": v} for v in ("v1beta1", "v1")
                ],
                "preferredVersion": {"groupVersion": group + "/" + preferred, "version": preferred},
            }
        ]
        for version in ("v1beta1", "v1"):
            values["/apis/" + group + "/" + version] = {
                "groupVersion": group + "/" + version,
                "resources": [
                    {
                        **descriptor("widgets", kind="Widget"),
                        "singularName": "widget",
                        "shortNames": ["wdg"],
                    }
                ],
            }
    return values


@pytest.mark.asyncio
async def test_install_preferred_version_change_removal_and_core_return_keep_owned_client(tmp_path):
    state = {"installed": False, "preferred": "v1"}
    requests = []

    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        requests.append(request.path)
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.startswith("/apis/"):
            parts = request.path.split("/")
            version, namespace = parts[3], parts[5]
            return web.json_response(
                server_table(custom_item(namespace=namespace, version=version))
            )
        scope = request.path.split("/")[4] if "/namespaces/" in request.path else "team"
        return web.json_response(collection(item(namespace=scope)))

    async with workspace_api(ns, handler, discovery_roots=lambda: roots(**state)) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        assert owner.discovery is None
        with pytest.raises(AppError):
            owner.select_discovered("widgets")
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            client = owner.sessions.client
            identity = owner.sessions.observation.identity
            with pytest.raises(AppError):
                owner.select_discovered("wdg")
            state["installed"] = True
            operation = owner.refresh_discovery()
            assert owner.discovery is None
            with pytest.raises(AppError):
                owner.select_discovered("wdg")
            await operation
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.discovery.resolve("wdg").version == "v1"
            await owner.select_discovered("wdg")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            view = owner.store.observation
            assert view.scope.resource.version == "v1" and view.snapshot.columns
            assert view.snapshot.items[0].manifest["apiVersion"] == "owned.example.test/v1"
            state["preferred"] = "v1beta1"
            await owner.refresh_discovery()
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.scope.resource.version == "v1beta1"
            assert (
                owner.sessions.client is client and owner.sessions.observation.identity == identity
            )
            # A refresh queued during namespace replacement must preserve its intent.
            owner.select_namespace("default")
            await owner.refresh_discovery()
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.scope.namespace == "default"
            assert owner.store.observation.snapshot.items[0].namespace == "default"
            state["installed"] = False
            await owner.refresh_discovery()
            assert owner.store.observation.status is ViewStatus.FAILED
            assert owner.discovery is not None
            await owner.select_discovered("pods", group="")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.store.observation.scope.resource.name == "pods"
            assert owner.sessions.client is client
            replacement = owner.connect("kuberich-test-Two")
            assert owner.discovery is None
            await replacement
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.sessions.client is not client and owner.discovery is not None
        finally:
            await owner.close()
        assert owner.discovery is None
        with pytest.raises(AppError):
            owner.refresh_discovery()
        with pytest.raises(AppError):
            owner.select_discovered("pods")
    assert any("/owned.example.test/v1beta1/" in path for path in requests)


@pytest.mark.asyncio
async def test_forbidden_named_discovery_remains_partial_and_core_watch_stays_usable(tmp_path):
    denied = False

    def discovery():
        values = roots(True, "v1")
        if denied:
            del values["/apis"]
        return values

    async def ns(request):
        return namespaces("team")

    async def handler(request):
        if request.path == "/apis":
            return web.Response(status=403)
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(item()))

    async with workspace_api(ns, handler, discovery_roots=discovery) as url:
        owner = WorkspaceService(
            SessionService(catalog_fixture(tmp_path, url), ConnectionRequest())
        )
        try:
            await owner.connect("kuberich-test-one")
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            client = owner.sessions.client
            denied = True
            await owner.refresh_discovery()
            await wait_for(lambda: owner.store.observation.status is ViewStatus.LIVE)
            assert owner.discovery.partial and owner.discovery.issues[0].status == 403
            assert owner.discovery.resolve("pods", group="").name == "pods"
            assert owner.sessions.client is client
            assert owner.store.observation.snapshot.items[0].name == "one"
            assert owner.store.observation.scope.resource.name == "pods"
        finally:
            await owner.close()
