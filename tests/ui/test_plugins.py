"""Actual command/key routing, typed review, cancellation and owned job views."""

import asyncio
import logging
import sys
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from textual.widgets import Button, Checkbox, Input, Select, Static

import kuberich.ui.plugins as plugin_ui
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.ui.app import KubeRichApp
from kuberich.ui.plugins import PluginCatalogue, PluginJobs, PluginScreen
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workers import CoroutineCalls
from tests.support.workspace import stable_watch, wait_for, workspace_api


@pytest.fixture
def plugin_tasks(monkeypatch):
    calls = CoroutineCalls()

    def created(coroutine):
        task = asyncio.create_task(coroutine)
        calls.tasks.append(task)
        return task

    monkeypatch.setattr(
        plugin_ui,
        "asyncio",
        SimpleNamespace(
            create_task=created,
            gather=asyncio.gather,
            shield=asyncio.shield,
            Task=asyncio.Task,
        ),
    )
    return calls


async def ns(request):
    return namespaces("team")


async def api(request):
    if "watch" in request.query:
        return await stable_watch(request)
    return web.json_response(
        collection(pod("api")) if request.path.endswith("/pods") else pod("api")
    )


def app_for(tmp_path, url, *, readonly=False, definitions=None, extension=None):
    commands = definitions or {
        "inspect": {
            "command": sys.executable,
            "args": ["-c", "print('plugin finished')"],
            "shortcut": "z",
            "dangerous": False,
            "trusted_read_only": True,
        }
    }
    settings = Settings(read_only=readonly)
    document = ConfigDocument(
        settings=settings,
        extensions={"plugins": extension or {"schema_version": 1, "commands": commands}},
    )
    return KubeRichApp(
        settings,
        logging.Logger("plugins", level=100),
        catalog=catalog_fixture(tmp_path, url),
        preferences=PreferenceSource(ConfigLocation(tmp_path / "preferences.yaml", True), document),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(44, 14), (110, 35)])
async def test_colon_catalogue_review_run_status_keys_and_input_ownership(tmp_path, size):
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url)
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.resources.row_count == 1 and bool(app.plugins.plugins))
            before = app.resources.capture_viewport()
            await pilot.press("colon", *"plugins", "enter")
            await wait_for(
                lambda: isinstance(app.screen, PluginCatalogue) and app.screen.is_mounted
            )
            assert app.screen.query_one("#plugin-catalogue").row_count == 1
            output = Path("artifacts/ui").resolve()
            output.mkdir(parents=True, exist_ok=True)
            app.save_screenshot(filename=f"plugin-catalogue-{size[0]}.svg", path=str(output))
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            assert "pods/api" in str(screen.query_one("#plugin-captured-target", Static).content)
            assert "UID:" in str(screen.query_one("#plugin-captured-target", Static).content)
            assert screen.focused.id == "plugin-cancel"
            assert screen.query_one("#plugin-run", Button).disabled
            await pilot.click("#plugin-review")
            await wait_for(lambda: screen.review is not None)
            assert not app.plugins.manager.jobs
            with pytest.raises(AppError, match="screenshot"):
                app.export_screenshot()
            assert app.deliver_screenshot() is None
            await pilot.click("#plugin-run")
            await wait_for(lambda: screen.job is not None and not screen.job.running)
            await wait_for(
                lambda: "Succeeded" in str(screen.query_one("#plugin-feedback", Static).content)
            )
            assert "plugin finished" in screen.job.output
            screen.run_plugin()
            assert len(app.plugins.manager.jobs) == 1
            await pilot.press("escape")
            assert app.resources.capture_viewport() == before
            await pilot.press("slash", "z")
            assert app.filter_input.value == "z" and not isinstance(app.screen, PluginScreen)
            await pilot.press("escape", "z")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            await pilot.press("escape")
            assert len(app.plugins.manager.jobs) == 1
            await pilot.press("colon", *"plugin in", "tab")
            assert app.command_input.value == "plugin inspect"
            await pilot.press("escape")
        assert all(
            not job.running and job.runner.active_count == 0 for job in app.plugins.manager.jobs
        )


