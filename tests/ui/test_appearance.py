"""Actual theme preview, persistence, context precedence and offline About UI."""

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Button, Static

from kuberich.cli import main
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.config.store import read_config, write_config
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.services.updates import UpdateService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.appearance import AboutScreen, ThemeScreen
from tests.contract.test_updates import releases
from tests.support.connections import catalog_fixture
from tests.support.workspace import wait_for
from tests.unit.test_appearance import PALETTE


def owned_app(
    tmp_path, *, raw=None, override=None, catalog=None, updates=None, initial=Command.EMPTY
):
    document = parse_document({"schema_version": 1, "opaque": "retained", **(raw or {})})
    path = tmp_path / "preferences.yaml"
    write_config(path, document)
    source = PreferenceSource(ConfigLocation(path, True), document, override)
    app = KubeRichApp(
        replace(document.settings, theme=override or document.settings.theme),
        logging.Logger("owned-themes", level=100),
        catalog=catalog,
        preferences=source,
        updates=updates,
        initial_command=initial,
    )
    return app, path


async def open_themes(app, pilot):
    app._submit_command(":themes")
    await wait_for(lambda: isinstance(app.screen, ThemeScreen))
    await pilot.pause()
    return app.screen


def choose(screen, name):
    screen.table.move_cursor(row=screen.names.index(name))


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (40, 12)])
async def test_live_custom_and_mono_preview_cancel_explicit_global_save_and_small_about(
    tmp_path, size, monkeypatch
):
    monkeypatch.delenv("NO_COLOR", raising=False)
    raw = {"appearance": {"themes": {"ocean": PALETTE}}}
    app, path = owned_app(tmp_path, raw=raw)
    original = path.read_bytes()
    async with app.run_test(size=size) as pilot:
        screen = await open_themes(app, pilot)
        assert app.focused is screen.table
        assert screen.query_one("#theme-context", Button).disabled
        choose(screen, "ocean")
        await wait_for(lambda: app.theme == "ocean")
        assert path.read_bytes() == original and "Preview: ocean" in str(screen.status.content)
        assert "Selected" in screen.table.get_row("ocean")
        await pilot.pause()
        assert screen.table.scrollable_content_region.height - screen.table.header_height >= 1
        assert "off" in str(screen.check.label)
        evidence = Path("artifacts/ui").resolve()
        evidence.mkdir(parents=True, exist_ok=True)
        app.save_screenshot(filename=f"theme-ocean-{size[0]}.svg", path=str(evidence))
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert app.theme == "k9s" and path.read_bytes() == original
        screen = await open_themes(app, pilot)
        choose(screen, "kuberich-mono")
        await wait_for(lambda: app.theme == "kuberich-mono")
        await pilot.click("#theme-global")
        await wait_for(lambda: screen._save_task is not None and screen._save_task.done())
        assert read_config(path).settings.theme == "kuberich-mono"
        assert read_config(path).unknown == {"opaque": "retained"}
        assert "effective theme: kuberich-mono" in str(screen.status.content)
        await pilot.click("#theme-back")
        assert app.theme == "kuberich-mono"
        app._submit_command(":about")
        await wait_for(lambda: isinstance(app.screen, AboutScreen))
        await pilot.pause()
        about = app.screen
        assert "KubeRich" in str(about.content.content) and "Apache-2.0" in str(
            about.content.content
        )
        assert "disabled" in str(about.content.content)
        assert about.query_one("#about-back", Button).region.bottom <= size[1]
        await pilot.press("pagedown", "end")
        if size[1] == 12:
            assert about.query_one("#about-scroll").scroll_y > 0
        app.save_screenshot(filename=f"themes-about-{size[0]}.svg", path=str(evidence))
        await pilot.click("#about-back")
        assert app.focused is app.resources
    assert app._update_task is None


@pytest.mark.asyncio
async def test_context_and_environment_precedence_apply_without_starting_authentication(tmp_path):
    catalog = catalog_fixture(tmp_path, "http://127.0.0.1:1")
    raw = {"appearance": {"contexts": {"kuberich-test-one": "textual-light"}}}
    app, path = owned_app(tmp_path, raw=raw, catalog=catalog, initial=Command.THEMES)
    async with app.run_test() as pilot:
        await wait_for(lambda: isinstance(app.screen, ThemeScreen))
        await pilot.pause()
        assert app._connection_task is None and app.theme == "textual-light"
        screen = app.screen
        choose(screen, "kuberich-mono")
        await wait_for(lambda: app.theme == "kuberich-mono")
        await pilot.click("#theme-context")
        await wait_for(lambda: screen._save_task is not None and screen._save_task.done())
        saved = read_config(path)
        assert saved.settings.theme == "k9s"
        assert saved.extensions["appearance"]["contexts"]["kuberich-test-one"] == "kuberich-mono"
        await pilot.press("escape")
        app._apply_theme("kuberich-test-Two")
        assert app.theme == "k9s"
        app._apply_theme("kuberich-test-one")
        assert app.theme == "kuberich-mono"
        app._theme_override = "textual-dark"
        app._apply_theme()
        assert app.theme == "textual-dark"
        screen = await open_themes(app, pilot)
        choose(screen, "textual-light")
        await pilot.pause()
        await pilot.click("#theme-global")
        await wait_for(lambda: screen._save_task is not None and screen._save_task.done())
        assert app.theme == "textual-dark" and read_config(path).settings.theme == "textual-light"
        assert "environment > context > global" in str(screen.status.content)


