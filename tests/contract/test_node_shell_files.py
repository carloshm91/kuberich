"""Actual private files, fault injection, cancellation drainage and flock ownership."""

import asyncio
import os
import stat
import subprocess
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.domain.node_shell_journal import JournalRecord, JournalState
from kuberich.errors import AppError


def record(index: int = 0) -> JournalRecord:
    operation = f"{index:032x}"
    return JournalRecord(
        operation,
        JournalState.PREPARED,
        "fixture",
        "b" * 64,
        "diagnostics",
        "namespace-uid",
        "worker-1",
        "node-uid",
        "kuberich-node-shell-" + operation,
        None,
        "c" * 64,
        1,
        1,
    )


@pytest.fixture
def directory(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "node-shell"


@pytest.mark.asyncio
async def test_private_atomic_roundtrip_lease_and_durable_removal(directory: Path) -> None:
    journal = NodeShellJournal(directory)
    assert await journal.scan() == () and not directory.exists()
    lease = await journal.acquire()
    try:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE((directory / ".lock").stat().st_mode) == 0o600
        await lease.write(record(2))
        await lease.write(record(1))
        assert await lease.scan() == (record(1), record(2))
        assert (
            stat.S_IMODE((directory / (record(1).operation_id + ".json")).stat().st_mode) == 0o600
        )
        with pytest.raises(AppError, match="Another process"):
            await journal.acquire()
        with pytest.raises(AppError, match="Another process"):
            await journal.scan()
        known = replace(
            record(1), state=JournalState.OWNED, pod_uid="created-uid", result_code="created"
        )
        await lease.write(known)
        assert await lease.scan() == (known, record(2))
        await lease.remove(known.operation_id)
        await lease.remove(known.operation_id)
        assert await lease.scan() == (record(2),)
    finally:
        await lease.close()
    await lease.close()
    assert await journal.scan() == (record(2),)
    with pytest.raises(AppError):
        await lease.scan()
    assert sorted(item.name for item in directory.iterdir()) == [
        ".lock",
        record(2).operation_id + ".json",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777, 0o500])
async def test_existing_directory_must_be_owned_and_private(directory: Path, mode: int) -> None:
    directory.mkdir(mode=mode)
    with pytest.raises(AppError):
        await NodeShellJournal(directory).acquire()


@pytest.mark.asyncio
async def test_directory_symlinks_are_not_followed(directory: Path) -> None:
    physical = directory.parent / "other"
    physical.mkdir(mode=0o700)
    directory.symlink_to(physical, target_is_directory=True)
    for call in (NodeShellJournal(directory).scan, NodeShellJournal(directory).acquire):
        with pytest.raises(AppError):
            await call()
    assert list(physical.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", [Path("relative"), Path("/tmp/../not-an-operation")])
async def test_nonphysical_or_relative_directory_is_rejected(relative: Path) -> None:
    with pytest.raises(AppError):
        await NodeShellJournal(relative).acquire()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        "public",
        "directory",
        "fifo",
        "hardlink",
        "corrupt",
        "oversized",
        "mismatch",
        "stage",
        "bad_name",
        "empty",
    ],
)
async def test_unsafe_record_entries_are_visible_errors(directory: Path, kind: str) -> None:
    directory.mkdir(mode=0o700)
    path = directory / (record().operation_id + ".json")
    outside = directory.parent / "outside"
    outside.write_bytes(record().to_bytes())
    outside.chmod(0o600)
    if kind == "symlink":
        path.symlink_to(outside)
    elif kind == "directory":
        path.mkdir(mode=0o600)
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "hardlink":
        os.link(outside, path)
    else:
        body = (
            b"{"
            if kind == "corrupt"
            else b"x" * 16385
            if kind == "oversized"
            else b""
            if kind == "empty"
            else record(1).to_bytes()
            if kind == "mismatch"
            else record().to_bytes()
        )
        if kind == "stage":
            path = directory / ".stage-left-by-crash"
        elif kind == "bad_name":
            path = directory / "wrong.json"
        path.write_bytes(body)
        path.chmod(0o644 if kind == "public" else 0o600)
    with pytest.raises(AppError):
        await NodeShellJournal(directory).scan()
    assert outside.read_bytes() == record().to_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["symlink", "public", "directory", "hardlink"])
async def test_unsafe_lock_is_not_opened_as_a_lease(directory: Path, kind: str) -> None:
    directory.mkdir(mode=0o700)
    lock = directory / ".lock"
    outside = directory.parent / "outside"
    outside.write_bytes(b"untouched")
    outside.chmod(0o600)
    if kind == "symlink":
        lock.symlink_to(outside)
    elif kind == "directory":
        lock.mkdir(mode=0o600)
    elif kind == "hardlink":
        os.link(outside, lock)
    else:
        lock.write_bytes(b"")
        lock.chmod(0o644)
    with pytest.raises(AppError):
        await NodeShellJournal(directory).acquire()
    assert outside.read_bytes() == b"untouched"


