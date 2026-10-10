"""Actual owned writes through captured confirmation, focus and responsive forms."""

import asyncio
import json
import logging
import threading

import pytest
from textual.widgets import Button, Input, Static

from kuberich.adapters import kubernetes
from kuberich.config.schema import Settings
from kuberich.domain.mutations import MutationState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.mutations import AnnotationScreen, MutationHistoryScreen
from tests.support.connections import catalog_fixture
from tests.support.mutations import mutation_api
from tests.support.workspace import wait_for


@pytest.mark.asyncio
@pytest.mark.parametrize("closing", ["retry", "exit", "escape"])
async def test_preparation_is_drained_before_client_cleanup(tmp_path, monkeypatch, closing):
    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    ready, finish_trial, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    decode = kubernetes.decode_json
    state = {}

    def held_decode(data):
        if json.loads(data).get("kind") == "ConfigMap":
            entered.set()
            try:
                assert released.wait(10)
                return decode(data)
            finally:
                finished.set()
        return decode(data)

    async with mutation_api() as (url, api):
        app = app_fixture(tmp_path, url)

        async def trial():
            async with app.run_test() as pilot:
                await wait_for(lambda: app.standard_table.row_count == 1)
                app.action_annotate()
                await wait_for(lambda: isinstance(app.screen, AnnotationScreen))
                await pilot.pause()
                screen = app.screen
                screen.query_one("#annotation-key", Input).value = "example.io/drain"
                await pilot.pause()
                monkeypatch.setattr(kubernetes, "decode_json", held_decode)
                old = app.sessions.client
                close = old.close

                async def checked_close():
                    assert finished.is_set() and screen._operation_task.done()
                    closed.set()
                    await close()

                monkeypatch.setattr(old, "close", checked_close)
                state.update(screen=screen, old=old, pilot=pilot)
                screen.review()
                await wait_for(entered.is_set)
                ready.set()
                await finish_trial.wait()

        owner = asyncio.create_task(trial())
        pressing = None
        try:
            await wait_for(ready.is_set)
            screen, old, pilot = state["screen"], state["old"], state["pilot"]
            if closing == "exit":
                finish_trial.set()
            else:
                pressing = asyncio.create_task(
                    pilot.press("f4" if closing == "retry" else "escape")
                )
            await wait_for(lambda: screen._operation_task.cancelling())
            another_drain = asyncio.create_task(screen.stop_owned())
            await asyncio.sleep(0)
            assert screen._operation_task.cancelling() == 1
            assert not closed.is_set() and old.configuration is not None
            assert not finished.is_set() and not api.requests
            released.set()
            await another_drain
            assert finished.is_set() and screen._operation_task.done()
            if pressing is not None:
                await pressing
            if closing == "retry":
                await wait_for(lambda: app.sessions.client is not old)
            elif closing == "escape":
                await wait_for(lambda: len(app.screen_stack) == 1)
        finally:
            released.set()
            finish_trial.set()
            if pressing is not None:
                await pressing
            await owner
        assert closed.is_set() and not api.requests


def app_fixture(tmp_path, url, *, read_only=False):
    return KubeRichApp(
        Settings(read_only=read_only),
        logging.getLogger("owned-mutation-ui"),
        catalog=catalog_fixture(tmp_path, url),
        initial_command=ResourceCommand(RESOURCE_ALIASES["cm"], "team"),
    )


