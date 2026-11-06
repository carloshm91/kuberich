"""Actual App relationship commands, HTTP identity and shared navigation history."""

import asyncio
from copy import deepcopy

import pytest
from aiohttp import web

from kuberich.domain.relationships import (
    RelationKind,
    RelationshipMode,
    RelationshipStatus,
    relationship_path_key,
)
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import ViewStatus
from tests.support.connections import catalog_fixture, namespaces
from tests.support.relationships import (
    ACCOUNTS,
    CLAIMS,
    CONFIGMAPS,
    DEPLOYMENTS,
    NODES,
    PODS,
    PRIORITIES,
    SECRETS,
    VOLUMES,
    descriptor,
    manifest,
    owner,
)
from tests.support.resources import descriptor as discovery_descriptor
from tests.support.resources import legacy_roots
from tests.support.workspace import stable_watch, wait_for, workspace_api
from tests.ui.test_navigation import make_app

REPLICAS = descriptor("replicasets", "ReplicaSet", "apps")
WIDGETS = descriptor("widgets", "Widget", "relationships.example.test", version="v1beta1")
WIDGETS_V1 = descriptor("widgets", "Widget", WIDGETS.group)
FAMILIES = (
    PODS,
    CONFIGMAPS,
    SECRETS,
    ACCOUNTS,
    CLAIMS,
    VOLUMES,
    NODES,
    PRIORITIES,
    DEPLOYMENTS,
    REPLICAS,
    descriptor("statefulsets", "StatefulSet", "apps"),
    descriptor("daemonsets", "DaemonSet", "apps"),
    descriptor("jobs", "Job", "batch"),
    descriptor("cronjobs", "CronJob", "batch"),
    descriptor("replicationcontrollers", "ReplicationController"),
    WIDGETS,
    WIDGETS_V1,
)


def pod_spec():
    return {
        "containers": [
            {
                "name": "app",
                "image": "synthetic",
                "envFrom": [
                    {"configMapRef": {"name": "settings"}},
                    {"secretRef": {"name": "credentials"}},
                ],
            }
        ],
        "serviceAccountName": "runner",
        "priorityClassName": "batch",
        "volumes": [{"persistentVolumeClaim": {"claimName": "storage"}}],
        "nodeName": "worker",
    }


