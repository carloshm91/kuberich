"""Pilot exercises exact service review, private inputs, cancellation and local browsing."""

import asyncio
import logging
import threading
from dataclasses import replace

import pytest
import yaml
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Button, Input, Select, TextArea

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.config.catalog import load_catalog
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.domain.commands import Command
from kuberich.domain.connections import ConnectionRequest
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.benchmark_store import BenchmarkStore
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.benchmarks import BenchmarkBrowserScreen, BenchmarkResultScreen, BenchmarkScreen
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.export_review import ArtifactConfirmation
from tests.contract.test_benchmark_store import record
from tests.support.benchmark_terminal import benchmark_fixture
from tests.support.benchmarks import executable, fixture, gone, receipt
from tests.support.workspace import wait_for

CHROME = WorkspaceChrome(lambda: ("synthetic", "synthetic", "synthetic", "team", "Ready"), "test")


class BenchmarkHost(App):
    def __init__(self, screen):
        super().__init__()
        self.initial_screen = screen

    def compose(self) -> ComposeResult:
        yield Button("Root", id="root")

    def on_mount(self):
        self.push_screen(self.initial_screen)


def screen_for(owner):
    return BenchmarkScreen(owner, chrome=CHROME, trail=("synthetic",), stopped=lambda: None)


async def ready(screen):
    await wait_for(lambda: bool(screen.backends) and not screen.busy)


async def review(screen, pilot):
    await pilot.pause()
    await pilot.press("f6")
    try:
        await wait_for(lambda: screen.review is not None and not screen.busy)
    except TimeoutError:
        pytest.fail(f"Review unavailable: {screen.feedback.content}")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_request_review_redacts_private_values_edit_revokes_and_limits_refuse(tmp_path, size):
    async with fixture(tmp_path) as (owner, _, forwards, processes, *_):
        screen = screen_for(owner)
        app = BenchmarkHost(screen)
        async with app.run_test(size=size) as pilot:
            await ready(screen)
            screen.query_one("#benchmark-target", Input).value = "/route?secret=private-query"
            screen.query_one("#benchmark-headers", TextArea).load_text(
                "Authorization: Bearer private-auth\nX-Test: private-header"
            )
            screen.query_one("#benchmark-body", TextArea).load_text("private-body")
            screen.query_one("#benchmark-method", Select).value = "POST"
            screen.query_one("#benchmark-duration", Input).value = "2"
            await review(screen, pilot)
            old = screen.review
            text = str(screen.preview.content)
            assert "route: /route" in text and "auth: present" in text and "body: 12 bytes" in text
            assert all(
                private not in text
                for private in ("private-query", "private-auth", "private-header", "private-body")
            )
            assert not screen.query_one("#benchmark-editor", Vertical).display
            assert screen.cancel_button.has_focus and not screen.run_button.disabled
            screen.edit()
            assert screen.review is None and screen.run_button.disabled
            with pytest.raises(AppError, match="exact benchmark review"):
                await owner.run(old)
            screen.query_one("#benchmark-rate", Input).value = "51"
            await pilot.press("f6")
            await wait_for(lambda: not screen.busy)
            assert screen.run_button.disabled and "limits" in str(screen.feedback.content)
            assert not (tmp_path / "version.json").exists()
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert processes.active_count == forwards.active_count == 0


@pytest.mark.asyncio
async def test_multiple_backends_need_an_explicit_choice_and_header_errors_remain_private(tmp_path):
    async with fixture(tmp_path) as (owner, _, _, _, _, service, *_):
        service["spec"]["ports"].append({"port": 81, "targetPort": "http"})
        screen = screen_for(owner)
        app = BenchmarkHost(screen)
        async with app.run_test() as pilot:
            await ready(screen)
            assert len(screen.backends) == 2
            assert screen.query_one("#benchmark-backend", Select).value is Select.NULL
            await pilot.press("f6")
            await wait_for(lambda: not screen.busy)
            assert "Choose one" in str(screen.feedback.content)
            screen.query_one("#benchmark-backend", Select).value = 1
            screen.query_one("#benchmark-headers", TextArea).load_text("private-malformed-header")
            await pilot.press("f6")
            await wait_for(lambda: not screen.busy)
            assert "Name: value" in str(screen.feedback.content)
            assert "private-malformed-header" not in str(screen.feedback.content)
            screen.query_one("#benchmark-headers", TextArea).load_text("")
            await review(screen, pilot)
            assert screen.review.backend.service_port == 81
            await screen.action_back()