async def prepare(app, pilot):
    await wait_for(lambda: app.standard_table.row_count == 1)
    app._submit_command(":annotate")
    await wait_for(lambda: isinstance(app.screen, AnnotationScreen))
    await pilot.pause()
    app.screen.query_one("#annotation-key", Input).value = "example.io/review"
    app.screen.query_one("#annotation-value", Input).value = "private-edit-value"
    await pilot.pause()
    await pilot.press("enter")
    await wait_for(lambda: app.screen.intent is not None)
    assert not app.screen.query_one("#annotation-confirm", Button).disabled
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_review_enter_cancel_confirm_and_public_history(tmp_path, size, monkeypatch):
    async with mutation_api() as (url, api):
        app = app_fixture(tmp_path, url)
        result_ready, show_result = asyncio.Event(), asyncio.Event()
        original_wait = app.mutations.wait

        async def delayed_feedback(identity):
            result = await original_wait(identity)
            result_ready.set()
            await show_result.wait()
            return result

        monkeypatch.setattr(app.mutations, "wait", delayed_feedback)
        async with app.run_test(size=size) as pilot:
            screen = await prepare(app, pilot)
            assert app.focused is screen.query_one("#annotation-cancel", Button)
            target = str(screen.query_one("#annotation-target", Static).content)
            preview = str(screen.query_one("#annotation-preview", Static).content)
            assert "Context: kuberich-test-one" in target and "Namespace: team" in target
            assert "configmaps/owned-one" in target and "UID:" in target
            assert (
                "opaque/version-7" in preview
                and "set example.io/review = private-edit-value" in preview
            )
            assert not api.requests
            await pilot.press("enter")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert not api.requests
            screen = await prepare(app, pilot)
            screen.confirm()
            await wait_for(result_ready.is_set)
            assert app.mutations.records[-1].result.state is MutationState.SUCCEEDED
            assert len(api.requests) == 1
            # Publishing the owned outcome precedes the screen's independent waiter.
            assert "Sending" in str(screen.query_one("#annotation-feedback", Static).content)
            show_result.set()
            await wait_for(
                lambda: "Succeeded" in str(screen.query_one("#annotation-feedback", Static).content)
            )
            assert "Succeeded" in str(screen.query_one("#annotation-feedback", Static).content)
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            app._submit_command(":writes")
            await wait_for(lambda: isinstance(app.screen, MutationHistoryScreen))
            await pilot.pause()
            content = str(app.screen.query_one("#write-history-content", Static).content)
            assert "Succeeded" in content and "configmaps/owned-one" in content
            assert "private-edit-value" not in content and "private-existing" not in content
            app.screen.back()
            await pilot.pause()
        assert app.sessions.client is None and not app.mutations._live


@pytest.mark.asyncio
async def test_changed_fields_and_context_invalidate_confirmation(tmp_path):
    async with mutation_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await prepare(app, pilot)
            screen.query_one("#annotation-value", Input).value = "another-change"
            await pilot.pause()
            screen.confirm()
            assert not api.requests and screen.intent is None
            screen.review()
            await wait_for(lambda: screen.intent is not None)
            app._namespace_selected("other")
            await wait_for(lambda: app.sessions.observation.namespace == "other")
            screen.confirm()
            assert not api.requests and "changed" in str(
                screen.query_one("#annotation-feedback", Static).content
            )
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_readonly_action_is_rejected_but_history_is_allowed(tmp_path):
    async with mutation_api() as (url, api):
        app = app_fixture(tmp_path, url, read_only=True)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            app._submit_command(":annotate")
            assert "Read-only" in str(app.status.content) and len(app.screen_stack) == 1
            app.action_annotate()
            assert not api.requests
            app._submit_command(":writes")
            await wait_for(lambda: isinstance(app.screen, MutationHistoryScreen))
            await pilot.pause()
            assert "No writes" in str(
                app.screen.query_one("#write-history-content", Static).content
            )
            await pilot.press("escape")


@pytest.mark.asyncio
async def test_escaping_pending_write_retains_outcome_and_exit_drains_uncertain_request(tmp_path):
    async with mutation_api() as (url, api):
        app = app_fixture(tmp_path, url)
        async with app.run_test() as pilot:
            screen = await prepare(app, pilot)
            api.mode = "stall"
            screen.confirm()
            await api.entered.wait()
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert len(app.mutations._live) == 1
            app.action_writes()
            await wait_for(lambda: isinstance(app.screen, MutationHistoryScreen))
            await pilot.pause()
            assert "revalidating" in str(
                app.screen.query_one("#write-history-content", Static).content
            )
        assert app.mutations.records[-1].result.state is MutationState.UNCERTAIN
        assert not app.mutations._live and app.sessions.client is None and len(api.requests) == 1
