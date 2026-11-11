"""Public owner refusals retain failed work while draining other collaborators."""

import pytest

from kuberich.adapters.editing import ManifestFile
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner
from kuberich.services.resource_creation import ResourceCreationService
from kuberich.services.resource_templates import TemplateCatalogService
from kuberich.ui.manifest_actions import ManifestActions
from kuberich.ui.manifest_browser import ManifestBrowserScreen
from kuberich.ui.resource_creation import ResourceCreationScreen

BODY = b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-cleanup}\n"


@pytest.mark.asyncio
async def test_creator_attempts_every_public_owner_after_draft_cleanup_refuses_then_retries(
    tmp_path, monkeypatch
):
    policy = AccessPolicy(False)
    service = ResourceCreationService(policy, {}, tmp_path)
    runner = ProcessRunner(policy)
    catalog = TemplateCatalogService(tmp_path / "config.yaml", tmp_path)
    screen = ResourceCreationScreen(
        service=service, runner=runner, catalog=catalog, open_review=lambda source: None
    )
    await service.capture_bytes(BODY, "paste", "Owned")
    intent = await service.prepare_editor()
    command = await service.open_editor(service.confirm_disclosure(intent))
    from pathlib import Path

    draft = Path(command.argv[-1])
    calls = []
    close_file, close_service, close_catalog = (
        ManifestFile.close,
        ResourceCreationService.close,
        TemplateCatalogService.close,
    )
    refused = [False]

    def file_close(owner):
        calls.append("draft")
        if not refused[0]:
            refused[0] = True
            raise OSError("owned cleanup refusal")
        close_file(owner)

    async def service_close(owner):
        calls.append("service")
        await close_service(owner)

    async def catalog_close(owner):
        calls.append("catalog")
        await close_catalog(owner)

    monkeypatch.setattr(ManifestFile, "close", file_close)
    monkeypatch.setattr(ResourceCreationService, "close", service_close)
    monkeypatch.setattr(TemplateCatalogService, "close", catalog_close)
    try:
        with pytest.raises(AppError, match="cleanup"):
            await screen.stop_owned()
        assert "service" in calls and "catalog" in calls and not draft.parent.exists()
        assert not screen.stopped
        await screen.stop_owned()
        assert screen.stopped and service.operation_count == 0
    finally:
        await screen.stop_owned()
        await runner.close()


@pytest.mark.asyncio
async def test_actions_drain_later_screens_and_local_after_child_refusal_and_retain_failed_owner(
    tmp_path, monkeypatch
):
    policy = AccessPolicy(False)
    local = LocalManifestService(policy, {}, tmp_path)
    runner, manager = ProcessRunner(policy), MutationManager()
    pushed = []
    actions = ManifestActions(
        local=local,
        runner=runner,
        manager=manager,
        capture_connection=lambda: None,
        push_screen=pushed.append,
        notice=lambda text: None,
    )
    actions.open_browser()
    actions.open_browser()
    actions.open_creation()
    first, second, creator = pushed
    calls = []
    stop_browser, stop_creator, close_local = (
        ManifestBrowserScreen.stop_owned,
        ResourceCreationScreen.stop_owned,
        LocalManifestService.close,
    )
    first_count = [0]

    async def browser_stop(owner):
        calls.append("first" if owner is first else "second")
        await stop_browser(owner)
        if owner is first:
            first_count[0] += 1
            if first_count[0] == 1:
                raise AppError("Owned browser cleanup refused after stop")

    async def creator_stop(owner):
        calls.append("creator")
        await stop_creator(owner)

    async def local_close(owner):
        calls.append("local")
        await close_local(owner)

    monkeypatch.setattr(ManifestBrowserScreen, "stop_owned", browser_stop)
    monkeypatch.setattr(ResourceCreationScreen, "stop_owned", creator_stop)
    monkeypatch.setattr(LocalManifestService, "close", local_close)
    try:
        with pytest.raises(AppError, match="refused"):
            await actions.stop_owned()
        assert calls == ["first", "second", "creator", "local"]
        assert first.stopped and second.stopped and creator.stopped
        await actions.stop_owned()
        assert calls == ["first", "second", "creator", "local", "first", "local"]
        assert actions.operation_count == 0
    finally:
        await actions.stop_owned()
        await runner.close()
        await manager.close()


@pytest.mark.asyncio
async def test_connected_creation_composition_binds_source_and_per_client_failure_drains_every_owner(
    tmp_path, monkeypatch
):
    from kuberich.domain.manifests import ManifestScope
    from kuberich.domain.resources import Discovery
    from kuberich.domain.targets import SessionIdentity
    from kuberich.ui.manifest_actions import ManifestConnection
    from kuberich.ui.manifest_review import ManifestReviewScreen
    from tests.support.manifest_ui import RESOURCE, OwnedClient

    policy = AccessPolicy(False)
    local = LocalManifestService(policy, {}, tmp_path)
    runner, manager, client = ProcessRunner(policy), MutationManager(), OwnedClient()
    pushed = []
    current = [True]
    connection = ManifestConnection(
        client=client,
        scope=ManifestScope(session=SessionIdentity(client.context.name, 1), namespace="team"),
        discovery=Discovery((RESOURCE,)),
        current=lambda: current[0],
    )
    actions = ManifestActions(
        local=local,
        runner=runner,
        manager=manager,
        capture_connection=lambda: connection,
        push_screen=pushed.append,
        notice=lambda text: None,
    )
    actions.open_creation()
    creator = pushed[-1]
    source = await creator.service.capture_bytes(BODY, "paste", "Owned")
    creator.open_review(source)
    first = pushed[-1]
    assert isinstance(first, ManifestReviewScreen) and first.action == "create"
    assert first.service.source is source and first.service.current()
    await first.service.require_source()
    creator.service.invalidate()
    assert not first.service.current()
    with pytest.raises(AppError, match="changed"):
        await first.service.require_source()
    source = await creator.service.capture_bytes(BODY, "paste", "Owned replacement")
    creator.open_review(source)
    second = pushed[-1]
    assert isinstance(second, ManifestReviewScreen) and second is not first
    calls = []
    stop_review, stop_creator = ManifestReviewScreen.stop_owned, ResourceCreationScreen.stop_owned
    first_calls = [0]

    async def review_stop(owner):
        calls.append("first" if owner is first else "second")
        await stop_review(owner)
        if owner is first:
            first_calls[0] += 1
            if first_calls[0] == 1:
                raise AppError("Owned review close refusal")

    async def creator_stop(owner):
        calls.append("creator")
        await stop_creator(owner)

    monkeypatch.setattr(ManifestReviewScreen, "stop_owned", review_stop)
    monkeypatch.setattr(ResourceCreationScreen, "stop_owned", creator_stop)
    try:
        with pytest.raises(AppError, match="refusal"):
            await actions.close_for_client(client)
        assert calls == ["first", "second", "creator"]
        await actions.close_for_client(client)
        assert calls == ["first", "second", "creator", "first"]
        await actions.stop_owned()
        count = len(pushed)
        actions.open_creation()
        creator.open_review(source)
        assert len(pushed) == count
    finally:
        await actions.stop_owned()
        await runner.close()
        await manager.close()
