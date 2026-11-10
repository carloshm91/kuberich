"""Actual ordinary files, bounded local dependency closure and reviewed replacement."""

import os
import stat
import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.domain.manifests import ManifestSaveIntent
from kuberich.errors import AppError


def cancel():
    return threading.Event()


def fixtures(tmp_path):
    files = ManifestFiles(cwd=tmp_path)
    return files, files.root(Path("."), cancel=cancel())


def save_intent(files, root, path="source.yaml", body=b"new: content\n"):
    return ManifestSaveIntent(
        identity=uuid4(),
        original=files.read(root, path, cancel=cancel()),
        root=root,
        body=body,
        preview_pages=("safe",),
    )


def test_physical_root_captured_cwd_metadata_listing_and_parent_boundary(tmp_path, monkeypatch):
    source = tmp_path / "physical"
    source.mkdir()
    (source / "nested").mkdir()
    (source / "source.yaml").write_bytes(b"ordinary: data")
    (source / "kustomization.yaml").write_text("resources: []")
    (source / "ignored.txt").write_text("not listed")
    (source / "alias.yaml").symlink_to(source / "source.yaml")
    os.mkfifo(source / "pipe.yaml")
    (tmp_path / "alias").symlink_to(source, target_is_directory=True)
    files = ManifestFiles(cwd=tmp_path)
    root = files.root(Path("alias"), cancel=cancel())
    assert root.path == source
    monkeypatch.chdir("/")
    listing = files.list(root, "", cancel=cancel())
    assert not listing.limited and listing.skipped == 1
    assert {Path(entry.relative_path).name: entry.kind for entry in listing.entries} == {
        "nested": "directory",
        "source.yaml": "manifest",
        "kustomization.yaml": "kustomization",
        "alias.yaml": "unavailable",
        "pipe.yaml": "unavailable",
    }
    assert files.read(root, "source.yaml", cancel=cancel()).data == b"ordinary: data"
    assert files.list(root, "nested", cancel=cancel()).entries == ()
    for path in ("../source.yaml", "nested/../source.yaml", "/source.yaml", "a\\b", "bad\nname"):
        with pytest.raises(AppError):
            files.read(root, path, cancel=cancel())
    for path in ("alias.yaml", "pipe.yaml", ""):
        with pytest.raises(AppError):
            files.read(root, path, cancel=cancel())


def test_root_replacement_ancestor_symlink_and_post_read_mutation_are_refused(
    tmp_path, monkeypatch
):
    files, root = fixtures(tmp_path)
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/source.yaml").write_bytes(b"safe: old")
    snapshot = files.read(root, "nested/source.yaml", cancel=cancel())
    (tmp_path / "nested/source.yaml").write_bytes(b"safe: new")
    with pytest.raises(AppError):
        files.require_unchanged(root, (snapshot,), cancel=cancel())
    (tmp_path / "nested").rename(tmp_path / "moved")
    (tmp_path / "nested").symlink_to(tmp_path / "moved", target_is_directory=True)
    with pytest.raises(AppError):
        files.read(root, "nested/source.yaml", cancel=cancel())
    with pytest.raises(AppError):
        files.list(replace(root, inode=root.inode + 1), "", cancel=cancel())
    with pytest.raises(AppError):
        ManifestFiles(cwd=Path("relative"))
    with pytest.raises(AppError):
        files.root(Path("absent"), cancel=cancel())
    event = cancel()
    event.set()
    with pytest.raises(AppError, match="cancelled"):
        files.list(root, "", cancel=event)


def test_changed_during_actual_read_and_moved_directory_are_refused(tmp_path, monkeypatch):
    files, root = fixtures(tmp_path)
    (tmp_path / "nested").mkdir()
    path = tmp_path / "nested/source.yaml"
    path.write_bytes(b"ordinary: old")
    original = os.read
    changed = False

    def read(descriptor, count):
        nonlocal changed
        data = original(descriptor, count)
        if data and not changed and os.fstat(descriptor).st_ino == path.stat().st_ino:
            changed = True
            path.write_bytes(b"ordinary: changed-longer")
        return data

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(AppError):
        files.read(root, "nested/source.yaml", cancel=cancel())


def test_directory_capture_sorted_immediate_complete_and_unchanged(tmp_path):
    files, root = fixtures(tmp_path)
    (tmp_path / "z.yaml").write_bytes(b"z: 1")
    (tmp_path / "a.json").write_bytes(b'{"a":1}')
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested/no.yaml").write_bytes(b"not included")
    snapshots = files.capture(root, "", "directory", cancel=cancel())
    assert [snapshot.relative_path for snapshot in snapshots] == ["a.json", "z.yaml"]
    files.require_unchanged(root, snapshots, cancel=cancel())
    assert files.capture(root, "a.json", "file", cancel=cancel()) == (snapshots[0],)
    (tmp_path / "kustomization.yml").write_bytes(b"resources: []")
    with pytest.raises(AppError, match="Render Kustomize"):
        files.capture(root, "", "directory", cancel=cancel())
    (tmp_path / "empty").mkdir()
    with pytest.raises(AppError):
        files.capture(root, "empty", "directory", cancel=cancel())
    with pytest.raises(AppError):
        files.capture(root, "a.json", "invalid", cancel=cancel())


