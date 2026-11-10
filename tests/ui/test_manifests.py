"""Public local navigation and guarded review actions through actual Pilot controls."""

import logging

import pytest
from textual.widgets import Button

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.domain.mutations import MutationState
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import CommandService, suggestions
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.manifest_browser import ManifestBrowserScreen
from kuberich.ui.manifest_review import ManifestReviewScreen
from kuberich.ui.mutations import MutationHistoryScreen
from tests.support.manifest_ui import ManifestTestApp, click_ready, review_fixture
from tests.support.workspace import wait_for


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 36), (80, 24)])
async def test_initial_local_route_is_offline_and_has_no_editor_or_helper(
    tmp_path, monkeypatch, size
):
    def unexpected(*args, **kwargs):
        raise AssertionError("Local route attempted cluster authentication or helper launch")

    monkeypatch.setattr(SessionService, "connect", unexpected)
    monkeypatch.setattr(ProcessRunner, "capture", unexpected)
    (tmp_path / "owned.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\ndata: {private: manifest-ui-sensitive-value}\n"
    )
    app = KubeRichApp(
        Settings(),
        logging.Logger("owned-local-manifests"),
        catalog=KubeCatalog(),
        directory=tmp_path,
        initial_command=Command.MANIFESTS,
    )
    assert app.manifests is None
    async with app.run_test(size=size) as pilot:
        await wait_for(
            lambda: (
                isinstance(app.screen, ManifestBrowserScreen)
                and app.screen.listing is not None
                and app.screen.operation_count == 0
            )
        )
        browser = app.screen
        assert app.sessions.client is None and app.sessions.observation.identity is None
        assert app.focused.id == "manifests-back"
        assert browser.table.row_count == 1
        browser.table.focus()
        await pilot.press("enter")
        await wait_for(lambda: browser.source is not None and browser.operation_count == 0)
        assert len(browser.source.documents) == 1
        assert "manifest-ui-sensitive-value" not in browser.viewer.text
        assert "[REDACTED]" in browser.viewer.text
        browser.open_review(browser.source, "apply")
        assert app.screen is browser and app.sessions.client is None
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)
        await app.run_command(":manifests")
        await wait_for(
            lambda: isinstance(app.screen, ManifestBrowserScreen) and app.screen.listing is not None
        )
        assert app.sessions.client is None
    assert app.manifests.operation_count == 0


def test_manifest_command_is_local_read_only_and_rejects_arguments():
    assert CommandService(AccessPolicy(True)).resolve(":manifests") is Command.MANIFESTS
    assert "manifests" in suggestions("manif", (), ())
    with pytest.raises(Exception, match="without arguments"):
        CommandService(AccessPolicy(False)).resolve(":manifests other")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(120, 36), (80, 24)])
async def test_browser_navigation_root_boundary_cursor_and_explicit_kustomization_inspection(
    tmp_path, size
):
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "kustomization.yaml").write_text(
        "resources: []\nsecretGenerator: [{name: private, literals: [password=manifest-ui-sensitive-value]}]\n"
    )
    (tmp_path / "link.yaml").symlink_to(tmp_path / "nested" / "kustomization.yaml")
    for index in range(12):
        (tmp_path / f"row-{index:02}.yaml").write_text(
            f"apiVersion: v1\nkind: ConfigMap\nmetadata: {{name: owned-{index}}}\n"
        )
    local = LocalManifestService(AccessPolicy(False), {}, tmp_path)
    runner = ProcessRunner(local.policy)
    screen = ManifestBrowserScreen(
        service=local, runner=runner, open_review=lambda source, action: None
    )
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: screen.listing is not None and screen.operation_count == 0)
            screen.table.move_cursor(row=10)
            selected = screen.selected_entry()
            screen.table.scroll_to(y=4, animate=False)
            screen.action_refresh()
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.selected_entry() == selected
            screen.table.move_cursor(
                row=next(
                    index
                    for index, entry in enumerate(screen.listing.entries)
                    if entry.kind == "unavailable"
                )
            )
            screen.action_inspect()
            assert screen.source is None and "symlink" in str(screen.status.content).lower()
            screen.table.move_cursor(
                row=next(
                    index
                    for index, entry in enumerate(screen.listing.entries)
                    if entry.kind == "directory"
                )
            )
            screen.table.focus()
            await pilot.press("enter")
            await wait_for(
                lambda: (
                    screen.listing.relative_directory == "nested" and screen.operation_count == 0
                )
            )
            await pilot.press("enter")
            await wait_for(lambda: bool(screen.pages) and screen.operation_count == 0)
            assert screen.source is None and "manifest-ui-sensitive-value" not in screen.viewer.text
            assert "structure only" in str(screen.status.content)
            screen.action_parent()
            await wait_for(
                lambda: screen.listing.relative_directory == "" and screen.operation_count == 0
            )
            screen.action_parent()
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.listing.root.path == tmp_path and screen.listing.relative_directory == ""
            screen.location.value = str(tmp_path / "nested")
            await wait_for(lambda: screen.listing is None)
            assert screen.query_one("#manifests-apply", Button).disabled
            screen.action_open_root()
            await wait_for(lambda: screen.listing is not None and screen.operation_count == 0)
            assert screen.listing.root.path == tmp_path / "nested"
    finally:
        await local.close()
        await runner.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["apply", "delete"])
