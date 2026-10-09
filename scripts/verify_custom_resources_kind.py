"""C05 real CRD discovery, Table transport, refresh and restricted legacy discovery."""

import argparse
import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

import yaml
from aiohttp import web
from kubernetes_asyncio import client

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.config.schema import Settings
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, HttpProblem
from kuberich.domain.views import ViewStatus
from kuberich.domain.watches import EventType, SyncStatus, SyncUpdate
from kuberich.errors import AppError
from kuberich.services.commands import GenericResourceCommand
from kuberich.services.resources import ResourceReader
from kuberich.services.sessions import SessionService
from kuberich.services.watches import ListWatch
from kuberich.services.workspace import WorkspaceService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from scripts.owned_kind import NODE_IMAGE, OwnedCluster, owned_cluster

GROUP = "owned.kuberich.test"
OTHER_GROUP = "other.kuberich.test"
NAMESPACE = "kuberich-owned-custom"


def definition(group: str, plural: str, kind: str, *, namespaced: bool) -> dict[str, Any]:
    schema = {
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "properties": {
                    "level": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                },
            }
        },
    }
    return {
        "apiVersion": "apiextensions.k8s.io/v1",
        "kind": "CustomResourceDefinition",
        "metadata": {"name": plural + "." + group},
        "spec": {
            "group": group,
            "scope": "Namespaced" if namespaced else "Cluster",
            "names": {
                "plural": plural,
                "singular": plural[:-1],
                "kind": kind,
                "shortNames": ["wdg"],
            },
            # API preference must come from discovery, not declaration order.
            "versions": [
                {
                    "name": version,
                    "served": True,
                    "storage": version == "v1",
                    "schema": {"openAPIV3Schema": schema},
                    "additionalPrinterColumns": [
                        {"name": "Level", "type": "integer", "jsonPath": ".spec.level"},
                        {"name": "Enabled", "type": "boolean", "jsonPath": ".spec.enabled"},
                    ],
                }
                for version in ("v1beta1", "v1")
            ],
        },
    }


