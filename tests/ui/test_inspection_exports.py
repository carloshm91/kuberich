"""Actual inspection GETs and loaded-document exports keep redaction and source identity."""

import asyncio
import copy
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from aiohttp import web

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.config.schema import Settings
from kuberich.diagnostics.reports import report_payload
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.exports import DocumentSource, ResourceSource, SupportSource
from kuberich.errors import AppError
from kuberich.services.exports import ExportService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.inspection import InspectionScreen
from tests.support.connections import catalog_fixture
from tests.support.resources import collection
from tests.support.watches import frame
from tests.support.workspace import wait_for, workspace_api
from tests.ui.test_inspection import loaded, manifest, ns, viewer_loaded
from tests.unit.test_inspection import event


class InspectionApi:
    """Synthetic list/watch and GET bodies deliberately have different versions."""

    def __init__(self, *, events_status=None, held=False, live_updates=False):
        self.listed = manifest("api", uid="owned-api")
        self.listed.update(apiVersion="v1", kind="Pod")
        self.listed["metadata"]["resourceVersion"] = "watch-listed/1"
        self.value = copy.deepcopy(self.listed)
        self.value["metadata"]["resourceVersion"] = "get-observed/42"
        self.value["spec"]["nodeName"] = "owned-get-worker"
        self.value["spec"]["containers"][0]["args"] = ["ARG-PRIVATE-MARKER"]
        self.event = event().manifest
        self.event["message"] = "BackOff [red]literal[/red] token=EVENT-PRIVATE-MARKER"
        self.events_status = events_status
        self.held = held
        self.live_updates = live_updates
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.updates = asyncio.Queue()
        self.requests = []
        self.get_at = []

    async def handle(self, request):
        self.requests.append((request.path, dict(request.query)))
        if "watch" in request.query:
            response = web.StreamResponse()
            await response.prepare(request)
            while request.transport is not None and not request.transport.is_closing():
                try:
                    update = await asyncio.wait_for(self.updates.get(), 0.05)
                except TimeoutError:
                    continue
                await response.write(frame(update))
            return response
        if request.path.endswith("/events"):
            if self.events_status is not None:
                return web.Response(status=self.events_status, text="PRIVATE-SERVER-ERROR")
            return web.json_response(collection(self.event))
        if request.path.endswith("/pods"):
            return web.json_response(collection(self.listed))
        if request.path.endswith("/pods/api"):
            self.started.set()
            if self.held:
                await self.release.wait()
            self.get_at.append(datetime.now(UTC))
            return web.json_response(self.value)
        return web.Response(status=404)

    @property
    def object_reads(self):
        return sum(path.endswith("/pods/api") for path, _ in self.requests)


@asynccontextmanager
async def inspection_app(tmp_path, *, all_namespaces=False, api=None):
    api = api or InspectionApi()
    service = ExportService(
        files=ArtifactFiles(cwd=tmp_path),
        default_root=tmp_path / "exports",
        report_payload=lambda: report_payload(config_status="valid"),
        clock=lambda: datetime.now(UTC),
        new_id=uuid4,
    )
    async with workspace_api(ns, api.handle) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("inspection-exports", level=100),
            catalog=catalog_fixture(tmp_path, url),
            connection=ConnectionRequest(all_namespaces=all_namespaces),
            export_service=service,
        )
        try:
            async with app.run_test() as pilot:
                await loaded(app)
                yield app, pilot, api, service
        finally:
            api.release.set()
            await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("all_namespaces", [False, True])