@pytest.mark.parametrize("size", [(120, 36), (80, 24)])
async def test_review_validation_then_explicit_confirmation_and_history(tmp_path, action, size):
    local, service, adapter, manager, _current = await review_fixture(
        tmp_path, existing=action == "delete"
    )
    screen = ManifestReviewScreen(service=service, manager=manager, action=action)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=size) as pilot:
            validate = screen.query_one("#manifest-review-validate", Button)
            confirm = screen.query_one("#manifest-review-confirm", Button)
            assert confirm.disabled and app.focused.id == "manifest-review-back"
            await click_ready(app, pilot, validate)
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            assert screen.plan.ready and not adapter.writes and not confirm.disabled
            assert app.focused.id == "manifest-review-back"
            assert "manifest-ui-sensitive-value" not in screen.viewer.text
            if action == "apply":
                assert "new name / no UID captured" in screen.table.get_row_at(0)[5].plain
            else:
                assert screen.table.get_row_at(0)[5].plain == "uid-owned-0"
            await click_ready(app, pilot, confirm)
            await wait_for(lambda: screen.result is not None and screen.operation_count == 0)
            assert len(adapter.writes) == 1 and screen.result.state is MutationState.SUCCEEDED
            assert confirm.disabled and manager.records[-1].result is screen.result
            assert "Owned API outcome" in screen.viewer.text
            await screen.action_back()
            history = MutationHistoryScreen(manager)
            app.push_screen(history)
            await wait_for(lambda: history.is_mounted)
            await pilot.pause()
            content = str(history.query_one("#write-history-content").content)
            assert "manifest-ui-sensitive-value" not in content and "UID None" not in content
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()


@pytest.mark.asyncio
async def test_review_fallback_namespace_field_and_late_validation_cannot_revive(tmp_path):
    local, service, adapter, manager, current = await review_fixture(tmp_path, namespace=None)
    screen = ManifestReviewScreen(service=service, manager=manager)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen.action_validate()
            await wait_for(lambda: screen.operation_count == 0)
            assert (
                screen.plan is None
                and screen.query_one("#manifest-review-confirm", Button).disabled
            )
            screen.namespace.value = "explicit-team"
            await pilot.pause()
            screen.action_validate()
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            assert screen.plan.items[0].target.namespace == "explicit-team"
            adapter.stall_validation = True
            adapter.entered.clear()
            screen.action_validate()
            await wait_for(adapter.entered.is_set)
            screen.namespace.value = "changed-team"
            await wait_for(lambda: screen.operation_count == 0)
            adapter.release.set()
            assert (
                screen.plan is None
                and screen.query_one("#manifest-review-confirm", Button).disabled
            )
            screen.namespace.value = "explicit-team"
            await pilot.pause()
            assert screen.plan is None
            current[0] = False
            screen.action_validate()
            await wait_for(lambda: screen.operation_count == 0)
            assert screen.plan is None and not adapter.writes
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [MutationState.DENIED, MutationState.REJECTED])
async def test_failed_validation_never_enables_confirmation(tmp_path, failure):
    local, service, adapter, manager, _current = await review_fixture(tmp_path)
    adapter.validation_state = failure
    screen = ManifestReviewScreen(service=service, manager=manager)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test():
            screen.action_validate()
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            assert (
                not screen.plan.ready
                and screen.query_one("#manifest-review-confirm", Button).disabled
            )
            screen.action_confirm()
            assert not adapter.writes
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()


