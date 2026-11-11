"""Actual files and owned threads bind user templates to the selected config root."""

import asyncio
import hashlib
import os
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.adapters.resource_templates import TemplateFiles
from kuberich.domain.manifests import canonical_manifest
from kuberich.domain.resource_templates import render_resource_template
from kuberich.errors import AppError
from kuberich.services.resource_templates import TemplateCatalogService


def template_data(identifier="owned-user", revision=1, extra=None):
    value = {
        "schema_version": 1,
        "kind": "ResourceTemplate",
        "id": identifier,
        "revision": revision,
        "title": "Owned user template",
        "parameters": {"name": {"type": "string", "required": True, "paths": ["/0/metadata/name"]}},
        "objects": [
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": ""},
                "data": {"synthetic": "template-catalog-private-value"},
            }
        ],
    }
    value.update(extra or {})
    return canonical_manifest(value)


def config_root(tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    templates = selected / "templates"
    templates.mkdir()
    return selected, templates


@pytest.mark.asyncio
async def test_explicit_lazy_catalog_uses_selected_config_parent_and_distinct_origins(
    tmp_path, monkeypatch
):
    selected, templates = config_root(tmp_path)
    (templates / "owned.yaml").write_bytes(template_data("configmap"))
    (templates / "ignored.txt").write_bytes(template_data("not-loaded"))
    other = tmp_path / "other"
    (other / "templates").mkdir(parents=True)
    (other / "templates/wrong.yaml").write_bytes(template_data("wrong-location"))
    service = TemplateCatalogService(Path("selected/preferences.yaml"), tmp_path)
    assert service.entries == () and service.operation_count == 0
    monkeypatch.chdir(other)
    entries = await service.load()
    assert len(entries) == 7
    users = [entry for entry in entries if entry.origin == "user"]
    assert len(users) == 1 and users[0].enabled
    user = users[0]
    assert user.relative_path == "templates/owned.yaml"
    assert user.identity == (
        "user",
        "configmap",
        1,
        hashlib.sha256(template_data("configmap")).hexdigest(),
    )
    assert any(entry.origin == "builtin" and entry.identity[1] == "configmap" for entry in entries)
    assert "template-catalog-private-value" not in repr(entries)
    await service.require_current(user)
    assert render_resource_template(user.template, {"name": "owned"})
    await service.require_current(next(entry for entry in entries if entry.origin == "builtin"))
    with pytest.raises(AppError, match="current"):
        await service.require_current(replace(user))
    old = user
    await service.load()
    with pytest.raises(AppError, match="current"):
        await service.require_current(old)
    await service.close()
    await service.close()
    assert service.operation_count == 0 and service.entries == ()
    with pytest.raises(AppError, match="closed"):
        await service.load()
    with pytest.raises(AppError, match="closed"):
        await service.require_current(old)
    assert selected.is_dir()


@pytest.mark.asyncio
async def test_absent_directories_do_not_create_config_or_template_paths(tmp_path):
    for path in (tmp_path / "missing/config.yaml", tmp_path / "config.yaml"):
        service = TemplateCatalogService(path, tmp_path)
        assert len(await service.load()) == 6
        await service.close()
    assert not (tmp_path / "missing").exists() and not (tmp_path / "templates").exists()


@pytest.mark.asyncio
async def test_invalid_and_duplicate_users_are_visible_disabled_without_builtin_shadowing(tmp_path):
    selected, templates = config_root(tmp_path)
    for name, data in {
        "a.yaml": template_data("configmap"),
        "b.yml": template_data("configmap"),
        "version.json": template_data("configmap", revision=2),
        "invalid.yaml": b"secret-value: [malformed-synthetic-secret-value",
        "kustomization.yaml": b"resources: [no-renderer]",
        "unsafe.yaml": b"!!python/object/apply:os.system ['must-not-run']",
    }.items():
        (templates / name).write_bytes(data)
    service = TemplateCatalogService(selected / "config.yaml", tmp_path)
    entries = await service.load()
    users = {entry.relative_path: entry for entry in entries if entry.origin == "user"}
    assert len(users) == 6
    for path in ("templates/a.yaml", "templates/b.yml"):
        assert not users[path].enabled and "Duplicate" in users[path].problem
    assert users["templates/version.json"].enabled
    assert all(
        "malformed-synthetic-secret-value" not in (entry.problem or "") for entry in users.values()
    )
    assert not users["templates/invalid.yaml"].enabled
    for entry in users.values():
        if not entry.enabled:
            with pytest.raises(AppError, match="enabled"):
                await service.require_current(entry)
    await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replacement", ["rewrite", "replace", "catalog-add", "template-directory", "root-directory"]
)
async def test_frozen_user_entries_refuse_changes_and_replacements(tmp_path, replacement):
    selected, templates = config_root(tmp_path)
    path = templates / "owned.yaml"
    path.write_bytes(template_data())
    service = TemplateCatalogService(selected / "config.yaml", tmp_path)
    user = next(entry for entry in await service.load() if entry.origin == "user")
    if replacement == "rewrite":
        path.write_bytes(template_data(extra={"description": "changed"}))
    elif replacement == "replace":
        path.unlink()
        path.write_bytes(template_data())
    elif replacement == "catalog-add":
        (templates / "added.yaml").write_bytes(template_data("other"))
    elif replacement == "template-directory":
        templates.rename(selected / "moved")
        templates.symlink_to(selected / "moved", target_is_directory=True)
    else:
        selected.rename(tmp_path / "moved-root")
        selected.mkdir()
    with pytest.raises(AppError):
        await service.require_current(user)
    await service.close()


