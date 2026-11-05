"""Bounded descriptor-anchored local artifact transactions.

A final rename/unlink authorizes the reviewed named entry, not an inode CAS.
No operation follows that entry's symlink target or trusts paths from metadata.
"""

import hashlib
import os
import stat
import threading
from pathlib import Path
from uuid import uuid4

from kuberich.domain.exports import (
    ArtifactRef,
    DestinationReview,
    DirectoryRef,
    FileIdentity,
    FileOutcome,
    FileScan,
    PreparedArtifact,
    inspect_metadata,
    validate_basename,
)
from kuberich.errors import AppError, ExitCode

MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_PREFIX_BYTES = 8192
MAX_ENTRIES = 2048
_CHUNK = 64 * 1024


class ArtifactDirectoryMissing(AppError):
    """The no-follow directory walk found a genuinely absent component."""

    def __init__(self) -> None:
        super().__init__("The selected export directory is missing.", ExitCode.LOCAL_IO)


def _error() -> AppError:
    return AppError(
        "Cannot access the selected local artifact; refresh and review the location.",
        ExitCode.LOCAL_IO,
    )


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise AppError("Local artifact operation cancelled before commit.", ExitCode.LOCAL_IO)


def _basename(name: str) -> str:
    try:
        return validate_basename(name)
    except AppError:
        raise _error() from None


def _identity(value: os.stat_result) -> FileIdentity:
    return FileIdentity(
        device=value.st_dev,
        inode=value.st_ino,
        size=value.st_size,
        mtime_ns=value.st_mtime_ns,
        ctime_ns=value.st_ctime_ns,
        mode=value.st_mode,
        uid=value.st_uid,
        nlink=value.st_nlink,
    )


def _eligible(value: os.stat_result) -> FileIdentity:
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != os.geteuid()
        or value.st_nlink != 1
        or not 0 <= value.st_size <= MAX_ARTIFACT_BYTES
    ):
        raise _error()
    return _identity(value)