class FailedSave(BenchmarkStore):
    async def save(self, result):
        raise AppError("Synthetic local save refusal")


@pytest.mark.asyncio
async def test_result_remains_visible_when_save_fails_and_private_editors_are_cleared(tmp_path):
    async with fixture(tmp_path, store=FailedSave(tmp_path / "records")) as (owner, manager, *_):
        screen = screen_for(owner)
        app = BenchmarkHost(screen)
        async with app.run_test() as pilot:
            await ready(screen)
            screen.query_one("#benchmark-body", TextArea).load_text("private-body")
            await review(screen, pilot)
            await pilot.press("f7")
            await wait_for(lambda: screen.finished)
            assert "Save failed" in str(screen.feedback.content)
            assert "p99" in str(screen.preview.content) and "complete" in str(
                screen.preview.content
            )
            assert screen.query_one("#benchmark-body", TextArea).text == ""
            assert screen.cancel_button.label.plain == "Back"
            await screen.action_back()
            assert manager.active_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_action", ["cancel", "escape", "target"])
async def test_live_run_cancellation_drains_before_return_and_keeps_classified_result(
    tmp_path, exit_action
):
    current = [True]
    async with fixture(tmp_path, mode="attack-sleep", current=lambda: current[0]) as (
        owner,
        manager,
        forwards,
        processes,
        *_,
    ):
        screen = screen_for(owner)
        app = BenchmarkHost(screen)
        async with app.run_test() as pilot:
            await ready(screen)
            await review(screen, pilot)
            await pilot.press("f7")
            attack = await receipt(tmp_path / "attack.json")
            if exit_action == "cancel":
                await screen.cancel()
                assert app.screen is screen and screen.finished
                assert owner.result.completion == "cancelled"
                await screen.action_back()
            elif exit_action == "escape":
                task = asyncio.create_task(screen.action_back())
                await asyncio.sleep(0)
                task.cancel()
                await task
            else:
                current[0] = False
                screen.validate_target()
                await screen.stop_owned()
                assert owner.result.completion == "target_lost"
                assert "target lost" in str(screen.preview.content)
                await screen.action_back()
            await gone(attack["pid"])
            assert forwards.active_count == processes.active_count == manager.active_count == 0
            assert not tuple(tmp_path.glob("benchmark-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (40, 12)])
async def test_offline_browser_filter_stable_viewport_open_delete_and_restart(tmp_path, size):
    store = BenchmarkStore(tmp_path / "records")
    saved = [
        await store.save(replace(record(), method="GET" if index % 2 else "HEAD"))
        for index in range(18)
    ]
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("benchmark-browser"),
        initial_command=Command.BENCHMARKS,
        benchmark_store=store,
    )
    async with app.run_test(size=size) as pilot:
        await wait_for(
            lambda: isinstance(app.screen, BenchmarkBrowserScreen) and len(app.screen.entries) == 18
        )
        screen = app.screen
        screen.table.move_cursor(row=12)
        selected = screen.selected()
        screen.table.scroll_to(y=5, animate=False, immediate=True)
        screen.action_refresh()
        await pilot.pause()
        await wait_for(lambda: screen.selected() == selected)
        assert app.sessions.client is None and app.benchmark_manager.active_count == 0
        screen.filter.value = str(selected.result.run_id)
        await wait_for(lambda: screen.table.row_count == 1)
        screen.action_open()
        await wait_for(lambda: isinstance(app.screen, BenchmarkResultScreen))
        assert app.screen.result == selected.result
        await pilot.press("escape")
        await wait_for(lambda: app.screen is screen)
        screen.action_delete()
        await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))
        app.screen.action_cancel()
        await wait_for(lambda: app.screen is screen)
        assert len(await store.scan()) == 18
        screen.action_delete()
        await wait_for(lambda: isinstance(app.screen, ArtifactConfirmation))
        app.screen.confirm()
        await wait_for(lambda: screen.table.row_count == 0)
        assert len(await store.scan()) == 17
        await pilot.press("escape")
        assert len(app.screen_stack) == 1
    assert len(await BenchmarkStore(store.default_root).scan()) == len(saved) - 1


