"""Reviewed kubeconfig saves: backup first, atomic replace, no silent overwrite."""

import os
import stat
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from kuberich.adapters.kubeconfig_files import read_documents, save_plan
from kuberich.domain.kubeconfig_edit import ContextChange, plan_context_edit
from kuberich.errors import AppError

NOW = datetime(2026, 10, 19, 10, 0, 0, 123456)


def kubeconfig(path: Path, *contexts: str, current: str | None = None, comment: bool = False):
    data = {
        "apiVersion": "v1",
        "kind": "Config",
        "contexts": [{"name": name, "context": {"cluster": "owned"}} for name in contexts],
        "clusters": [{"name": "owned", "cluster": {"server": "https://127.0.0.1:1"}}],
        "users": [{"name": "owned", "user": {"token": "synthetic-secret"}}],
    }
    if current:
        data["current-context"] = current
    text = yaml.safe_dump(data, sort_keys=False)
    path.write_text(("# owned comment\n" if comment else "") + text)
    path.chmod(0o640)
    return path


def plan_for(paths, change, name, new_name=None):
    return plan_context_edit(read_documents(paths), change, name, new_name)


def backups(directory: Path):
    return sorted(directory.glob("*.kuberich-*.bak"))


def test_read_skips_missing_files_and_notices_comments(tmp_path):
    first = kubeconfig(tmp_path / "first", "alpha", comment=True)
    documents = read_documents([tmp_path / "missing", first])
    assert [document.path for document in documents] == [first]
    assert documents[0].commented and len(documents[0].digest) == 64


def test_rename_writes_backup_then_replaces_file_and_keeps_mode(tmp_path):
    path = kubeconfig(tmp_path / "config", "alpha", "beta", current="alpha", comment=True)
    original = path.read_bytes()
    backup = save_plan(plan_for([path], ContextChange.RENAME, "alpha", "short"), NOW)
    assert backup == tmp_path / "config.kuberich-20261019T100000123456.bak"
    assert backup.read_bytes() == original
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    saved = yaml.safe_load(path.read_text())
    assert [entry["name"] for entry in saved["contexts"]] == ["short", "beta"]
    assert saved["current-context"] == "short"
    assert saved["users"] == [{"name": "owned", "user": {"token": "synthetic-secret"}}]
    assert not list(tmp_path.glob(".kuberich-*.tmp"))


def test_symbolic_links_are_kept_and_the_target_file_is_edited(tmp_path):
    real = kubeconfig(tmp_path / "real-config", "alpha", "beta")
    link = tmp_path / "config"
    link.symlink_to(real)
    backup = save_plan(plan_for([link], ContextChange.DELETE, "beta"), NOW)
    assert link.is_symlink() and backup.parent == tmp_path
    assert backup.name.startswith("real-config.kuberich-")
    assert [entry["name"] for entry in yaml.safe_load(real.read_text())["contexts"]] == ["alpha"]


def test_changed_file_is_never_overwritten_and_leaves_no_backup(tmp_path):
    path = kubeconfig(tmp_path / "config", "alpha", "beta")
    plan = plan_for([path], ContextChange.DELETE, "beta")
    kubeconfig(path, "alpha", "beta", "gamma")
    changed = path.read_bytes()
    with pytest.raises(AppError, match="changed after review"):
        save_plan(plan, NOW)
    assert path.read_bytes() == changed and backups(tmp_path) == []


def test_change_between_backup_and_replace_is_detected(tmp_path, monkeypatch):
    path = kubeconfig(tmp_path / "config", "alpha", "beta")
    plan = plan_for([path], ContextChange.DELETE, "beta")
    original = os.fsync
    calls = []

    def concurrent_edit(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:  # after the backup, while the replacement is staged
            kubeconfig(path, "alpha", "beta", "late")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", concurrent_edit)
    with pytest.raises(AppError, match="changed after review"):
        save_plan(plan, NOW)
    assert "late" in path.read_text() and backups(tmp_path) == []


def test_existing_backup_name_is_never_replaced_or_removed(tmp_path):
    path = kubeconfig(tmp_path / "config", "alpha", "beta")
    existing = tmp_path / "config.kuberich-20261019T100000123456.bak"
    existing.write_text("someone else's file")
    with pytest.raises(AppError, match="Cannot save"):
        save_plan(plan_for([path], ContextChange.DELETE, "beta"), NOW)
    assert existing.read_text() == "someone else's file"
    assert "beta" in path.read_text()


def test_unwritable_directory_reports_a_local_error(tmp_path):
    directory = tmp_path / "locked"
    directory.mkdir()
    path = kubeconfig(directory / "config", "alpha", "beta")
    plan = plan_for([path], ContextChange.DELETE, "beta")
    directory.chmod(0o500)
    try:
        if os.access(directory, os.W_OK):
            pytest.skip("The test user can write to read-only directories.")
        with pytest.raises(AppError, match="Cannot save"):
            save_plan(plan, NOW)
    finally:
        directory.chmod(0o700)
    assert "beta" in path.read_text()


def test_unrepresentable_document_is_refused_before_any_write(tmp_path):
    path = kubeconfig(tmp_path / "config", "alpha", "beta")
    plan = plan_for([path], ContextChange.DELETE, "beta")
    plan.document["extensions"] = [object()]
    with pytest.raises(AppError, match="safe YAML"):
        save_plan(plan, NOW)
    assert backups(tmp_path) == []


def test_durability_failure_after_commit_is_reported_honestly(tmp_path, monkeypatch):
    path = kubeconfig(tmp_path / "config", "alpha", "beta")
    plan = plan_for([path], ContextChange.DELETE, "beta")

    original = os.fsync

    def broken(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("owned fsync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", broken)
    with pytest.raises(AppError, match="durability"):
        save_plan(plan, NOW)
    assert "beta" not in path.read_text() and len(backups(tmp_path)) == 1


def test_unreadable_file_is_a_local_error(tmp_path, monkeypatch):
    import kuberich.adapters.kubeconfig_files as files

    path = kubeconfig(tmp_path / "config", "alpha")

    def denied(_):
        raise PermissionError("owned denial")

    monkeypatch.setattr(files, "regular_bytes", denied)
    with pytest.raises(AppError, match="Cannot read kubeconfig"):
        read_documents([path])