class RelationshipAPI:
    """One owned loopback API; fresh GETs and racing LISTs are independently controlled."""

    def __init__(self, *, custom_owner=False):
        self.objects = {}
        self.reads = []
        self.list_replacements = {}
        self.active_watches = 0
        self.hold_path = None
        self.route_discovery = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        for namespace in ("team", "default"):
            self.add(
                PODS,
                "example",
                namespace=namespace,
                uid=f"{namespace}-pod-uid",
                spec=pod_spec(),
                metadata={
                    "ownerReferences": [
                        owner(
                            WIDGETS if custom_owner else REPLICAS,
                            name="custom" if custom_owner else "replica",
                            uid="custom-uid" if custom_owner else "replica-uid",
                        )
                    ]
                },
            )
            self.add(
                REPLICAS,
                "replica",
                namespace=namespace,
                uid="replica-uid",
                spec={"template": {"spec": pod_spec()}},
                metadata={
                    "ownerReferences": [owner(DEPLOYMENTS, name="workload", uid="workload-uid")]
                },
            )
            self.add(
                DEPLOYMENTS,
                "workload",
                namespace=namespace,
                uid="workload-uid",
                spec={"replicas": 0, "template": {"spec": pod_spec()}},
            )
            self.add(
                ACCOUNTS,
                "runner",
                namespace=namespace,
                uid="runner-uid",
                secrets=[{"name": "credentials", "uid": "credentials-uid"}],
            )
            self.add(
                CONFIGMAPS,
                "settings",
                namespace=namespace,
                uid="settings-uid",
                data={"value": "SYNTHETIC-CONFIGURATION-MUST-NOT-APPEAR"},
            )
            self.add(
                SECRETS,
                "credentials",
                namespace=namespace,
                uid="credentials-uid",
                data={"value": "SYNTHETIC-SECRET-MUST-NOT-APPEAR"},
            )
            self.add(CLAIMS, "storage", namespace=namespace, uid="storage-uid", spec={})
            for resource in (WIDGETS, WIDGETS_V1):
                self.add(resource, "custom", namespace=namespace, uid="custom-uid")
        self.add(NODES, "worker", uid="worker-uid", spec={})
        self.add(PRIORITIES, "batch", uid="batch-uid", spec={}, value=1000)
        self.add(
            VOLUMES,
            "disk",
            uid="disk-uid",
            spec={
                "claimRef": {
                    "name": "storage",
                    "namespace": "team",
                    "uid": "storage-uid",
                }
            },
        )

    def add(self, resource, name, *, namespace="team", uid, **fields):
        value = manifest(resource, name=name, uid=uid, namespace=namespace, **fields)
        self.objects[
            (
                resource.group,
                resource.version,
                resource.name,
                namespace if resource.namespaced else None,
                name,
            )
        ] = value

    def roots(self):
        values = legacy_roots()
        values["/api/v1"]["resources"] = [
            discovery_descriptor(resource.name, kind=resource.kind, namespaced=resource.namespaced)
            for resource in FAMILIES
            if not resource.group
        ] + [discovery_descriptor("namespaces", kind="Namespace", namespaced=False)]
        groups = {}
        for resource in FAMILIES:
            if resource.group:
                groups.setdefault(resource.group, {})[resource.version] = None
        values["/apis"]["groups"] = [
            {
                "name": group,
                "versions": [
                    {"groupVersion": f"{group}/{version}", "version": version}
                    for version in versions
                ],
                "preferredVersion": {"groupVersion": group + "/v1", "version": "v1"},
            }
            for group, versions in groups.items()
        ]
        for group, versions in groups.items():
            for version in versions:
                values[f"/apis/{group}/{version}"] = {
                    "groupVersion": f"{group}/{version}",
                    "resources": [
                        discovery_descriptor(
                            resource.name, kind=resource.kind, namespaced=resource.namespaced
                        )
                        for resource in FAMILIES
                        if (resource.group, resource.version) == (group, version)
                    ],
                }
        if self.route_discovery:
            values.pop("/api")
        return values

    async def handler(self, request):
        self.reads.append((request.path, dict(request.query)))
        if request.path == self.hold_path:
            self.started.set()
            await self.release.wait()
        if request.path == "/api":
            return web.json_response(
                {"kind": "APIVersions", "apiVersion": "v1", "versions": ["v1"]}
            )
        if "watch" in request.query:
            self.active_watches += 1
            try:
                return await stable_watch(request)
            finally:
                self.active_watches -= 1
        parts = request.path.strip("/").split("/")
        if parts[0] == "api":
            group, version, tail = "", parts[1], parts[2:]
        else:
            group, version, tail = parts[1], parts[2], parts[3:]
        namespace = None
        if len(tail) >= 3 and tail[0] == "namespaces":
            namespace, tail = tail[1], tail[2:]
        resource = next(
            (
                item
                for item in FAMILIES
                if (item.group, item.version, item.name) == (group, version, tail[0])
            ),
            None,
        )
        if resource is None:
            return web.Response(status=404)
        if len(tail) == 2:
            value = self.objects.get((group, version, resource.name, namespace, tail[1]))
            return web.Response(status=404) if value is None else web.json_response(value)
        items = []
        for key, value in self.objects.items():
            if key[:3] != (group, version, resource.name) or (
                namespace is not None and key[3] != namespace
            ):
                continue
            value = deepcopy(value)
            if key in self.list_replacements:
                value["metadata"]["uid"] = self.list_replacements[key]
            items.append(value)
        return web.json_response(
            {
                "apiVersion": resource.api_version,
                "kind": resource.kind + "List",
                "metadata": {"resourceVersion": "synthetic-list"},
                "items": items,
            }
        )


