"""Owned actual filesystem descriptors and cancellation of held worker threads."""

import asyncio
import gc
import os
import stat
import threading
import weakref
from pathlib import Path

import pytest

from kuberich.adapters.editing import ManifestFile, file_worker
from kuberich.domain.editing import MAX_EDIT_BYTES
from kuberich.errors import AppError
from kuberich.services.editing import EditingService
from tests.contract.test_editing import source_fixture
from tests.support.workspace import wait_for


@pytest.mark.asyncio
async def test_real_permissions_replaced_file_and_no_follow_read(tmp_path):
    file = await file_worker(lambda: ManifestFile(b"x: original"))
    path = file.path
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        replacement = path.with_suffix(".new")
        replacement.write_bytes(b"x: replacement")
        replacement.replace(path)
        assert await file_worker(file.read) == b"x: replacement"
        path.unlink()
        outside = tmp_path / "outside"
        outside.write_text("private-outside")
        path.symlink_to(outside)
        with pytest.raises(OSError):
            await file_worker(file.read)
        path.unlink()
        os.mkfifo(path)
        with pytest.raises(AppError, match="regular"):
            await file_worker(file.read)
        path.unlink()
        path.write_bytes(b"x" * (MAX_EDIT_BYTES + 1))
        with pytest.raises(AppError, match="1 MiB"):
            await file_worker(file.read)
    finally:
        await file_worker(file.close)
    assert not path.parent.exists() and outside.read_text() == "private-outside"


def test_growth_after_stat_is_still_bounded(monkeypatch):
    file = ManifestFile(b"x: original")
    original = os.fstat

    def growing(descriptor):
        info = original(descriptor)
        if stat.S_ISREG(info.st_mode):
            file.path.write_bytes(b"x" * (MAX_EDIT_BYTES + 1))
        return info

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fstat", growing)
            with pytest.raises(AppError, match="exceeds 1 MiB"):
                file.read()
    finally:
        file.close()


@pytest.mark.asyncio
async def test_cancelled_creation_drains_worker_and_discards_created_directory(tmp_path):
    entered, release = threading.Event(), threading.Event()
    paths = []

    def create():
        entered.set()
        assert release.wait(10)
        file = ManifestFile(b"x: private")
        paths.append(file.path)
        return file

    task = asyncio.create_task(file_worker(create, discard=lambda file: file.close()))
    await wait_for(entered.is_set)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert paths and not paths[0].parent.exists()


