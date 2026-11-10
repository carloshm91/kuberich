"""Real descriptor-anchored result records, retention and drained local cancellation."""

import asyncio
import json
import os
import stat
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.domain.benchmark_results import BenchmarkProvenance, BenchmarkResult, encode_result
from kuberich.domain.benchmarks import LoadOptions
from kuberich.domain.exports import FileOutcome
from kuberich.errors import AppError
from kuberich.services.benchmark_store import BenchmarkStore


def record(*, days=0):
    now = datetime.now(UTC) - timedelta(days=days)
    return BenchmarkResult(
        uuid4(),
        now,
        now,
        None,
        BenchmarkProvenance("local", "demo", "web", "pod-uid", 8080),
        "GET",
        LoadOptions(),
        "cancelled",
        None,
    )


def write(root, result):
    path = root / (str(result.run_id) + ".json")
    path.write_bytes(encode_result(result))
    path.chmod(0o600)
    return path


@pytest.mark.asyncio
async def test_opening_empty_browser_never_creates_directory_then_private_save_reopens(tmp_path):
    root = tmp_path / "new" / "benchmarks"
    store = BenchmarkStore(root)
    assert store.default_root == root and await store.scan() == () and not root.exists()
    result = record()
    saved = await store.save(result)
    assert saved.result == result and saved.ref.name == str(result.run_id) + ".json"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / saved.ref.name).stat().st_mode) == 0o600
    restarted = BenchmarkStore(root)
    assert await restarted.scan() == (saved,)
    assert await restarted.read(saved.ref) == result
    with pytest.raises(AppError, match="Confirm"):
        await store.delete(saved.ref, confirmed=False)
    assert await store.read(saved.ref) == result
    await store.delete(saved.ref, confirmed=True)
    assert await restarted.scan() == ()


@pytest.mark.asyncio
async def test_no_automatic_prune_on_scan_and_expired_only_removed_on_explicit_save(tmp_path):
    root = tmp_path / "benchmarks"
    root.mkdir(mode=0o700)
    old, recent = record(days=31), record()
    old_path, recent_path = write(root, old), write(root, recent)
    store = BenchmarkStore(root)
    assert len(await store.scan()) == 2 and old_path.exists()
    saved = await store.save(record())
    assert not old_path.exists() and recent_path.exists()
    assert {item.result.run_id for item in await store.scan()} == {
        recent.run_id,
        saved.result.run_id,
    }
    with pytest.raises(AppError):
        await store.save(saved.result)


@pytest.mark.asyncio
async def test_hundred_record_limit_prunes_oldest_verified_identity_only(tmp_path):
    root = tmp_path / "benchmarks"
    root.mkdir(mode=0o700)
    oldest = record(days=2)
    oldest_path = write(root, oldest)
    for _ in range(99):
        write(root, record())
    store = BenchmarkStore(root)
    assert len(await store.scan()) == 100
    await store.save(record())
    assert len(await store.scan()) == 100 and not oldest_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "foreign",
        "malformed",
        "symlink",
        "hardlink",
        "directory",
        "public",
        "oversize",
        "overflow",
        "aggregate",
    ],
)
async def test_foreign_unsafe_and_overflow_entries_block_browse_and_prune(tmp_path, kind):
    root = tmp_path / "benchmarks"
    root.mkdir(mode=0o700)
    old = write(root, record(days=31))
    other = root / "unrelated"
    if kind == "foreign":
        other.write_bytes(encode_result(record()))
        other.chmod(0o600)
    elif kind == "malformed":
        other.write_text('{"credential":"private"}')
        other.chmod(0o600)
    elif kind == "symlink":
        other.symlink_to(old)
    elif kind == "hardlink":
        os.link(old, other)
    elif kind == "directory":
        other.mkdir()
    elif kind == "public":
        old.chmod(0o644)
    elif kind in {"oversize", "aggregate"}:
        other.write_bytes(b" " * (32769 if kind == "oversize" else 4 * 1024**2 + 1))
        other.chmod(0o600)
    else:
        for _ in range(101):
            write(root, record())
    store = BenchmarkStore(root)
    for operation in (store.scan, lambda: store.save(record())):
        with pytest.raises(AppError) as error:
            await operation()
        assert "private" not in str(error.value)
    assert old.exists()