async def namespace_handler(request):
    return namespaces("team", "default")


async def graph_ready(app, *, name=None):
    def rendered():
        snapshot = app.workspace.store.observation.relationships
        rows = (
            tuple(row for row in snapshot.rows if name is None or row.ref.name == name)
            if snapshot is not None
            else ()
        )
        return (
            app.state.view_kind == "relationships"
            and snapshot is not None
            and app.relationships_table.request == app.workspace.relationship_request
            and any(row.status is RelationshipStatus.READY for row in rows)
            and all(
                relationship_path_key(row.path) in app.relationships_table.rows
                and app.relationships_table.row_at(row.path) == row
                for row in rows
            )
            and app.state.status is ViewStatus.LIVE
            and not app.workspace.relationship_collecting
        )

    await wait_for(rendered)


def graph_row(app, name, *, relation=None):
    return next(
        row
        for row in app.workspace.store.observation.relationships.rows
        if row.ref.name == name and (relation is None or row.relation == relation)
    )


def select_graph(app, row):
    app.relationships_table.move_cursor(
        row=app.relationships_table.get_row_index(relationship_path_key(row.path))
    )
    app.relationships_table.focus()


def graph_geometry(app):
    table = app.relationships_table
    return {
        "max_scroll_x": table.max_scroll_x,
        "virtual_size": table.virtual_size,
        "region": table.region,
        "columns": tuple(
            (key.value, column.content_width, column.width, column.auto_width)
            for key, column in table.columns.items()
        ),
    }


async def pods_ready(app, namespace="team"):
    await wait_for(
        lambda: (
            app.state.view_kind == "pods"
            and app.state.status is ViewStatus.LIVE
            and app.state.namespace == namespace
            and app.resources.row_count == 1
        )
    )


@pytest.mark.asyncio
async def test_actual_xray_keyboard_expansion_keeps_graph_scope_and_resource_actions_separate(
    tmp_path,
):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(120, 30)) as pilot:
            await pods_ready(app)
            await pilot.press("colon", *"xray", "enter")
            await graph_ready(app, name="replica")
            assert app.views.route.kind is ViewKind.RELATIONSHIPS
            assert app.state.scope is None and app.workspace.store.observation.snapshot is None
            request = app.workspace.relationship_request
            assert request.expanded == frozenset({()})
            assert request.scope.root.uid == "team-pod-uid"
            assert not app.check_action("inspect_yaml", ()) and not app.check_action(
                "review_delete", ()
            )
            before_history = len(app.history.previous)
            replica = graph_row(app, "replica", relation=RelationKind.CONTROLLER_OWNER)
            select_graph(app, replica)
            await pilot.press("enter")
            await graph_ready(app, name="workload")
            await pilot.pause()
            assert app.relationships_table.selected_path() == replica.path, (
                app.relationships_table.capture_viewport()
            )
            assert replica.path in app.workspace.relationship_request.expanded
            await pilot.press("right")
            selected = app.relationships_table.row_at(app.relationships_table.selected_path())
            assert selected is not None, (
                app.relationships_table.capture_viewport(),
                app.focused,
                app.relationships_table.request,
                app.workspace.store.observation.relationships.rows,
            )
            assert selected.path and selected.path[:-1] == replica.path
            await pilot.press("left")
            assert app.relationships_table.selected_path() == replica.path
            await pilot.press("left")
            await graph_ready(app)
            assert replica.path not in app.workspace.relationship_request.expanded
            assert not any(
                row.ref.name == "workload"
                for row in app.workspace.store.observation.relationships.rows
            )
            assert len(app.history.previous) == before_history
            assert app.state.scope is None and len(app.screen_stack) == 1
            await app.run_command("usedby")
            assert "UsedBy supports" in str(app.status.content)
            assert app.workspace.relationship_request.scope.mode is RelationshipMode.XRAY
        await wait_for(lambda: api.active_watches == 0)
        assert app.workspace.ownership.relationships_count == api.active_watches == 0
        assert app.sessions.client is None


