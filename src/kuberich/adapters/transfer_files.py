"""Bounded local snapshots and inspected archives with anchored destination commits."""

import os
import shutil
import stat
import tarfile
import threading
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from kuberich.domain.transfers import (
    MAX_ARCHIVE_BYTES,
    MAX_EXTENDED_METADATA_BYTES,
    MAX_TRANSFER_BYTES,
    MAX_TRANSFER_DEPTH,
    MAX_TRANSFER_ENTRIES,
    utf8_size,
    validate_pax_records,
)
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument


@dataclass(frozen=True, slots=True)
class FileInventory:
    size: int
    entries: int
    directory: bool


def _directory(path: Path) -> int:
    """Open every ancestor without following a symlink, then retain its descriptor."""
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if part in {".", ".."}:
                raise AppError("Local paths cannot contain dot segments.")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_mode)


def _existing(parent: int, name: str) -> tuple[int, int, int, int, int] | None:
    try:
        value = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise AppError(
            "Existing destination must be a regular, unlinked file; directory merges are refused."
        )
    return _identity(value)


class DownloadDestination:
    def __init__(self, path: Path, overwrite: bool) -> None:
        self.path, self.overwrite = path, overwrite
        self.parent = _directory(path.parent)
        self.stage_name = f".kuberich-copy-{uuid4().hex}"
        self.stage = -1
        self.published = False
        self.cancelled = threading.Event()
        created = False
        try:
            self.expected = _existing(self.parent, path.name)
            if self.expected is not None and not overwrite:
                raise AppError(
                    "Local destination exists. Review explicit overwrite or choose another path."
                )
            os.mkdir(self.stage_name, 0o700, dir_fd=self.parent)
            created = True
            self.stage = os.open(
                self.stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.parent
            )
        except BaseException:
            if created:
                shutil.rmtree(self.stage_name, dir_fd=self.parent)
            os.close(self.parent)
            raise

    def close(self) -> None:
        if self.stage < 0:
            return
        try:
            shutil.rmtree(self.stage_name, dir_fd=self.parent)
        finally:
            os.close(self.stage)
            os.close(self.parent)
            self.stage = -1

    def extract(self, archive: Path, root: str) -> FileInventory:
        _scan_headers(archive)
        paths: dict[str, bool] = {}
        spellings: dict[str, str] = {}
        total = 0
        with tarfile.open(archive, mode="r:") as source:
            for entry in source:
                name = entry.name.rstrip("/")
                validate_argument(name)
                parts = name.split("/")
                key = unicodedata.normalize("NFC", name).casefold()
                if (
                    parts[0] != root
                    or len(parts) > MAX_TRANSFER_DEPTH
                    or utf8_size(name) > 4096
                    or any(part in {"", ".", ".."} for part in parts)
                    or key in paths
                    or len(paths) >= MAX_TRANSFER_ENTRIES
                    or not (entry.isfile() or entry.isdir())
                    or entry.sparse is not None
                    or any(field.startswith("GNU.sparse") for field in entry.pax_headers)
                    or entry.size < 0
                    or (entry.isdir() and entry.size != 0)
                ):
                    raise AppError(
                        "Archive contains unsafe, duplicate, linked, sparse or excessive entries."
                    )
                total += entry.size
                if total > MAX_TRANSFER_BYTES:
                    raise AppError("Archive exceeds the 512 MiB payload limit.")
                paths[key] = entry.isdir()
                for depth in range(1, len(parts) + 1):
                    spelling = "/".join(parts[:depth])
                    normalized = unicodedata.normalize("NFC", spelling).casefold()
                    previous = spellings.get(normalized)
                    if previous is not None and previous != spelling:
                        raise AppError("Archive contains colliding directory/file spellings.")
                    if previous is None and len(spellings) >= MAX_TRANSFER_ENTRIES:
                        raise AppError("Archive exceeds its total file/directory entry limit.")
                    spellings[normalized] = spelling
                parent = os.dup(self.stage)
                try:
                    for component in parts[:-1]:
                        with suppress(FileExistsError):
                            os.mkdir(component, 0o700, dir_fd=parent)
                        child = os.open(
                            component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                        )
                        os.close(parent)
                        parent = child
                    if entry.isdir():
                        try:
                            os.mkdir(parts[-1], 0o700, dir_fd=parent)
                        except FileExistsError:
                            checked = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                            if not stat.S_ISDIR(checked.st_mode):
                                raise AppError(
                                    "Archive has conflicting file/directory entries."
                                ) from None
                    else:
                        content = source.extractfile(entry)
                        assert content is not None
                        descriptor = os.open(
                            parts[-1],
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                            0o600,
                            dir_fd=parent,
                        )
                        with content, os.fdopen(descriptor, "wb") as output:
                            shutil.copyfileobj(content, output, length=64 * 1024)
                finally:
                    os.close(parent)
        root_key = unicodedata.normalize("NFC", root).casefold()
        if root_key not in paths:
            raise AppError("Archive lacks the exact requested root entry.")
        return FileInventory(total, len(spellings), paths[root_key])

    def publish(self, root: str, inventory: FileInventory) -> None:
        if self.cancelled.is_set():
            raise AppError("Download publication cancelled; local destination retained.")
        if _existing(self.parent, self.path.name) != self.expected:
            raise AppError(
                "Local destination changed since review. Review again; staged copy was not published."
            )
        if self.cancelled.is_set():
            raise AppError("Download publication cancelled; local destination retained.")
        if inventory.directory:
            if self.expected is not None:
                raise AppError(
                    "A downloaded directory cannot replace an existing file or merge directories."
                )
            # mkdir is an exclusive reservation. Only its newly-owned children are
            # populated; an existing directory is never replaced by rename.
            source = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.stage)
            destination = -1
            created = False
            try:
                os.mkdir(self.path.name, 0o700, dir_fd=self.parent)
                created = True
                destination = os.open(
                    self.path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.parent
                )
                for name in os.listdir(source):
                    os.rename(name, name, src_dir_fd=source, dst_dir_fd=destination)
            except BaseException:
                if created:
                    shutil.rmtree(self.path.name, dir_fd=self.parent)
                raise
            finally:
                os.close(source)
                if destination >= 0:
                    os.close(destination)
        elif self.overwrite:
            os.replace(root, self.path.name, src_dir_fd=self.stage, dst_dir_fd=self.parent)
        else:
            os.link(
                root,
                self.path.name,
                src_dir_fd=self.stage,
                dst_dir_fd=self.parent,
                follow_symlinks=False,
            )
        self.published = True


