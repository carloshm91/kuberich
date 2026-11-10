"""Boundary and cleanup faults that must remain visible without raw source details."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from kuberich.adapters.kustomize import KustomizeRenderer
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from tests.contract.test_kustomize_renderer import capture, helper
from tests.contract.test_manifest_files import cancel, fixtures, save_intent


def test_moved_ancestor_during_read_cannot_publish_from_detached_directory(tmp_path, monkeypatch):
    files, root = fixtures(tmp_path)
    directory = tmp_path / "nested"
    directory.mkdir()
    path = directory / "source.yaml"
    path.write_bytes(b"ordinary: old")
    inode = path.stat().st_ino
    original = os.read
    moved = False

    def read(descriptor, count):
        nonlocal moved
        data = original(descriptor, count)
        if data and not moved and os.fstat(descriptor).st_ino == inode:
            moved = True
            directory.rename(tmp_path / "detached")
            directory.mkdir()
            path.write_bytes(b"ordinary: replacement")
        return data

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(AppError):
        files.read(root, "nested/source.yaml", cancel=cancel())
    assert moved and path.read_bytes() == b"ordinary: replacement"


@pytest.mark.parametrize("budget", ["files", "bytes", "depth"])
def test_kustomize_closure_enforces_cumulative_file_byte_and_depth_bounds(tmp_path, budget):
    files, root = fixtures(tmp_path)
    if budget == "depth":
        (tmp_path / "kustomization.yaml").write_text(
            "resources: [" + "/".join(["nested"] * 33) + "]"
        )
    else:
        count = 257 if budget == "files" else 9
        names = [f"source-{index}.yaml" for index in range(count)]
        (tmp_path / "kustomization.yaml").write_text("resources: [" + ", ".join(names) + "]")
        for name in names:
            with (tmp_path / name).open("wb") as stream:
                stream.truncate(1024 * 1024 if budget == "bytes" else 1)
    with pytest.raises(AppError):
        files.capture(root, "", "kustomize", cancel=cancel())


def test_kustomize_shared_base_is_reused_but_symlink_dependency_is_unavailable(tmp_path):
    files, root = fixtures(tmp_path)
    (tmp_path / "base").mkdir()
    (tmp_path / "base/kustomization.yaml").write_text("resources: []")
    (tmp_path / "kustomization.yaml").write_text("resources: [base, base]")
    assert len(files.capture(root, "", "kustomize", cancel=cancel())) == 2
    (tmp_path / "alias").symlink_to(tmp_path / "base", target_is_directory=True)
    (tmp_path / "kustomization.yaml").write_text("resources: [alias]")
    with pytest.raises(AppError):
        files.capture(root, "", "kustomize", cancel=cancel())


def test_save_stage_cleanup_failure_is_a_truthful_none_outcome(tmp_path, monkeypatch):
    files, root = fixtures(tmp_path)
    source = tmp_path / "source.yaml"
    source.write_bytes(b"old: data")
    intent = save_intent(files, root)
    original_unlink = os.unlink

    def refuse(*args, **kwargs):
        raise OSError("private-source-sentinel")

    monkeypatch.setattr(os, "replace", refuse)
    monkeypatch.setattr(os, "unlink", refuse)
    outcome = files.save(intent, cancel=cancel())
    assert outcome.effect == "none" and not outcome.cleanup_complete and not outcome.durable
    assert "cleanup" in outcome.notice and "private-source-sentinel" not in outcome.notice
    assert source.read_bytes() == b"old: data"
    stages = tuple(tmp_path.glob(".kuberich-manifest-*"))
    assert len(stages) == 1 and (stages[0].stat().st_mode & 0o777) == 0o600
    for stage in stages:
        original_unlink(stage)


@pytest.mark.asyncio
async def test_renderer_requires_actual_frozen_configuration_and_safe_staging_io(
    tmp_path, monkeypatch
):
    snapshots = capture(tmp_path)
    renderer = KustomizeRenderer(AccessPolicy(False), {"PATH": str(tmp_path)}, tmp_path)
    with pytest.raises(AppError, match="exactly one"):
        await renderer.render((snapshots[1],), "", guard=lambda: None)

    def fail(*args, **kwargs):
        raise OSError("private-staging-path-sentinel")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", fail)
    with pytest.raises(AppError) as error:
        await renderer.render(snapshots, "", guard=lambda: None)
    assert "private-staging-path-sentinel" not in str(error.value)
    await renderer.close()


@pytest.mark.asyncio
async def test_renderer_reports_cleanup_failure_even_when_private_files_were_removed(
    tmp_path, monkeypatch
):
    snapshots = capture(tmp_path)
    helper(tmp_path, "print('kind: ConfigMap')\n")
    original = tempfile.TemporaryDirectory

    class CleanupFailure:
        def __init__(self, *args, **kwargs):
            self.owned = original(*args, **kwargs)
            self.name = self.owned.name
            self.calls = 0

        def cleanup(self):
            self.owned.cleanup()
            self.calls += 1
            if self.calls == 1:
                raise OSError("private-cleanup-sentinel")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", CleanupFailure)
    renderer = KustomizeRenderer(AccessPolicy(False), {"PATH": str(tmp_path)}, tmp_path)
    with pytest.raises(AppError, match="cleanup could not be confirmed") as error:
        await renderer.render(snapshots, "", guard=lambda: None)
    assert "private-cleanup-sentinel" not in str(error.value)
    assert renderer.operation_count == 1
    await renderer.close()
    assert renderer.operation_count == 0


@pytest.mark.asyncio
async def test_renderer_close_drains_active_helper_under_repeated_close_cancellation(tmp_path):
    snapshots = capture(tmp_path)
    record = tmp_path / "running"
    helper(
        tmp_path,
        "from pathlib import Path\nimport os,time\nPath(os.environ['RECORD']).write_text(str(Path.cwd()))\ntime.sleep(60)\n",
    )
    renderer = KustomizeRenderer(
        AccessPolicy(False), {"PATH": str(tmp_path), "RECORD": str(record)}, tmp_path
    )
    rendering = asyncio.create_task(renderer.render(snapshots, "", guard=lambda: None))
    async with asyncio.timeout(5):
        while not record.exists():
            await asyncio.sleep(0.01)
    closing = asyncio.create_task(renderer.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    with pytest.raises(asyncio.CancelledError):
        await rendering
    assert not Path(record.read_text()).exists() and renderer.operation_count == 0
