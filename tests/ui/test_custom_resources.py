"""Real discovery, Table/JSON, UID inspection and generic workspace navigation."""

import asyncio
import logging
import threading

import pytest

from kuberich.config.schema import Settings
from kuberich.domain.views import ViewStatus
from kuberich.services.commands import GenericResourceCommand
from kuberich.services.pods import CustomProjection
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture
from tests.support.custom import GROUP, CustomAPI, custom_api
from tests.support.workspace import wait_for
from tests.ui.test_standard_resources import command


def app_for(tmp_path, url, initial=None):
    return KubeRichApp(
        Settings(),
        logging.Logger("custom-browser", level=100),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=initial or GenericResourceCommand("widgets", GROUP),
    )


async def loaded(app, *, name="widgets", version="v1", namespace="team", count=3):
    await wait_for(
        lambda: (
            app.workspace.store.observation.status is ViewStatus.LIVE
            and app.workspace.store.observation.scope.resource.name == name
            and app.workspace.store.observation.scope.resource.version == version
            and app.workspace.store.observation.scope.namespace == namespace
            and app.custom_table.row_count == count
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_server_columns_scope_typed_sort_filter_inspection_and_history(tmp_path, size):
    async with custom_api() as (url, owner):
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await loaded(app)
            await pilot.pause()
            table = app.custom_table
            bounds = app.query_one("#resource-view").region
            assert tuple(c.value for c in table.columns) == ("namespace", "name", "c2", "c3", "age")
            assert table.get_cell("owned-missing", "c2").text == "—"
            assert GROUP + "/v1" in str(app.query_one("#resource-view").border_title)
            table.set_sort("c2")
            assert [r.key.value for r in table.ordered_rows] == [
                "owned-two",
                "owned-ten",
                "owned-missing",
            ]
            table.move_cursor(row=0)
            await pilot.press("j")
            assert table.selected_uid == "owned-ten"
            before = table.capture_viewport()
            await pilot.press("enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            assert app.screen.page == "details" and "Widget" in app.screen.viewer.text
            await pilot.press("y")
            assert "raw-field" in app.screen.viewer.text and GROUP + "/v1" in app.screen.viewer.text
            await pilot.press("escape")
            assert app.focused is table and table.capture_viewport() == before
            assert not app.check_action("edit", ()) and not app.check_action("shell", ())
            await command(app, pilot, "delete")
            assert "read-only" in str(app.status.content) and len(app.screen_stack) == 1
            await command(app, pilot, "columns")
            assert "c2=Level" in str(app.status.content)
            await command(app, pilot, "columns c2")
            await wait_for(lambda: "c3" not in table.columns)
            await pilot.pause()
            assert table.selected_uid == "owned-ten" and table.sort_column == "c2"
            await command(app, pilot, "columns c99")
            await pilot.pause()
            assert "retained" in str(app.status.content) and "c3" not in table.columns
            await command(app, pilot, "gdt")
            await loaded(app, name="gadgets", namespace=None)
            assert "(cluster)" in str(app.query_one("#resource-view").border_title)
            await command(app, pilot, "gdt team")
            assert "cluster-scoped" in str(app.status.content)
            await pilot.press("alt+left")
            await loaded(app)
            await pilot.pause()
            assert (
                table.sort_column == "c2"
                and table.selected_uid == "owned-ten"
                and "c3" not in table.columns
            )
            await pilot.press("slash", *"true", "enter")
            await wait_for(lambda: "Filter active" in str(app.status.content))
            # Hidden server columns do not participate in the visible local filter.
            assert table.row_count == 0
            await pilot.press("escape")
            await loaded(app)
            await command(app, pilot, "columns default")
            await wait_for(lambda: "c3" in table.columns)
            await command(app, pilot, "wdg other")
            await loaded(app, namespace="other")
            assert app.query_one("#resource-view").region == bounds
            await command(app, pilot, "ns team")
            await loaded(app)
            await command(app, pilot, "widgets.owned.example.test/v1beta1 *")
            await loaded(app, version="v1beta1", namespace=None)
            assert app.workspace.selection.version == "v1beta1"
            await pilot.press("c")
            await wait_for(lambda: app.context_table.row_count == 2)
            await pilot.press("escape")
            await loaded(app, version="v1beta1", namespace=None)
            await command(app, pilot, "ctx kuberich-test-Two")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.context == "kuberich-test-Two"
                )
            )
            await command(app, pilot, "wdg")
            await loaded(app, namespace="default")
        assert app.sessions.client is None and app._render_task.done() and app._view_task.done()
        assert any("as=Table" in (accept or "") for _, _, accept in owner.reads)


@pytest.mark.asyncio
async def test_schema_refresh_preference_removal_alias_ambiguity_and_core_recovery(tmp_path):
    async with custom_api(CustomAPI(ambiguous=True)) as (url, owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            client = app.sessions.client
            assert "wdg" not in app._suggestions("wd")
            await command(app, pilot, "wdg")
            assert "ambiguous" in str(app.status.content)
            assert app.custom_table.row_count == 3
            table = app.custom_table
            table.set_sort("c2")
            table.move_cursor(row=1)
            before = table.selected_uid
            await command(app, pilot, "columns none")
            await wait_for(lambda: "c2" not in table.columns)
            await command(app, pilot, "columns default")
            await wait_for(lambda: "c2" in table.columns)
            table.set_sort("c2")
            path = "/apis/" + GROUP + "/v1/namespaces/team/widgets"
            await wait_for(lambda: path in owner.streams)
            await owner.update(path, changed=True)
            await wait_for(
                lambda: table.columns["c2"].label.plain == "[bold]Ready" and table.row_count == 3
            )
            await pilot.pause()
            # Retained rows from a different schema become unknown, never reinterpreted.
            assert table.get_cell("owned-two", "c2").text == "—"
            assert table.selected_uid == before and table.sort_column == "name"
            owner.changed = True
            owner.preferred = "v1beta1"
            await command(app, pilot, "refresh")
            await loaded(app, version="v1beta1")
            assert app.sessions.client is client
            owner.installed = False
            await command(app, pilot, "refresh")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            assert app.custom_table.row_count == 0
            await command(app, pilot, "po")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.scope.resource.name == "pods"
                )
            )
            assert app.sessions.client is client