@pytest.mark.asyncio
async def test_failed_creation_drains_without_discard_and_regular_read_error_is_safe(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def fail():
        entered.set()
        assert release.wait(10)
        raise OSError("sensitive-failure")

    task = asyncio.create_task(
        file_worker(fail, discard=lambda result: pytest.fail("discarded failure"))
    )
    await wait_for(entered.is_set)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    file = ManifestFile(b"x: private")
    try:

        def denied(*args, **kwargs):
            raise OSError("sensitive-read")

        with monkeypatch.context() as patch:
            patch.setattr(os, "fstat", denied)
            with pytest.raises(AppError) as error:
                file.read()
        assert "sensitive" not in str(error.value)
    finally:
        file.close()


@pytest.mark.asyncio
async def test_fdopen_failure_closes_descriptor_and_removes_directory(monkeypatch):
    opened = []
    original = os.open

    def track(*args, **kwargs):
        fd = original(*args, **kwargs)
        opened.append((fd, args[0]))
        return fd

    def fail(*args, **kwargs):
        raise OSError("sensitive-fdopen")

    monkeypatch.setattr(os, "open", track)
    monkeypatch.setattr(os, "fdopen", fail)
    with pytest.raises(OSError):
        ManifestFile(b"x: private")
    with pytest.raises(OSError):
        os.fstat(opened[0][0])
    assert not Path(opened[0][1]).parent.exists()


@pytest.mark.asyncio
async def test_preparation_and_cleanup_failures_have_safe_owned_errors(tmp_path, monkeypatch):
    async with source_fixture(tmp_path) as (source, api, _):

        def fail(*args, **kwargs):
            raise OSError("sensitive-file-error")

        with monkeypatch.context() as patch:
            patch.setattr("kuberich.services.editing.ManifestFile", fail)
            with pytest.raises(AppError) as error:
                await source.open()
            assert "sensitive" not in str(error.value)
        file = await source.open()
        file.path.unlink()
        with pytest.raises(AppError):
            await source.prepare()
        await source.close_file()
        faulted = EditingService(
            source.client, source.resource, source.target, source.policy, source.current
        )
        file = await faulted.open()
        cleanup = file.close
        monkeypatch.setattr(file, "close", fail)
        with pytest.raises(AppError) as error:
            await faulted.close_file()
        assert "sensitive" not in str(error.value)
        cleanup()
        assert not api.requests


@pytest.mark.asyncio
async def test_concurrent_cleanup_and_repeated_cancellation_join_one_owned_worker(
    tmp_path, monkeypatch
):
    async with source_fixture(tmp_path) as (source, api, _):
        file = await source.open()
        path = file.path
        entered, release = threading.Event(), threading.Event()
        close = file.close

        def held_close():
            entered.set()
            assert release.wait(10)
            close()

        monkeypatch.setattr(file, "close", held_close)
        first = asyncio.create_task(source.close_file())
        await wait_for(entered.is_set)
        second = asyncio.create_task(source.close_file())
        first.cancel()
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.sleep(0)
        assert not first.done() and not second.done() and path.exists()
        with pytest.raises(AppError, match="closing"):
            await source.open()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        await second
        assert not path.parent.exists() and not api.requests
        reopened = await source.open()
        assert reopened.path != path


@pytest.mark.parametrize("replace_parent", [False, True])
def test_editor_root_and_parent_replacement_refuse_reads_and_cleanup_without_removing_replacement(
    tmp_path, monkeypatch, replace_parent
):
    parent = tmp_path / "owned-parent"
    parent.mkdir(mode=0o700)
    monkeypatch.setattr("kuberich.adapters.editing.tempfile.tempdir", str(parent))
    file = ManifestFile(b"private-original")
    original = file.path.parent
    selected = parent if replace_parent else original
    retired = selected.with_name(selected.name + "-retired")
    selected.rename(retired)
    selected.mkdir(mode=0o700)
    replacement = selected / original.name if replace_parent else selected
    replacement.mkdir(mode=0o700, exist_ok=True)
    sentinel = replacement / "sentinel"
    sentinel.write_bytes(b"private-replacement")
    (replacement / "manifest.yaml").write_bytes(b"private-injected")
    try:
        with pytest.raises(AppError, match="directory changed"):
            file.read()
        with pytest.raises(AppError, match="directory changed"):
            file.close()
        assert sentinel.read_bytes() == b"private-replacement"
        original_file = (
            retired / original.name / "manifest.yaml"
            if replace_parent
            else retired / "manifest.yaml"
        )
        assert original_file.read_bytes() == b"private-original"
    finally:
        (replacement / "manifest.yaml").unlink()
        sentinel.unlink()
        if replace_parent:
            replacement.rmdir()
        selected.rmdir()
        retired.rename(selected)
        file.close()
        file.close()


def test_editor_cleanup_refusal_has_no_later_garbage_collector_path_deletion(tmp_path):
    file = ManifestFile(b"private-original")
    root = file.path.parent
    retired = root.with_name(root.name + "-retired")
    root.rename(retired)
    root.mkdir(mode=0o700)
    sentinel = root / "sentinel"
    sentinel.write_bytes(b"private-replacement")
    try:
        with pytest.raises(AppError, match="directory changed"):
            file.close()
        reference = weakref.ref(file)
        del file
        gc.collect()
        assert reference() is None and sentinel.read_bytes() == b"private-replacement"
        assert (retired / "manifest.yaml").read_bytes() == b"private-original"
    finally:
        sentinel.unlink()
        root.rmdir()
        (retired / "manifest.yaml").unlink()
        retired.rmdir()


@pytest.mark.asyncio
async def test_cancelled_editor_discard_retains_replacement_refusal_and_never_removes_sentinel(
    tmp_path,
):
    entered, release = threading.Event(), threading.Event()
    files = []

    def create():
        file = ManifestFile(b"private-original")
        files.append(file)
        entered.set()
        assert release.wait(10)
        return file

    task = asyncio.create_task(file_worker(create, discard=lambda value: value.close()))
    await wait_for(entered.is_set)
    file = files[0]
    root = file.path.parent
    retired = root.with_name(root.name + "-retired")
    root.rename(retired)
    root.mkdir(mode=0o700)
    sentinel = root / "sentinel"
    sentinel.write_bytes(b"private-replacement")
    try:
        task.cancel()
        release.set()
        with pytest.raises(AppError, match="directory changed"):
            await task
        assert sentinel.read_bytes() == b"private-replacement"
        assert (retired / "manifest.yaml").read_bytes() == b"private-original"
    finally:
        release.set()
        sentinel.unlink()
        root.rmdir()
        retired.rename(root)
        file.close()