@pytest.mark.asyncio
async def test_invalid_override_recovers_and_cannot_overwrite_the_broken_file(tmp_path, capsys):
    raw = {
        "theme": "missing",
        "appearance": {"themes": {"bad": {**PALETTE, "foreground": "#000000"}}},
    }
    app, path = owned_app(tmp_path, raw=raw)
    original = path.read_bytes()
    assert app.theme == "k9s" and app._appearance_warning
    assert main(["--config", str(path), "config", "check"]) != 0
    assert "contrast" in capsys.readouterr().err
    async with app.run_test() as pilot:
        screen = await open_themes(app, pilot)
        assert screen.query_one("#theme-global", Button).disabled
        choose(screen, "textual-light")
        await wait_for(lambda: app.theme == "textual-light")
        with pytest.raises(AppError, match="Correct appearance"):
            await app._save_theme("textual-dark", None, False)
        await pilot.press("escape")
        assert app.theme == "k9s" and path.read_bytes() == original
    assert main(["--config", str(path), "info"]) == 0
    assert "opaque" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_competing_file_save_error_keeps_preview_usable_and_cancel_restores(tmp_path):
    app, path = owned_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await open_themes(app, pilot)
        choose(screen, "textual-light")
        await pilot.pause()
        write_config(
            path,
            replace(read_config(path), settings=Settings(theme="textual-dark")),
            overwrite=True,
        )
        before = path.read_bytes()
        await pilot.click("#theme-global")
        await wait_for(lambda: "changed on disk" in str(screen.status.content))
        assert app.theme == "textual-light" and path.read_bytes() == before
        await pilot.press("escape")
        assert app.theme == "k9s"


@pytest.mark.asyncio
async def test_optin_is_required_and_about_updates_after_verified_async_notice(tmp_path):
    async with releases(hold=True) as (url, seen, started, stop):
        service = UpdateService("0.1.0", tmp_path / "cache", endpoint=url)
        app, _ = owned_app(tmp_path, updates=service)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not seen and app._update_task is None
            screen = await open_themes(app, pilot)
            screen.check.value = True
            await pilot.press("escape")
            assert not seen
            screen = await open_themes(app, pilot)
            screen.check.value = True
            await pilot.click("#theme-global")
            await asyncio.wait_for(started.wait(), 5)
            await wait_for(lambda: screen._save_task.done())
            await pilot.press("escape")
            app.action_about()
            await wait_for(lambda: isinstance(app.screen, AboutScreen))
            about = app.screen
            stop.set()
            await wait_for(lambda: app.update_result.release is not None)
            assert "0.2.0" in str(about.content.content)
            assert "0.2.0" in str(app.header.query_one("#build-info", Static).content)
            await pilot.press("escape")
            screen = await open_themes(app, pilot)
            screen.check.value = False
            await pilot.click("#theme-global")
            await wait_for(lambda: not app.appearance.check_updates)
            assert app.update_result.release is None
            assert "↑" not in str(app.header.query_one("#build-info", Static).content)
        assert app._update_task.done()


@pytest.mark.asyncio
async def test_exit_drains_a_pending_release_request_and_does_not_publish_late_notice(tmp_path):
    async with releases(hold=True) as (url, seen, started, _):
        app, _ = owned_app(
            tmp_path,
            raw={"appearance": {"check_updates": True}},
            updates=UpdateService("0.1.0", tmp_path / "cache", endpoint=url),
            initial=Command.ABOUT,
        )
        async with app.run_test():
            await asyncio.wait_for(started.wait(), 5)
            assert len(seen) == 1
        assert (
            app._updates_stopped and app._update_task.done() and app.update_result.release is None
        )


@pytest.mark.asyncio
async def test_direct_embedded_app_cannot_write_preferences_and_unknown_global_recovers(tmp_path):
    app = KubeRichApp(Settings(theme="unknown"), logging.Logger("themes", level=100))
    async with app.run_test() as pilot:
        screen = await open_themes(app, pilot)
        assert app.theme == "k9s" and screen.query_one("#theme-global", Button).disabled
        with pytest.raises(AppError, match="CLI"):
            await app._save_theme("k9s", None, False)
        await pilot.press("escape")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_save_refuses_missing_theme_and_changed_context_before_writing(tmp_path):
    app, path = owned_app(tmp_path)
    async with app.run_test():
        original = path.read_bytes()
        for name, context in [("missing", None), ("k9s", "not-current")]:
            with pytest.raises(AppError, match="changed"):
                await app._save_theme(name, context, False)
        assert path.read_bytes() == original