@pytest.mark.asyncio
async def test_typed_inputs_validation_change_invalidates_review_and_cancel_never_runs(tmp_path):
    definitions = {
        "inputs": {
            "command": sys.executable,
            "args": [
                "-c",
                "print('typed')",
                "${INPUT_COUNT}",
                "${INPUT_ACTIVE}",
                "${INPUT_CHOICE}",
                "${INPUT_TEXT}",
            ],
            "inputs": [
                {"name": "count", "type": "number", "default": 3},
                {"name": "active", "type": "bool", "default": "false"},
                {"name": "choice", "type": "dropdown", "options": ["one", "two"]},
                {"name": "text", "default": "literal"},
            ],
        }
    }
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, definitions=definitions)
        async with app.run_test(size=(100, 40)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command("plugin inputs")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            screen.prepare()
            await wait_for(lambda: screen.operation.done())
            assert screen.review is None and "required" in str(
                screen.query_one("#plugin-feedback").content
            )
            assert not screen.query_one("#plugin-input-1", Checkbox).value
            screen.query_one("#plugin-input-2", Select).value = "two"
            screen.query_one("#plugin-input-1", Checkbox).value = True
            await pilot.pause()
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            screen.query_one("#plugin-input-0", Input).value = "not-number"
            await pilot.pause()
            assert screen.review is None and screen.query_one("#plugin-run", Button).disabled
            assert screen.source.pending_reviews == 0
            screen.prepare()
            await wait_for(lambda: screen.operation.done())
            assert "finite number" in str(screen.query_one("#plugin-feedback").content)
            await pilot.press("escape")
            assert not app.plugins.manager.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize("readonly", [False, True])
async def test_background_survives_form_close_jobs_output_stop_and_context_cleanup(
    tmp_path, readonly
):
    definitions = {
        "work": {
            "command": sys.executable,
            "args": ["-c", "import time;print('done',flush=True);time.sleep(30)"],
            "mode": "background",
            "dangerous": False,
            "trusted_read_only": True,
        }
    }
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, definitions=definitions, readonly=readonly)
        async with app.run_test(size=(100, 35)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            await app.run_command("plugin work")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            screen.run_plugin()
            await wait_for(lambda: screen.job is not None and screen.job.status == "Running")
            job = screen.job
            await pilot.press("escape")
            assert job.running
            await app.run_command("pluginjobs")
            assert isinstance(app.screen, PluginJobs)
            jobs = app.screen
            await pilot.pause()
            await pilot.press("enter")
            assert "Running" in str(jobs.query_one("#plugin-job-text", Static).content)
            await pilot.click("#plugin-job-stop")
            await wait_for(lambda: not job.running)
            assert job.status == "Cancelled"
            await pilot.press("escape")
            await app.run_command("plugin work")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            app.screen.prepare()
            await wait_for(lambda: app.screen.review is not None)
            app.screen.run_plugin()
            await wait_for(lambda: len(app.plugins.manager.jobs) == 2)
            await pilot.press("escape")
            await app.sessions.close()
            assert all(not item.running for item in app.plugins.manager.jobs)


@pytest.mark.asyncio
async def test_readonly_unknown_missing_scope_and_offline_catalogue_are_actionable(
    tmp_path, plugin_tasks
):
    definitions = {"unsafe": {"command": "missing"}}
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, readonly=True, definitions=definitions)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1 and bool(app.plugins.plugins))
            await app.run_command("plugin unsafe")
            await wait_for(lambda: plugin_tasks.latest.done())
            assert "Read-only" in str(app.status.content) and len(app.screen_stack) == 1
            await app.run_command("plugin missing")
            await wait_for(lambda: plugin_tasks.latest.done())
            assert "not configured" in str(app.status.content)
            assert not app.plugins.manager.jobs
    app = KubeRichApp(Settings(), logging.Logger("offline", level=100))
    async with app.run_test() as pilot:
        await app.run_command("plugins")
        await wait_for(lambda: isinstance(app.screen, PluginCatalogue) and app.screen.is_mounted)
        assert app.screen.query_one("#plugin-catalogue").row_count == 0
        await pilot.click("#plugin-back")


@pytest.mark.asyncio
async def test_invalid_explicit_manifest_refuses_catalogue_without_executing(
    tmp_path, plugin_tasks
):
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, extension={"schema_version": 1, "locations": ["missing.yaml"]})
        async with app.run_test():
            await wait_for(lambda: app.resources.row_count == 1 and app.plugins.error is not None)
            await app.run_command("plugins")
            await wait_for(lambda: plugin_tasks.latest.done())
            assert "plugin" in str(app.status.content).lower() and len(app.screen_stack) == 1
            assert not app.plugins.manager.jobs