@pytest.mark.asyncio
async def test_nonregular_symlink_and_oversized_files_are_not_opened_as_templates(tmp_path):
    selected, templates = config_root(tmp_path)
    (templates / "ordinary.yaml").write_bytes(template_data())
    (templates / "alias.yaml").symlink_to(templates / "ordinary.yaml")
    os.mkfifo(templates / "pipe.yml")
    (templates / "folder.json").mkdir()
    (templates / "oversized.yaml").write_bytes(b"x" * (1024 * 1024 + 1))
    service = TemplateCatalogService(selected / "config.yaml", tmp_path)
    users = {entry.relative_path: entry for entry in await service.load() if entry.origin == "user"}
    assert users["templates/ordinary.yaml"].enabled
    assert all(
        not entry.enabled for path, entry in users.items() if path != "templates/ordinary.yaml"
    )
    assert len(users) == 5
    await service.close()


@pytest.mark.parametrize("kind", ["symlink", "file", "fifo"])
def test_templates_directory_never_follows_an_entry_below_selected_root(tmp_path, kind):
    selected = tmp_path / "selected"
    selected.mkdir()
    target = selected / "templates"
    if kind == "symlink":
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        target.symlink_to(elsewhere, target_is_directory=True)
    elif kind == "file":
        target.write_bytes(b"not a directory")
    else:
        os.mkfifo(target)
    with pytest.raises(AppError, match="ordinary directory"):
        TemplateFiles(selected / "config.yaml", tmp_path).capture(cancel=threading.Event())


def test_template_capture_bounds_file_count_combined_bytes_and_config_listing(tmp_path):
    selected, templates = config_root(tmp_path)
    for index in range(257):
        (templates / f"{index}.yaml").write_bytes(b"x")
    files = TemplateFiles(selected / "config.yaml", tmp_path)
    with pytest.raises(AppError, match="256"):
        files.capture(cancel=threading.Event())
    for path in templates.iterdir():
        path.unlink()
    for index in range(9):
        (templates / f"{index}.yaml").write_bytes(b"x" * (1024 * 1024))
    with pytest.raises(AppError, match="8 MiB"):
        files.capture(cancel=threading.Event())
    for index in range(2049):
        (selected / f"irrelevant-{index}.txt").write_text("bounded")
    with pytest.raises(AppError, match="listing"):
        files.capture(cancel=threading.Event())


def test_selected_physical_parent_is_resolved_once_and_worker_cancellation_is_explicit(tmp_path):
    selected, templates = config_root(tmp_path)
    (templates / "owned.yaml").write_bytes(template_data())
    alias = tmp_path / "alias"
    alias.symlink_to(selected, target_is_directory=True)
    files = TemplateFiles(alias / "config.yaml", tmp_path)
    capture = files.capture(cancel=threading.Event())
    assert capture.root.path == selected
    alias.unlink()
    alias.mkdir()
    files.require_current(capture, cancel=threading.Event())
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(AppError, match="cancelled"):
        files.capture(cancel=cancelled)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "close"])
async def test_catalog_cancellation_drains_its_worker_before_returning(
    tmp_path, monkeypatch, action
):
    selected, _ = config_root(tmp_path)
    service = TemplateCatalogService(selected / "config.yaml", tmp_path)
    entered, exited = threading.Event(), threading.Event()

    def held(*, cancel):
        entered.set()
        assert cancel.wait(5)
        exited.set()
        raise AppError("Owned cancelled worker")

    monkeypatch.setattr(service.files, "capture", held)
    load = asyncio.create_task(service.load())
    assert await asyncio.to_thread(entered.wait, 5)
    assert service.operation_count == 1
    if action == "close":
        await service.close()
    else:
        load.cancel()
    with pytest.raises(asyncio.CancelledError):
        await load
    assert exited.is_set() and service.operation_count == 0
    await service.close()


@pytest.mark.asyncio
async def test_late_load_cannot_replace_a_newer_catalog_generation(tmp_path, monkeypatch):
    selected, _ = config_root(tmp_path)
    service = TemplateCatalogService(selected / "config.yaml", tmp_path)
    original = service.files.capture
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def held(*, cancel):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            assert release.wait(5)
        return original(cancel=cancel)

    monkeypatch.setattr(service.files, "capture", held)
    old = asyncio.create_task(service.load())
    assert await asyncio.to_thread(entered.wait, 5)
    current = await service.load()
    release.set()
    with pytest.raises(AppError, match="changed"):
        await old
    assert service.entries is current
    await service.close()
