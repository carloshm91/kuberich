"""C01-C04 qualification on a newly created, explicitly owned disposable kind cluster."""

import argparse
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml
from kubernetes_asyncio.client import CoreV1Api, V1Namespace, V1ObjectMeta

from kubetrol.config.catalog import load_catalog
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.domain.pods import pod_row, utc_now
from kubetrol.domain.resources import resource_record
from kubetrol.domain.views import ResourceSelection, ViewStatus
from kubetrol.domain.watches import EventType, SyncStatus, SyncUpdate
from kubetrol.services.resources import ResourceReader
from kubetrol.services.sessions import SessionService
from kubetrol.services.watches import ListWatch
from kubetrol.services.workspace import WorkspaceService
from kubetrol.ui.app import KubetrolApp

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)


async def verify_pod_table(reader, resource, catalog, path, context):
    """Compare real pod columns with the API server's Table and run the UI on kind."""
    table = await reader.session.get_json(
        resource.path("kube-system"),
        params={"includeObject": "Object"},
        accept="application/json;as=Table;g=meta.k8s.io;v=v1",
    )
    assert table["kind"] == "Table" and table["rows"]
    for entry in table["rows"]:
        row = pod_row(resource_record(resource, entry["object"], "kube-system"))
        cells = row.cells(utc_now())
        assert cells[1] == entry["cells"][0]
        assert cells[2] == entry["cells"][1]
        assert cells[3] == entry["cells"][2]
        assert row.restarts == int(str(entry["cells"][3]).split()[0])
        assert row.created_at is not None and cells[-1] != "—"
    app = KubetrolApp(
        Settings(read_only=True),
        logging.Logger("owned-kind-pod-table"),
        catalog=catalog,
        connection=ConnectionRequest(
            kubeconfig=str(path), context=context, namespace="kube-system", timeout=15
        ),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        async with asyncio.timeout(30):
            while (
                app.workspace.store.observation.status is not ViewStatus.LIVE
                or not app.resources.row_count
            ):
                await asyncio.sleep(0.01)
        await pilot.pause()
        assert not app.query_one("#empty-state").display
        selected = app.resources.selected_uid
        await pilot.press("s", "s", "s", "S")
        assert app.resources.selected_uid == selected
        assert app.resources.descending
        output = Path("artifacts/ui").resolve()
        output.mkdir(parents=True, exist_ok=True)
        app.save_screenshot(filename="pods-owned-kind.svg", path=str(output))
        await pilot.press("slash", *"re:coredns", "enter")
        async with asyncio.timeout(30):
            while not app.resources.row_count or any(
                "coredns" not in str(app.resources.get_cell(row.key, "name"))
                for row in app.resources.ordered_rows
            ):
                await asyncio.sleep(0.01)
        assert "Filter active" in str(app.status.content)
        await pilot.press("escape", "colon", *"ns def")
        await pilot.pause()
        assert "ns default" in app.command_input.choices
        await pilot.press("tab", "enter")
        async with asyncio.timeout(30):
            while (
                app.workspace.store.observation.status is not ViewStatus.LIVE
                or app.workspace.store.observation.connection.namespace != "default"
            ):
                await asyncio.sleep(0.01)
        await pilot.pause()
        assert app.resources.row_count == 0
        assert "No pods in this scope" in str(app.query_one("#empty-title").content)
        await pilot.press("alt+left")
        async with asyncio.timeout(30):
            while (
                app.workspace.store.observation.status is not ViewStatus.LIVE
                or app.workspace.store.observation.connection.namespace != "kube-system"
                or app.resources.selected_uid != selected
            ):
                await asyncio.sleep(0.01)
        assert app.resources.descending
        await pilot.press("alt+right")
        async with asyncio.timeout(30):
            while (
                app.workspace.store.observation.status is not ViewStatus.LIVE
                or app.workspace.store.observation.connection.namespace != "default"
            ):
                await asyncio.sleep(0.01)
        assert app.resources.row_count == 0
        await pilot.press("ctrl+q")
    assert app.sessions.client is None and app._view_task.done() and not app._pod_projection._cache
    return {
        "real_pod_columns_match_server_table": True,
        "real_live_pod_widget": True,
        "real_pod_widget_selection_sort_scope": True,
        "pod_widget_clients_and_projection_closed": True,
        "real_local_regex_filter": True,
        "real_namespace_tab_completion": True,
        "real_navigation_history_selection_and_sort": True,
        "server_table_pod_count": len(table["rows"]),
    }


async def verify_watch(reader: ResourceReader, resource) -> dict[str, object]:
    """Mutate only fixtures inside this script's newly created local kind cluster."""
    api = CoreV1Api(reader.session.api)
    namespace = "kubetrol-watch-" + uuid4().hex[:12]
    created_namespace = await api.create_namespace(
        V1Namespace(metadata=V1ObjectMeta(name=namespace))
    )
    name = "owned-watch-example"
    finished = asyncio.Event()
    uid = None
    steps = []

    async def sink(update) -> None:
        nonlocal uid
        if update.status is SyncStatus.SNAPSHOT:
            assert all(record.name != name for record in update.snapshot.items)
            # This write happens between LIST and opening WATCH: it must not be lost.
            await api.create_namespaced_config_map(
                namespace,
                {"metadata": {"name": name}, "data": {"stage": "created"}},
            )
        if update.event is None or update.event.record is None:
            return
        record = update.event.record
        # Namespace controllers may also publish kube-root-ca.crt here.
        if record.name != name:
            return
        assert record.name == name and record.namespace == namespace and record.uid
        target_items = tuple(item for item in update.snapshot.items if item.name == name)
        if update.event.type is EventType.ADDED and uid is None:
            uid = record.uid
            steps.append("ADDED")
            assert len(target_items) == 1
            await api.replace_namespaced_config_map(
                name,
                namespace,
                {
                    "apiVersion": "v1",
                    "kind": "ConfigMap",
                    "metadata": {"name": name, "resourceVersion": record.resource_version},
                    "data": {"stage": "modified"},
                },
            )
        elif update.event.type is EventType.MODIFIED:
            assert record.uid == uid and record.manifest["data"]["stage"] == "modified"
            steps.append("MODIFIED")
            await api.delete_namespaced_config_map(
                name,
                namespace,
                body={"preconditions": {"uid": uid}},
            )
        elif update.event.type is EventType.DELETED:
            assert record.uid == uid and not target_items
            steps.append("DELETED")
            await api.create_namespaced_config_map(
                namespace,
                {"metadata": {"name": name}, "data": {"stage": "recreated"}},
            )
        elif update.event.type is EventType.ADDED:
            assert record.uid != uid and len(target_items) == 1
            assert target_items[0].uid == record.uid
            steps.append("RECREATED")
            finished.set()

    task = asyncio.create_task(ListWatch(reader).run(resource, namespace, sink))
    completion = asyncio.create_task(finished.wait())
    try:
        done, _ = await asyncio.wait(
            {task, completion}, timeout=30, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            await task
        assert finished.is_set() and steps == ["ADDED", "MODIFIED", "DELETED", "RECREATED"]
    finally:
        completion.cancel()
        task.cancel()
        results = await asyncio.gather(task, completion, return_exceptions=True)
        await api.delete_namespace(
            namespace,
            body={"preconditions": {"uid": created_namespace.metadata.uid}},
        )
    assert isinstance(results[0], asyncio.CancelledError)
    return {
        "real_list_watch_gap": True,
        "real_added_modified_deleted": True,
        "real_same_name_new_uid": True,
        "watch_cancellation_awaited": True,
        "owned_watch_fixture_deleted": True,
    }


async def verify_workspace(catalog, path: Path, context: str) -> dict[str, object]:
    owner = WorkspaceService(
        SessionService(
            catalog, ConnectionRequest(kubeconfig=str(path), namespace="kube-system", timeout=15)
        )
    )
    subscription = owner.subscribe()

    async def live():
        async with asyncio.timeout(30):
            while owner.store.observation.status is not ViewStatus.LIVE:
                if owner.store.observation.status is ViewStatus.FAILED:
                    raise AssertionError(
                        "Owned workspace could not synchronize its selected resource."
                    )
                await asyncio.sleep(0.01)
        return owner.store.observation

    try:
        await owner.connect(context)
        first = await live()
        assert first.scope.namespace == "kube-system" and len(first.snapshot.items) > 2
        old_watch = owner._watch
        transition = owner.select_namespace("default")
        assert owner.store.observation.snapshot is None
        await transition
        second = await live()
        assert old_watch.done() and second.scope.namespace == "default"
        assert second.scope.session.generation > first.scope.session.generation
        assert second.scope.session.connection_id == first.scope.session.connection_id
        await owner.select_resource(ResourceSelection("namespaces"))
        cluster = await live()
        assert cluster.scope.namespace is None and len(cluster.snapshot.items) > 1
        for _ in range(20):
            owner.select_namespace("default")
            owner.select_namespace("kube-system")
        await owner.select_resource(ResourceSelection("po"))
        current = await live()
        assert current.scope.namespace == "kube-system" and current.scope.resource.name == "pods"
        assert all(record.namespace == "kube-system" for record in current.snapshot.items)
        api = owner.sessions.client.api
        directory = Path(owner.sessions.client.directory.name)
        await owner.connect(context)
        reopened = await live()
        assert reopened.scope.session.connection_id != current.scope.session.connection_id
        assert api.rest_client.pool_manager.closed and not directory.exists()
        assert not owner.store.apply(
            first.revision, first.scope, SyncUpdate(SyncStatus.LIVE, first.snapshot)
        )
        assert (await anext(subscription)) is reopened
        final_api = owner.sessions.client.api
    finally:
        await owner.close()
    assert final_api.rest_client.pool_manager.closed
    assert owner._watch is None and owner._operation is None and owner.task.done()
    assert not owner._subscriptions and owner.store.observation.status is ViewStatus.DISCONNECTED
    assert not [
        task
        for task in asyncio.all_tasks()
        if task.get_name() in {"kubetrol-workspace", "kubetrol-resource-watch"}
    ]
    return {
        "real_workspace_scope_switch": True,
        "real_workspace_resource_switch": True,
        "real_coalesced_switches": True,
        "prior_generation_rejected": True,
        "real_workspace_reopened_client": True,
        "latest_subscription_observation": True,
        "workspace_exit_cleanup": True,
    }


async def verify_quiet_renewal(reader, resource, catalog, path, context) -> dict[str, object]:
    """Renew a quiet read in a namespace created only inside the owned cluster."""
    api = CoreV1Api(reader.session.api)
    namespace = "kubetrol-quiet-" + uuid4().hex[:12]
    created = await api.create_namespace(V1Namespace(metadata=V1ObjectMeta(name=namespace)))
    sessions = SessionService(
        catalog,
        ConnectionRequest(kubeconfig=str(path), context=context, namespace=namespace, timeout=2),
    )
    updates, opened = [], 0
    finished = asyncio.Event()

    async def sink(update):
        nonlocal opened
        updates.append(update.status)
        if update.status is SyncStatus.LIVE and update.event is None:
            opened += 1
            if opened == 3:
                finished.set()

    try:
        await sessions.connect(context)
        task = asyncio.create_task(
            ListWatch(ResourceReader(sessions.client)).run(resource, namespace, sink)
        )
        completion = asyncio.create_task(finished.wait())
        try:
            done, _ = await asyncio.wait(
                {task, completion}, timeout=15, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                await task
            assert finished.is_set() and opened == 3
            assert updates.count(SyncStatus.SNAPSHOT) == 1
            assert not set(updates) & {SyncStatus.RETRYING, SyncStatus.RELISTING, SyncStatus.FAILED}
        finally:
            task.cancel()
            completion.cancel()
            results = await asyncio.gather(task, completion, return_exceptions=True)
        assert isinstance(results[0], asyncio.CancelledError)
        assert not sessions.client.api.rest_client.pool_manager.connector._acquired
        owned_api = sessions.client.api
    finally:
        try:
            await sessions.close()
        finally:
            await api.delete_namespace(
                namespace, body={"preconditions": {"uid": created.metadata.uid}}
            )
    assert owned_api.rest_client.pool_manager.closed
    return {
        "real_quiet_watch_renewal": True,
        "normal_watch_renewal_stays_live": True,
        "quiet_watch_renews_without_relist": True,
        "owned_quiet_watch_cleanup": True,
    }


async def verify(path: Path, context: str) -> dict[str, object]:
    request = ConnectionRequest(kubeconfig=str(path), context=context, timeout=15)
    catalog = load_catalog(request, {})
    before = path.read_bytes()
    sessions = SessionService(catalog, request)
    try:
        first = await sessions.connect(context)
        assert first.state is ConnectionState.CONNECTED and not first.insecure
        assert {"default", "kube-system"} <= set(first.namespaces)
        api = sessions.client.api
        scoped = sessions.select_namespace("kube-system")
        assert scoped.identity.generation > first.identity.generation
        assert scoped.identity.connection_id == first.identity.connection_id
        second = await sessions.connect(context)
        assert second.state is ConnectionState.CONNECTED
        assert second.identity.connection_id != first.identity.connection_id
        assert second.namespace == "kube-system"
        assert api.rest_client.pool_manager.closed
        reader = ResourceReader(sessions.client)
        discovery = await reader.discover()
        assert not discovery.partial
        pods = discovery.find("po")
        assert pods.namespaced and {"list", "watch"} <= pods.verbs
        scoped_pods = await reader.list(pods, "kube-system", page_size=2)
        assert scoped_pods.namespace == "kube-system" and scoped_pods.resource_version
        assert len(scoped_pods.items) > 2
        assert all(record.uid and record.namespace == "kube-system" for record in scoped_pods.items)
        assert all(record.manifest["kind"] == "Pod" for record in scoped_pods.items)
        namespaces = discovery.find("namespaces")
        assert not namespaces.namespaced
        namespace_snapshot = await reader.list(namespaces, page_size=1)
        assert namespace_snapshot.resource_version and len(namespace_snapshot.items) > 1
        assert {"default", "kube-system"} <= {record.name for record in namespace_snapshot.items}
        assert all(record.uid and record.namespace is None for record in namespace_snapshot.items)
        deployments = discovery.find("deployments", group="apps")
        assert deployments.api_version == "apps/v1"
        deployment_snapshot = await reader.list(deployments, "kube-system", page_size=1)
        assert deployment_snapshot.resource_version and deployment_snapshot.items
        watch_evidence = await verify_watch(reader, discovery.find("configmaps"))
        quiet_evidence = await verify_quiet_renewal(
            reader, discovery.find("secrets"), catalog, path, context
        )
        workspace_evidence = await verify_workspace(catalog, path, context)
        pod_evidence = await verify_pod_table(reader, pods, catalog, path, context)
        assert path.read_bytes() == before
        active = sessions.client.api
    finally:
        await sessions.close()
    assert active.rest_client.pool_manager.closed
    return {
        "result": "passed",
        "tls_verified": True,
        "client_certificate_auth": True,
        "namespace_listing": True,
        "scope_generation_changed": True,
        "reopened_client_distinct": True,
        "prior_and_current_clients_closed": True,
        "kubeconfig_unchanged": True,
        "namespace_count": len(first.namespaces),
        "api_discovery": True,
        "discovery_complete": True,
        "core_and_named_groups": True,
        "resource_aliases": True,
        "namespaced_and_cluster_scoped_listing": True,
        "consistent_paginated_snapshots": True,
        "collection_versions_and_item_uids": True,
        "discovered_resource_count": len(discovery.resources),
        "scoped_pod_count": len(scoped_pods.items),
        **watch_evidence,
        **quiet_evidence,
        **workspace_evidence,
        **pod_evidence,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, help="verified kind v0.33.0 binary")
    parser.add_argument("--evidence", default="artifacts/cluster/context-sessions.json")
    arguments = parser.parse_args()
    name = "kubetrol-test-" + uuid4().hex[:12]
    with TemporaryDirectory(prefix="kubetrol-kind-") as directory:
        path = Path(directory) / "owned-kubeconfig"
        environment = {**os.environ, "KUBECONFIG": str(path)}
        command = [
            arguments.kind,
            "create",
            "cluster",
            "--name",
            name,
            "--kubeconfig",
            str(path),
            "--image",
            NODE_IMAGE,
            "--wait",
            "180s",
        ]
        try:
            print("Creating owned disposable kind cluster.", flush=True)
            subprocess.run(command, env=environment, check=True, timeout=300)
            # Local kind output is never read through the ambient default path.
            data = yaml.safe_load(path.read_text())
            context = "kind-" + name
            assert data["current-context"] == context
            evidence = asyncio.run(verify(path, context))
            output = Path(arguments.evidence)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"kind": "0.33.0", "node_image": NODE_IMAGE, **evidence}, indent=2)
                + "\n"
            )
            print(
                "Real API, discovery, snapshots, list/watch changes, TLS, scope and cleanup passed.",
                flush=True,
            )
        finally:
            subprocess.run(
                [arguments.kind, "delete", "cluster", "--name", name],
                env=environment,
                check=True,
                timeout=90,
            )
            print("Owned disposable cluster deleted.", flush=True)


if __name__ == "__main__":
    main()