@pytest.mark.asyncio
async def test_empty_local_browser_does_not_create_store_or_start_connection(tmp_path):
    root = tmp_path / "absent"
    app = KubeRichApp(
        Settings(),
        logging.Logger("benchmark-empty"),
        initial_command=Command.BENCHMARKS,
        benchmark_store=BenchmarkStore(root),
    )
    async with app.run_test() as pilot:
        await wait_for(lambda: isinstance(app.screen, BenchmarkBrowserScreen))
        await pilot.pause()
        screen = app.screen
        screen.action_open()
        screen.action_delete()
        assert "Select a saved" in str(screen.status.content)
        assert not root.exists() and app.sessions.client is None
        await pilot.press("escape")


@pytest.mark.asyncio
async def test_detached_browser_retains_and_drains_held_filesystem_worker(tmp_path):
    root = tmp_path / "records"
    await BenchmarkStore(root).save(record())
    entered, released = threading.Event(), threading.Event()

    class HeldFiles(ArtifactFiles):
        def read(self, ref, *, cancel):
            entered.set()
            assert released.wait(5)
            return super().read(ref, cancel=cancel)

    app = KubeRichApp(
        Settings(),
        logging.Logger("benchmark-held"),
        initial_command=Command.BENCHMARKS,
        benchmark_store=BenchmarkStore(root, files=HeldFiles()),
    )
    async with app.run_test() as pilot:
        assert await asyncio.to_thread(entered.wait, 5)
        screen = app.screen
        assert isinstance(screen, BenchmarkBrowserScreen)
        screen.dismiss()
        closing = asyncio.create_task(app.benchmarks.close())
        await asyncio.sleep(0.02)
        assert not closing.done()
        released.set()
        await closing
        await pilot.pause()
        assert app.sessions.client is None


@pytest.mark.asyncio
async def test_application_screenshots_are_refused_for_private_draft_and_redacted_after_review(
    tmp_path,
):
    async with fixture(tmp_path) as (owner, *_):
        screen = screen_for(owner)
        app = KubeRichApp(
            Settings(),
            logging.Logger("benchmark-screenshot"),
            initial_command=Command.BENCHMARKS,
            benchmark_store=BenchmarkStore(tmp_path / "screenshots"),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: isinstance(app.screen, BenchmarkBrowserScreen))
            await app.screen.action_back()
            app.push_screen(screen)
            await ready(screen)
            screen.query_one("#benchmark-headers", TextArea).load_text(
                "Authorization: private-screenshot-value"
            )
            assert screen.private_draft_visible
            assert app.deliver_screenshot("refused.svg", str(tmp_path)) is None
            with pytest.raises(AppError, match="private benchmark draft"):
                app.export_screenshot()
            assert not (tmp_path / "refused.svg").exists()
            await review(screen, pilot)
            assert not screen.private_draft_visible
            exported = app.export_screenshot()
            assert "private-screenshot-value" not in exported
            await screen.action_back()


@pytest.mark.asyncio
async def test_native_service_action_captures_settings_and_client_teardown_revokes_review(tmp_path):
    with benchmark_fixture(tmp_path, executable(tmp_path)) as (path, environment, http):
        preference_path = tmp_path / "preferences.yaml"
        document = yaml.safe_load(preference_path.read_text())
        preferences = PreferenceSource(
            ConfigLocation(preference_path, True), parse_document(document)
        )
        app = KubeRichApp(
            Settings(),
            logging.Logger("benchmark-native"),
            initial_command=ResourceCommand(RESOURCE_ALIASES["svc"], "team"),
            catalog=load_catalog(ConnectionRequest(kubeconfig=str(path)), {}),
            preferences=preferences,
            environment=environment,
            directory=tmp_path,
            benchmark_store=BenchmarkStore(tmp_path / "results"),
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            await app.run_command(":benchmark")
            await wait_for(lambda: isinstance(app.screen, BenchmarkScreen))
            screen = app.screen
            await ready(screen)
            await review(screen, pilot)
            assert app.benchmark_manager.active_count == 1
            document["benchmarks"]["defaults"]["load"]["rate"] = 3
            preferences.document = parse_document(document)
            app.benchmarks.observe()
            await screen.stop_owned()
            assert screen.run_button.disabled and app.benchmark_manager.active_count == 0
            await pilot.press("escape")
            await app.run_command(":benchmark")
            await wait_for(lambda: isinstance(app.screen, BenchmarkScreen))
            screen = app.screen
            await ready(screen)
            assert screen.owner.settings.load.rate == 3
            client = app.sessions.client
            await app.operations.close_for_client(client)
            assert app.benchmark_manager.active_count == 0
            assert not screen.owner.validate_target()
            await pilot.press("escape")
            assert http.requests == 0 and app.processes.active_count == 0
