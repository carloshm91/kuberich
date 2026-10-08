"""Private owned editor files, bounded no-follow reads and drained cleanup."""

import asyncio
import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from kuberich.domain.editing import MAX_EDIT_BYTES
from kuberich.errors import AppError, ExitCode


async def _drain[T](task: asyncio.Future[T]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


async def file_worker[T](
    operation: Callable[[], T], *, discard: Callable[[T], None] | None = None
) -> T:
    """Cancellation waits for filesystem ownership; newly created files are discarded."""
    task = asyncio.create_task(asyncio.to_thread(operation))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _drain(asyncio.gather(task, return_exceptions=True))
        if discard is not None and not task.cancelled() and task.exception() is None:
            await _drain(asyncio.create_task(asyncio.to_thread(discard, task.result())))
        raise


class ManifestFile:
    def __init__(self, data: bytes) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="kuberich-edit-")
        self.path = Path(self.directory.name) / "manifest.yaml"
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                stream = os.fdopen(descriptor, "wb")
            except BaseException:
                os.close(descriptor)
                raise
            with stream:
                stream.write(data)
        except BaseException:
            self.directory.cleanup()
            raise

    def read(self) -> bytes:
        descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EDIT_BYTES:
                raise AppError("Editor output must be a regular file of at most 1 MiB.")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_EDIT_BYTES + 1)
            if len(data) > MAX_EDIT_BYTES:
                raise AppError("Editor output exceeds 1 MiB.")
            return data
        except OSError:
            raise AppError("Cannot read the private editor output.", ExitCode.LOCAL_IO) from None
        finally:
            os.close(descriptor)

    def close(self) -> None:
        self.directory.cleanup()