async def wait_for(predicate: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(45):
        while not await predicate():
            await asyncio.sleep(0.1)


@asynccontextmanager
async def representation_gateway(
    cluster: OwnedCluster, upstream: KubernetesSession, *, legacy: bool
) -> AsyncIterator[tuple[KubernetesSession, list[dict[str, Any]]]]:
    """Owned HTTP gateway changes representation only; upstream owns real TLS/RBAC.

    Legacy discovery and missing Table are explicitly injected transport cases,
    not claims that the pinned apiserver lacks aggregated discovery or Tables.
    """
    requests: list[dict[str, Any]] = []

    async def handle(request: web.Request) -> web.Response:
        requests.append(
            {"path": request.path, "table": "as=Table" in request.headers.get("Accept", "")}
        )
        try:
            value = await upstream.get_json(request.path, params=dict(request.query))
        except HttpProblem as problem:
            return web.json_response({"kind": "Status"}, status=problem.status)
        return web.json_response(value)

    app = web.Application()
    app.router.add_get("/{path:.*}", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    try:
        await site.start()
        address = runner.addresses[0]
        config = cluster.directory / ("legacy" if legacy else "plain-table")
        config.write_text(
            yaml.safe_dump(
                {
                    "apiVersion": "v1",
                    "kind": "Config",
                    "current-context": "owned-gateway",
                    "contexts": [
                        {"name": "owned-gateway", "context": {"cluster": "owned", "user": "owned"}}
                    ],
                    "clusters": [
                        {"name": "owned", "cluster": {"server": f"http://127.0.0.1:{address[1]}"}}
                    ],
                    "users": [{"name": "owned", "user": {}}],
                }
            )
        )
        config.chmod(0o600)
        request = ConnectionRequest(kubeconfig=str(config), context="owned-gateway", timeout=15)
        session = KubernetesSession(load_catalog(request, {}).select("owned-gateway"), 15)
        try:
            await session.open()
            yield session, requests
        finally:
            await session.close()
            config.unlink()
    finally:
        await runner.cleanup()


async def verify_browser(
    cluster: OwnedCluster,
    extensions: client.ApiextensionsV1Api,
    custom: client.CustomObjectsApi,
) -> None:
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-custom-browser", level=100),
        catalog=load_catalog(request, {}),
        connection=request,
        initial_command=GenericResourceCommand("widgets", GROUP, "v1beta1", NAMESPACE),
    )

    async def loaded() -> bool:
        view = app.workspace.store.observation
        return view.status is ViewStatus.LIVE and app.custom_table.row_count == 3

    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(loaded)
        await pilot.pause()
        table = app.custom_table
        assert tuple(key.value for key in table.columns) == ("namespace", "name", "c2", "c3", "age")
        assert GROUP + "/v1beta1" in str(app.query_one("#resource-view").border_title)
        table.set_sort("c2")
        await pilot.press("G")
        selected = table.selected_uid
        app._submit_command("columns c2")
        await pilot.pause()
        assert "c3" not in table.columns and table.selected_uid == selected
        app._submit_command("columns c99")
        await pilot.pause()
        assert "retained" in str(app.status.content) and "c3" not in table.columns
        app.action_inspect_yaml()

        async def inspected() -> bool:
            return isinstance(app.screen, InspectionScreen) and app.screen.result is not None

        await wait_for(inspected)
        assert isinstance(app.screen, InspectionScreen)
        assert (
            "kind: Widget" in app.screen.viewer.text
            and GROUP + "/v1beta1" in app.screen.viewer.text
        )
        await pilot.press("escape")
        app._submit_command("wdg")
        assert "ambiguous" in str(app.status.content)
        app._submit_command("gadgets." + OTHER_GROUP)

        async def cluster_loaded() -> bool:
            view = app.workspace.store.observation
            return (
                view.status is ViewStatus.LIVE
                and view.scope is not None
                and view.scope.resource.name == "gadgets"
                and table.row_count == 1
            )

        await wait_for(cluster_loaded)
        assert (
            app.workspace.store.observation.scope is not None
            and app.workspace.store.observation.scope.namespace is None
        )
        await pilot.press("alt+left")
        await wait_for(loaded)
        await pilot.pause()
        assert (
            app.workspace.selection.version == "v1beta1"
            and table.selected_uid == selected
            and "c3" not in table.columns
        )
        app._submit_command("widgets." + GROUP + " *")
        await wait_for(loaded)
        assert (
            app.workspace.store.observation.scope is not None
            and app.workspace.store.observation.scope.namespace is None
        )
        app._submit_command("widgets." + GROUP + "/v1beta1 " + NAMESPACE)
        await wait_for(loaded)
        connection = app.sessions.client
        app._submit_command("refresh")
        await wait_for(loaded)
        assert app.sessions.client is connection
        await custom.patch_namespaced_custom_object(
            GROUP,
            "v1beta1",
            NAMESPACE,
            "widgets",
            "owned-0",
            [{"op": "replace", "path": "/spec/level", "value": 20}],
        )

        async def observed() -> bool:
            return any(
                row.name == "owned-0" and row.values[2].sort == 20 for row in table._rows.values()
            )

        await wait_for(observed)
        await extensions.delete_custom_resource_definition("widgets." + GROUP)

        async def removed() -> bool:
            app._submit_command("refresh")
            if app._connection_task is not None:
                await app._connection_task
            return app.workspace.discovery is not None and not any(
                resource.group == GROUP for resource in app.workspace.discovery.resources
            )

        await wait_for(removed)
        assert app.workspace.store.observation.status is ViewStatus.FAILED and table.row_count == 0
        app._submit_command("po")

        async def core_loaded() -> bool:
            view = app.workspace.store.observation
            return (
                view.status is ViewStatus.LIVE
                and view.scope is not None
                and view.scope.resource.name == "pods"
            )

        await wait_for(core_loaded)
        assert app.sessions.client is connection
    assert app.sessions.client is None


async def verify(cluster: OwnedCluster) -> dict[str, Any]:
    request = ConnectionRequest(
        kubeconfig=str(cluster.path), context=cluster.context, namespace=NAMESPACE, timeout=15
    )
    sessions = SessionService(load_catalog(request, {}), request)
    workspace = WorkspaceService(sessions)
    delegated: KubernetesSession | None = None
    watch: asyncio.Task[None] | None = None
    before = cluster.path.read_bytes()
    checks: list[str] = []

    async def live() -> bool:
        return workspace.store.observation.status is ViewStatus.LIVE

    try:
        await sessions.connect(cluster.context)
        connection = sessions.client
        assert connection is not None and connection.api is not None
        core = client.CoreV1Api(connection.api)
        extensions = client.ApiextensionsV1Api(connection.api)
        custom = client.CustomObjectsApi(connection.api)
        await core.create_namespace(
            client.V1Namespace(metadata=client.V1ObjectMeta(name=NAMESPACE))
        )
        await workspace.connect(cluster.context)
        await wait_for(live)
        connection = sessions.client
        assert connection is not None and connection.api is not None
        core = client.CoreV1Api(connection.api)
        extensions = client.ApiextensionsV1Api(connection.api)
        custom = client.CustomObjectsApi(connection.api)
        reader = ResourceReader(connection, tables=True)
        assert workspace.discovery is not None
        assert not any(resource.group == GROUP for resource in workspace.discovery.resources)

        for group, plural, kind, namespaced in (
            (GROUP, "widgets", "Widget", True),
            (OTHER_GROUP, "gadgets", "Gadget", False),
        ):
            await extensions.create_custom_resource_definition(
                cast(
                    client.V1CustomResourceDefinition,
                    definition(group, plural, kind, namespaced=namespaced),
                )
            )

        async def established() -> bool:
            for name in ("widgets." + GROUP, "gadgets." + OTHER_GROUP):
                value = await extensions.read_custom_resource_definition(name)
                if not any(
                    c.type == "Established" and c.status == "True"
                    for c in value.status.conditions or []
                ):
                    return False
            return True

        await wait_for(established)

        async def installed() -> bool:
            await workspace.refresh_discovery()
            return workspace.discovery is not None and any(
                resource.group == GROUP for resource in workspace.discovery.resources
            )

        await wait_for(installed)
        discovery = workspace.discovery
        assert discovery is not None
        widget = discovery.resolve("widgets", group=GROUP)
        gadget = discovery.resolve("gadgets", group=OTHER_GROUP)
        assert widget.version == "v1" and widget.namespaced
        assert gadget.version == "v1" and not gadget.namespaced
        beta = discovery.resolve("wdg", group=GROUP, version="v1beta1")
        assert beta.name == "widgets"
        try:
            discovery.resolve("wdg")
            raise AssertionError("Cross-group short name was silently resolved")
        except AppError:
            pass
        checks.append("actual-installed-namespaced-cluster-preferred-versions-and-alias-collision")

        for index in range(3):
            await custom.create_namespaced_custom_object(
                GROUP,
                "v1",
                NAMESPACE,
                "widgets",
                {
                    "apiVersion": GROUP + "/v1",
                    "kind": "Widget",
                    "metadata": {"name": f"owned-{index}"},
                    "spec": {"level": index, "enabled": True},
                },
            )
        await custom.create_cluster_custom_object(
            OTHER_GROUP,
            "v1",
            "gadgets",
            {
                "apiVersion": OTHER_GROUP + "/v1",
                "kind": "Gadget",
                "metadata": {"name": "owned-cluster"},
                "spec": {"level": 9, "enabled": False},
            },
        )
        snapshot = await reader.list(widget, NAMESPACE, page_size=1)
        assert len(snapshot.items) == 3 and snapshot.resource_version
        assert [column.name for column in snapshot.columns] == ["Name", "Level", "Enabled"]
        assert all(
            record.server is not None and record.server.cells[1] == record.manifest["spec"]["level"]
            for record in snapshot.items
        )
        value = await reader.get(widget, "owned-0", NAMESPACE)
        converted = await reader.get(beta, "owned-0", NAMESPACE)
        assert value.uid == converted.uid and converted.manifest["apiVersion"] == GROUP + "/v1beta1"
        cluster_snapshot = await reader.list(gadget, page_size=1)
        cluster_value = await reader.get(gadget, "owned-cluster")
        assert cluster_snapshot.columns and cluster_value.namespace is None
        assert cluster_value.server is not None and cluster_value.server.cells[1:] == (9, False)
        assert len((await reader.list(widget)).items) == 3
        checks.append("actual-paged-table-list-get-cross-version-full-objects-and-both-scopes")

        opened, changed = asyncio.Event(), asyncio.Event()
        events: list[EventType] = []

        async def receive(update: SyncUpdate) -> None:
            if update.status is SyncStatus.LIVE:
                opened.set()
            if update.event is not None:
                events.append(update.event.type)
                assert update.event.record is not None and update.event.record.server is not None
                assert update.snapshot is not None and update.snapshot.columns == snapshot.columns
                if update.event.type is EventType.DELETED:
                    changed.set()

        watch = asyncio.create_task(ListWatch(reader).run(widget, NAMESPACE, receive))
        async with asyncio.timeout(30):
            await opened.wait()
        await custom.create_namespaced_custom_object(
            GROUP,
            "v1",
            NAMESPACE,
            "widgets",
            {
                "apiVersion": GROUP + "/v1",
                "kind": "Widget",
                "metadata": {"name": "owned-watch"},
                "spec": {"level": 11, "enabled": True},
            },
        )
        await custom.patch_namespaced_custom_object(
            GROUP,
            "v1",
            NAMESPACE,
            "widgets",
            "owned-watch",
            [{"op": "replace", "path": "/spec/level", "value": 12}],
        )
        await custom.delete_namespaced_custom_object(
            GROUP, "v1", NAMESPACE, "widgets", "owned-watch"
        )
        async with asyncio.timeout(30):
            await changed.wait()
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)
        watch = None
        assert events == [EventType.ADDED, EventType.MODIFIED, EventType.DELETED]
        checks.append("actual-table-watch-header-and-headerless-events-owned-cancellation")

        async with representation_gateway(cluster, connection, legacy=False) as (gateway, requests):
            fallback = ResourceReader(gateway, tables=True)
            ordinary = await fallback.list(widget, NAMESPACE, page_size=1)
            assert len(ordinary.items) == 3 and not ordinary.columns
            assert all(record.server is None for record in ordinary.items)
            assert requests[0]["table"] and not any(entry["table"] for entry in requests[1:])
            assert (await fallback.get(widget, "owned-0", NAMESPACE)).uid == value.uid
        checks.append("injected-ordinary-json-representation-over-real-cluster-fallback")

        # Only this owned cluster's default discovery grant is removed. Actual
        # RBAC then permits core directory access and denies named-version paths.
        rbac = client.RbacAuthorizationV1Api(connection.api)
        await rbac.delete_cluster_role_binding("system:discovery")
        username = "kuberich-owned-custom-reader"
        await rbac.create_cluster_role(
            client.V1ClusterRole(
                metadata=client.V1ObjectMeta(name=username),
                rules=[
                    client.V1PolicyRule(
                        non_resource_urls=["/api", "/api/*", "/apis"], verbs=["get"]
                    ),
                    client.V1PolicyRule(
                        api_groups=[""],
                        resources=["pods", "namespaces"],
                        verbs=["get", "list", "watch"],
                    ),
                ],
            )
        )
        await rbac.create_cluster_role_binding(
            client.V1ClusterRoleBinding(
                metadata=client.V1ObjectMeta(name=username),
                role_ref=client.V1RoleRef(
                    api_group="rbac.authorization.k8s.io", kind="ClusterRole", name=username
                ),
                subjects=[
                    client.RbacV1Subject(
                        kind="User", name=username, api_group="rbac.authorization.k8s.io"
                    )
                ],
            )
        )
        delegated = KubernetesSession(
            sessions.catalog.select(cluster.context, ConnectionOverrides(as_user=username)), 15
        )
        await delegated.open()
        async with representation_gateway(cluster, delegated, legacy=True) as (gateway, _):
            restricted_reader = ResourceReader(gateway, tables=True)
            restricted = await restricted_reader.discover()
            assert restricted.partial
            assert any(
                issue.source == GROUP + "/v1" and issue.status == 403 for issue in restricted.issues
            )
            pods = restricted.resolve("pods", group="")
            assert (await restricted_reader.list(pods, NAMESPACE)).items == ()
            try:
                await restricted_reader.list(widget, NAMESPACE)
                raise AssertionError("Actual custom-resource RBAC denial was hidden")
            except HttpProblem as problem:
                assert problem.status == 403
        checks.append(
            "actual-rbac-restricted-discovery-core-read-and-crd-denial-through-legacy-gateway"
        )

        await workspace.select_discovered("widgets", group=GROUP)
        await wait_for(live)
        identity = sessions.observation.identity
        assert workspace.store.observation.scope is not None
        assert workspace.store.observation.scope.resource.version == "v1"
        await extensions.patch_custom_resource_definition(
            "widgets." + GROUP,
            [{"op": "replace", "path": "/spec/versions/1/served", "value": False}],
        )

        async def version_changed() -> bool:
            await workspace.refresh_discovery()
            return (
                workspace.discovery is not None
                and workspace.discovery.resolve("widgets", group=GROUP).version == "v1beta1"
            )

        await wait_for(version_changed)
        await wait_for(live)
        assert workspace.store.observation.scope is not None
        assert workspace.store.observation.scope.resource.version == "v1beta1"
        assert sessions.client is connection and sessions.observation.identity == identity
        assert workspace.store.observation.snapshot is not None
        assert len(workspace.store.observation.snapshot.items) == 3
        checks.append("actual-preferred-served-version-change-rebind-without-client-replacement")

        await workspace.select_discovered("pods", group="")
        await wait_for(live)
        await verify_browser(cluster, extensions, custom)
        checks.append(
            "actual-pilot-generic-columns-sort-inspection-version-scopes-history-refresh-and-removal"
        )

        async def removed() -> bool:
            await workspace.refresh_discovery()
            return workspace.discovery is not None and not any(
                resource.group == GROUP for resource in workspace.discovery.resources
            )

        await wait_for(removed)
        await wait_for(live)
        assert workspace.store.observation.scope is not None
        assert workspace.store.observation.scope.resource.name == "pods"
        assert sessions.client is connection and sessions.observation.identity == identity
        assert cluster.path.read_bytes() == before
        checks.extend(("actual-crd-removal-refresh-preserves-core-view", "caller-config-unchanged"))
        return {
            "node_image": NODE_IMAGE,
            "checks": checks,
            "transport_injections": [
                "ordinary JSON representation",
                "legacy discovery representation",
            ],
            "permissions": "actual owned-cluster RBAC, not injected status codes",
        }
    finally:
        if watch is not None:
            watch.cancel()
            await asyncio.gather(watch, return_exceptions=True)
        if delegated is not None:
            await delegated.close()
        await workspace.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", type=Path, default="artifacts/cluster/custom-resources.json")
    args = parser.parse_args()
    with owned_cluster(args.kind) as cluster:
        result = asyncio.run(verify(cluster))
        result["cluster"] = cluster.name
    result["owned_cluster_deleted"] = True
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2) + "\n")
    print("Actual owned-kind custom resource checks passed.", flush=True)


if __name__ == "__main__":
    main()