@pytest.mark.asyncio
async def test_requested_save_is_drained_on_exit_and_escape_does_not_detach_it(
    tmp_path, monkeypatch
):
    import threading

    from kuberich.services import appearance

    entered, released, finished = threading.Event(), threading.Event(), threading.Event()
    ready, exit_owner = asyncio.Event(), asyncio.Event()
    real_write = appearance.write_config
    app, path = owned_app(tmp_path)

    def held_write(*args, **kwargs):
        entered.set()
        try:
            assert released.wait(10)
            real_write(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(appearance, "write_config", held_write)

    async def trial():
        async with app.run_test() as pilot:
            screen = await open_themes(app, pilot)
            choose(screen, "textual-light")
            await pilot.pause()
            await pilot.click("#theme-global")
            await wait_for(entered.is_set)
            await pilot.press("escape")
            assert app.screen is screen and "Wait for" in str(screen.status.content)
            ready.set()
            await exit_owner.wait()

    owner = asyncio.create_task(trial())
    try:
        await asyncio.wait_for(ready.wait(), 5)
        exit_owner.set()
        await asyncio.sleep(0.02)
        assert not owner.done() and not finished.is_set()
        released.set()
        await asyncio.wait_for(owner, 5)
        assert finished.is_set() and read_config(path).settings.theme == "textual-light"
    finally:
        released.set()
        exit_owner.set()
        await owner


@pytest.mark.asyncio
async def test_reenable_waits_for_cancelled_request_cleanup_and_then_checks_again(tmp_path):
    async with releases(hold=True) as (url, seen, started, stop):
        app, _ = owned_app(
            tmp_path,
            raw={"appearance": {"check_updates": True}},
            updates=UpdateService("0.1.0", tmp_path / "cache", endpoint=url),
        )
        async with app.run_test():
            await asyncio.wait_for(started.wait(), 5)
            old = app._update_task
            app.appearance = replace(app.appearance, check_updates=False)
            app._start_update_check()
            app.appearance = replace(app.appearance, check_updates=True)
            app._start_update_check()
            stop.set()
            await wait_for(lambda: app.update_result.release is not None)
            assert old.done() and app._update_task is not old and len(seen) == 2


@pytest.mark.asyncio
async def test_notice_during_child_before_parent_teardown_does_not_query_detached_widgets(tmp_path):
    async with releases(hold=True) as (url, _, started, stop):
        app, _ = owned_app(
            tmp_path,
            raw={"appearance": {"check_updates": True}},
            updates=UpdateService("0.1.0", tmp_path / "cache", endpoint=url),
            initial=Command.ABOUT,
        )
        async with app.run_test() as pilot:
            await asyncio.wait_for(started.wait(), 5)
            await pilot.pause()
            about = app.screen
            await app._build_info.remove()
            await about.content.remove()
            stop.set()
            await wait_for(lambda: app.update_result.release is not None)
            await pilot.pause()
            assert app.is_running and app._update_task.done()


@pytest.mark.asyncio
async def test_inverted_session_is_runtime_only_and_retains_status_words(tmp_path):
    from kuberich.ui.presentation import Presentation

    app, path = owned_app(tmp_path)
    original = path.read_bytes()
    app = KubeRichApp(
        Settings(),
        logging.Logger("inverted", level=100),
        presentation=Presentation(invert=True),
        preferences=app.preferences,
    )
    async with app.run_test(size=(40, 12)) as pilot:
        assert not app.current_theme.dark and app.current_theme.background == "#ffffff"
        assert "inverted" in app.chrome.build and path.read_bytes() == original
        screen = await open_themes(app, pilot)
        choose(screen, "textual-light")
        await wait_for(lambda: app.theme == "textual-light")
        assert app.current_theme.dark
        await pilot.press("escape")
        assert app.theme == "k9s" and path.read_bytes() == original


@pytest.mark.asyncio
async def test_about_identifies_verified_cached_release_without_a_network_request(tmp_path):
    import time

    from kuberich.domain.releases import release_record
    from kuberich.services.updates import write_cache
    from tests.unit.test_releases import release

    cache = tmp_path / "cache"
    write_cache(cache, release_record(release()), time.time())
    service = UpdateService("0.1.0", cache, endpoint="http://127.0.0.1:1/never-needed")
    app, _ = owned_app(
        tmp_path,
        raw={"appearance": {"check_updates": True}},
        updates=service,
        initial=Command.ABOUT,
    )
    async with app.run_test():
        await wait_for(lambda: app.update_result.cached)
        assert "cached within 24 hours" in str(app.screen.content.content)
