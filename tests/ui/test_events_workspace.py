"""Events share native commands/history while aggregates stay separate from objects."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kuberich.domain.events import EventOptions
from kuberich.domain.exports import ResourceSource, TableSource
from kuberich.domain.view_routes import ViewKind
from kuberich.domain.views import ViewStatus
from kuberich.ui.inspection import InspectionScreen
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_resources import CuratedResourcesApi, curated_resources_api
from tests.support.events import EVENT_CANARY, event_manifest, event_resource
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, shown, started


async def events_ready(app, resource, *, count):
    await wait_for(
        lambda: (
            app.state.status is ViewStatus.LIVE
            and app.state.scope is not None
            and app.state.scope.resource == resource
            and app.events_table.display
            and app.events_table.row_count == count
            and app.events_table.source is not None
            and app.events_table.source.scope == app.state.scope
            and app.events_table.source.revision == app.workspace.store.observation.revision
        )
    )


@pytest.mark.asyncio
async def test_native_events_prefers_discovered_modern_api_without_combining_core(tmp_path):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource.name == "events"
                    and app.state.status is ViewStatus.LIVE
                )
            )
            assert app.state.scope.resource.group == "events.k8s.io"
            assert not any(
                request.path == "/api/v1/namespaces/team/events" for request in api.requests
            )


@pytest.mark.asyncio
async def test_escape_from_event_members_returns_to_the_same_grouped_parent(tmp_path):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            resource = api.resource("events", group="events.k8s.io")
            await app.run_command("resource events.events.k8s.io/v1 team")
            await events_ready(app, resource, count=7)
            app.navigator.events_options(EventOptions(grouped=True))
            await wait_for(lambda: app.events_table.options.grouped)
            selected = app.events_table.selected_group()
            assert selected is not None
            await pilot.press("enter")
            await wait_for(lambda: app.events_table.options.members is not None)
            await pilot.press("escape")
            assert app.views.event_options == EventOptions(grouped=True)
            await wait_for(lambda: app.events_table.selected_group() is not None)
            assert app.events_table.selected_group().key == selected.key


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_native_events_warning_group_members_back_exports_and_real_object_inspection(
    tmp_path, size
):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            resource = api.resource("events", group="events.k8s.io")
            await events_ready(app, resource, count=7)
            assert (
                app.views.route.kind is ViewKind.EVENTS
                and app.events_table.selected_event_uid() is not None
            )
            assert EVENT_CANARY not in shown(app.events_table)
            source_time = app.events_table.source.snapshot_seen_at
            stamp = source_time.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
            await pilot.pause()
            assert stamp in str(app.query_one("#resource-view").border_subtitle)
            before = [(request.path, request.query) for request in api.requests]
            await pilot.press("w", "t")
            await wait_for(
                lambda: app.events_table.options == EventOptions(grouped=True, warnings_only=True)
            )
            assert app.events_table.row_count == 4
            assert app.events_table.selected_event_uid() is None
            assert app.targets.capture() is None
            assert app.events_table.source.snapshot_seen_at == source_time
            assert stamp in str(app.query_one("#resource-view").border_subtitle)
            assert [(request.path, request.query) for request in api.requests] == before
            await pilot.pause()
            choices = app.export_sources.capture(datetime.now(UTC))
            assert not any(isinstance(lease.capture.source, ResourceSource) for _, lease in choices)
            screen = next(lease for kind, lease in choices if kind == "screen")
            assert isinstance(screen.capture.source, TableSource)
            assert screen.capture.scope.source_at == source_time
            assert EVENT_CANARY not in repr(screen.capture.source)
            # Select the repeated BackOff observation with three members; replacement
            # and missing-UID observations remain different groups.
            selected = None
            for row in app.events_table.ordered_rows:
                app.events_table.move_cursor(row=app.events_table.get_row_index(row.key))
                group = app.events_table.selected_group()
                if group is not None and len(group.member_uids) == 3:
                    selected = group
                    break
            assert (
                selected is not None
                and selected.known_occurrences == 8
                and selected.unknown_count_members == 1
            )
            await pilot.press("enter")
            await wait_for(
                lambda: app.events_table.row_count == 3 and not app.events_table.options.grouped
            )
            assert app.events_table.options.members.key == selected.key
            assert not screen.current()
            await pilot.press("escape")
            await wait_for(
                lambda: app.events_table.options == EventOptions(grouped=True, warnings_only=True)
            )
            assert app.events_table.row_count == 4
            app.navigator.history_forward()
            await wait_for(
                lambda: (
                    app.events_table.row_count == 3 and app.events_table.options.members is not None
                )
            )
            await pilot.press("enter")
            await wait_for(
                lambda: isinstance(app.screen, InspectionScreen) and app.screen.result is not None
            )
            assert app.screen.service.resource == resource
            assert app.screen.service.target.uid in selected.member_uids
            assert EVENT_CANARY not in app.screen.result.documents.details
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_modern_only_events_and_explicit_core_modern_commands_do_not_mix_sources(tmp_path):
    api = CuratedEventsApi(modern_only=True)
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("ev team")
            resource = api.resource("events", group="events.k8s.io")
            await events_ready(app, resource, count=7)
            assert app.workspace.selection.group == "events.k8s.io"
            await app.run_command("resource events.core/v1 team")
            assert app.workspace.selection.group == "events.k8s.io"
            assert not any(
                request.path == "/api/v1/namespaces/team/events" for request in api.requests
            )


@pytest.mark.asyncio
async def test_forbidden_preferred_events_never_silently_falls_back_to_core(tmp_path):
    path = "/apis/events.k8s.io/v1/namespaces/team/events"
    api = CuratedEventsApi(denied_paths={path: 403})
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await wait_for(lambda: app.state.status is ViewStatus.FAILED)
            assert app.state.scope.resource.group == "events.k8s.io"
            assert not any(
                request.path == "/api/v1/namespaces/team/events" for request in api.requests
            )
            await app.run_command("resource events.core/v1 team")
            await events_ready(app, api.resource("events", group=""), count=7)


@pytest.mark.asyncio
async def test_compact_events_keep_identity_and_report_unknown_body_facts(tmp_path):
    api = CuratedEventsApi(metadata_only={("events.k8s.io", "v1", "events")})
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            resource = api.resource("events", group="events.k8s.io")
            await events_ready(app, resource, count=7)
            await app.run_command("server compact")
            await wait_for(lambda: app.workspace.selection.query.compact)
            await events_ready(app, resource, count=7)
            assert all(
                record.metadata_only for record in app.workspace.store.observation.snapshot.items
            )
            assert app.events_table.selected_event_uid() is not None
            assert "metadata" in " ".join(app.events_table.notices).lower()
            assert EVENT_CANARY not in shown(app.events_table)
            await pilot.press("w")
            await wait_for(
                lambda: app.events_table.options.warnings_only and app.events_table.row_count == 0
            )
            assert "unknown" in " ".join(app.events_table.notices).lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"version": "v99"}, {"kind": "OtherEvent"}, {"namespaced": False}]
)
async def test_unknown_event_descriptor_uses_identity_metadata_with_no_printer_interpretation(
    tmp_path, change
):
    api = CuratedResourcesApi()
    resource = replace(event_resource(), **change)
    body = event_manifest()
    body.update(apiVersion=resource.api_version, kind=resource.kind)
    if not resource.namespaced:
        body["metadata"].pop("namespace")
    api.put(resource, body)
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command(
                f"resource events.events.k8s.io/{resource.version}"
                + (" team" if resource.namespaced else "")
            )
            await wait_for(
                lambda: (
                    app.state.status is ViewStatus.LIVE
                    and app.state.scope.resource == resource
                    and app.standard_table.row_count == 1
                )
            )
            assert app.views.route.kind is ViewKind.STANDARD
            assert tuple(column.key for column in app.standard_table.definition.columns) == (
                ("namespace",) if resource.namespaced else ()
            ) + ("name", "info", "age")
            assert "Unsupported" in shown(app.standard_table)
            assert EVENT_CANARY not in shown(app.standard_table)