async def test_actual_loaded_pages_export_only_redacted_documents_with_get_scope(
    tmp_path, all_namespaces
):
    async with inspection_app(tmp_path, all_namespaces=all_namespaces) as (
        app,
        pilot,
        api,
        service,
    ):
        watch_version = app.workspace.store.observation.snapshot.items[0].resource_version
        assert watch_version == "watch-listed/1"
        await pilot.press("y")
        screen = await viewer_loaded(app)
        assert isinstance(screen, InspectionScreen)
        assert screen.result.resource_version == "get-observed/42"
        assert screen.result.observed_at.tzinfo is UTC
        assert screen.result.observed_at >= api.get_at[0]
        assert (
            screen.service.target.uid == "owned-api" and screen.service.target.namespace == "team"
        )
        before_reads = tuple(api.requests)
        previous = None
        for page, managed, tag in [
            ("yaml", False, "yaml"),
            ("yaml", True, "managed-yaml"),
            ("details", True, "details"),
            ("events", True, "events"),
        ]:
            if page == "yaml" and managed:
                screen.action_managed()
            else:
                screen.action_page(page)
            if previous is not None:
                assert not previous.current()
            at = datetime.now(UTC)
            choices = dict(screen.capture_export(at))
            assert set(choices) == ({"resource-yaml", "screen"} if page == "yaml" else {"screen"})
            lease = choices["screen"]
            assert isinstance(lease.capture.source, DocumentSource)
            assert not isinstance(lease.capture.source, ResourceSource)
            assert lease.resource_reader is None and lease.capture.source.page == tag
            assert lease.capture.source.text == screen.viewer.text
            assert lease.capture.scope.export_at == at
            assert lease.capture.scope.source_at == screen.result.observed_at
            assert lease.capture.scope.resource_version == "get-observed/42"
            assert lease.capture.scope.uid == "owned-api"
            assert lease.capture.scope.header_namespace == (None if all_namespaces else "team")
            assert lease.capture.scope.collection_namespace == "team"
            assert lease.capture.scope.namespace_mode == "one"
            for marker in (
                "hidden-env",
                "hidden-annotation",
                "ARG-PRIVATE-MARKER",
                "EVENT-PRIVATE-MARKER",
            ):
                assert marker not in lease.capture.source.text
            if managed and page == "yaml":
                assert "managedFields" in lease.capture.source.text
            prepared = await service.prepare(lease, "resource-yaml" if page == "yaml" else "screen")
            assert not prepared.metadata.sensitive and prepared.payload
            service.discard(prepared)
            review = await service.review_destination(service.default_root, "denied-sensitive.yaml")
            with pytest.raises(AppError, match="approval"):
                await service.approve_sensitive(
                    lease, "resource-yaml", intent="save", destination=review
                )
            assert lease.current()
            previous = lease
        assert tuple(api.requests) == before_reads and api.object_reads == 1
        assert not (service.default_root / "denied-sensitive.yaml").exists()
        # The explicit workspace origin uses this loaded page, never the table below it.
        choices = dict(app.export_sources.origin(screen, datetime.now(UTC)))
        assert set(choices) == {"screen", "support"}
        assert choices["screen"].capture.source.page == "events"
        assert isinstance(choices["support"].capture.source, SupportSource)
        assert choices["support"].capture.source.resource is None
        await pilot.press("escape")
        await wait_for(lambda: screen.invalidated)
        assert not previous.current() and screen.capture_export(datetime.now(UTC)) == ()
        assert service.operation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404])
async def test_unavailable_events_capture_exact_loaded_error_without_health_claim(tmp_path, status):
    async with inspection_app(tmp_path, api=InspectionApi(events_status=status)) as (
        app,
        pilot,
        api,
        service,
    ):
        await pilot.press("e")
        screen = await viewer_loaded(app)
        assert screen.result.events_error is not None and str(status) in screen.viewer.text
        before = tuple(api.requests)
        lease = dict(screen.capture_export(datetime.now(UTC)))["screen"]
        assert lease.capture.source.page == "events"
        assert lease.capture.source.text == screen.viewer.text == screen.result.events_error
        assert lease.capture.notices == (screen.result.events_error,)
        assert "No related events" not in lease.capture.source.text
        assert "PRIVATE-SERVER-ERROR" not in lease.capture.source.text
        prepared = await service.prepare(lease, "screen")
        assert str(status).encode() in prepared.payload
        service.discard(prepared)
        assert tuple(api.requests) == before


@pytest.mark.asyncio
async def test_pending_load_capture_is_unavailable_then_public_stop_revokes_document(tmp_path):
    api = InspectionApi(held=True)
    async with inspection_app(tmp_path, api=api) as (app, pilot, api, service):
        await pilot.press("y")
        await api.started.wait()
        screen = app.screen
        assert isinstance(screen, InspectionScreen) and screen.result is None
        before = tuple(api.requests)
        assert screen.capture_export(datetime.now(UTC)) == ()
        choices = dict(app.export_sources.origin(screen, datetime.now(UTC)))
        assert set(choices) == {"support"} and choices["support"].capture.source.resource is None
        assert tuple(api.requests) == before
        api.release.set()
        await viewer_loaded(app)
        lease = dict(screen.capture_export(datetime.now(UTC)))["resource-yaml"]
        assert lease.current()
        await screen.stop_owned()
        assert not lease.current() and screen.capture_export(datetime.now(UTC)) == ()
        with pytest.raises(AppError, match="changed"):
            await service.prepare(lease, "resource-yaml")


