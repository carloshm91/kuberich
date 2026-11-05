"""Actual App client closure drains diagnostic actions before reporting outcomes."""

import asyncio
import gc
import warnings
from pathlib import Path

import pytest

from kuberich.ui.diagnostic_evidence import DiagnosticEvidenceScreen
from tests.support.authorization_ui import authorization_api
from tests.support.diagnostic_api import DiagnosticAPI
from tests.support.workspace import wait_for
from tests.ui.test_cluster_diagnostics_app import diagnostics_ready, pods_ready, select
from tests.ui.test_live_preferences import owned_app

pytestmark = pytest.mark.fast


@pytest.mark.asyncio
async def test_caller_cancel_preserves_unexpected_cleanup_failure_after_all_owners_drain(
    tmp_path, monkeypatch
):
    async with authorization_api(DiagnosticAPI()) as url:
        app, _, _ = owned_app(tmp_path, {}, url=url)
        async with app.run_test() as pilot:
            await pods_ready(app)
            await app.run_command("diagnostics")
            await diagnostics_ready(app)
            select(app)
            await pilot.press("enter")
            await wait_for(lambda app=app: isinstance(app.screen, DiagnosticEvidenceScreen))
            screen = app.screen
            client = app.sessions.client
            directory = Path(client.directory.name)
            operation_started, operation_release, operation_drained = (
                asyncio.Event(),
                asyncio.Event(),
                asyncio.Event(),
            )
            evidence_started, evidence_release, evidence_drained = (
                asyncio.Event(),
                asyncio.Event(),
                asyncio.Event(),
            )
            operations_close = app.operations.close_for_client
            evidence_stop = screen.stop_owned

            async def failing_operations(selected):
                assert selected is client
                operation_started.set()
                await operation_release.wait()
                await operations_close(selected)
                operation_drained.set()
                raise RuntimeError("Controlled diagnostic cleanup failure")

            async def held_evidence():
                evidence_started.set()
                await evidence_release.wait()
                await evidence_stop()
                evidence_drained.set()

            monkeypatch.setattr(app.operations, "close_for_client", failing_operations)
            monkeypatch.setattr(screen, "stop_owned", held_evidence)
            closing = asyncio.create_task(app.sessions.close())
            outcome = None
            try:
                async with asyncio.timeout(5):
                    await operation_started.wait()
                    await evidence_started.wait()
                    closing.cancel()
                    operation_release.set()
                    await operation_drained.wait()
                    await asyncio.sleep(0)
                    assert not closing.done()
                    assert directory.exists() and app.sessions.client is client
                    evidence_release.set()
                    try:
                        await closing
                    except BaseException as error:
                        outcome = error
                    assert evidence_drained.is_set() and operation_drained.is_set()
                    assert app.sessions.client is None and not directory.exists()
                    assert isinstance(outcome, RuntimeError), (
                        "Caller cancellation hid the unexpected cleanup outcome",
                        type(outcome).__name__,
                    )
                    assert str(outcome) == "Controlled diagnostic cleanup failure"
            finally:
                operation_release.set()
                evidence_release.set()
                await asyncio.gather(closing, return_exceptions=True)
                monkeypatch.undo()


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["root", "evidence"])
async def test_cancel_before_action_starts_reaps_worker_and_creates_no_unawaited_coroutine(
    tmp_path, origin
):
    close_errors = []
    remaining = []
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always", RuntimeWarning)
        async with authorization_api(DiagnosticAPI()) as url:
            app, _, _ = owned_app(tmp_path, {}, url=url)
            async with app.run_test() as pilot:
                await pods_ready(app)
                await app.run_command("diagnostics")
                await diagnostics_ready(app)
                select(app)
                if origin == "evidence":
                    await pilot.press("enter")
                    await wait_for(lambda app=app: isinstance(app.screen, DiagnosticEvidenceScreen))
                    app.screen.action_open_object()
                else:
                    app.action_open_relationship()
                # No event-loop yield occurs between queueing and public client
                # closure; the action coroutine has not performed its first read.
                try:
                    async with asyncio.timeout(5):
                        await app.sessions.close()
                except Exception as error:
                    close_errors.append((type(error).__name__, str(error)))
                await pilot.pause()
                remaining = [
                    (worker.group, worker.state.name)
                    for worker in app.workers
                    if worker.group == "diagnostic-object" or worker.node is app.screen
                ]
                assert app.sessions.client is None
            del pilot
            del app
            gc.collect()
            await asyncio.sleep(0)
            gc.collect()
        unawaited = [
            str(item.message)
            for item in observed
            if issubclass(item.category, RuntimeWarning)
            and "was never awaited" in str(item.message)
        ]
    assert not close_errors and not remaining and not unawaited, {
        "origin": origin,
        "client_close_errors": close_errors,
        "remaining_workers": remaining,
        "unawaited_coroutines": unawaited,
    }