@pytest.mark.asyncio
async def test_record_count_and_total_bytes_never_silently_evict(directory: Path) -> None:
    journal = NodeShellJournal(directory)
    lease = await journal.acquire()
    try:
        for index in range(100):
            await lease.write(record(index))
        with pytest.raises(AppError):
            await lease.write(record(100))
        assert len(await lease.scan()) == 100
        # An overfull on-disk journal is corrupt, not a truncated successful scan.
        path = directory / (record(100).operation_id + ".json")
        path.write_bytes(record(100).to_bytes())
        path.chmod(0o600)
        with pytest.raises(AppError):
            await lease.scan()
        path.unlink()
        for index in range(100):
            path = directory / (record(index).operation_id + ".json")
            path.write_bytes(record(index).to_bytes() + b" " * 11000)
        with pytest.raises(AppError):
            await lease.scan()
    finally:
        await lease.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["file_fsync", "replace", "directory_fsync"])
async def test_failed_durable_transition_preserves_existing_record_and_reports_failure(
    directory: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    original = record()
    await lease.write(original)
    known = replace(
        original, state=JournalState.OWNED, pod_uid="created-uid", result_code="created"
    )
    real_sync = os.fsync

    def sync(descriptor: int) -> None:
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if (stage == "directory_fsync") == is_directory:
            raise OSError("private injected fault")
        real_sync(descriptor)

    def fail_replace(*args: Any, **kwargs: Any) -> None:
        raise OSError("private injected fault")

    try:
        with monkeypatch.context() as patch:
            if stage == "replace":
                patch.setattr(os, "replace", fail_replace)
            else:
                patch.setattr(os, "fsync", sync)
            with pytest.raises(AppError) as failure:
                await lease.write(known)
            assert "private injected fault" not in str(failure.value)
        assert await lease.scan() == ((known if stage == "directory_fsync" else original),)
        assert all(not path.name.startswith(".stage-") for path in directory.iterdir())
    finally:
        await lease.close()


@pytest.mark.asyncio
async def test_stage_open_failure_leaves_existing_record_and_no_temporary_file(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    await lease.write(record())
    real_open = os.open

    def open_file(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if isinstance(path, str) and path.startswith(".stage-"):
            raise PermissionError("injected private stage failure")
        return real_open(path, flags, *args, **kwargs)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "open", open_file)
            with pytest.raises(AppError):
                await lease.write(record(1))
        assert await lease.scan() == (record(),)
        assert sorted(path.name for path in directory.iterdir()) == [
            ".lock",
            record().operation_id + ".json",
        ]
    finally:
        await lease.close()


@pytest.mark.asyncio
async def test_cancelled_fsync_failure_is_drained_and_remains_a_durability_error(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    await lease.write(record())
    entered, release = threading.Event(), threading.Event()

    def fail_after_release(descriptor: int) -> None:
        entered.set()
        assert release.wait(5)
        raise OSError("injected private durability failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", fail_after_release)
            writing = asyncio.create_task(lease.write(record(1)))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                writing.cancel()
                await asyncio.sleep(0)
                assert not writing.done()
            finally:
                release.set()
            with pytest.raises(AppError) as failure:
                await writing
            assert "injected private" not in str(failure.value)
        assert await lease.scan() == (record(),)
    finally:
        release.set()
        await lease.close()


@pytest.mark.asyncio
async def test_fsync_worker_is_drained_through_repeated_cancellation(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    entered, release = threading.Event(), threading.Event()
    real_sync = os.fsync

    def delayed(descriptor: int) -> None:
        entered.set()
        assert release.wait(5)
        real_sync(descriptor)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fsync", delayed)
            writing = asyncio.create_task(lease.write(record()))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                writing.cancel()
                await asyncio.sleep(0)
                writing.cancel()
                await asyncio.sleep(0)
                assert not writing.done()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await writing
        assert await lease.scan() == (record(),)
    finally:
        release.set()
        await lease.close()


@pytest.mark.asyncio
async def test_cancelled_acquisition_drains_worker_and_releases_the_acquired_flock(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcntl

    entered, release = threading.Event(), threading.Event()
    real_flock = fcntl.flock

    def delayed(descriptor: int, operation: int) -> None:
        real_flock(descriptor, operation)
        entered.set()
        assert release.wait(5)

    with monkeypatch.context() as patch:
        patch.setattr(fcntl, "flock", delayed)
        acquiring = asyncio.create_task(NodeShellJournal(directory).acquire())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            acquiring.cancel()
            await asyncio.sleep(0)
            assert not acquiring.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await acquiring
    lease = await NodeShellJournal(directory).acquire()
    await lease.close()


@pytest.mark.asyncio
async def test_replaced_directory_and_lock_invalidate_existing_lease(directory: Path) -> None:
    journal = NodeShellJournal(directory)
    lease = await journal.acquire()
    moved = directory.with_name("moved")
    directory.rename(moved)
    directory.mkdir(mode=0o700)
    try:
        with pytest.raises(AppError):
            await lease.write(record())
    finally:
        await lease.close()
    assert not (directory / (record().operation_id + ".json")).exists()
    lease = await journal.acquire()
    (directory / ".lock").rename(directory / ".old-lock")
    (directory / ".lock").touch(mode=0o600)
    try:
        with pytest.raises(AppError):
            await lease.write(record())
    finally:
        await lease.close()


@pytest.mark.asyncio
async def test_remove_failure_retains_record_and_untrusted_ids_do_not_access_paths(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    await lease.write(record())

    def denied(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("private exception")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "unlink", denied)
            with pytest.raises(AppError):
                await lease.remove(record().operation_id)
        assert await lease.scan() == (record(),)
        with pytest.raises(AppError):
            await lease.remove("../outside")
        assert await lease.scan() == (record(),)
    finally:
        await lease.close()


@pytest.mark.asyncio
async def test_write_counts_actual_record_bytes_including_whitespace(directory: Path) -> None:
    journal = NodeShellJournal(directory)
    lease = await journal.acquire()
    try:
        for index in range(64):
            item = record(index)
            body = item.to_bytes()
            path = directory / (item.operation_id + ".json")
            path.write_bytes(body + b" " * (16384 - len(body)))
            path.chmod(0o600)
        assert len(await lease.scan()) == 64
        with pytest.raises(AppError):
            await lease.write(record(64))
        assert len(await lease.scan()) == 64
        await lease.write(record(0))
        await lease.write(record(64))
        assert len(await lease.scan()) == 65
    finally:
        await lease.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["replace", "early_eof", "grow"])
async def test_record_race_and_truncated_reads_are_not_trusted(
    directory: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    lease = await NodeShellJournal(directory).acquire()
    await lease.write(record())
    real_read = os.read
    applied = False
    path = directory / (record().operation_id + ".json")

    def read(descriptor: int, amount: int) -> bytes:
        nonlocal applied
        if not applied:
            applied = True
            if fault == "early_eof":
                return b""
            if fault == "replace":
                changed = directory / "replacement"
                changed.write_bytes(record().to_bytes())
                changed.chmod(0o600)
                changed.replace(path)
            else:
                with path.open("ab") as stream:
                    stream.write(b" " * 16385)
        return real_read(descriptor, amount)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(os, "read", read)
            with pytest.raises(AppError):
                await lease.scan()
    finally:
        await lease.close()


@pytest.mark.asyncio
async def test_foreign_directory_owner_is_not_accepted(
    directory: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory.mkdir(mode=0o700)
    foreign = os.geteuid() + 1
    with monkeypatch.context() as patch:
        patch.setattr(os, "geteuid", lambda: foreign)
        with pytest.raises(AppError):
            await NodeShellJournal(directory).acquire()


@pytest.mark.asyncio
async def test_crashed_process_releases_flock_without_losing_record(directory: Path) -> None:
    program = """
import asyncio, os, sys
from pathlib import Path
from kuberich.adapters.node_shell_files import NodeShellJournal
from kuberich.domain.node_shell_journal import JournalRecord, JournalState
async def run():
    lease = await NodeShellJournal(Path(sys.argv[1])).acquire()
    await lease.write(JournalRecord('a'*32, JournalState.CREATE_UNCERTAIN, 'fixture', 'b'*64,
        'diagnostics', 'namespace-uid', 'worker-1', 'node-uid', 'kuberich-node-shell-'+'a'*32,
        None, 'c'*64, 1, 1, 'create_uncertain'))
    print('ready', flush=True)
    sys.stdin.buffer.readline()
    os._exit(0)
asyncio.run(run())
"""
    process = subprocess.Popen(
        [sys.executable, "-c", program, str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert process.stdout is not None
        assert await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 5) == b"ready\n"
        with pytest.raises(AppError, match="Another process"):
            await NodeShellJournal(directory).acquire()
        assert process.stdin is not None
        process.stdin.write(b"exit\n")
        process.stdin.flush()
        assert await asyncio.to_thread(process.wait, timeout=5) == 0
        recovered = await NodeShellJournal(directory).scan()
        assert len(recovered) == 1 and recovered[0].state is JournalState.CREATE_UNCERTAIN
        assert recovered[0].pod_uid is None
    finally:
        if process.poll() is None:
            process.kill()
        await asyncio.to_thread(process.wait, timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()
