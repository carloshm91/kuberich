"""Private atomic catalog generations and separately owned credential files."""

import hashlib
import json
import os
import stat
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from kuberich.domain.helm_catalog import (
    MAX_INDEX_BYTES,
    CatalogSnapshot,
    ChartVersion,
    HelmRepository,
    HelmRepositoryKind,
    RepositoryCredentials,
    digest,
)
from kuberich.domain.helm_cli import helm_json
from kuberich.errors import AppError


def _refused() -> AppError:
    return AppError(
        "Helm catalog storage is unsafe, changed or exceeds its private inventory bound."
    )


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_uid,
        value.st_nlink,
    )


@dataclass(frozen=True, slots=True, repr=False)
class CatalogReceipt:
    snapshot: CatalogSnapshot
    identity: tuple[int, ...] | None = None
    credentials_file: str | None = None
    credentials_sha256: str | None = None
    root_identity: tuple[int, int] | None = None
    credentials_identity: tuple[int, ...] | None = None


def _decode(data: bytes) -> tuple[CatalogSnapshot, str, str]:
    value = helm_json(data, limit=MAX_INDEX_BYTES)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "generation",
            "repositories",
            "charts",
            "credentials_file",
            "credentials_sha256",
        }
        or type(value["schema"]) is not int
        or value["schema"] != 1
    ):
        raise _refused()
    repositories, charts = value["repositories"], value["charts"]
    if not isinstance(repositories, list) or not isinstance(charts, list):
        raise _refused()
    try:
        restored = []
        for raw in repositories:
            if not isinstance(raw, dict) or set(raw) != {
                "name",
                "url",
                "kind",
                "revision",
                "allow_loopback_http",
                "ca_file",
                "token_origins",
                "download_origins",
            }:
                raise _refused()
            if raw["ca_file"] is not None and not isinstance(raw["ca_file"], str):
                raise _refused()
            if not isinstance(raw["token_origins"], list) or not isinstance(
                raw["download_origins"], list
            ):
                raise _refused()
            restored.append(
                HelmRepository(
                    raw["name"],
                    raw["url"],
                    HelmRepositoryKind(raw["kind"]),
                    raw["revision"],
                    raw["allow_loopback_http"],
                    Path(raw["ca_file"]) if raw["ca_file"] is not None else None,
                    tuple(raw["token_origins"]),
                    tuple(raw["download_origins"]),
                )
            )
        versions = []
        for raw in charts:
            if not isinstance(raw, dict) or set(raw) != {
                "repository",
                "name",
                "version",
                "url",
                "sha256",
                "catalog_revision",
                "manifest_digest",
            }:
                raise _refused()
            versions.append(ChartVersion(**raw))
        snapshot = CatalogSnapshot(value["generation"], tuple(restored), tuple(versions))
        filename, sha256 = value["credentials_file"], value["credentials_sha256"]
        if (
            not isinstance(filename, str)
            or not filename.startswith("credentials-")
            or not filename.endswith(".json")
        ):
            raise _refused()
        digest(filename[12:-5])
        digest(sha256)
        return snapshot, filename, sha256
    except (TypeError, ValueError):
        raise _refused() from None


