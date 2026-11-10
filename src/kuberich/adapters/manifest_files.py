"""No-follow local source capture and reviewed directory-entry replacement."""

import hashlib
import os
import stat
import threading
from pathlib import Path
from typing import Literal
from uuid import uuid4

from kuberich.domain.exports import (
    ArtifactRef,
    DirectoryRef,
    FileIdentity,
    FileOutcome,
    validate_basename,
)
from kuberich.domain.kustomize import KUSTOMIZATION_NAMES, kustomize_references, local_reference
from kuberich.domain.manifests import (
    MAX_MANIFEST_BYTES,
    MAX_MANIFEST_DEPTH,
    MAX_MANIFEST_ENTRIES,
    MAX_MANIFEST_FILES,
    MAX_SOURCE_BYTES,
    ManifestEntry,
    ManifestFileSnapshot,
    ManifestListing,
    ManifestSaveIntent,
    ManifestSourceKind,
)
from kuberich.errors import AppError, ExitCode

_CHUNK = 65536


def _error() -> AppError:
    return AppError(
        "Local manifest source changed or is unavailable; refresh the selected root/source.",
        ExitCode.LOCAL_IO,
    )


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise AppError("Local manifest operation cancelled before commit.", ExitCode.LOCAL_IO)


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


def _parts(relative: str) -> tuple[str, ...]:
    if not isinstance(relative, str) or relative.startswith("/") or "\\" in relative:
        raise _error()
    parts = tuple(relative.split("/")) if relative else ()
    if len(parts) > MAX_MANIFEST_DEPTH:
        raise AppError("Local manifest paths exceed 32 levels.")
    for part in parts:
        validate_basename(part)
    return parts