@pytest.mark.asyncio
async def test_ordinary_watch_update_keeps_frozen_get_document_but_uid_deletion_revokes(tmp_path):
    async with inspection_app(tmp_path) as (app, pilot, api, service):
        await pilot.press("y")
        screen = await viewer_loaded(app)
        lease = dict(screen.capture_export(datetime.now(UTC)))["resource-yaml"]
        text, result = lease.capture.source.text, screen.result
        update = copy.deepcopy(api.listed)
        update["metadata"]["resourceVersion"] = "watch-updated/2"
        update["status"]["containerStatuses"][0]["restartCount"] = 17
        await api.updates.put({"type": "MODIFIED", "object": update})
        await wait_for(
            lambda: app.workspace.store.observation.snapshot.resource_version == "watch-updated/2"
        )
        assert screen.result is result and lease.current()
        assert (
            lease.capture.source.text == text
            and lease.capture.scope.resource_version == "get-observed/42"
        )
        prepared = await service.prepare(lease, "resource-yaml")
        assert b"get-observed/42" in prepared.payload and b"watch-updated/2" not in prepared.payload
        service.discard(prepared)
        assert api.object_reads == 1
        update["metadata"]["resourceVersion"] = "watch-deleted/3"
        await api.updates.put({"type": "DELETED", "object": update})
        await wait_for(lambda: screen.invalidated)
        assert not lease.current() and screen.result is None
        assert lease.capture.source.text == text  # The immutable capture was never relabelled.
        assert screen.capture_export(datetime.now(UTC)) == ()


@pytest.mark.asyncio
async def test_reloading_result_and_reopening_viewer_invalidate_prior_document_leases(tmp_path):
    async with inspection_app(tmp_path) as (app, pilot, api, service):
        await pilot.press("y")
        screen = await viewer_loaded(app)
        original = dict(screen.capture_export(datetime.now(UTC)))["resource-yaml"]
        api.value["metadata"]["resourceVersion"] = "get-reloaded/43"
        # Exercise the public producer/result boundary with an actual fresh GET.
        replacement = await screen.service.load()
        screen.result = replacement
        screen.show_page()
        assert (
            not original.current() and original.capture.scope.resource_version == "get-observed/42"
        )
        reloaded = dict(screen.capture_export(datetime.now(UTC)))["resource-yaml"]
        assert reloaded.capture.scope.resource_version == "get-reloaded/43"
        assert reloaded.capture.scope.source_at == replacement.observed_at
        assert reloaded.capture.scope.source_at >= original.capture.scope.source_at
        assert api.object_reads == 2
        await pilot.press("escape")
        await wait_for(lambda: screen.invalidated)
        assert not reloaded.current()
        await pilot.press("y")
        reopened = await viewer_loaded(app)
        assert reopened is not screen and api.object_reads == 3
        newest = dict(reopened.capture_export(datetime.now(UTC)))["resource-yaml"]
        assert newest.current() and newest.capture.scope.resource_version == "get-reloaded/43"
        assert service.operation_count == 0


@pytest.mark.asyncio
async def test_recreated_uid_get_never_yields_a_loaded_capture(tmp_path):
    api = InspectionApi()
    api.value["metadata"]["uid"] = "replacement-uid"
    async with inspection_app(tmp_path, api=api) as (app, pilot, api, _):
        await pilot.press("y")
        await wait_for(
            lambda: (
                isinstance(app.screen, InspectionScreen)
                and "stale" in str(app.screen.status.content)
            )
        )
        screen = app.screen
        assert screen.result is None and screen.capture_export(datetime.now(UTC)) == ()
        choices = dict(app.export_sources.origin(screen, datetime.now(UTC)))
        assert set(choices) == {"support"} and choices["support"].capture.source.resource is None
        assert api.object_reads == 1
