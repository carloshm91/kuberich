"""Private, bounded, durable recovery metadata and process-lifetime flock leases."""

import asyncio
import fcntl
import os
import stat
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from platformdirs import user_state_path

from kuberich.domain.node_shell_journal import (
    MAX_JOURNAL_BYTES,
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    JournalRecord,
    parse_record,
)
from kuberich.errors import AppError, ExitCode
from kuberich.services.ownership import finish_owned


def _error() -> AppError:
    return AppError(
        "Node-shell recovery journal is unsafe, corrupt or unavailable; inspect the private state directory.",
        ExitCode.LOCAL_IO,
    )


def _private(info: os.stat_result, *, directory: bool = False) -> None:
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if (
        not expected
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
        or (not directory and info.st_nlink != 1)
    ):
        raise _error()


def _open_directory(path: Path, *, create: bool) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise _error()
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        _private(os.fstat(descriptor), directory=True)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _operation_name(operation_id: str) -> str:
    from re import fullmatch

    if not isinstance(operation_id, str) or fullmatch(r"[a-f0-9]{32}", operation_id) is None:
        raise _error()
    return operation_id + ".json"


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


class _Lease:
    def __init__(self, path: Path, directory: int, lock: int) -> None:
        self.path, self.directory, self.lock = path, directory, lock
        self.closed = False

    def verify(self) -> None:
        if self.closed:
            raise _error()
        _private(os.fstat(self.directory), directory=True)
        current = _open_directory(self.path, create=False)
        try:
            first, second = os.fstat(self.directory), os.fstat(current)
            if (first.st_dev, first.st_ino) != (second.st_dev, second.st_ino):
                raise _error()
            locked = os.fstat(self.lock)
            present = os.stat(".lock", dir_fd=self.directory, follow_symlinks=False)
            _private(locked)
            if (locked.st_dev, locked.st_ino) != (present.st_dev, present.st_ino):
                raise _error()
        finally:
            os.close(current)

    def scan(self) -> tuple[JournalRecord, ...]:
        self.verify()
        result: list[JournalRecord] = []
        total = 0
        with os.scandir(self.directory) as listing:
            for entry in listing:
                if entry.name == ".lock":
                    continue
                # Crashed temporary writes need explicit inspection, never silent removal.
                if len(result) >= MAX_RECORDS or not entry.name.endswith(".json"):
                    raise _error()
                _operation_name(entry.name[:-5])
                descriptor = os.open(
                    entry.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory
                )
                try:
                    info = os.fstat(descriptor)
                    _private(info)
                    total += info.st_size
                    if not 1 <= info.st_size <= MAX_RECORD_BYTES or total > MAX_JOURNAL_BYTES:
                        raise _error()
                    chunks = bytearray()
                    while len(chunks) <= MAX_RECORD_BYTES:
                        chunk = os.read(descriptor, min(4096, MAX_RECORD_BYTES + 1 - len(chunks)))
                        if not chunk:
                            break
                        chunks.extend(chunk)
                    current = os.stat(entry.name, dir_fd=self.directory, follow_symlinks=False)
                    if (
                        _identity(os.fstat(descriptor)) != _identity(info)
                        or _identity(current) != _identity(info)
                        or len(chunks) != info.st_size
                    ):
                        raise _error()
                    record = parse_record(bytes(chunks))
                    if entry.name != _operation_name(record.operation_id):
                        raise _error()
                    result.append(record)
                finally:
                    os.close(descriptor)
        self.verify()
        return tuple(sorted(result, key=lambda record: (record.created_at, record.operation_id)))

    def write(self, record: JournalRecord) -> None:
        records = self.scan()
        body = record.to_bytes()
        previous = next(
            (item for item in records if item.operation_id == record.operation_id), None
        )
        sizes = {
            item.operation_id: os.stat(
                _operation_name(item.operation_id), dir_fd=self.directory, follow_symlinks=False
            ).st_size
            for item in records
        }
        if (
            len(body) > MAX_RECORD_BYTES
            or (previous is None and len(records) >= MAX_RECORDS)
            or sum(sizes.values()) - sizes.get(record.operation_id, 0) + len(body)
            > MAX_JOURNAL_BYTES
        ):
            raise _error()
        stage = ".stage-" + uuid4().hex
        descriptor = -1
        staged = False
        try:
            descriptor = os.open(
                stage,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.directory,
            )
            staged = True
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(body)
                stream.flush()
                os.fsync(descriptor)
            self.verify()
            os.replace(
                stage,
                _operation_name(record.operation_id),
                src_dir_fd=self.directory,
                dst_dir_fd=self.directory,
            )
            staged = False
            os.fsync(self.directory)
        finally:
            try:
                if staged:
                    os.unlink(stage, dir_fd=self.directory)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)

    def remove(self, operation_id: str) -> None:
        _operation_name(operation_id)
        records = self.scan()
        if not any(record.operation_id == operation_id for record in records):
            return
        self.verify()
        os.unlink(_operation_name(operation_id), dir_fd=self.directory)
        os.fsync(self.directory)

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                os.close(self.lock)
            finally:
                os.close(self.directory)


def _acquire(path: Path, *, create: bool) -> _Lease:
    directory = _open_directory(path, create=create)
    lock = -1
    try:
        lock = os.open(
            ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory
        )
        _private(os.fstat(lock))
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AppError(
                "Another process owns the node-shell recovery journal.", ExitCode.LOCAL_IO
            ) from None
        lease = _Lease(path, directory, lock)
        lease.verify()
        return lease
    except BaseException:
        if lock >= 0:
            os.close(lock)
        os.close(directory)
        raise


async def _worker[T](function: Callable[[], T], discard: Callable[[T], None] | None = None) -> T:
    def guarded() -> T:
        try:
            return function()
        except OSError:
            raise _error() from None

    task = asyncio.create_task(asyncio.to_thread(guarded))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await finish_owned(task)
        if discard is not None:
            cleanup = asyncio.create_task(asyncio.to_thread(discard, task.result()))
            await finish_owned(cleanup)
        raise


class JournalLease:
    """The original owner retains this lease until its tasks and cleanup drain."""

    def __init__(self, lease: _Lease) -> None:
        self._lease = lease
        self._serial = asyncio.Lock()

    async def scan(self) -> tuple[JournalRecord, ...]:
        async with self._serial:
            return await _worker(self._lease.scan)

    async def write(self, record: JournalRecord) -> None:
        async with self._serial:
            await _worker(lambda: self._lease.write(record))

    async def remove(self, operation_id: str) -> None:
        async with self._serial:
            await _worker(lambda: self._lease.remove(operation_id))

    async def close(self) -> None:
        async with self._serial:
            await _worker(self._lease.close)


class NodeShellJournal:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (
            directory if directory is not None else user_state_path("kuberich") / "node-shell"
        )

    async def acquire(self) -> JournalLease:
        lease = await _worker(
            lambda: _acquire(self.directory, create=True), lambda item: item.close()
        )
        return JournalLease(lease)

    async def scan(self) -> tuple[JournalRecord, ...]:
        """Local metadata only; a missing journal stays missing on startup."""
        try:
            lease = await _worker(
                lambda: _acquire(self.directory, create=False), lambda item: item.close()
            )
        except AppError:
            # Check absence separately in an owned worker; all unsafe entries stay errors.
            absent = await _worker(
                lambda: not self.directory.exists() and not self.directory.is_symlink()
            )
            if absent:
                return ()
            raise
        owned = JournalLease(lease)
        try:
            return await owned.scan()
        finally:
            completion = asyncio.create_task(owned.close())
            await finish_owned(completion)
