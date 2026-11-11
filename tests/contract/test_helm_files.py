"""Physical private input receipts fail closed before the native tool consumes bytes."""

import gc
import os
import shutil
from pathlib import Path

import pytest

from kuberich.adapters.helm_files import HelmCommandFiles
from kuberich.errors import AppError


@pytest.mark.parametrize(
    "change", ["contents", "replacement", "missing", "symlink", "fifo", "mode", "directory"]
)
def test_private_inputs_reject_content_physical_type_and_permission_drift(tmp_path, change):
    files = HelmCommandFiles(tmp_path, package=b"owned-package", values=b"private: owned\n")
    try:
        files.require_current()
        path = files.values
        assert path is not None
        if change == "contents":
            path.write_bytes(b"private: changed\n")
        elif change == "replacement":
            replacement = path.with_suffix(".new")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(path)
        elif change in {"missing", "symlink", "fifo"}:
            path.unlink()
            if change == "symlink":
                path.symlink_to(tmp_path / "outside-private-values")
            elif change == "fifo":
                os.mkfifo(path, 0o600)
        elif change == "mode":
            path.chmod(0o644)
        else:
            (files.path / "docker").chmod(0o755)
        with pytest.raises(AppError, match="Private Helm command") as error:
            files.require_current()
        assert "private: " not in str(error.value) and str(tmp_path) not in str(error.value)
    finally:
        root = files.path
        files.close()
    assert not root.exists()


def test_directory_symlink_cannot_reuse_original_private_input_inodes(tmp_path):
    files = HelmCommandFiles(tmp_path, package=b"owned-package")
    original = files.path / "docker"
    relocated = files.path / "relocated"
    original.rename(relocated)
    original.symlink_to(relocated, target_is_directory=True)
    try:
        with pytest.raises(AppError, match="directories changed"):
            files.require_current()
    finally:
        original.unlink()
        relocated.rename(original)
        files.close()


def test_private_input_read_is_bounded_and_rejects_a_concurrent_change(tmp_path, monkeypatch):
    files = HelmCommandFiles(tmp_path, package=b"owned-package", values=b"p" * 65537)
    read = os.read
    changed = False

    def changing(descriptor, size):
        nonlocal changed
        value = read(descriptor, size)
        if not changed and value == b"p" * 65536:
            changed = True
            assert files.values is not None
            files.values.write_bytes(b"q" * 65537)
        return value

    monkeypatch.setattr(os, "read", changing)
    try:
        with pytest.raises(AppError, match="inputs changed"):
            files.require_current()
        assert changed
    finally:
        files.close()
    oversized = HelmCommandFiles(tmp_path, package=b"p" * (16 * 1024 * 1024 + 1))
    try:
        with pytest.raises(AppError, match="exceeds its limit"):
            oversized.require_current()
    finally:
        oversized.close()


def test_partial_staging_failure_removes_already_created_private_inputs(tmp_path, monkeypatch):
    opening = os.open

    def refuse_values(path, flags, mode=0o777, **kwargs):
        if Path(path).name == "values.yaml":
            raise OSError("owned private staging refusal")
        return opening(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", refuse_values)
    with pytest.raises(OSError, match="staging refusal"):
        HelmCommandFiles(tmp_path, package=b"owned-package", values=b"private: owned\n")
    assert list(tmp_path.iterdir()) == []


def test_cleanup_refuses_replaced_root_and_has_no_deferred_deletion_finalizer(tmp_path):
    files = HelmCommandFiles(tmp_path, package=b"owned-package", values=b"private: owned\n")
    original_path = files.path
    retired = tmp_path / "retired-owned-inputs"
    original_path.rename(retired)
    original_path.mkdir(mode=0o700)
    sentinel = original_path / "replacement-sentinel"
    sentinel.write_text("replacement must survive")
    with pytest.raises(AppError, match="cleanup could not be verified") as error:
        files.close()
    assert str(tmp_path) not in str(error.value)
    assert sentinel.read_text() == "replacement must survive"
    assert (retired / "chart.tgz").read_bytes() == b"owned-package"
    del files
    gc.collect()
    assert sentinel.exists() and (retired / "values.yaml").exists()
    shutil.rmtree(original_path)
    shutil.rmtree(retired)


def test_verified_cleanup_is_idempotent_and_never_follows_inner_links(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("outside must survive")
    files = HelmCommandFiles(tmp_path, package=b"owned-package")
    (files.path / "cache" / "external-link").symlink_to(outside, target_is_directory=True)
    (files.path / "direct-link").symlink_to(outside, target_is_directory=True)
    files.close()
    files.close()
    assert not files.path.exists() and sentinel.read_text() == "outside must survive"


def test_missing_root_cleanup_is_unverified_and_can_resume_only_for_original_identity(tmp_path):
    files = HelmCommandFiles(tmp_path)
    retired = tmp_path / "retired-owned-inputs"
    files.path.rename(retired)
    with pytest.raises(AppError, match="cleanup could not be verified"):
        files.close()
    retired.rename(files.path)
    files.close()
    assert not files.path.exists()


def test_root_rename_during_cleanup_keeps_all_deletion_bound_to_original_descriptor(
    tmp_path, monkeypatch
):
    files = HelmCommandFiles(tmp_path, package=b"owned-package")
    retired = tmp_path / "retired-owned-inputs"
    sentinel = files.path / "replacement-sentinel"
    removing = shutil.rmtree
    replaced = False

    def replace_root(path, *, dir_fd):
        nonlocal replaced
        if not replaced:
            replaced = True
            files.path.rename(retired)
            files.path.mkdir(mode=0o700)
            sentinel.write_text("replacement must survive")
        removing(path, dir_fd=dir_fd)

    monkeypatch.setattr(shutil, "rmtree", replace_root)
    with pytest.raises(AppError, match="cleanup could not be verified"):
        files.close()
    assert replaced and sentinel.read_text() == "replacement must survive"
    assert list(retired.iterdir()) == []
    sentinel.unlink()
    files.path.rmdir()
    retired.rmdir()
