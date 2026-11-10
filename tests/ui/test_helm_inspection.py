"""Document secrecy, reviewed rollback and cleanup through actual App/Pilot flows."""

import json

import pytest
from textual.widgets import Button, Checkbox, Input, Static

from kuberich.ui.helm_inspection import HelmDisclosureReviewScreen, HelmRollbackReviewScreen
from kuberich.ui.keybindings import NavigationHelpScreen
from tests.support.helm import PRIVATE_VALUE, calls
from tests.support.workspace import wait_for
from tests.ui.test_helm import helm_app, helm_ready, open_inspector


@pytest.mark.asyncio
@pytest.mark.parametrize("page", ["notes", "values", "all-values", "manifest"])
async def test_every_document_has_redacted_default_fresh_one_use_disclosure_and_hide(
    tmp_path, page
):
    async with (
        helm_app(tmp_path) as (app, _api, _services, _scenario, record),
        app.run_test(size=(100, 30)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        assert PRIVATE_VALUE not in screen.viewer.text
        await pilot.click("#helm-" + page)
        await wait_for(lambda: screen.operation_count == 0 and bool(screen.viewer.text))
        assert PRIVATE_VALUE not in screen.viewer.text
        before = len(calls(record))
        await pilot.click("#helm-reveal")
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        assert PRIVATE_VALUE not in str(app.screen.query_one(Static).content)
        await pilot.pause()
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: app.screen is screen and screen.revealed)
        assert PRIVATE_VALUE in screen.viewer.text
        assert len(calls(record)) > before
        assert "REVEALED" in str(screen.query_one(".helm-status", Static).content)
        await pilot.click("#helm-reveal")
        await wait_for(lambda: screen.operation_count == 0 and bool(screen.viewer.text))
        assert not screen.revealed and PRIVATE_VALUE not in screen.viewer.text
        await pilot.click("#helm-status")
        assert "Description: withheld" in screen.viewer.text
        await screen.stop_owned()
        assert screen.viewer.text == "" and screen.operation_count == 0


@pytest.mark.asyncio
async def test_disclosure_cancel_switch_section_and_nested_navigation_clear_text(tmp_path):
    async with (
        helm_app(tmp_path) as (app, _api, _services, _scenario, _record),
        app.run_test() as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_page("notes")
        await wait_for(lambda: screen.operation_count == 0)
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen)
        assert not screen.revealed and PRIVATE_VALUE not in screen.viewer.text
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: screen.revealed)
        screen.action_page("history")
        assert screen.viewer.text == "" and not screen.revealed
        assert screen.history.row_count == 3
        app.command_routes.route(screen, "pods")
        await wait_for(lambda: len(app.screen_stack) == 1 and app.state.scope is not None)
        assert screen.viewer.text == "" and screen.operation_count == 0