@pytest.mark.asyncio
async def test_partial_and_uncertain_batch_results_survive_stop_and_detached_close(tmp_path):
    local, service, adapter, manager, _current = await review_fixture(tmp_path, count=3)
    adapter.write_states = [MutationState.SUCCEEDED, MutationState.CONFLICT]
    screen = ManifestReviewScreen(service=service, manager=manager)
    app = ManifestTestApp(screen)
    try:
        async with app.run_test() as pilot:
            screen.action_validate()
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            screen.action_confirm()
            await wait_for(lambda: screen.result is not None and screen.operation_count == 0)
            assert len(adapter.writes) == 2 and len(screen.result.items) == 3
            partial = screen.result
            assert partial.state is MutationState.PARTIAL
            assert "Partial batch" in str(screen.status.content)
            assert screen.result.items[0][1].state is MutationState.SUCCEEDED
            assert screen.result.items[1][1].state is MutationState.CONFLICT
            assert "unsent" in screen.result.items[2][1].message.lower()
            assert "unsent" in screen.table.get_row_at(2)[-1].plain.lower()
            history = MutationHistoryScreen(manager)
            app.push_screen(history)
            await wait_for(lambda: history.is_mounted)
            assert await history.wait_for_refresh()
            assert "Partial batch" in str(history.query_one("#write-history-content").content)
            await click_ready(app, pilot, history.query_one("#write-history-back", Button))
            await wait_for(lambda: app.screen is screen)
            adapter.stall = True
            adapter.entered.clear()
            screen.action_validate()
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            adapter.entered.clear()
            screen.action_confirm()
            await wait_for(adapter.entered.is_set)
            await screen.action_stop()
            assert screen.result.state is MutationState.UNCERTAIN and manager.active_count == 0
            assert len(screen.result.items) == 3
            screen.dismiss()
            await wait_for(lambda: not screen.is_attached)
            await screen.stop_owned()
            assert adapter.closed and service.operation_count == 0
            assert manager.records[-1].result.state is MutationState.UNCERTAIN
            assert partial.state is MutationState.PARTIAL
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()


@pytest.mark.asyncio
async def test_accepted_delete_then_stop_renders_partial_batch_in_review_and_history(tmp_path):
    local, service, adapter, manager, _current = await review_fixture(
        tmp_path, count=2, existing=True
    )
    adapter.write_states = [MutationState.ACCEPTED]
    adapter.stall_observation = True
    screen = ManifestReviewScreen(service=service, manager=manager, action="delete")
    app = ManifestTestApp(screen)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            await click_ready(app, pilot, screen.query_one("#manifest-review-validate", Button))
            await wait_for(lambda: screen.plan is not None and screen.operation_count == 0)
            await click_ready(app, pilot, screen.query_one("#manifest-review-confirm", Button))
            await wait_for(adapter.observing.is_set)
            assert len(adapter.writes) == 1
            await click_ready(app, pilot, screen.query_one("#manifest-review-stop", Button))
            await wait_for(lambda: screen.result is not None and screen.operation_count == 0)
            result = screen.result
            assert result.state is MutationState.PARTIAL
            assert result.items[0][1].state is MutationState.ACCEPTED
            assert "unsent" in result.items[1][1].message.lower()
            assert "Partial batch" in str(screen.status.content)
            assert "Accepted" in screen.table.get_row_at(0)[-1].plain
            assert "unsent" in screen.table.get_row_at(1)[-1].plain.lower()
            assert manager.records[-1].result is result
            await screen.action_back()
            history = MutationHistoryScreen(manager)
            app.push_screen(history)
            await wait_for(lambda: history.is_mounted)
            assert await history.wait_for_refresh()
            content = str(history.query_one("#write-history-content").content)
            assert "Partial batch" in content and "Deletion accepted" in content
            assert "manifest-ui-sensitive-value" not in content
    finally:
        await screen.stop_owned()
        await manager.close()
        await local.close()