@pytest.mark.asyncio
async def test_recreated_gvr_with_identical_columns_renews_scope_kind_and_uid(tmp_path):
    async with custom_api() as (url, owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            table = app.custom_table
            headers = table.resource_layout.headers
            selected = table.selected_uid
            connection = app.sessions.client
            await command(app, pilot, "columns c3")
            await wait_for(lambda: "c2" not in table.columns)
            owner.installed = False
            await command(app, pilot, "refresh")
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
            assert table.row_count == 0
            owner.installed, owner.recreated = True, True
            await command(app, pilot, "refresh")
            await loaded(app, namespace=None)
            await pilot.pause()
            scope = app.workspace.store.observation.scope
            assert scope.resource.kind == "Secret" and not scope.resource.namespaced
            assert table.resource_layout.headers == headers
            assert tuple(key.value for key in table.columns) == ("name", "c2", "c3", "age")
            assert table.get_cell("replacement-ten", "c2").text == "[REDACTED]"
            assert table.get_cell("replacement-ten", "c3").text == "[REDACTED]"
            assert table.get_cell("replacement-ten", "name").text == "ten"
            assert table.selected_uid != selected and selected not in table.rows
            await pilot.press("y")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            assert "kind: Secret" in app.screen.viewer.text
            assert "synthetic-private-replacement" not in app.screen.viewer.text
            assert "[REDACTED]" in app.screen.viewer.text
            await pilot.press("escape")
            assert app.sessions.client is connection
            assert any(path == "/apis/" + GROUP + "/v1/widgets" for path, _, _ in owner.reads)


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_deferred_unavailable_startup_reports_failure_and_recovers(tmp_path, ambiguous):
    async with custom_api(CustomAPI(ambiguous=ambiguous)) as (url, _owner):
        app = app_for(tmp_path, url, GenericResourceCommand("wdg" if ambiguous else "missing"))
        async with app.run_test() as pilot:
            await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
            app._refresh_tables()
            await pilot.pause()
            assert ("ambiguous" if ambiguous else "not discovered") in str(app.status.content)
            assert app.resources.display and not app.custom_table.display
            await command(app, pilot, "widgets." + GROUP)
            await loaded(app)
            assert "not discovered" not in str(app.status.content)
            assert "ambiguous" not in str(app.status.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["fallback", "denied", "malformed"])
async def test_plain_json_fallback_and_rbac_keep_useful_metadata_and_navigation(tmp_path, mode):
    denied = mode == "denied"
    async with custom_api(CustomAPI(**{mode: True})) as (url, owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            if denied:
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.FAILED)
                await pilot.pause()
                assert "403" in str(app.status.content)
            else:
                await loaded(app)
                assert tuple(c.value for c in app.custom_table.columns) == (
                    "namespace",
                    "name",
                    "age",
                )
                await command(app, pilot, "columns")
                assert "metadata only" in str(app.status.content)
                await pilot.press("y")
                await wait_for(
                    lambda: (
                        isinstance(app.screen, InspectionScreen) and app.screen.result is not None
                    )
                )
                assert "raw-field" in app.screen.viewer.text
                await pilot.press("escape")
            await command(app, pilot, "po")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.workspace.store.observation.scope.resource.name == "pods"
                )
            )
        assert (
            any(accept == "application/json" for _, _, accept in owner.reads)
            if not denied
            else True
        )


