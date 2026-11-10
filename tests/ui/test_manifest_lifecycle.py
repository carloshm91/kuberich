"""Captured session generations and retained local/cluster UI owners."""

import logging

import pytest
from aiohttp import web
from textual.widgets import Button

from kuberich.config.schema import Settings
from kuberich.domain.manifests import ManifestScope
from kuberich.domain.mutations import MutationState
from kuberich.domain.resources import Discovery
from kuberich.domain.targets import SessionIdentity
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.mutations import MutationManager
from kuberich.services.processes import ProcessRunner
from kuberich.ui.app import KubeRichApp
from kuberich.ui.manifest_actions import ManifestActions, ManifestConnection
from kuberich.ui.manifest_browser import ManifestBrowserScreen
from kuberich.ui.manifest_review import ManifestReviewScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.manifest_ui import RESOURCE, ManifestTestApp, OwnedClient, review_fixture
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


@pytest.mark.asyncio
async def test_app_captured_client_header_and_full_namespace_generation_never_revive(tmp_path):
    async def ns(request):
        return namespaces("team", "other")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("owned-api")))

    (tmp_path / "owned.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\n"
    )
    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            Settings(),
            logging.Logger("manifest-owned-scope"),
            catalog=catalog_fixture(tmp_path, url),
            directory=tmp_path,
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command(":manifests")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ManifestBrowserScreen) and app.screen.listing is not None
                )
            )
            owner = app.manifests
            captured = owner.capture_connection()
            assert captured is not None and captured.current()
            original = captured.scope.namespace
            await app.workspace.select_namespace("other" if original != "other" else "team")
            assert not captured.current()
            await app.workspace.select_namespace(original)
            assert not captured.current()
            fresh = owner.capture_connection()
            assert (
                fresh is not None
                and fresh.current()
                and fresh.scope.session != captured.scope.session
            )
            client = fresh.client
            browser = app.screen
            await wait_for(lambda: browser.operation_count == 0)
            browser.table.move_cursor(
                row=next(
                    index
                    for index, entry in enumerate(browser.listing.entries)
                    if entry.relative_path == "owned.yaml"
                )
            )
            browser.action_inspect()
            await wait_for(lambda: browser.source is not None and browser.operation_count == 0)
            owner.open_review(browser.source, "apply")
            await wait_for(
                lambda: isinstance(app.screen, ManifestReviewScreen) and app.screen.is_mounted
            )
            review = app.screen
            await owner.close_for_client(client)
            assert review.stopped and review.operation_count == 0
            await pilot.press("escape")
        assert owner.operation_count == 0


@pytest.mark.asyncio
async def test_manifest_owner_offline_notice_retains_and_closes_every_screen(tmp_path):
    local = LocalManifestService(AccessPolicy(False), {}, tmp_path)
    runner = ProcessRunner(local.policy)
    manager = MutationManager()
    (tmp_path / "owned.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\n"
    )
    await local.open_root(tmp_path)
    source = await local.capture("owned.yaml", "file")
    screens, notices = [], []
    connection = [None]
    owner = ManifestActions(
        local=local,
        manager=manager,
        runner=runner,
        capture_connection=lambda: connection[0],
        push_screen=screens.append,
        notice=notices.append,
    )
    owner.open_review(source, "apply")
    assert notices and not screens
    client = OwnedClient()
    connection[0] = ManifestConnection(
        client=client,
        scope=ManifestScope(session=SessionIdentity("owned-manifest-ui", 1), namespace="team"),
        discovery=Discovery((RESOURCE,)),
        current=lambda: True,
    )
    owner.open_review(source, "apply")
    review = screens[-1]
    owner.open_browser()
    browser = screens[-1]
    assert isinstance(review, ManifestReviewScreen) and isinstance(browser, ManifestBrowserScreen)
    await owner.close_for_client(OwnedClient())
    assert not review.stopped
    await owner.close_for_client(client)
    assert review.stopped
    await owner.stop_owned()
    assert browser.stopped and owner.operation_count == 0
    size = len(screens)
    owner.open_browser()
    owner.open_review(source, "delete")
    assert len(screens) == size
    await manager.close()
    await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("readonly", [False, True])
async def test_action_changes_need_fresh_review_and_absent_delete_sends_no_request(
    tmp_path, readonly
):
    local, service, adapter, manager, _current = await review_fixture(tmp_path, read_only=readonly)
    screen = ManifestReviewScreen(service=service, manager=manager)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test() as pilot:
            if readonly:
                assert screen.query_one("#manifest-review-validate", Button).disabled
                screen.action_validate()
                await wait_for(lambda: screen.operation_count == 0)
                assert screen.plan is None and not adapter.validations
            else:
                screen.action_validate()
                await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
                first = screen.plan
                screen.action_field.value = "delete"
                await pilot.pause()
                assert (
                    screen.plan is None
                    and screen.query_one("#manifest-review-confirm", Button).disabled
                )
                screen.action_field.value = "apply"
                await pilot.pause()
                assert screen.plan is None
                screen.action_field.value = "delete"
                await pilot.pause()
                screen.action_validate()
                await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
                assert screen.plan is not first and screen.plan.items[0].change == "absent"
                screen.action_confirm()
                await wait_for(lambda: screen.result is not None and screen.operation_count == 0)
                assert screen.result.state is MutationState.SUCCEEDED and not adapter.writes
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()