@pytest.mark.asyncio
@pytest.mark.parametrize("custom,opening", [(False, "open"), (True, "o")])
@pytest.mark.parametrize("recreated", [False, True])
async def test_open_relationship_pins_observed_uid_and_exact_served_version(
    tmp_path, custom, opening, recreated
):
    api = RelationshipAPI(custom_owner=custom)
    resource, name, expected_uid = (
        (WIDGETS, "custom", "custom-uid") if custom else (REPLICAS, "replica", "replica-uid")
    )
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(120, 30)) as pilot:
            await pods_ready(app)
            await app.run_command("xray")
            await graph_ready(app, name=name)
            row = graph_row(app, name, relation=RelationKind.CONTROLLER_OWNER)
            assert row.observed_uid == expected_uid
            assert row.ref.resource.version == resource.version
            select_graph(app, row)
            if recreated:
                api.list_replacements[
                    (resource.group, resource.version, resource.name, "team", name)
                ] = "recreated-same-name"
            if opening == "o":
                await pilot.press("o")
            else:
                await app.run_command("open")
            table = app.custom_table if custom else app.standard_table
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.status is ViewStatus.LIVE
                    and (
                        app.state.scope.resource.group,
                        app.state.scope.resource.version,
                        app.state.scope.resource.name,
                    )
                    == (resource.group, resource.version, resource.name)
                    and table.display
                    and table.row_count == (0 if recreated else 1)
                )
            )
            assert app.views.expected_uid == expected_uid
            assert app.state.scope.resource.version == resource.version
            if custom:
                assert app.workspace.selection.version == resource.version
            assert app.state.selected == (None if recreated else expected_uid)
            assert any(path == resource.path("team") + "/" + name for path, _ in api.reads)
            assert any(
                path == resource.path("team") for path, query in api.reads if "watch" not in query
            )
            if recreated:
                reads_before = [
                    path for path, _ in api.reads if path == resource.path("team") + "/" + name
                ]
                await pilot.press("y")
                await pilot.pause()
                assert len(app.screen_stack) == 1 and app.state.selected is None
                assert [
                    path for path, _ in api.reads if path == resource.path("team") + "/" + name
                ] == reads_before
            await pilot.press("escape")
            await graph_ready(app, name=name)
            assert app.workspace.relationship_request.scope.root.uid == "team-pod-uid"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource,name,uid",
    [
        (CONFIGMAPS, "settings", "settings-uid"),
        (SECRETS, "credentials", "credentials-uid"),
        (ACCOUNTS, "runner", "runner-uid"),
        (CLAIMS, "storage", "storage-uid"),
        (PRIORITIES, "batch", "batch-uid"),
    ],
)
async def test_actual_usedby_scans_all_five_root_types_without_publishing_values(
    tmp_path, resource, name, uid
):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(120, 30)) as pilot:
            await pods_ready(app)
            await app.run_command(
                f"resource {resource.name}.{resource.group or 'core'}/{resource.version}"
            )
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == resource.name
                    and app.state.status is ViewStatus.LIVE
                    and app.custom_table.row_count == 1
                )
            )
            await pilot.press("colon", *"usedby", "enter")
            await graph_ready(app, name="example")
            snapshot = app.workspace.store.observation.relationships
            request = snapshot.request
            assert request.scope.mode is RelationshipMode.USED_BY
            assert request.scope.root.uid == uid and request.scope.root.name == name
            assert request.scope.root.namespace == ("team" if resource.namespaced else None)
            assert request.scope.namespace == "team"
            incoming = [
                row for row in snapshot.rows if row.path and row.relation is RelationKind.REFERENCE
            ]
            assert any(
                row.ref.name == "example" and row.observed_uid == "team-pod-uid" for row in incoming
            )
            assert any(
                row.ref.name == "workload" for row in incoming
            )  # The template has zero replicas.
            assert snapshot.sources and all(
                source.status is RelationshipStatus.READY for source in snapshot.sources
            )
            assert "SYNTHETIC-SECRET-MUST-NOT-APPEAR" not in repr(snapshot)
            assert "SYNTHETIC-CONFIGURATION-MUST-NOT-APPEAR" not in repr(snapshot)
            assert app.state.scope is None and app.workspace.store.observation.snapshot is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [RelationshipMode.XRAY, RelationshipMode.USED_BY])