@pytest.mark.asyncio
async def test_owned_generic_projection_rejects_replaced_context_and_gvr_reply(
    tmp_path, monkeypatch
):
    async with custom_api(CustomAPI(sensitive=True)) as (url, _owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            assert app.custom_table.get_cell("owned-ten", "c4").text == "[REDACTED]"
            assert "synthetic-column-secret" not in str(app.custom_table._rows)
            entered, release = threading.Event(), threading.Event()
            original = CustomProjection._project

            def held(self, snapshot):
                if snapshot.namespace == "team":
                    entered.set()
                    assert release.wait(5)
                return original(self, snapshot)

            monkeypatch.setattr(CustomProjection, "_project", held)
            app._render_ready.set()
            assert await asyncio.to_thread(entered.wait, 5)
            try:
                old_client = app.sessions.client
                app._context_selected("kuberich-test-Two")
                await wait_for(
                    lambda: (
                        app.workspace.store.observation.context == "kuberich-test-Two"
                        and app.workspace.store.observation.status is ViewStatus.LIVE
                    )
                )
                assert app.sessions.client is not old_client
                app._submit_command("gadgets.owned.example.test/v1beta1")
                await wait_for(
                    lambda: (
                        app.workspace.store.observation.scope is not None
                        and app.workspace.store.observation.scope.resource.name == "gadgets"
                        and app.workspace.store.observation.status is ViewStatus.LIVE
                    )
                )
            finally:
                release.set()
            await loaded(app, name="gadgets", version="v1beta1", namespace=None)
            await pilot.pause()
            assert app.custom_table.resource_layout.resource.kind == "Gadget"
            assert all(row.namespace == "—" for row in app.custom_table._rows.values())
            assert "c4" in app.custom_table.columns
            assert app._generic_selection.version == "v1beta1"


@pytest.mark.asyncio
async def test_column_change_while_projection_is_held_rejects_old_positional_rows(
    tmp_path, monkeypatch
):
    async with custom_api() as (url, _owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            entered, release = threading.Event(), threading.Event()
            original = CustomProjection._project

            def held(self, snapshot):
                if not entered.is_set():
                    entered.set()
                    assert release.wait(5)
                return original(self, snapshot)

            monkeypatch.setattr(CustomProjection, "_project", held)
            app._render_ready.set()
            assert await asyncio.to_thread(entered.wait, 5)
            try:
                app._submit_command("columns c3")
                assert "c2" not in app.custom_table.columns
            finally:
                release.set()
            await loaded(app)
            await pilot.pause()
            assert tuple(key.value for key in app.custom_table.columns) == (
                "namespace",
                "name",
                "c3",
                "age",
            )
            assert app.custom_table.get_cell("owned-ten", "c3").text == "true"
            assert not app._render_task.done()


@pytest.mark.asyncio
async def test_context_workspace_escape_during_generic_reconnect_keeps_qualified_route(
    tmp_path, monkeypatch
):
    async with custom_api() as (url, _owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            entered, release = asyncio.Event(), asyncio.Event()
            original = app.sessions.connect

            async def held(*args, **kwargs):
                entered.set()
                await release.wait()
                return await original(*args, **kwargs)

            monkeypatch.setattr(app.sessions, "connect", held)
            app.action_retry()
            await entered.wait()
            try:
                app.action_contexts()
                await wait_for(lambda: app.context_table.row_count == 2)
                assert app._context_parent is None
                await pilot.press("escape")
                assert app.custom_table.display and app._resource_name == "widgets." + GROUP
                assert app._generic_selection.group == GROUP
            finally:
                release.set()
            await loaded(app)
            assert app.workspace.selection.server_columns


@pytest.mark.asyncio
async def test_explicit_core_group_uses_generic_layout_and_builtin_command_recovers(tmp_path):
    async with custom_api() as (url, _owner):
        app = app_for(tmp_path, url, GenericResourceCommand("pods", "", "v1"))
        async with app.run_test() as pilot:
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.custom_table.display
                )
            )
            await pilot.pause()
            assert app._resource_name == "pods.core" and not app.resources.display
            assert tuple(key.value for key in app.custom_table.columns) == (
                "namespace",
                "name",
                "age",
            )
            await command(app, pilot, "po")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.resources.display
                )
            )
            assert not app.custom_table.display


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["pods", "namespaces"])
async def test_explicit_core_command_owns_one_table_and_keeps_inspection_read_only(tmp_path, name):
    async with custom_api(CustomAPI(core_pods=True)) as (url, _owner):
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await loaded(app)
            await command(app, pilot, "resource " + name)
            await loaded(
                app,
                name=name,
                namespace="team" if name == "pods" else None,
                count=1 if name == "pods" else 3,
            )
            await pilot.pause()
            table = app.custom_table
            assert app._resource_name == name + ".core"
            assert app.workspace.store.observation.scope.resource.group == ""
            assert table.display and app._active_table is table
            assert not any(
                widget.display
                for widget in (
                    app.resources,
                    app.namespace_table,
                    app.standard_table,
                    app.context_table,
                )
            )
            assert ("namespace" in table.columns) == (name == "pods")
            selected = table.selected_uid
            for action in ("delete", "shell", "attach", "upload", "download", "portforward"):
                await command(app, pilot, action)
                assert "Generic resources are read-only" in str(app.status.content)
                assert len(app.screen_stack) == 1 and table.selected_uid == selected
            assert not app.check_action("edit", ())
            assert not app.check_action("logs", ())
            await pilot.press("y")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            assert ("kind: Pod" if name == "pods" else "kind: Namespace") in app.screen.viewer.text
            assert selected in app.screen.viewer.text
            await pilot.press("escape")
            assert app.focused is table and table.selected_uid == selected
            await command(app, pilot, "po" if name == "pods" else "ns")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and not table.display
                    and (app.resources.display if name == "pods" else app.namespace_table.display)
                )
            )