async def review_revision_one(app, pilot, screen):
    screen.action_page("history")
    await pilot.pause()
    screen.history.move_cursor(row=screen.history.get_row_index("3"))
    screen.set_focus(screen.history)
    await pilot.press("enter")
    assert screen.selected_revision is None
    assert screen.query_one("#helm-rollback", Button).disabled
    screen.history.move_cursor(row=screen.history.get_row_index("1"))
    screen.set_focus(screen.history)
    await pilot.press("enter")
    assert screen.selected_revision == 1
    assert not screen.query_one("#helm-rollback", Button).disabled
    await pilot.click("#helm-rollback")
    await wait_for(lambda: isinstance(app.screen, HelmRollbackReviewScreen))
    await pilot.pause()
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("hooks", [False, True])
async def test_reviewed_rollback_explicit_prior_revision_options_and_real_process(tmp_path, hooks):
    async with (
        helm_app(tmp_path) as (app, _api, _services, scenario, record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_rollback()
        assert app.screen is screen
        review = await review_revision_one(app, pilot, screen)
        assert review.query_one("#helm-rollback-hooks", Checkbox).value is False
        assert review.query_one("#helm-rollback-wait", Checkbox).value is True
        assert review.query_one("#helm-rollback-timeout", Input).value == "300"
        assert review.query_one("#helm-confirm-rollback", Button).disabled
        if hooks:
            review.query_one("#helm-rollback-hooks", Checkbox).value = True
        review.query_one("#helm-rollback-timeout", Input).value = "20"
        await pilot.pause()
        review.prepare()
        await wait_for(lambda: review.intent is not None)
        effects = str(review.query_one("#helm-rollback-effects", Static).content)
        assert "not atomic" in effects and "retained" in effects
        assert all(
            f"{name}:" in str(review.query_one(Static).content)
            for name in (
                "Context",
                "Namespace",
                "Release",
                "Current revision",
                "Selected target revision",
            )
        )
        review.confirm()
        review.confirm()  # One-use UI submission; service independently consumes its approval.
        await wait_for(lambda: review.operation_count == 0)
        assert "SUCCEEDED" in str(review.query_one(".helm-status", Static).content)
        mutations = [item for item in calls(record) if "rollback" in item["argv"]]
        assert len(mutations) == 1
        argv = mutations[0]["argv"]
        assert argv[argv.index("rollback") + 1 : argv.index("rollback") + 3] == ["demo", "1"]
        assert ("--no-hooks=true" in argv) is not hooks
        assert "--history-max=0" in argv and "--timeout=20s" in argv
        assert json.loads(scenario.read_text())["revision"] == 4
        await pilot.press("escape", "escape")
        await helm_ready(app)
        await pilot.press("f4")
        await helm_ready(app)
        await wait_for(lambda: app.helm_table.selected_release().revision == 4)
        assert app.helm_table.selected_release().revision == 4


@pytest.mark.asyncio
async def test_changing_review_options_expires_prepared_intent_and_read_only_never_launches(
    tmp_path,
):
    async with (
        helm_app(tmp_path, read_only=True) as (app, _api, _services, _scenario, record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        review = await review_revision_one(app, pilot, screen)
        review.prepare()
        await wait_for(lambda: review.operation_count == 0)
        assert "read-only" in str(review.query_one(".helm-status", Static).content).lower()
        assert review.intent is None and review.query_one("#helm-confirm-rollback", Button).disabled
        review.query_one("#helm-rollback-timeout", Input).value = "0"
        await pilot.pause()
        review.prepare()
        await wait_for(lambda: review.operation_count == 0)
        assert "timeout" in str(review.query_one(".helm-status", Static).content).lower()
        assert not any("rollback" in item["argv"] for item in calls(record))


@pytest.mark.asyncio
async def test_review_changes_stale_storage_forbidden_and_cancelled_inspection_drain(tmp_path):
    async with (
        helm_app(tmp_path) as (app, api, services, _scenario, record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        review = await review_revision_one(app, pilot, screen)
        review.prepare()
        await wait_for(lambda: review.intent is not None)
        review.query_one("#helm-rollback-timeout", Input).value = "12"
        await pilot.pause()
        assert review.intent is None
        assert review.query_one("#helm-confirm-rollback", Button).disabled
        review.prepare()
        await wait_for(lambda: review.intent is not None)
        api.records[1]["metadata"]["resourceVersion"] = "changed-after-review"
        review.confirm()
        await wait_for(lambda: review.operation_count == 0)
        assert (
            "stale" in str(review.query_one(".helm-status", Static).content).lower()
            or "changed" in str(review.query_one(".helm-status", Static).content).lower()
        )
        assert not any("rollback" in item["argv"] for item in calls(record))
        await review.action_back()
        api.status = 403
        screen.action_page("manifest")
        await wait_for(lambda: screen.operation_count == 0)
        assert "storage" in str(screen.query_one(".helm-status", Static).content).lower()
        api.status = 200
        api.block = True
        api.started.clear()
        screen.action_page("values")
        await api.started.wait()
        await screen.stop_owned()
        assert screen.operation_count == 0 and screen.viewer.text == ""
        assert all(service.operation_count == 0 for service in services)


@pytest.mark.asyncio
async def test_disclosure_refusals_stale_default_reads_and_context_departure_clear_owned_text(
    tmp_path,
):
    async with (
        helm_app(tmp_path) as (app, api, _services, _scenario, _record),
        app.run_test(size=(100, 30)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_reveal()  # Status is metadata only.
        assert screen.operation_count == 0
        api.block = True
        api.started.clear()
        screen.action_page("values")
        await api.started.wait()
        screen.action_page("notes")
        api.block = False
        api.release.set()
        await wait_for(lambda: screen.operation_count == 0)
        assert "notes" in screen.viewer.text.lower() and screen.page == "notes"
        api.records[3]["metadata"]["resourceVersion"] = "changed-before-disclosure"
        screen.action_reveal()
        await wait_for(lambda: screen.operation_count == 0)
        assert app.screen is screen and not screen.revealed
        assert "changed" in str(screen.query_one(".helm-status", Static).content).lower()
        api.records[3]["metadata"]["resourceVersion"] = "opaque-3"
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        api.records[3]["metadata"]["resourceVersion"] = "changed-after-review"
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: app.screen is screen and screen.operation_count == 0)
        assert not screen.revealed and PRIVATE_VALUE not in screen.viewer.text
        api.records[3]["metadata"]["resourceVersion"] = "opaque-3"
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: screen.revealed)
        app.workspace.refresh_helm()
        await wait_for(lambda: screen.invalidated)
        assert screen.viewer.text == "" and screen.operation_count == 0
        screen.action_page("manifest")
        screen.action_reveal()
        assert screen.viewer.text == ""
        await screen.stop_owned()
        await screen.stop_owned()


@pytest.mark.asyncio
async def test_revealed_content_is_cleared_when_screen_is_covered_and_faults_are_safe(tmp_path):
    async with (
        helm_app(tmp_path) as (app, _api, _services, _scenario, _record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_page("notes")
        await wait_for(lambda: screen.operation_count == 0)
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: screen.revealed)
        review = HelmRollbackReviewScreen(screen.service, screen.inspection, 1)
        app.push_screen(review)
        await pilot.pause()
        assert not screen.revealed and screen.viewer.text == ""
        review.query_one("#helm-rollback-timeout", Input).value = ""
        await pilot.pause()
        review.query_one("#helm-prepare-rollback", Button).press()
        await wait_for(
            lambda: "whole-number" in str(review.query_one(".helm-status", Static).content)
        )
        assert "whole-number" in str(review.query_one(".helm-status", Static).content)
        review.query_one("#helm-cancel-rollback", Button).press()
        await wait_for(lambda: app.screen is screen)

        async def unexpected_failure():
            raise RuntimeError(PRIVATE_VALUE)

        screen.launch(unexpected_failure())
        await wait_for(lambda: screen.operation_count == 0)
        assert PRIVATE_VALUE not in str(screen.query_one(".helm-status", Static).content)
        assert "operation failed" in str(screen.query_one(".helm-status", Static).content)
        await pilot.click("#helm-back")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("complete_while_covered", [True, False])
async def test_pending_disclosure_cannot_repopulate_covered_or_returned_inspector(
    tmp_path, complete_while_covered
):
    async with (
        helm_app(tmp_path) as (app, api, _services, _scenario, record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_page("notes")
        await wait_for(lambda: screen.operation_count == 0)
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        api.block = True
        api.started.clear()
        await pilot.click("#helm-disclosure-confirm")
        await api.started.wait()
        await wait_for(lambda: app.screen is screen)
        assert not screen.revealed
        app.set_focus(screen.viewer)
        app.action_navigation_help()
        await pilot.pause()
        assert isinstance(app.screen, NavigationHelpScreen)
        assert not screen.revealed
        if not complete_while_covered:
            await pilot.press("escape")
            await wait_for(lambda: app.screen is screen)
        api.block = False
        api.release.set()
        await wait_for(lambda: screen.operation_count == 0)
        assert not screen.revealed
        assert PRIVATE_VALUE not in screen.viewer.text
        if complete_while_covered:
            await pilot.press("escape")
            await wait_for(lambda: app.screen is screen)
        assert not screen.revealed
        assert PRIVATE_VALUE not in screen.viewer.text
        assert any("get" in item["argv"] for item in calls(record))
        # The disclosure review remains usable after returning, but needs a new
        # preparation and explicit approval; the old delayed completion is dead.
        screen.action_page("notes")
        await wait_for(lambda: screen.operation_count == 0)
        screen.action_reveal()
        await wait_for(lambda: isinstance(app.screen, HelmDisclosureReviewScreen))
        await pilot.pause()
        await pilot.click("#helm-disclosure-confirm")
        await wait_for(lambda: screen.revealed)
        assert PRIVATE_VALUE in screen.viewer.text
        await screen.stop_owned()
        assert screen.viewer.text == ""


@pytest.mark.asyncio
async def test_covering_inspector_during_disclosure_preparation_does_not_open_late_review(tmp_path):
    async with (
        helm_app(tmp_path) as (app, api, _services, _scenario, _record),
        app.run_test(size=(100, 35)) as pilot,
    ):
        await wait_for(lambda: app.state.scope is not None)
        await app.run_command("helm")
        screen = await open_inspector(app, pilot)
        screen.action_page("notes")
        await wait_for(lambda: screen.operation_count == 0)
        api.block = True
        api.started.clear()
        screen.action_reveal()
        await api.started.wait()
        app.set_focus(screen.viewer)
        app.action_navigation_help()
        await pilot.pause()
        assert isinstance(app.screen, NavigationHelpScreen)
        api.block = False
        api.release.set()
        await wait_for(lambda: screen.operation_count == 0)
        assert isinstance(app.screen, NavigationHelpScreen)
        assert not screen.revealed and PRIVATE_VALUE not in screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen)
        assert not screen.revealed and PRIVATE_VALUE not in screen.viewer.text