async def test_graph_history_restores_mode_expansion_filter_and_descendant_viewport_after_delayed_back(
    tmp_path, mode
):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(100, 24)) as pilot:
            await pods_ready(app)
            if mode is RelationshipMode.USED_BY:
                await app.run_command("cm")
                await wait_for(
                    lambda: (
                        app.state.scope is not None
                        and app.state.scope.resource.name == "configmaps"
                        and app.standard_table.row_count == 1
                    )
                )
            await app.run_command(mode.value)
            name = "example" if mode is RelationshipMode.USED_BY else "replica"
            await graph_ready(app, name=name)
            selected = graph_row(
                app,
                name,
                relation=RelationKind.REFERENCE
                if mode is RelationshipMode.USED_BY
                else RelationKind.CONTROLLER_OWNER,
            )
            select_graph(app, selected)
            await pilot.press("enter")
            await graph_ready(app)
            await pilot.pause()
            query = "example" if mode is RelationshipMode.USED_BY else "re:replica|workload"
            await pilot.press("slash")
            app.filter_input.value = query
            await pilot.press("enter")
            snapshot = app.workspace.store.observation.relationships
            matching_names = (
                {"example"} if mode is RelationshipMode.USED_BY else {"replica", "workload"}
            )
            ancestors = {
                row.path[:depth]
                for row in snapshot.rows
                if row.ref.name in matching_names
                for depth in range(len(row.path) + 1)
            }
            expected_visible = {
                relationship_path_key(row.path) for row in snapshot.rows if row.path in ancestors
            }
            graph_keys = {relationship_path_key(row.path) for row in snapshot.rows}
            await wait_for(
                lambda: (
                    graph_keys.intersection(app.relationships_table.rows) == expected_visible
                    and all(
                        app.relationships_table.row_at(row.path) == row
                        for row in snapshot.rows
                        if row.path in ancestors
                    )
                )
            )
            select_graph(app, selected)
            app.relationships_table.scroll_to(x=9, animate=False, immediate=True, force=True)
            await pilot.pause()
            viewport = app.relationships_table.capture_viewport()
            original_geometry = graph_geometry(app)
            bookmark = app.navigator.capture()
            assert selected.path in bookmark.relationships.expanded
            assert viewport.selected == relationship_path_key(selected.path) and viewport.x == 9
            await app.run_command("open")
            await wait_for(
                lambda: app.state.scope is not None and app.state.status is ViewStatus.LIVE
            )
            # Hold the actual graph root GET so the first restored publication contains no descendant.
            root = bookmark.relationships.root
            api.hold_path = root.resource.path(root.namespace) + "/" + root.name
            await pilot.press("escape")
            await wait_for(api.started.is_set)
            assert app.state.view_kind == "relationships" and app.state.scope is None
            assert app.workspace.relationship_collecting
            api.release.set()
            await graph_ready(app, name=name)
            async with asyncio.timeout(5):
                await wait_for(
                    lambda: app.relationships_table.capture_viewport().selected == viewport.selected
                )
                assert await app.relationships_table.wait_for_refresh()
            restored = app.navigator.capture()
            assert restored.relationships.mode is mode
            assert restored.relationships.expanded == bookmark.relationships.expanded
            assert app.filter_input.value == query
            assert app.relationships_table.capture_viewport() == viewport, (
                original_geometry,
                graph_geometry(app),
            )
            await pilot.press("alt+right")
            await wait_for(
                lambda: app.state.scope is not None and app.state.status is ViewStatus.LIVE
            )
            await pilot.press("alt+left")
            await graph_ready(app, name=name)
            async with asyncio.timeout(5):
                await wait_for(
                    lambda: app.relationships_table.capture_viewport().selected == viewport.selected
                )
                assert await app.relationships_table.wait_for_refresh()
            assert app.filter_input.value == query
            assert app.relationships_table.capture_viewport() == viewport, (
                original_geometry,
                graph_geometry(app),
            )


