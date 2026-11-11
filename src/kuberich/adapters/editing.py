"""Private owned editor files, bounded no-follow reads and drained cleanup."""

import asyncio
import os
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

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
        # Explicit lifetime avoids a TemporaryDirectory finalizer later deleting
        # an unrelated replacement after an identity-aware cleanup refusal.
        self.directory = Path(tempfile.mkdtemp(prefix="kuberich-edit-")).resolve()
        self.path = self.directory / "manifest.yaml"
        root, parent = self.directory.stat(), self.directory.parent.stat()
        self._root_identity = root.st_dev, root.st_ino
        self._parent_identity = parent.st_dev, parent.st_ino
        self._closed = False
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
            self.close()
            raise

    def _require_root(self, descriptor: int) -> None:
        try:
            root = os.fstat(descriptor)
            current = self.directory.stat(follow_symlinks=False)
            parent = self.directory.parent.stat(follow_symlinks=False)
        except OSError:
            raise AppError("Private editor directory is unavailable.", ExitCode.LOCAL_IO) from None
        if (
            self._closed
            or not stat.S_ISDIR(current.st_mode)
            or not stat.S_ISDIR(parent.st_mode)
            or (root.st_dev, root.st_ino) != self._root_identity
            or (current.st_dev, current.st_ino) != self._root_identity
            or (parent.st_dev, parent.st_ino) != self._parent_identity
            or current.st_mode & 0o077
        ):
            raise AppError("Private editor directory changed; replacement paths were not removed.")

    def read(self) -> bytes:
        from kuberich.domain.editing import MAX_EDIT_BYTES

        root = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            self._require_root(root)
            descriptor = os.open(
                self.path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root
            )
        except BaseException:
            os.close(root)
            raise
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EDIT_BYTES:
                raise AppError("Editor output must be a regular file of at most 1 MiB.")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                data = stream.read(MAX_EDIT_BYTES + 1)
            if len(data) > MAX_EDIT_BYTES:
                raise AppError("Editor output exceeds 1 MiB.")
            self._require_root(root)
            return data
        except OSError:
            raise AppError("Cannot read the private editor output.", ExitCode.LOCAL_IO) from None
        finally:
            os.close(descriptor)
            os.close(root)

    def close(self) -> None:
        if self._closed:
            return
        descriptor = -1
        try:
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self._require_root(descriptor)
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        shutil.rmtree(entry.name, dir_fd=descriptor)
                    else:
                        os.unlink(entry.name, dir_fd=descriptor)
            self._require_root(descriptor)
            self.directory.rmdir()
            self._closed = True
        except OSError:
            raise AppError(
                "Private editor cleanup could not be verified; replacement paths were not removed."
            ) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
