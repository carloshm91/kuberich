"""Private exact Helm command inputs and isolated, empty tool configuration."""

import os
import shutil
import stat
import tempfile
from pathlib import Path

from kuberich.domain.helm_lifecycle import fingerprint
from kuberich.errors import AppError


class HelmCommandFiles:
    def __init__(
        self, parent: Path, *, package: bytes | None = None, values: bytes | None = None
    ) -> None:
        # Explicit lifetime: an automatic TemporaryDirectory finalizer would delete
        # a replacement path after a physical-identity cleanup refusal.
        self.path = Path(tempfile.mkdtemp(prefix="helm-inputs-", dir=parent))
        root = self.path.stat(follow_symlinks=False)
        self._root_identity = root.st_dev, root.st_ino
        self._closed = False
        self.chart = self.path / "chart.tgz" if package is not None else None
        self.values = self.path / "values.yaml" if values is not None else None
        self._inputs: dict[Path, tuple[int, int, str]] = {}
        self._directories: dict[Path, tuple[int, int]] = {}
        try:
            for name in ("config", "cache", "data", "plugins", "repository", "content", "docker"):
                (self.path / name).mkdir(mode=0o700)
            for directory_path in (self.path, *self.path.iterdir()):
                info = directory_path.stat(follow_symlinks=False)
                self._directories[directory_path] = info.st_dev, info.st_ino
            for path, data in (
                # ORAS 2.6.2 disables native-store detection only when auths is
                # nonempty. This inert host contains no usable credential.
                (
                    self.path / "registry.json",
                    b'{"auths":{"kuberich-credential-empty.invalid":{}}}\n',
                ),
                (
                    self.path / "docker/config.json",
                    b'{"auths":{"kuberich-credential-empty.invalid":{}}}\n',
                ),
                (self.path / "repositories.yaml", b"apiVersion: v1\nrepositories: []\n"),
                (self.chart, package),
                (self.values, values),
            ):
                if path is None or data is None:
                    continue
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                info = path.stat(follow_symlinks=False)
                self._inputs[path] = info.st_dev, info.st_ino, fingerprint(data)
        except BaseException:
            self.close()
            raise

    def require_current(self) -> None:
        try:
            self._require_current()
        except OSError:
            raise AppError(
                "Private Helm command inputs are unavailable; prepare a fresh review."
            ) from None

    def _require_current(self) -> None:
        for path, identity in self._directories.items():
            info = path.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(info.st_mode)
                or (info.st_dev, info.st_ino) != identity
                or info.st_mode & 0o077
            ):
                raise AppError("Private Helm command directories changed; prepare a fresh review.")
        for path, (device, inode, digest) in self._inputs.items():
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_dev != device
                    or info.st_ino != inode
                    or info.st_mode & 0o077
                ):
                    raise AppError("Private Helm command inputs changed; prepare a fresh review.")
                data = bytearray()
                while chunk := os.read(descriptor, 65536):
                    data.extend(chunk)
                    if len(data) > 16 * 1024 * 1024:
                        raise AppError("Private Helm command input exceeds its limit.")
                after = os.fstat(descriptor)
                if (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                    after.st_ctime_ns,
                ) or fingerprint(bytes(data)) != digest:
                    raise AppError("Private Helm command inputs changed; prepare a fresh review.")
            finally:
                os.close(descriptor)

    def close(self) -> None:
        if self._closed:
            return
        descriptor = -1
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            root = os.fstat(descriptor)
            current = self.path.stat(follow_symlinks=False)
            if (
                (root.st_dev, root.st_ino) != self._root_identity
                or not stat.S_ISDIR(current.st_mode)
                or (current.st_dev, current.st_ino) != self._root_identity
            ):
                raise OSError("Owned Helm input directory identity changed.")
            # Work relative to the verified original descriptor. Renaming the root
            # cannot redirect content deletion into a replacement directory.
            with os.scandir(descriptor) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        shutil.rmtree(entry.name, dir_fd=descriptor)
                    else:
                        os.unlink(entry.name, dir_fd=descriptor)
            current = self.path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino) != self._root_identity:
                raise OSError("Owned Helm input directory identity changed.")
            self.path.rmdir()
            self._closed = True
        except OSError:
            raise AppError(
                "Private Helm input cleanup could not be verified; replacement paths were not removed."
            ) from None
        finally:
            if descriptor >= 0:
                os.close(descriptor)