def _scan_headers(archive: Path) -> None:
    """Bound extended metadata before tarfile can materialize a hostile PAX record."""
    size = archive.stat().st_size
    if not 1024 <= size <= MAX_ARCHIVE_BYTES:
        raise AppError("Archive is truncated or exceeds its wire-size limit.")
    headers = metadata = 0
    with archive.open("rb") as stream:
        while stream.tell() < size:
            block = stream.read(512)
            if block == bytes(512):
                if stream.read(512) != bytes(512):
                    raise AppError("Archive has no complete end marker.")
                while extra := stream.read(64 * 1024):
                    if extra.strip(b"\0"):
                        raise AppError("Archive contains trailing nonzero data.")
                return
            try:
                entry = tarfile.TarInfo.frombuf(block, "utf-8", "strict")
            except (tarfile.TarError, UnicodeError, ValueError):
                raise AppError("Archive has malformed headers.") from None
            headers += 1
            if headers > MAX_TRANSFER_ENTRIES * 3 or entry.size < 0:
                raise AppError("Archive has excessive or invalid headers.")
            extended = {
                tarfile.XHDTYPE,
                tarfile.XGLTYPE,
                tarfile.GNUTYPE_LONGNAME,
                tarfile.GNUTYPE_LONGLINK,
            }
            if entry.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, *extended}:
                raise AppError("Archive contains linked, sparse or special entries.")
            if (
                entry.type
                in {
                    tarfile.XHDTYPE,
                    tarfile.XGLTYPE,
                    tarfile.GNUTYPE_LONGNAME,
                    tarfile.GNUTYPE_LONGLINK,
                }
                and entry.size > 64 * 1024
            ):
                raise AppError("Archive extended metadata exceeds 64 KiB.")
            offset = stream.tell() + ((entry.size + 511) // 512) * 512
            if offset > size:
                raise AppError("Archive payload is truncated.")
            if entry.type in extended:
                metadata += entry.size
                if metadata > MAX_EXTENDED_METADATA_BYTES:
                    raise AppError("Archive extended metadata exceeds its aggregate limit.")
                if entry.type in {tarfile.XHDTYPE, tarfile.XGLTYPE}:
                    validate_pax_records(stream.read(entry.size))
            stream.seek(offset)
    raise AppError("Archive has no complete end marker.")


def snapshot_upload(source: Path, destination: Path) -> FileInventory:
    """Read a source tree through no-follow descriptors into private immutable input."""
    parent = _directory(source.parent)
    entries, total = 0, 0

    def names_at(descriptor: int) -> list[str]:
        names: list[str] = []
        with os.scandir(descriptor) as listing:
            for entry in listing:
                if len(names) >= MAX_TRANSFER_ENTRIES:
                    raise AppError("Upload exceeds its entry limit.")
                names.append(entry.name)
        return sorted(names)

    def copy(owner: int, name: str, output: Path, depth: int) -> bool:
        nonlocal entries, total
        validate_argument(name)
        utf8_size(name)
        entries += 1
        if entries > MAX_TRANSFER_ENTRIES or depth > MAX_TRANSFER_DEPTH:
            raise AppError("Upload exceeds its entry/depth limit.")
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=owner)
        try:
            before = os.fstat(fd)
            if stat.S_ISDIR(before.st_mode):
                output.mkdir(mode=0o700)
                names = names_at(fd)
                for child in names:
                    copy(fd, child, output / child, depth + 1)
                if _identity(os.fstat(fd)) != _identity(before) or names_at(fd) != names:
                    raise AppError("Upload directory changed during snapshot. Review again.")
                return True
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise AppError(
                    "Upload accepts regular files/directories without links or special files."
                )
            total += before.st_size
            if total > MAX_TRANSFER_BYTES:
                raise AppError("Upload exceeds the 512 MiB payload limit.")
            with os.fdopen(os.dup(fd), "rb") as content, output.open("xb") as target:
                os.chmod(output, 0o600)
                remaining = before.st_size
                while remaining:
                    data = content.read(min(remaining, 64 * 1024))
                    if not data:
                        raise AppError("Upload file changed during snapshot. Review again.")
                    target.write(data)
                    remaining -= len(data)
                if content.read(1) or _identity(os.fstat(fd)) != _identity(before):
                    raise AppError("Upload file changed during snapshot. Review again.")
            return False
        finally:
            os.close(fd)

    try:
        directory = copy(parent, source.name, destination, 1)
        return FileInventory(total, entries, directory)
    finally:
        os.close(parent)
