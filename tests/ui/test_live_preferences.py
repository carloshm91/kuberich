"""Preference changes reload while the app runs; invalid files keep the last valid set."""

import logging

import pytest

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.views import ViewStatus
from kuberich.services.access import Action
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture
from tests.support.custom import CustomAPI, custom_api
from tests.support.workspace import wait_for
from tests.unit.test_appearance import PALETTE

GLASS = {"themes": {"glass": {**PALETTE, "background": "default"}}}


def owned_app(tmp_path, raw, *, url="http://127.0.0.1:1", initial=Command.EMPTY, **source):
    path = tmp_path / "preferences.yaml"
    write_config(path, parse_document({"schema_version": 1, **raw}))
    document = read_config(path)
    preferences = PreferenceSource(ConfigLocation(path, True), document, **source)
    app = KubeRichApp(
        preferences.settings(document),
        logging.Logger("live-preferences", level=100),
        preferences=preferences,
        catalog=catalog_fixture(tmp_path, url),
        initial_command=initial,
    )
    notes: list[tuple[str, str]] = []
    app.notify = lambda message, *, severity="information", **_: notes.append(  # type: ignore[method-assign]
        (message, severity)
    )
    return app, path, notes


def save(path, raw):
    write_config(path, parse_document({"schema_version": 1, **raw}), overwrite=True)


async def command(app, pilot, value):
    await pilot.press("colon")
    app.command_input.value = value
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_valid_reload_applies_every_section_and_keeps_the_current_view(tmp_path):
    app, path, notes = owned_app(tmp_path, {})
    async with app.run_test() as pilot:
        await app.live_preferences.check()
        assert notes == []
        app.filter_input.value = "keep"
        save(
            path,
            {
                "theme": "glass",
                "legacy": 1,
                "appearance": {**GLASS, "full_gvr_titles": True},
                "navigation": {"aliases": {"work": "pods"}},
                "jumps": {"definitions": {"nodes": {"source": "v1/pods", "target": "v1/nodes"}}},
                "context_settings": {
                    "contexts": {"kuberich-test-one": {"read_only": True, "refresh_seconds": 9}}
                },
            },
        )
        await app.live_preferences.check()
        assert notes == [
            (
                "Preferences reloaded. Unsupported preference fields are kept but ignored: legacy.",
                "information",
            )
        ]
        assert app.theme == "glass" and app.current_theme.ansi
        assert app.current_theme.background == "ansi_default"
        assert app.appearance.full_gvr_titles and app.jumps.names == ("nodes",)
        assert app.commands.resolve("work") is Command.PODS
        assert app.commands.policy.read_only and app.live_preferences.refresh_seconds == 9
        assert app.filter_input.value == "keep"
        with pytest.raises(Exception, match="Read-only mode blocks"):
            app.commands.policy.require(Action.MUTATE)
        await command(app, pilot, "ctx kuberich-test-Two")
        await wait_for(lambda: app.live_preferences.refresh_seconds == 2)
        assert not app.commands.policy.read_only
        save(path, {"theme": "k9s"})
        await app.live_preferences.check()
        assert app.theme == "k9s" and "glass" not in app.available_themes
        assert app.jumps.names == () and app.commands.resolve("work") is Command.UNAVAILABLE


@pytest.mark.asyncio
async def test_invalid_reload_keeps_the_last_valid_preferences_and_reports_once(tmp_path):
    app, path, notes = owned_app(tmp_path, {"appearance": GLASS, "theme": "glass"})
    async with app.run_test():
        await app.live_preferences.check()
        document = app.preferences.document
        path.write_text(
            "schema_version: 1\ncontext_settings:\n  contexts:\n    a: {read_only: false}\n"
        )
        await app.live_preferences.check()
        await app.live_preferences.check()
        assert notes == [
            (
                "Preferences were not reloaded: A context can set read_only: true; it cannot"
                " turn read-only off. The last valid preferences remain active.",
                "warning",
            )
        ]
        assert app.preferences.document is document and app.theme == "glass"
        path.unlink()
        await app.live_preferences.check()
        assert app.preferences.document is document and len(notes) == 1
        save(
            path,
            {
                "read_only": True,
                "appearance": GLASS,
                "theme": "glass",
                "navigation": {"keys": {"resources": {"first": "H"}}},
            },
        )
        await app.live_preferences.check()
        assert notes[-1][0] == (
            "Preferences reloaded. Key binding and mouse changes apply after restart."
        )
        assert app.commands.policy.read_only
        save(path, {"read_only": False, "appearance": GLASS, "theme": "glass"})
        await app.live_preferences.check()
        assert app.commands.policy.read_only, "a reload never lifts read-only mode"
        assert app.preferences.document.settings.read_only is False
        save(path, {})
        await wait_for(lambda: app.theme == "k9s")
        assert notes[-1] == ("Preferences reloaded.", "information")


@pytest.mark.asyncio
async def test_startup_reports_invalid_and_unsupported_sections_without_a_second_notice(tmp_path):
    raw = {"other": True, "context_settings": {"contexts": {"kuberich-test-one": {}}}}
    app, _path, notes = owned_app(tmp_path, raw)
    async with app.run_test():
        await app.live_preferences.check()
    assert notes == [
        (
            "Each context accepts only read_only and refresh_seconds."
            " Run kuberich config check; working defaults retained.",
            "warning",
        ),
        ("Unsupported preference fields are kept but ignored: other.", "information"),
    ]
    assert not app.commands.policy.read_only


@pytest.mark.asyncio
async def test_flags_and_environment_keep_precedence_over_context_refresh(tmp_path):
    raw = {"context_settings": {"contexts": {"kuberich-test-one": {"refresh_seconds": 9}}}}
    app, path, _notes = owned_app(
        tmp_path,
        raw,
        theme_override="textual-dark",
        overrides={"refresh_seconds": 1.0},
        environment={"KUBERICH_READONLY": "false"},
    )
    async with app.run_test():
        assert app.live_preferences.refresh_seconds == 1.0
        save(path, {**raw, "refresh_seconds": 30, "read_only": True, "theme": "textual-light"})
        await app.live_preferences.check()
        assert app.live_preferences.refresh_seconds == 1.0 and app.theme == "textual-dark"
        assert not app.commands.policy.read_only


@pytest.mark.asyncio
async def test_an_embedded_app_without_a_preference_file_does_not_watch_files():
    app = KubeRichApp(Settings(), logging.Logger("embedded", level=100))
    async with app.run_test():
        await app.live_preferences.check()
        assert app.live_preferences.refresh_seconds == 2.0 and app.preferences is None
        await app.live_preferences.close()


@pytest.mark.asyncio
async def test_full_titles_show_the_api_version_of_built_in_views(tmp_path):
    async with custom_api(CustomAPI(core_pods=True)) as (url, _owner):
        raw = {
            "appearance": {"full_gvr_titles": True},
            "context_settings": {"contexts": {"kuberich-test-one": {"refresh_seconds": 9}}},
        }
        app, path, _notes = owned_app(tmp_path, raw, url=url, initial=Command.PODS)
        async with app.run_test():
            await wait_for(lambda: app.live_preferences.refresh_seconds == 9)
            view = app.query_one("#resource-view")
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and "· v1 · live" in str(view.border_title)
                )
            )
            columns = {"columns": [{"key": "name"}, {"key": "age"}]}
            save(path, {**raw, "navigation": {"schema_version": 1, "views": {"v1/pods": columns}}})
            await app.live_preferences.check()
            await wait_for(lambda: [c.value for c in app.resources.columns] == ["name", "age"])
