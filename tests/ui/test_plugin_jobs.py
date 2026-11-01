"""Opened job output follows completion without another selection or Enter."""

import sys
from types import SimpleNamespace

import pytest
from textual.app import App
from textual.widgets import Button, DataTable, Static

from kuberich.domain.processes import ProcessMode
from kuberich.ui.plugins import PluginJobs, PluginScreen
from tests.support.workspace import wait_for, workspace_api
from tests.ui.test_plugins import api, app_for, ns


@pytest.mark.asyncio
async def test_opened_background_output_updates_after_a_real_child_finishes(tmp_path):
    ready, release = tmp_path / "ready", tmp_path / "release"
    script = (
        "import sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text('ready')\n"
        "while not Path(sys.argv[2]).exists(): time.sleep(0.01)\n"
        "print('PLUGIN_BACKGROUND [red]literal[/red]')\n"
    )
    program = tmp_path / "held-output.py"
    program.write_text(script)
    definitions = {
        "work": {
            "command": sys.executable,
            "args": [str(program), str(ready), str(release)],
            "mode": "background",
            "dangerous": False,
            "trusted_read_only": True,
        }
    }
    async with workspace_api(ns, api) as url:
        app = app_for(tmp_path, url, definitions=definitions)
        async with app.run_test(size=(100, 35)) as pilot:
            await wait_for(lambda: app.resources.row_count == 1 and bool(app.plugins.plugins))
            await pilot.press("colon", *"plugin work", "enter")
            await wait_for(lambda: isinstance(app.screen, PluginScreen))
            await pilot.click("#plugin-review")
            await wait_for(lambda: not app.screen.query_one("#plugin-run", Button).disabled)
            await pilot.click("#plugin-run")
            await wait_for(ready.exists)
            job = app.plugins.manager.jobs[0]
            assert job.running and not job.output
            await pilot.press("escape", "colon", *"pluginjobs", "enter")
            await wait_for(lambda: isinstance(app.screen, PluginJobs))
            await pilot.press("enter")
            text = app.screen.query_one("#plugin-job-text", Static)
            assert "Running" in str(text.content)
            release.write_text("finish")
            await job.wait()
            assert job.status == "Succeeded" and job.returncode == 0
            await wait_for(lambda: "PLUGIN_BACKGROUND" in str(text.content))
            assert "Succeeded" in str(text.content) and "exit 0" in str(text.content)
        assert job.runner.active_count == 0


def job(number, output=""):
    return SimpleNamespace(
        number=number,
        name=f"job-{number}",
        mode=ProcessMode.BACKGROUND,
        status="Running",
        returncode=None,
        output=output,
    )


class JobApp(App):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def on_mount(self):
        self.push_screen(PluginJobs(self.manager))


@pytest.mark.asyncio
async def test_opened_identity_output_only_changes_and_retirement(monkeypatch):
    first, second = job(1, "first"), job(2, "second")
    manager = SimpleNamespace(jobs=[first, second])
    app = JobApp(manager)
    async with app.run_test(size=(100, 35)) as pilot:
        screen = app.screen
        table = screen.query_one(DataTable)
        text = screen.query_one("#plugin-job-text", Static)
        assert str(text.content) == ""
        await pilot.press("enter")
        assert "first" in str(text.content)
        await pilot.press("down")
        assert table.cursor_row == 1
        first.output = "changed without a status transition"
        first.returncode = 7
        screen.refresh_jobs()
        assert "changed without a status transition" in str(text.content)
        assert "exit 7" in str(text.content) and "second" not in str(text.content)
        assert table.cursor_row == 1
        assert str(table.get_row_at(0)[4]) == "7"
        first.output = "later output with the same status and exit"
        screen.refresh_jobs()
        assert "later output with the same status and exit" in str(text.content)
        assert table.cursor_row == 1
        updates = []
        original = text.update

        def update(value):
            updates.append(value)
            original(value)

        monkeypatch.setattr(text, "update", update)
        screen.refresh_jobs()
        screen.refresh_jobs()
        assert not updates
        await pilot.press("enter")
        assert "second" in str(text.content)
        manager.jobs.remove(second)
        screen.refresh_jobs()
        assert str(text.content) == "Job is no longer in history."
        assert "second" not in str(text.content)
        manager.jobs.clear()
        screen.refresh_jobs()
        assert table.row_count == 0 and screen.selected_job() is None
        await pilot.press("enter")
        assert str(text.content) == "Job is no longer in history."