@pytest.mark.asyncio
async def test_namespace_picker_keeps_cluster_root_separate_from_its_new_search_namespace(tmp_path):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(120, 30)) as pilot:
            await pods_ready(app)
            await app.run_command("resource priorityclasses.scheduling.k8s.io/v1")
            await wait_for(
                lambda: (
                    app.custom_table.row_count == 1
                    and app.state.scope is not None
                    and app.state.scope.resource.name == "priorityclasses"
                )
            )
            await app.run_command("usedby")
            await graph_ready(app, name="example")
            root = app.workspace.relationship_request.scope.root
            await app.run_command("ns")
            await wait_for(
                lambda: app.state.view_kind == "namespaces" and app.namespace_table.row_count == 2
            )
            app.namespace_table.move_cursor(
                row=app.namespace_table.get_row_index("namespace-default")
            )
            await pilot.press("enter")
            await graph_ready(app, name="example")
            request = app.workspace.relationship_request
            assert request.scope.root.uid == root.uid and request.scope.root.name == root.name
            assert request.scope.root.namespace is None
            assert request.scope.root.session == app.sessions.observation.identity
            assert request.scope.namespace == app.state.namespace == "default"
            assert request.scope.mode is RelationshipMode.USED_BY
            assert graph_row(app, "example").ref.namespace == "default"
            assert graph_row(app, "example").observed_uid == "default-pod-uid"


@pytest.mark.asyncio
async def test_namespace_picker_changes_namespaced_graph_root_to_an_ordinary_resource_list(
    tmp_path,
):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        async with app.run_test(size=(120, 30)) as pilot:
            await pods_ready(app)
            await app.run_command("xray")
            await graph_ready(app, name="replica")
            await app.run_command("ns")
            await wait_for(
                lambda: app.state.view_kind == "namespaces" and app.namespace_table.row_count == 2
            )
            await pilot.press("escape")
            await graph_ready(app, name="replica")
            assert app.workspace.relationship_request.scope.root.namespace == "team"
            await app.run_command("ns")
            await wait_for(
                lambda: app.namespace_table.row_count == 2 and app.namespace_table.display
            )
            app.namespace_table.move_cursor(
                row=app.namespace_table.get_row_index("namespace-default")
            )
            await pilot.press("enter")
            await pods_ready(app, "default")
            assert app.workspace.relationship_request is None
            assert app.views.expected_uid is None
            assert app.state.selected == "default-pod-uid"


@pytest.mark.asyncio
async def test_context_switch_retires_pending_graph_read_and_rejects_its_late_response(tmp_path):
    api = RelationshipAPI()
    api.hold_path = "/api/v1/namespaces/team/serviceaccounts/runner"
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                await pods_ready(app)
                await app.run_command("xray")
                await wait_for(api.started.is_set)
                previous = app.workspace.relationship_request
                assert previous is not None and app.workspace.relationship_collecting
                await app.run_command("ctx kuberich-test-Two")
                await pods_ready(app, "default")
                assert app.state.context == "kuberich-test-Two"
                assert app.workspace.relationship_request is None
                assert app.sessions.observation.identity != previous.scope.root.session
                api.release.set()
                await pilot.pause()
                assert app.workspace.store.observation.relationships is None
                assert app.state.view_kind == "pods" and app.state.selected == "default-pod-uid"
                assert not app.workspace.relationship_collecting
        finally:
            api.release.set()
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None and app.workspace.ownership.relationships_count == 0


