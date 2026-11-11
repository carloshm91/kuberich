"""Bounded user-template capture below the selected physical config directory."""

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.domain.exports import DirectoryRef
from kuberich.domain.manifests import MAX_MANIFEST_FILES, MAX_SOURCE_BYTES, ManifestFileSnapshot
from kuberich.errors import AppError


@dataclass(frozen=True, slots=True)
class TemplateFilesCapture:
    root: DirectoryRef | None
    snapshots: tuple[ManifestFileSnapshot, ...]
    unavailable: tuple[str, ...]


class TemplateFiles:
    """Synchronous port; its service owns cancellation and drains worker threads."""

    def __init__(self, config_path: Path, directory: Path) -> None:
        self.directory = directory.absolute()
        selected = config_path.expanduser()
        self.config_path = selected if selected.is_absolute() else self.directory / selected
        self.files = ManifestFiles(cwd=self.directory)
        self.root: DirectoryRef | None = None

    def capture(self, *, cancel: threading.Event) -> TemplateFilesCapture:
        if self.root is None:
            try:
                physical = self.config_path.parent.resolve(strict=True)
            except FileNotFoundError:
                return TemplateFilesCapture(None, (), ())
            except (OSError, RuntimeError):
                raise AppError("Selected template config directory is unavailable.") from None
            self.root = self.files.root(physical, cancel=cancel)
        root = self.root
        listing = self.files.list(root, "", cancel=cancel)
        if listing.limited:
            raise AppError("Selected config directory exceeds the bounded template listing.")
        entry = next((item for item in listing.entries if item.relative_path == "templates"), None)
        if entry is None:
            # The manifest browser intentionally omits ordinary extensionless files.
            # Distinguish an absent catalog from an occupied non-directory name.
            try:
                os.lstat(root.path / "templates")
            except FileNotFoundError:
                self.files.list(root, "", cancel=cancel)
            except OSError:
                raise AppError("Selected user template entry is unavailable.") from None
            else:
                raise AppError(
                    "User templates must be an ordinary directory below the selected config root."
                )
            return TemplateFilesCapture(root, (), ())
        if entry.kind != "directory":
            raise AppError(
                "User templates must be an ordinary directory below the selected config root."
            )
        templates = self.files.list(root, "templates", cancel=cancel)
        candidates = tuple(
            item
            for item in templates.entries
            if Path(item.relative_path).suffix.lower() in {".yaml", ".yml", ".json"}
        )
        if templates.limited or len(candidates) > MAX_MANIFEST_FILES:
            raise AppError("User template catalog exceeds 256 files or its directory bound.")
        snapshots: list[ManifestFileSnapshot] = []
        unavailable: list[str] = []
        total = 0
        for item in candidates:
            if item.kind not in {"manifest", "kustomization"}:
                unavailable.append(item.relative_path)
                continue
            try:
                snapshot = self.files.read(root, item.relative_path, cancel=cancel)
            except AppError:
                if cancel.is_set():
                    raise
                unavailable.append(item.relative_path)
                continue
            total += len(snapshot.data)
            if total > MAX_SOURCE_BYTES:
                raise AppError("User template catalog exceeds 8 MiB combined input.")
            snapshots.append(snapshot)
        self.files.require_unchanged(root, tuple(snapshots), cancel=cancel)
        return TemplateFilesCapture(root, tuple(snapshots), tuple(unavailable))

    def require_current(self, capture: TemplateFilesCapture, *, cancel: threading.Event) -> None:
        current = self.capture(cancel=cancel)
        if current != capture:
            raise AppError("User template catalog changed; select and render a fresh template.")