def test_nested_kustomize_closure_is_local_bounded_opaque_and_deduplicated(tmp_path):
    files, root = fixtures(tmp_path)
    for directory in ("base", "overlays/dev", "component"):
        (tmp_path / directory).mkdir(parents=True)
    (tmp_path / "base/kustomization.yaml").write_text(
        "resources: [resource.yaml]\nconfigMapGenerator:\n- name: data\n  files: [key=opaque.bin]\n"
    )
    (tmp_path / "base/resource.yaml").write_text(
        "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\n"
    )
    (tmp_path / "base/opaque.bin").write_bytes(b"\xff\x00opaque")
    (tmp_path / "component/kustomization.yaml").write_text(
        "apiVersion: kustomize.config.k8s.io/v1alpha1\nkind: Component\n"
    )
    (tmp_path / "overlays/dev/kustomization.yaml").write_text(
        "resources: [../../base, ../../base/resource.yaml]\ncomponents: [../../component]\npatches: [{path: patch.yaml}]\n"
    )
    (tmp_path / "overlays/dev/patch.yaml").write_text("kind: ConfigMap\nmetadata: {name: owned}\n")
    captured = files.capture(root, "overlays/dev", "kustomize", cancel=cancel())
    assert {item.relative_path for item in captured} == {
        "overlays/dev/kustomization.yaml",
        "overlays/dev/patch.yaml",
        "base/kustomization.yaml",
        "base/resource.yaml",
        "base/opaque.bin",
        "component/kustomization.yaml",
    }
    assert (
        next(item for item in captured if item.relative_path.endswith("opaque.bin")).data
        == b"\xff\x00opaque"
    )
    narrow = files.root(tmp_path / "overlays/dev", cancel=cancel())
    with pytest.raises(AppError, match="escapes"):
        files.capture(narrow, "", "kustomize", cancel=cancel())


@pytest.mark.parametrize(
    "content",
    [
        "resources: [https://example.invalid/base]",
        "resources: [github.com/team/repo]",
        "generators: [plugin.yaml]",
        "helmCharts: []",
        "resources: [../outside]",
        "resources: [.]",
    ],
)
def test_invalid_kustomize_dependency_is_refused_before_process_launch(tmp_path, content):
    files, root = fixtures(tmp_path)
    (tmp_path / "kustomization.yaml").write_text(content)
    with pytest.raises(AppError):
        files.capture(root, "", "kustomize", cancel=cancel())


def test_kustomize_refuses_ambiguous_config_missing_file_directory_role_and_component_file(
    tmp_path,
):
    files, root = fixtures(tmp_path)
    config = tmp_path / "kustomization.yaml"
    other = tmp_path / "kustomization.yml"
    config.write_text("resources: []")
    other.write_text("resources: []")
    with pytest.raises(AppError, match="exactly one"):
        files.capture(root, "", "kustomize", cancel=cancel())
    other.unlink()
    for text in (
        "resources: [missing.yaml]",
        "configurations: [directory]",
        "components: [data.txt]",
    ):
        config.write_text(text)
        (tmp_path / "directory").mkdir(exist_ok=True)
        (tmp_path / "data.txt").write_text("data")
        with pytest.raises(AppError):
            files.capture(root, "", "kustomize", cancel=cancel())


def test_source_and_listing_budgets_refuse_without_truncating_apply(tmp_path):
    files, root = fixtures(tmp_path)
    large = tmp_path / "large.yaml"
    with large.open("wb") as stream:
        stream.truncate(1024 * 1024 + 1)
    with pytest.raises(AppError):
        files.read(root, "large.yaml", cancel=cancel())
    large.unlink()
    for index in range(2049):
        (tmp_path / f"{index}.yaml").touch()
    assert files.list(root, "", cancel=cancel()).limited
    with pytest.raises(AppError):
        files.capture(root, "", "directory", cancel=cancel())


def test_reviewed_save_preserves_mode_raw_bytes_and_rejects_changed_or_hardlinked_source(tmp_path):
    files, root = fixtures(tmp_path)
    source = tmp_path / "source.yaml"
    source.write_bytes(b"old: raw\n")
    source.chmod(0o640)
    intent = save_intent(files, root, body=b"new: raw-sensitive-value\n")
    outcome = files.save(intent, cancel=cancel())
    assert source.read_bytes() == intent.body and stat.S_IMODE(source.stat().st_mode) == 0o640
    assert (
        outcome.effect == "published"
        and outcome.durable
        and outcome.cleanup_complete
        and outcome.ref is not None
    )
    assert outcome.ref.sha256 != intent.original.sha256
    assert not tuple(tmp_path.glob(".kuberich-manifest-*"))
    with pytest.raises(AppError):
        files.save(intent, cancel=cancel())
    os.link(source, tmp_path / "other.yaml")
    with pytest.raises(AppError):
        files.save(save_intent(files, root), cancel=cancel())
    (tmp_path / "other.yaml").unlink()
    event = cancel()
    event.set()
    with pytest.raises(AppError):
        files.save(save_intent(files, root), cancel=event)
    assert source.read_bytes() == intent.body


@pytest.mark.parametrize("after_commit", [False, True])
def test_save_failure_before_or_after_rename_retains_truthful_effect(
    tmp_path, monkeypatch, after_commit
):
    files, root = fixtures(tmp_path)
    source = tmp_path / "source.yaml"
    source.write_bytes(b"old: raw\n")
    intent = save_intent(files, root)
    original = os.fsync

    def fsync(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) == after_commit:
            raise OSError("synthetic fsync failure")
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", fsync)
    if after_commit:
        outcome = files.save(intent, cancel=cancel())
        assert (
            outcome.effect == "published"
            and not outcome.durable
            and outcome.cleanup_complete
            and "durability" in outcome.notice
        )
        assert source.read_bytes() == intent.body
    else:
        with pytest.raises(AppError):
            files.save(intent, cancel=cancel())
        assert source.read_bytes() == b"old: raw\n"
    assert not tuple(tmp_path.glob(".kuberich-manifest-*"))
