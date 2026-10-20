"""Read kubeconfig files for review and save one reviewed edit with a backup."""

import hashlib
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from kuberich.config.catalog import parse_kubeconfig, regular_bytes
from kuberich.domain.kubeconfig_edit import ContextEditPlan, KubeconfigDocument
from kuberich.errors import AppError, ExitCode


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_documents(paths: list[Path]) -> tuple[KubeconfigDocument, ...]:
    """Parse existing files in precedence order; missing optional entries are skipped."""
    documents = []
    for path in paths:
        if not path.exists():
            continue
        try:
            raw = regular_bytes(path)
        except OSError:
            raise AppError(
                "Cannot read kubeconfig; check the file and permissions.", ExitCode.LOCAL_IO
            ) from None
        commented = any(line.lstrip().startswith(b"#") for line in raw.splitlines())
        documents.append(KubeconfigDocument(path, parse_kubeconfig(raw), _digest(raw), commented))
    return tuple(documents)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save_plan(plan: ContextEditPlan, now: datetime) -> Path:
    """Write a 0600 backup, then atomically replace the reviewed file; return the backup.

    Symbolic links are kept: the edit goes to the file they point to. A file that
    changed after review is never overwritten, and a failed save removes its backup.
    """
    committed = False
    backup: Path | None = None
    try:
        real = plan.path.resolve(strict=True)
        raw = regular_bytes(real)
        if _digest(raw) != plan.digest:
            raise AppError("The kubeconfig file changed after review. Review again.")
        text = yaml.safe_dump(
            plan.document, sort_keys=False, allow_unicode=True, default_flow_style=False
        )
        parse_kubeconfig(text.encode("utf-8"))
        mode = stat.S_IMODE(os.stat(real).st_mode)
        candidate = real.with_name(f"{real.name}.kuberich-{now:%Y%m%dT%H%M%S%f}.bak")
        descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        backup = candidate
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        descriptor, name = tempfile.mkstemp(prefix=".kuberich-", suffix=".tmp", dir=real.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                os.fchmod(stream.fileno(), mode)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            if _digest(regular_bytes(real)) != plan.digest:
                raise AppError("The kubeconfig file changed after review. Review again.")
            os.replace(temporary, real)
            committed = True
            _fsync_directory(real.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return backup
    except (yaml.YAMLError, RecursionError):
        raise AppError("The edited kubeconfig cannot be written as safe YAML.") from None
    except OSError:
        if committed:
            raise AppError(
                "The kubeconfig was saved, but durability could not be confirmed.",
                ExitCode.LOCAL_IO,
            ) from None
        raise AppError(
            "Cannot save the kubeconfig; check permissions and free space.", ExitCode.LOCAL_IO
        ) from None
    finally:
        if not committed and backup is not None:
            backup.unlink(missing_ok=True)