@pytest.mark.asyncio
async def test_cross_context_back_restores_graph_under_a_new_session_and_revalidates_root_uid(
    tmp_path,
):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test(size=(100, 24)) as pilot:
                await pods_ready(app)
                await app.run_command("xray")
                await graph_ready(app, name="replica")
                original = app.workspace.relationship_request
                replica = graph_row(app, "replica", relation=RelationKind.CONTROLLER_OWNER)
                select_graph(app, replica)
                await pilot.press("enter")
                await graph_ready(app, name="workload")
                bookmark = app.navigator.capture()
                await app.run_command("ctx kuberich-test-Two")
                await pods_ready(app, "default")
                assert app.state.context == "kuberich-test-Two"
                other_session = app.sessions.observation.identity
                assert other_session != original.scope.root.session
                root_path = (
                    original.scope.resource.path(original.scope.root.namespace)
                    + "/"
                    + original.scope.root.name
                )
                before_gets = sum(path == root_path for path, _ in api.reads)
                api.hold_path = "/api"
                api.route_discovery = True
                await pilot.press("alt+left")
                await wait_for(api.started.is_set)
                assert app.state.context == bookmark.context
                api.release.set()
                await graph_ready(app, name="workload")
                restored = app.workspace.relationship_request
                session = app.sessions.observation.identity
                assert session.context == bookmark.context
                assert session != original.scope.root.session and session != other_session
                assert restored.scope.root.session == session
                assert restored.scope.root.uid == original.scope.root.uid == "team-pod-uid"
                assert restored.scope.root.namespace == original.scope.root.namespace == "team"
                assert restored.scope.namespace == bookmark.namespace
                assert restored.expanded == bookmark.relationships.expanded
                assert sum(path == root_path for path, _ in api.reads) == before_gets + 1
                root = next(
                    row
                    for row in app.workspace.store.observation.relationships.rows
                    if not row.path
                )
                assert root.status is RelationshipStatus.READY
                assert root.ref.uid == root.observed_uid == "team-pod-uid"
                await pilot.pause()
                assert app.relationships_table.capture_viewport().selected == bookmark.selected
                assert app.workspace.store.observation.scope is None
        finally:
            api.release.set()
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_new_pulse_intent_survives_late_discovery_from_cross_context_graph_back(tmp_path):
    api = RelationshipAPI()
    async with workspace_api(namespace_handler, api.handler, discovery_roots=api.roots) as url:
        app = make_app(catalog_fixture(tmp_path, url))
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                await pods_ready(app)
                await app.run_command("xray")
                await graph_ready(app, name="replica")
                await app.run_command("ctx kuberich-test-Two")
                await pods_ready(app, "default")
                api.hold_path = "/api"
                api.route_discovery = True
                await pilot.press("alt+left")
                await wait_for(api.started.is_set)
                assert app.state.context == "kuberich-test-one"
                await app.run_command("pulse")
                assert app.state.view_kind == "pulse"
                api.release.set()
                await wait_for(
                    lambda: app.pulse_table.scope is not None and app.pulse_table.row_count > 0
                )
                await pilot.pause()
                assert app.state.view_kind == "pulse" and app.views.route.kind is ViewKind.PULSE
                assert app.pulse_table.scope.session.context == "kuberich-test-one"
                assert app.pulse_table.scope.namespace == "team"
                assert app.workspace.relationship_request is None
                assert app.workspace.store.observation.relationships is None
                assert not app.workspace.relationship_collecting
        finally:
            api.release.set()
        await wait_for(lambda: api.active_watches == 0)
        assert app.sessions.client is None