class ManifestFiles:
    """Blocking bounded operations; callers own and drain the worker thread."""

    def __init__(self, *, cwd: Path) -> None:
        if not cwd.is_absolute():
            raise _error()
        self.cwd = cwd

    def root(self, path: Path, *, cancel: threading.Event) -> DirectoryRef:
        try:
            _check(cancel)
            selected = path.expanduser()
            physical = (selected if selected.is_absolute() else self.cwd / selected).resolve(
                strict=True
            )
            descriptor = self._open_absolute(physical, cancel)
            try:
                info = os.fstat(descriptor)
                return DirectoryRef(path=physical, device=info.st_dev, inode=info.st_ino)
            finally:
                os.close(descriptor)
        except (OSError, RuntimeError):
            raise _error() from None

    def _open_absolute(self, path: Path, cancel: threading.Event) -> int:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in path.parts[1:]:
                _check(cancel)
                validate_basename(part)
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            _check(cancel)
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _directory(self, root: DirectoryRef, relative: str, cancel: threading.Event) -> int:
        descriptor = self._open_absolute(root.path, cancel)
        try:
            info = os.fstat(descriptor)
            if (info.st_dev, info.st_ino) != (root.device, root.inode):
                raise _error()
            for part in _parts(relative):
                _check(cancel)
                child = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = child
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def list(
        self, root: DirectoryRef, relative: str, *, cancel: threading.Event
    ) -> ManifestListing:
        descriptor = -1
        try:
            descriptor = self._directory(root, relative, cancel)
            entries: list[ManifestEntry] = []
            limited = False
            skipped = 0
            with os.scandir(descriptor) as listing:
                for index, entry in enumerate(listing):
                    _check(cancel)
                    if index >= MAX_MANIFEST_ENTRIES:
                        limited = True
                        break
                    try:
                        validate_basename(entry.name)
                        info = entry.stat(follow_symlinks=False)
                        path = "/".join(filter(None, (relative, entry.name)))
                        kind: Literal["directory", "manifest", "kustomization", "unavailable"] = (
                            "unavailable"
                        )
                        problem: str | None = "Symlinks and nonregular entries are unavailable."
                        if stat.S_ISDIR(info.st_mode):
                            kind, problem = "directory", None
                        elif stat.S_ISREG(info.st_mode):
                            if entry.name in KUSTOMIZATION_NAMES:
                                kind, problem = "kustomization", None
                            elif Path(entry.name).suffix.lower() in {".yaml", ".yml", ".json"}:
                                kind, problem = "manifest", None
                            else:
                                skipped += 1
                                continue
                        entries.append(
                            ManifestEntry(
                                relative_path=path,
                                kind=kind,
                                identity=_identity(info),
                                problem=problem,
                            )
                        )
                    except (AppError, OSError):
                        skipped += 1
                        limited = True
            _check(cancel)
            self._verify_directory(root, relative, descriptor, cancel)
            return ManifestListing(
                root=root,
                relative_directory=relative,
                entries=tuple(sorted(entries, key=lambda entry: entry.relative_path)),
                limited=limited,
                skipped=skipped,
            )
        except OSError:
            raise _error() from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _read(
        self, root: DirectoryRef, relative: str, cancel: threading.Event, limit: int
    ) -> ManifestFileSnapshot:
        parent = descriptor = -1
        try:
            parts = _parts(relative)
            if not parts:
                raise _error()
            parent = self._directory(root, "/".join(parts[:-1]), cancel)
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
            before = _identity(os.fstat(descriptor))
            if (
                not stat.S_ISREG(before.mode)
                or not 0 <= before.size <= limit
                or _identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != before
            ):
                raise _error()
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining:
                _check(cancel)
                chunk = os.read(descriptor, min(remaining, _CHUNK))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if (
                len(data) > limit
                or _identity(os.fstat(descriptor)) != before
                or _identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != before
            ):
                raise _error()
            _check(cancel)
            self._verify_directory(root, "/".join(parts[:-1]), parent, cancel)
            return ManifestFileSnapshot(
                relative_path=relative,
                identity=before,
                sha256=hashlib.sha256(data).hexdigest(),
                data=data,
            )
        except OSError:
            raise _error() from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if parent >= 0:
                os.close(parent)

    def _verify_directory(
        self, root: DirectoryRef, relative: str, descriptor: int, cancel: threading.Event
    ) -> None:
        current = self._directory(root, relative, cancel)
        try:
            expected, actual = os.fstat(descriptor), os.fstat(current)
            if (expected.st_dev, expected.st_ino) != (actual.st_dev, actual.st_ino):
                raise _error()
        finally:
            os.close(current)

    def read(
        self, root: DirectoryRef, relative: str, *, cancel: threading.Event
    ) -> ManifestFileSnapshot:
        return self._read(root, relative, cancel, MAX_MANIFEST_BYTES)

    def _is_directory(self, root: DirectoryRef, relative: str, cancel: threading.Event) -> bool:
        parts = _parts(relative)
        if not parts:
            return True
        parent = self._directory(root, "/".join(parts[:-1]), cancel)
        try:
            info = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)
            ):
                raise _error()
            return stat.S_ISDIR(info.st_mode)
        finally:
            os.close(parent)

    def capture(
        self,
        root: DirectoryRef,
        relative: str,
        kind: ManifestSourceKind,
        *,
        cancel: threading.Event,
    ) -> tuple[ManifestFileSnapshot, ...]:
        snapshots: dict[str, ManifestFileSnapshot] = {}
        active: set[str] = set()
        visited: set[str] = set()
        total = 0

        def add(path: str, *, opaque: bool = False) -> ManifestFileSnapshot:
            nonlocal total
            if path in snapshots:
                return snapshots[path]
            if len(snapshots) >= MAX_MANIFEST_FILES:
                raise AppError("Kustomize closure exceeds 256 dependency files.")
            snapshot = self._read(
                root, path, cancel, MAX_SOURCE_BYTES if opaque else MAX_MANIFEST_BYTES
            )
            total += len(snapshot.data)
            if total > MAX_SOURCE_BYTES:
                raise AppError("Frozen manifest source exceeds 8 MiB.")
            snapshots[path] = snapshot
            return snapshot

        def walk(directory: str, depth: int) -> None:
            _check(cancel)
            if depth > MAX_MANIFEST_DEPTH:
                raise AppError("Kustomize dependency graph exceeds 32 levels.")
            if directory in active:
                raise AppError("Kustomize dependency cycle is unsupported.")
            if directory in visited:
                return
            active.add(directory)
            listing = self.list(root, directory, cancel=cancel)
            configurations = tuple(
                entry for entry in listing.entries if entry.kind == "kustomization"
            )
            if listing.limited or len(configurations) != 1:
                raise AppError("Select a bounded directory with exactly one Kustomization file.")
            configuration = add(configurations[0].relative_path)
            for reference in kustomize_references(configuration.data):
                path = local_reference(directory, reference.path)
                if self._is_directory(root, path, cancel):
                    if reference.role == "file":
                        raise AppError("Kustomize file dependency names a directory.")
                    walk(path, depth + 1)
                else:
                    if reference.role == "component":
                        raise AppError("A Kustomize component must name a local directory.")
                    add(path, opaque=reference.role == "file")
            active.remove(directory)
            visited.add(directory)

        try:
            if kind == "file":
                add(relative)
            elif kind == "directory":
                listing = self.list(root, relative, cancel=cancel)
                if listing.limited or any(
                    entry.kind == "kustomization" for entry in listing.entries
                ):
                    raise AppError(
                        "Use explicit Render Kustomize for this directory, or select a bounded ordinary directory."
                    )
                for entry in listing.entries:
                    if entry.kind == "manifest":
                        add(entry.relative_path)
                if not snapshots:
                    raise AppError("Selected directory contains no immediate manifest files.")
            elif kind == "kustomize":
                walk(relative, 0)
            else:
                raise AppError("Unknown manifest source kind.")
            result = tuple(snapshots.values())
            self.require_unchanged(root, result, cancel=cancel)
            return result
        except OSError:
            raise _error() from None

    def require_unchanged(
        self,
        root: DirectoryRef,
        files: tuple[ManifestFileSnapshot, ...],
        *,
        cancel: threading.Event,
    ) -> None:
        for expected in files:
            actual = self._read(root, expected.relative_path, cancel, MAX_SOURCE_BYTES)
            if actual.identity != expected.identity or actual.sha256 != expected.sha256:
                raise _error()
        descriptor = self._directory(root, "", cancel)
        os.close(descriptor)

    def save(self, intent: ManifestSaveIntent, *, cancel: threading.Event) -> FileOutcome:
        parent = descriptor = -1
        stage = ".kuberich-manifest-" + uuid4().hex
        staged = committed = durable = False
        cleanup = True
        failure: AppError | None = None
        identity: FileIdentity | None = None
        parts = _parts(intent.original.relative_path)
        try:
            if (
                not parts
                or len(intent.body) > MAX_MANIFEST_BYTES
                or intent.original.identity.nlink != 1
                or intent.original.identity.uid != os.geteuid()
            ):
                raise _error()
            self.require_unchanged(intent.root, (intent.original,), cancel=cancel)
            parent = self._directory(intent.root, "/".join(parts[:-1]), cancel)
            descriptor = os.open(
                stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
            )
            staged = True
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(intent.body)
                stream.flush()
                os.fsync(descriptor)
            self.require_unchanged(intent.root, (intent.original,), cancel=cancel)
            _check(cancel)
            os.replace(stage, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
            committed, staged = True, False
            os.fchmod(descriptor, intent.original.identity.mode & 0o777)
            os.fsync(descriptor)
            identity = _identity(os.fstat(descriptor))
            os.fsync(parent)
            durable = True
        except (OSError, AppError) as error:
            failure = error if isinstance(error, AppError) else _error()
        finally:
            if staged:
                try:
                    os.unlink(stage, dir_fd=parent)
                except OSError:
                    cleanup = False
            if descriptor >= 0:
                os.close(descriptor)
            if parent >= 0:
                os.close(parent)
        if not committed and cleanup:
            assert failure is not None
            raise failure
        notice = (
            "Local stage cleanup failed; inspect the reviewed source directory before retrying."
            if not cleanup
            else ("Local source saved; durability could not be confirmed." if not durable else None)
        )
        ref = (
            None
            if identity is None
            else ArtifactRef(
                directory=intent.root,
                name=intent.original.relative_path,
                identity=identity,
                sha256=hashlib.sha256(intent.body).hexdigest(),
            )
        )
        return FileOutcome(
            effect="published" if committed else "none",
            ref=ref,
            durable=durable,
            cleanup_complete=cleanup,
            notice=notice,
        )