@pytest.mark.asyncio
async def test_loading_captures_the_original_row_before_waiting_and_does_not_retarget(
    tmp_path, monkeypatch
):
    import kuberich.ui.plugins as module

    entered, release = threading.Event(), threading.Event()
    original = module.load_plugins

    def delayed(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "load_plugins", delayed)

    async def rows(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(
            collection(pod("api"), pod("worker"))
            if request.path.endswith("/pods")
            else pod(request.path.rsplit("/", 1)[-1])
        )

    async with workspace_api(ns, rows) as url:
        app = app_for(tmp_path, url)
        try:
            async with app.run_test() as pilot:
                await wait_for(lambda: app.resources.row_count == 2 and entered.is_set())
                captured = []
                capture = app.plugins.capture_source

                def remember():
                    owner = capture()
                    captured.append(owner)
                    return owner

                monkeypatch.setattr(app.plugins, "capture_source", remember)
                app.plugins.open("inspect")
                await wait_for(lambda: bool(captured))
                original_uid = captured[0].selection.target.uid
                app.resources.action_cursor_down()
                assert app.resources.capture_viewport().selected != original_uid
                release.set()
                await wait_for(lambda: isinstance(app.screen, PluginScreen))
                await pilot.pause()
                assert app.screen.source.selection.target.uid == original_uid
                assert dict(app.screen.source.selection.columns)["NAME"] == "api"
                await pilot.press("escape")
        finally:
            release.set()


@pytest.mark.asyncio
async def test_changed_fields_during_review_discard_the_old_proof_and_empty_jobs_are_safe(
    tmp_path, monkeypatch
):
    definitions = {
        "note": {"command": sys.executable, "inputs": [{"name": "note", "default": "old"}]}
    }
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, definitions=definitions)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            app.plugins.open("note")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            entered, release = asyncio.Event(), asyncio.Event()
            prepare = screen.source.prepare

            async def delayed(*args):
                entered.set()
                await release.wait()
                return await prepare(*args)

            monkeypatch.setattr(screen.source, "prepare", delayed)
            screen.prepare()
            await entered.wait()
            operation = screen.operation
            screen.prepare()
            assert screen.operation is operation
            screen.query_one(Input).value = "new"
            await pilot.pause()
            release.set()
            await wait_for(lambda: screen.operation.done())
            assert screen.review is None and screen.source.pending_reviews == 0
            assert "Inputs changed" in str(screen.query_one("#plugin-feedback").content)
            await pilot.press("escape")
            await app.run_command("pluginjobs")
            await pilot.pause()
            assert app.screen.selected_job() is None
            app.screen.stop_job()
            await pilot.click("#plugin-job-back")


@pytest.mark.asyncio
async def test_offline_execution_and_native_foreground_refusal_are_visible(tmp_path, plugin_tasks):
    async with workspace_api(ns, api) as url:
        app = app_for(
            tmp_path,
            url,
            definitions={"terminal": {"command": sys.executable, "mode": "foreground"}},
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            app.plugins.open("terminal")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            screen = app.screen
            screen.prepare()
            await wait_for(lambda: screen.review is not None)
            screen.run_plugin()
            await wait_for(lambda: screen.job is not None and not screen.job.running)
            assert screen.job.status == "Error: AppError"
            await pilot.press("escape")
    app = KubeRichApp(Settings(), logging.Logger("offline", level=100))
    async with app.run_test() as pilot:
        app.plugins.open("unknown")
        await wait_for(lambda: plugin_tasks.latest.done())
        assert "connected context" in str(app.status.content)


@pytest.mark.asyncio
async def test_context_catalogue_does_not_inherit_pod_scope_or_keys_and_loading_gvr_is_refused(
    tmp_path, monkeypatch, plugin_tasks
):
    definitions = {
        "pod": {"command": sys.executable, "scopes": ["v1/pods"], "shortcut": "z"},
        "global": {"command": sys.executable},
    }
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, definitions=definitions)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1 and bool(app.plugins.plugins))
            selections = []
            with monkeypatch.context() as patch:
                # Hold the public selection port at its previous observation to
                # exercise a late old snapshot after real command dispatch.
                def pending_selection(selection):
                    task = asyncio.create_task(asyncio.sleep(0))
                    selections.append(task)
                    return task

                patch.setattr(app.workspace, "select_resource", pending_selection)
                await app.run_command("deploy")
                with pytest.raises(AppError, match="loading"):
                    app.plugins.capture_source()
                resource = app.workspace.store.observation.scope.resource
                patch.setattr(
                    type(app.workspace.discovery),
                    "resolve",
                    lambda *args, **kwargs: replace(resource, group="other.example", version="v2"),
                )
                await app.run_command("pods.other.example/v2")
                with pytest.raises(AppError, match="version is loading"):
                    app.plugins.capture_source()
                await asyncio.gather(*selections)
            await pilot.press("colon", *"ctx", "enter")
            assert app.state.view_kind == "contexts" and app.plugins.resource() is None
            assert app.plugins.bindings() == ()
            app.plugins.open("pod")
            await wait_for(lambda: plugin_tasks.latest.done())
            assert len(app.screen_stack) == 1 and "does not apply" in str(app.status.content)
            app.plugins.open()
            await wait_for(lambda: isinstance(app.screen, PluginCatalogue))
            await pilot.pause()
            assert app.screen.query_one("#plugin-catalogue").row_count == 1
            await pilot.press("enter")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.pause()
            values = app.screen.source.selection.values()
            assert (
                values["CONTEXT"] == "kuberich-test-one"
                and "NAME" not in values
                and "RESOURCE" not in values
            )
            assert app.screen.source.resource is None
            await pilot.press("escape")
