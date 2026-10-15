"""Explicit private writes retain the original settings, appearance and opaque fields."""

from dataclasses import replace

import pytest

from kuberich.config.navigation import NavigationPreferences, navigation_from
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.appearance import Appearance
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource


@pytest.mark.asyncio
async def test_explicit_navigation_save_migrates_and_composes_with_appearance(tmp_path):
    path = tmp_path / "preferences.yaml"
    original = parse_document(
        {
            "schema_version": 1,
            "read_only": False,
            "opaque": {"retained": True},
            "navigation": {"aliases": {"work": "pods"}},
            "appearance": {"check_updates": False},
        }
    )
    write_config(path, original)
    source = PreferenceSource(ConfigLocation(path, True), original, "textual-light")
    nav = navigation_from(original).with_view(
        "v1/pods", ViewSpec((ColumnSpec("name", 24, "center"),), "restarts", True), "demo"
    )
    await source.save_navigation(nav)
    saved = read_config(path)
    assert saved.unknown == original.unknown and saved.settings == original.settings
    assert saved.extensions["appearance"] == original.extensions["appearance"]
    assert navigation_from(saved) == replace(nav, migrated=False)
    assert saved.extensions["navigation"]["schema_version"] == 1
    await source.save(Appearance(), "kuberich-mono", None)
    assert navigation_from(read_config(path)) == replace(nav, migrated=False)
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
async def test_new_preferences_written_only_on_explicit_navigation_save(tmp_path):
    path = tmp_path / "new" / "preferences.yaml"
    source = PreferenceSource(ConfigLocation(path, False), ConfigDocument())
    assert not path.exists()
    await source.save_navigation(NavigationPreferences())
    assert navigation_from(read_config(path)) == NavigationPreferences()
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["competing", "legacy", "symlink", "invalid"])
async def test_navigation_save_refuses_competing_legacy_symlink_and_invalid_models(tmp_path, kind):
    path = tmp_path / "preferences.yaml"
    original = ConfigDocument(unknown={"original": True})
    write_config(path, original)
    source = PreferenceSource(
        ConfigLocation(path, True, tmp_path / "new" if kind == "legacy" else None), original
    )
    if kind == "competing":
        write_config(path, ConfigDocument(unknown={"foreign": True}), overwrite=True)
    elif kind == "symlink":
        actual = tmp_path / "original.yaml"
        path.rename(actual)
        path.symlink_to(actual)
    before = path.read_bytes()
    nav = (
        NavigationPreferences(aliases=(("po", "ns"),))
        if kind == "invalid"
        else NavigationPreferences()
    )
    with pytest.raises(AppError):
        await source.save_navigation(nav)
    assert path.read_bytes() == before and source.document == original


def test_startup_aliases_share_original_view_and_interactive_action_policy(
    tmp_path, monkeypatch, capsys
):
    from kuberich import cli
    from kuberich.services.commands import Command

    path = tmp_path / "preferences.yaml"
    write_config(
        path,
        parse_document(
            {
                "schema_version": 1,
                "navigation": {
                    "schema_version": 1,
                    "aliases": {"local": "views", "erase": "delete", "inspect": "columns c2"},
                },
            }
        ),
    )
    captured = []
    monkeypatch.setattr(
        cli, "run_terminal", lambda *a, **kw: captured.append(kw["initial_command"])
    )
    assert cli.main(["--config", str(path), "--command", "local"]) == 0
    assert captured == [Command.VIEWS]
    for action in ("erase", "inspect"):
        assert cli.main(["--config", str(path), "--command", action]) == 4
        assert "interactive resource selection" in capsys.readouterr().err
    assert captured == [Command.VIEWS]