def _named(parent: int, name: str) -> FileIdentity | None:
    try:
        return _eligible(os.stat(name, dir_fd=parent, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _owned_directory(descriptor: int) -> os.stat_result:
    value = os.fstat(descriptor)
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o022:
        raise _error()
    return value


class ArtifactFiles:
    """Capture relative locations against launch cwd; own all descriptors per call."""

    def __init__(self, *, cwd: Path | None = None) -> None:
        self._cwd = Path.cwd() if cwd is None else cwd
        if not self._cwd.is_absolute():
            raise _error()

    def _path(self, path: Path) -> Path:
        text = str(path)
        if (
            not text
            or any(ord(char) < 32 or ord(char) == 127 for char in text)
            or ".." in path.parts
        ):
            raise _error()
        expanded = path.expanduser()
        return expanded if expanded.is_absolute() else self._cwd / expanded

    def _open(self, path: Path, *, create: bool, cancel: threading.Event) -> int:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:]:
                _check(cancel)
                created = False
                try:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(part, 0o700, dir_fd=descriptor)
                        created = True
                        # A restrictive umask can remove owner access before an
                        # ordinary directory descriptor can be opened. Only the
                        # just-created named entry receives this no-follow mode.
                        os.chmod(part, 0o700, dir_fd=descriptor, follow_symlinks=False)
                    except FileExistsError:
                        pass
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                os.close(descriptor)
                descriptor = child
                if created:
                    os.fchmod(descriptor, 0o700)
            _owned_directory(descriptor)
            _check(cancel)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _anchor(self, root: DirectoryRef, cancel: threading.Event) -> int:
        descriptor = self._open(self._path(root.path), create=False, cancel=cancel)
        value = os.fstat(descriptor)
        if (value.st_dev, value.st_ino) != (root.device, root.inode):
            os.close(descriptor)
            raise _error()
        return descriptor

    def directory(self, path: Path, *, create: bool, cancel: threading.Event) -> DirectoryRef:
        try:
            selected = self._path(path)
            descriptor = self._open(selected, create=create, cancel=cancel)
            try:
                value = os.fstat(descriptor)
                return DirectoryRef(path=selected, device=value.st_dev, inode=value.st_ino)
            finally:
                os.close(descriptor)
        except FileNotFoundError:
            raise ArtifactDirectoryMissing() from None
        except (OSError, RuntimeError):
            raise _error() from None

    def scan(self, root: DirectoryRef, *, cancel: threading.Event) -> FileScan:
        descriptor = -1
        try:
            descriptor = self._anchor(root, cancel)
            refs: list[ArtifactRef] = []
            skipped = 0
            limited = False
            with os.scandir(descriptor) as entries:
                for index, entry in enumerate(entries):
                    _check(cancel)
                    if index >= MAX_ENTRIES:
                        limited = True
                        break
                    try:
                        name = _basename(entry.name)
                        identity = _named(descriptor, name)
                        if identity is None:
                            skipped += 1
                            continue
                        refs.append(ArtifactRef(directory=root, name=name, identity=identity))
                    except (AppError, OSError):
                        skipped += 1
            return FileScan(
                refs=tuple(sorted(refs, key=lambda ref: ref.name)), limited=limited, skipped=skipped
            )
        except OSError:
            raise _error() from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def read(self, ref: ArtifactRef, *, prefix: bool = False, cancel: threading.Event) -> bytes:
        parent = descriptor = -1
        try:
            name = _basename(ref.name)
            parent = self._anchor(ref.directory, cancel)
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            before = _eligible(os.fstat(descriptor))
            if before != ref.identity or _named(parent, name) != before:
                raise _error()
            limit = MAX_PREFIX_BYTES + 1 if prefix else MAX_ARTIFACT_BYTES + 1
            chunks: list[bytes] = []
            remaining = limit
            while remaining:
                _check(cancel)
                chunk = os.read(descriptor, min(remaining, _CHUNK))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if not prefix and len(data) > MAX_ARTIFACT_BYTES:
                raise _error()
            if _identity(os.fstat(descriptor)) != before or _named(parent, name) != before:
                raise _error()
            metadata = inspect_metadata(data[: MAX_PREFIX_BYTES + 1])
            if metadata is not None and metadata.sensitive and before.mode & 0o077:
                raise _error()
            if (
                not prefix
                and ref.sha256 is not None
                and hashlib.sha256(data).hexdigest() != ref.sha256
            ):
                raise _error()
            _check(cancel)
            return data
        except OSError:
            raise _error() from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if parent >= 0:
                os.close(parent)

    def review(
        self, root: DirectoryRef, name: str, *, replace: bool, cancel: threading.Event
    ) -> DestinationReview:
        parent = -1
        try:
            name = _basename(name)
            parent = self._anchor(root, cancel)
            expected = _named(parent, name)
            _check(cancel)
            return DestinationReview(directory=root, name=name, expected=expected, replace=replace)
        except OSError:
            raise _error() from None
        finally:
            if parent >= 0:
                os.close(parent)

    def publish(
        self, prepared: PreparedArtifact, review: DestinationReview, *, cancel: threading.Event
    ) -> FileOutcome:
        parent = descriptor = -1
        stage = ".kuberich-export-" + uuid4().hex
        staged = committed = False
        cleanup = True
        durable = False
        failure: AppError | None = None
        identity: FileIdentity | None = None
        try:
            _basename(review.name)
            if (
                len(prepared.payload) > MAX_ARTIFACT_BYTES
                or hashlib.sha256(prepared.payload).hexdigest() != prepared.sha256
            ):
                raise _error()
            parent = self._anchor(review.directory, cancel)
            if _named(parent, review.name) != review.expected or (
                review.expected is not None and not review.replace
            ):
                raise AppError(
                    "Destination exists or changed; review explicit overwrite or choose another name.",
                    ExitCode.LOCAL_IO,
                )
            _check(cancel)
            descriptor = os.open(
                stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            staged = True
            os.fchmod(descriptor, 0o600)
            offset = 0
            while offset < len(prepared.payload):
                _check(cancel)
                written = os.write(descriptor, prepared.payload[offset : offset + _CHUNK])
                if written <= 0:
                    raise _error()
                offset += written
            os.fsync(descriptor)
            _check(cancel)
            if _named(parent, review.name) != review.expected:
                raise _error()
            _check(cancel)
            if review.replace:
                os.replace(stage, review.name, src_dir_fd=parent, dst_dir_fd=parent)
                staged = False
            else:
                os.link(
                    stage, review.name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False
                )
            committed = True
        except (AppError, OSError) as error:
            failure = error if isinstance(error, AppError) else _error()
        finally:
            if staged:
                try:
                    named = os.stat(stage, dir_fd=parent, follow_symlinks=False)
                    owned = os.fstat(descriptor)
                    if (named.st_dev, named.st_ino) != (owned.st_dev, owned.st_ino):
                        raise OSError()
                    os.unlink(stage, dir_fd=parent)
                except OSError:
                    cleanup = False
            if committed:
                try:
                    identity = _identity(os.fstat(descriptor))
                    os.fsync(parent)
                    durable = True
                except OSError:
                    pass
            if descriptor >= 0:
                os.close(descriptor)
            if parent >= 0:
                os.close(parent)
        if not committed and cleanup:
            assert failure is not None
            raise failure
        notice = None
        if not cleanup:
            notice = (
                "Artifact stage cleanup failed; inspect the reviewed directory before retrying."
            )
        elif committed and not durable:
            notice = "Artifact saved; durability could not be confirmed."
        ref = (
            None
            if identity is None
            else ArtifactRef(
                directory=review.directory,
                name=review.name,
                identity=identity,
                sha256=prepared.sha256,
            )
        )
        return FileOutcome(
            effect="published" if committed else "none",
            ref=ref,
            durable=durable,
            cleanup_complete=cleanup,
            notice=notice,
        )

    def delete(self, ref: ArtifactRef, *, cancel: threading.Event) -> FileOutcome:
        parent = -1
        try:
            name = _basename(ref.name)
            parent = self._anchor(ref.directory, cancel)
            if _named(parent, name) != ref.identity:
                raise _error()
            _check(cancel)
            os.unlink(name, dir_fd=parent)
            try:
                os.fsync(parent)
            except OSError:
                return FileOutcome(
                    effect="deleted",
                    ref=None,
                    durable=False,
                    cleanup_complete=True,
                    notice="Artifact deleted; durability could not be confirmed.",
                )
            return FileOutcome(effect="deleted", ref=None, durable=True, cleanup_complete=True)
        except OSError:
            raise _error() from None
        finally:
            if parent >= 0:
                os.close(parent)
