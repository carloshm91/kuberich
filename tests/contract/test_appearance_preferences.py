"""Actual explicit local saves preserve unrelated, legacy and competing preferences."""

from dataclasses import replace

import pytest

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings, parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.appearance import Appearance
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource


@pytest.mark.asyncio
async def test_global_and_context_saves_never_persist_runtime_overrides(tmp_path):
    path = tmp_path / "config.yaml"
    original = parse_document(
        {"schema_version": 1, "theme": "k9s", "read_only": False, "opaque": "retained"}
    )
    write_config(path, original)
    source = PreferenceSource(ConfigLocation(path, True), original, "textual-light")
    appearance = Appearance(check_updates=True)
    await source.save(appearance, "textual-dark", "demo-lab")
    saved = read_config(path)
    assert saved.settings.theme == "k9s" and not saved.settings.read_only
    assert saved.unknown == original.unknown
    assert saved.extensions["appearance"]["contexts"] == {"demo-lab": "textual-dark"}
    await source.save(
        replace(appearance, contexts=(("demo-lab", "textual-dark"),)), "kuberich-mono", None
    )
    assert read_config(path).settings.theme == "kuberich-mono"
    assert read_config(path).extensions["appearance"]["check_updates"]
    assert path.stat().st_mode & 0o777 == 0o600
    assert source.theme_override == "textual-light"


@pytest.mark.asyncio
async def test_missing_default_is_created_only_on_explicit_save(tmp_path):
    path = tmp_path / "new" / "config.yaml"
    source = PreferenceSource(ConfigLocation(path, False), ConfigDocument())
    assert not path.exists()
    await source.save(Appearance(), "k9s", None)
    assert path.exists() and path.parent.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["competing", "legacy", "symlink", "bad-theme", "bad-context"])
async def test_failed_save_retains_the_prior_document_and_never_overwrites_external_changes(
    tmp_path, problem
):
    path = tmp_path / "config.yaml"
    original = ConfigDocument(settings=Settings(theme="k9s"), unknown={"retained": True})
    write_config(path, original)
    location = ConfigLocation(path, True, tmp_path / "migrated" if problem == "legacy" else None)
    source = PreferenceSource(location, original)
    if problem == "competing":
        write_config(
            path, replace(original, settings=Settings(theme="textual-light")), overwrite=True
        )
    elif problem == "symlink":
        actual = tmp_path / "actual"
        path.rename(actual)
        path.symlink_to(actual)
    before = path.read_bytes()
    with pytest.raises(AppError):
        await source.save(
            Appearance(),
            "bad theme" if problem == "bad-theme" else "textual-dark",
            "bad\x1b" if problem == "bad-context" else None,
        )
    assert path.read_bytes() == before and source.document == original


@pytest.mark.asyncio
async def test_competing_theme_and_favorite_saves_are_serialized_without_lost_extensions(
    tmp_path, monkeypatch
):
    import asyncio

    from kuberich.config.navigation import NavigationPreferences
    from kuberich.services import appearance as module

    path = tmp_path / "preferences.yaml"
    original = parse_document({"schema_version": 1, "opaque": "retained"})
    write_config(path, original)
    source = PreferenceSource(ConfigLocation(path, True), original)
    entered, release = asyncio.Event(), asyncio.Event()
    worker = module.file_worker

    async def held(operation):
        entered.set()
        await release.wait()
        return await worker(operation)

    monkeypatch.setattr(module, "file_worker", held)
    theme = asyncio.create_task(source.save(Appearance(), "textual-light", None))
    await entered.wait()
    favorite = asyncio.create_task(
        source.save_navigation(NavigationPreferences().with_favorite("demo-lab", "team-a"))
    )
    await asyncio.sleep(0)
    assert not favorite.done()
    release.set()
    await theme
    with pytest.raises(AppError, match="another save"):
        await favorite
    assert source.document.settings.theme == "textual-light"
    assert "navigation" not in source.document.extensions
    assert read_config(path).unknown == original.unknown
    await source.save_navigation(NavigationPreferences().with_favorite("demo-lab", "team-a"))
    assert read_config(path).settings.theme == "textual-light"
    assert read_config(path).extensions["navigation"]["favorites"] == {"demo-lab": ["team-a"]}