class CatalogFiles:
    """No-follow directory traversal; a final rename is not interprocess inode CAS."""

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
            raise _refused()
        self.root = root

    def _open(self, *, create: bool, guard: Callable[[], None], cancel: threading.Event) -> int:
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in self.root.parts[1:]:
                guard()
                if cancel.is_set():
                    raise _refused()
                try:
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                except FileNotFoundError:
                    if not create:
                        raise
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                    )
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise _refused()
            entries = os.listdir(descriptor)
            if len(entries) > 130 or any(
                name != "catalog.json"
                and not (
                    name.startswith("credentials-") and name.endswith(".json") and len(name) == 81
                )
                for name in entries
            ):
                raise _refused()
            for name in entries:
                if name != "catalog.json":
                    digest(name[12:-5])
                item = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if (
                    not stat.S_ISREG(item.st_mode)
                    or stat.S_IMODE(item.st_mode) != 0o600
                    or item.st_uid != os.geteuid()
                    or item.st_nlink != 1
                    or item.st_size > MAX_INDEX_BYTES
                ):
                    raise _refused()
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def _read(self, parent: int, name: str, limit: int) -> tuple[bytes, tuple[int, ...]]:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.geteuid()
                or before.st_nlink != 1
                or before.st_size > limit
            ):
                raise _refused()
            data = bytearray()
            while chunk := os.read(descriptor, min(65_536, limit + 1 - len(data))):
                data.extend(chunk)
                if len(data) > limit:
                    raise _refused()
            identity = _identity(before)
            if (
                len(data) != before.st_size
                or _identity(os.fstat(descriptor)) != identity
                or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity
            ):
                raise _refused()
            return bytes(data), identity
        finally:
            os.close(descriptor)

    def _current(self, parent: int) -> CatalogReceipt:
        root = os.fstat(parent)
        try:
            data, identity = self._read(parent, "catalog.json", MAX_INDEX_BYTES)
        except FileNotFoundError:
            return CatalogReceipt(CatalogSnapshot(), root_identity=(root.st_dev, root.st_ino))
        snapshot, filename, sha256 = _decode(data)
        credential = os.stat(filename, dir_fd=parent, follow_symlinks=False)
        if credential.st_size > 1024 * 1024:
            raise _refused()
        return CatalogReceipt(
            snapshot, identity, filename, sha256, (root.st_dev, root.st_ino), _identity(credential)
        )

    def _anchor(self, parent: int, *, guard: Callable[[], None], cancel: threading.Event) -> None:
        current = self._open(create=False, guard=guard, cancel=cancel)
        try:
            before, after = os.fstat(parent), os.fstat(current)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise _refused()
        finally:
            os.close(current)

    def read(self, *, guard: Callable[[], None], cancel: threading.Event) -> CatalogReceipt:
        parent = -1
        try:
            try:
                parent = self._open(create=False, guard=guard, cancel=cancel)
            except FileNotFoundError:
                return CatalogReceipt(CatalogSnapshot())
            result = self._current(parent)
            self._anchor(parent, guard=guard, cancel=cancel)
            return result
        except OSError:
            raise _refused() from None
        finally:
            if parent >= 0:
                os.close(parent)

    def credentials(
        self, receipt: CatalogReceipt, *, guard: Callable[[], None], cancel: threading.Event
    ) -> dict[str, RepositoryCredentials]:
        if receipt.credentials_file is None:
            return {}
        parent = -1
        try:
            parent = self._open(create=False, guard=guard, cancel=cancel)
            if self._current(parent) != receipt:
                raise _refused()
            data, identity = self._read(parent, receipt.credentials_file, 1024 * 1024)
            if (
                identity != receipt.credentials_identity
                or hashlib.sha256(data).hexdigest() != receipt.credentials_sha256
            ):
                raise _refused()
            value = helm_json(data, limit=1024 * 1024)
            if not isinstance(value, dict) or set(value) != {
                item.name for item in receipt.snapshot.repositories
            }:
                raise _refused()
            result = {}
            for name, raw in value.items():
                if not isinstance(raw, dict) or set(raw) != {"username", "password", "token"}:
                    raise _refused()
                result[name] = RepositoryCredentials(**raw)
            self._anchor(parent, guard=guard, cancel=cancel)
            return result
        except (OSError, TypeError):
            raise _refused() from None
        finally:
            if parent >= 0:
                os.close(parent)

    def write(
        self,
        snapshot: CatalogSnapshot,
        credentials: dict[str, RepositoryCredentials],
        receipt: CatalogReceipt,
        *,
        guard: Callable[[], None],
        cancel: threading.Event,
    ) -> CatalogReceipt:
        parent = -1
        created: list[str] = []
        try:
            guard()
            if receipt.root_identity is None:
                try:
                    existing = self._open(create=False, guard=guard, cancel=cancel)
                except FileNotFoundError:
                    pass
                else:
                    os.close(existing)
                    raise _refused()
            parent = self._open(create=True, guard=guard, cancel=cancel)
            current = self._current(parent)
            if (
                current.snapshot != receipt.snapshot
                or current.identity != receipt.identity
                or current.credentials_file != receipt.credentials_file
                or current.credentials_sha256 != receipt.credentials_sha256
                or current.credentials_identity != receipt.credentials_identity
                or (
                    receipt.root_identity is not None
                    and current.root_identity != receipt.root_identity
                )
            ):
                raise _refused()
            if snapshot.generation != receipt.snapshot.generation + 1 or set(credentials) != {
                item.name for item in snapshot.repositories
            }:
                raise _refused()
            previous_identity = None
            if receipt.credentials_file is not None:
                previous, previous_identity = self._read(
                    parent, receipt.credentials_file, 1024 * 1024
                )
                if hashlib.sha256(previous).hexdigest() != receipt.credentials_sha256:
                    raise _refused()
            secret = json.dumps(
                {name: asdict(value) for name, value in credentials.items()},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            credentials_sha256 = hashlib.sha256(secret).hexdigest()
            filename = "credentials-" + uuid4().hex + uuid4().hex + ".json"
            # Credential filenames are independent opaque generation IDs, never credential hashes.
            values = []
            for repository in snapshot.repositories:
                value = asdict(repository)
                value["ca_file"] = (
                    str(repository.ca_file) if repository.ca_file is not None else None
                )
                values.append(value)
            data = json.dumps(
                {
                    "schema": 1,
                    "generation": snapshot.generation,
                    "repositories": values,
                    "charts": [asdict(chart) for chart in snapshot.charts],
                    "credentials_file": filename,
                    "credentials_sha256": credentials_sha256,
                },
                separators=(",", ":"),
            ).encode()
            if len(secret) > 1024 * 1024 or len(data) > MAX_INDEX_BYTES:
                raise _refused()
            temporary = "credentials-" + uuid4().hex + uuid4().hex + ".json"
            for name, payload in ((filename, secret), (temporary, data)):
                guard()
                if cancel.is_set():
                    raise _refused()
                descriptor = os.open(
                    name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
                )
                created.append(name)
                try:
                    os.fchmod(descriptor, 0o600)
                    with os.fdopen(descriptor, "wb", closefd=False) as stream:
                        stream.write(payload)
                        stream.flush()
                        os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            guard()
            if cancel.is_set() or self._current(parent) != current:
                raise _refused()
            self._anchor(parent, guard=guard, cancel=cancel)
            if receipt.credentials_file is not None:
                previous, identity = self._read(parent, receipt.credentials_file, 1024 * 1024)
                if (
                    identity != previous_identity
                    or hashlib.sha256(previous).hexdigest() != receipt.credentials_sha256
                ):
                    raise _refused()
            os.replace(temporary, "catalog.json", src_dir_fd=parent, dst_dir_fd=parent)
            created.remove(temporary)
            created.remove(filename)
            os.fsync(parent)
            result = self._current(parent)
            # Remove exactly the previous private credential generation after publication.
            if receipt.credentials_file is not None:
                old, identity = self._read(parent, receipt.credentials_file, 1024 * 1024)
                if (
                    hashlib.sha256(old).hexdigest() != receipt.credentials_sha256
                    or identity != previous_identity
                    or _identity(
                        os.stat(receipt.credentials_file, dir_fd=parent, follow_symlinks=False)
                    )
                    != identity
                ):
                    raise _refused()
                os.unlink(receipt.credentials_file, dir_fd=parent)
                os.fsync(parent)
            return result
        except OSError:
            raise _refused() from None
        finally:
            if parent >= 0:
                try:
                    for name in created:
                        os.unlink(name, dir_fd=parent)
                finally:
                    os.close(parent)