@pytest.mark.asyncio
async def test_path_symlink_ancestor_world_writable_root_and_stale_entry_refused(tmp_path):
    physical = tmp_path / "physical"
    physical.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    store = BenchmarkStore(alias / "child")
    for operation in (store.scan, lambda: store.save(record())):
        with pytest.raises(AppError):
            await operation()
    assert not (physical / "child").exists()
    store = BenchmarkStore(physical)
    saved = await store.save(record())
    # Same name and content are insufficient once the physical file changes.
    path = physical / saved.ref.name
    path.unlink()
    write(physical, saved.result)
    for operation in (
        lambda: store.read(saved.ref),
        lambda: store.delete(saved.ref, confirmed=True),
    ):
        with pytest.raises(AppError):
            await operation()
    assert path.exists()
    physical.chmod(0o777)
    with pytest.raises(AppError):
        await store.scan()


@pytest.mark.asyncio
async def test_saved_ref_cannot_authorize_other_directory_or_changed_record(tmp_path):
    store = BenchmarkStore(tmp_path / "one")
    saved = await store.save(record())
    with pytest.raises(AppError):
        await BenchmarkStore(tmp_path / "two").read(saved.ref)
    path = saved.ref.directory.path / saved.ref.name
    raw = json.loads(path.read_bytes())
    raw["target"]["endpoint"] = "http://elsewhere"
    path.write_text(json.dumps(raw))
    with pytest.raises(AppError):
        await store.read(saved.ref)


class UncertainFiles(ArtifactFiles):
    def __init__(self, *, deletion=False):
        super().__init__()
        self.deletion = deletion

    def publish(self, prepared, review, *, cancel):
        outcome = super().publish(prepared, review, cancel=cancel)
        return outcome if self.deletion else replace(outcome, durable=False)

    def delete(self, ref, *, cancel):
        return FileOutcome(effect="none", ref=None, durable=False, cleanup_complete=False)


@pytest.mark.asyncio
async def test_uncertain_publication_prune_and_delete_are_reported_as_failures(tmp_path):
    root = tmp_path / "benchmarks"
    store = BenchmarkStore(root, files=UncertainFiles())
    with pytest.raises(AppError):
        await store.save(record())
    saved = (await store.scan())[0]
    with pytest.raises(AppError):
        await store.delete(saved.ref, confirmed=True)
    assert len(await store.scan()) == 1
    root2 = tmp_path / "other"
    root2.mkdir(mode=0o700)
    old_path = write(root2, record(days=31))
    with pytest.raises(AppError):
        await BenchmarkStore(root2, files=UncertainFiles(deletion=True)).save(record())
    assert old_path.exists()


class SlowFiles(ArtifactFiles):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.drained = threading.Event()
        self.release = threading.Event()

    def directory(self, path, *, create, cancel):
        self.started.set()
        assert cancel.wait(5)
        assert self.release.wait(5)
        self.drained.set()
        raise AppError("local operation cancelled")


@pytest.mark.asyncio
async def test_repeated_cancel_waits_for_thread_cleanup(tmp_path):
    files = SlowFiles()
    store = BenchmarkStore(tmp_path, files=files)
    pending = asyncio.create_task(store.scan())
    assert await asyncio.to_thread(files.started.wait, 5)
    pending.cancel()
    await asyncio.sleep(0)
    pending.cancel()
    assert not pending.done()
    files.release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert files.drained.is_set()


def test_default_root_is_offline_user_state_path(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "kuberich.services.benchmark_store.user_state_path", lambda *args, **kwargs: tmp_path
    )
    assert BenchmarkStore().default_root == tmp_path / "benchmarks"
    assert not (tmp_path / "benchmarks").exists()
