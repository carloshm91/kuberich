"""Literal bounded file-transfer intent; no transport or UI dependencies."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from kuberich.domain.processes import (
    ProcessCommand,
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_TRANSFER_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_BYTES = MAX_TRANSFER_BYTES + 16 * 1024 * 1024
MAX_TRANSFER_ENTRIES = 2048
MAX_TRANSFER_DEPTH = 32
MAX_EXTENDED_METADATA_BYTES = 16 * 1024 * 1024
PAX_FIELDS = frozenset(
    {
        b"path",
        b"linkpath",
        b"size",
        b"mtime",
        b"atime",
        b"ctime",
        b"uid",
        b"gid",
        b"uname",
        b"gname",
        b"charset",
        b"comment",
    }
)


class TransferDirection(Enum):
    UPLOAD = "Upload"
    DOWNLOAD = "Download"


def utf8_size(value: str) -> int:
    try:
        return len(value.encode("utf-8"))
    except UnicodeError:
        raise AppError("Transfer paths require valid UTF-8 text.") from None


def validate_pax_records(data: bytes) -> None:
    """Reject sparse/unknown PAX extensions before tarfile can expand their metadata."""
    offset = 0
    while offset < len(data):
        space = data.find(b" ", offset)
        if space < 0 or space - offset > 6:
            raise AppError("Archive has malformed extended metadata records.")
        digits = data[offset:space]
        if not digits.isdigit():
            raise AppError("Archive has malformed extended metadata lengths.")
        end = offset + int(digits)
        if end > len(data) or end <= space + 1 or data[end - 1] != 10:
            raise AppError("Archive has truncated or malformed extended metadata.")
        key, equals, value = data[space + 1 : end - 1].partition(b"=")
        if not equals or key not in PAX_FIELDS:
            raise AppError("Archive has unsupported or sparse extended metadata.")
        if key == b"size" and (
            not value.isdigit() or len(value) > 10 or int(value) > MAX_TRANSFER_BYTES
        ):
            raise AppError("Archive has invalid or excessive extended payload size.")
        offset = end


def remote_path(value: str) -> PurePosixPath:
    validate_argument(value)
    parts = value.split("/")
    if (
        not value.startswith("/")
        or value == "/"
        or utf8_size(value) > 4096
        or len(parts) > MAX_TRANSFER_DEPTH + 1
        or any(part in {"", ".", ".."} for part in parts[1:])
    ):
        raise AppError("Remote path must be an absolute file/directory path without dot segments.")
    return PurePosixPath(value)


@dataclass(frozen=True, slots=True, repr=False)
class TransferIntent:
    direction: TransferDirection
    target: ResourceTarget
    local: Path
    remote: PurePosixPath
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.direction, TransferDirection):
            raise AppError("Choose an explicit upload or download direction.")
        if (
            self.target.group
            or self.target.resource != "pods"
            or self.target.namespace is None
            or self.target.container is None
        ):
            raise AppError("Transfer requires a captured pod, namespace and container.")
        if (
            not isinstance(self.local, Path)
            or not self.local.is_absolute()
            or not self.local.name
            or ".." in self.local.parts
        ):
            raise AppError("Choose an explicit absolute local file/directory path.")
        validate_argument(str(self.local))
        utf8_size(str(self.local))
        remote_path(str(self.remote))
        if type(self.overwrite) is not bool:
            raise AppError("Overwrite intent must be true or false.")


def transfer_command(
    intent: TransferIntent,
    configuration: Path,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    directory: Path,
    mode: ProcessMode = ProcessMode.CAPTURE,
) -> ProcessCommand:
    if not configuration.is_absolute():
        raise AppError("Transfer requires an absolute captured private kubeconfig.")
    purpose = (
        ProcessPurpose.UPLOAD
        if intent.direction is TransferDirection.UPLOAD
        else ProcessPurpose.DOWNLOAD
    )
    return capture_command(
        (
            "kubectl",
            f"--kubeconfig={configuration}",
            f"--context={intent.target.session.context}",
            f"--namespace={intent.target.namespace}",
            *arguments,
        ),
        environment={**environment, "KUBECONFIG": str(configuration)},
        directory=directory,
        mode=mode,
        purpose=purpose,
        target=intent.target,
    )


def remote_exec(intent: TransferIntent, arguments: Sequence[str]) -> tuple[str, ...]:
    return (
        "exec",
        f"--container={intent.target.container}",
        intent.target.name,
        "--",
        *arguments,
    )


def remote_test_result(result: ProcessResult) -> bool:
    """An exec infrastructure failure is not proof that the destination is absent."""
    if (
        result.status is ProcessStatus.SUCCEEDED
        and result.returncode == 0
        and not result.stdout
        and not result.stderr
    ):
        return True
    if (
        result.status is ProcessStatus.FAILED
        and result.returncode == 1
        and not result.stdout
        and result.stderr == b"command terminated with exit code 1\n"
    ):
        return False
    raise AppError(
        "Remote path check failed. Verify pods/exec permission, test utility and connectivity."
    )


def download_arguments(intent: TransferIntent) -> tuple[str, ...]:
    return remote_exec(
        intent, ("tar", "cf", "-", "-C", str(intent.remote.parent), "--", intent.remote.name)
    )


def upload_arguments(intent: TransferIntent, snapshot: Path) -> tuple[str, ...]:
    if not snapshot.is_absolute():
        raise AppError("Upload requires an absolute private snapshot.")
    if ":" in str(snapshot):
        raise AppError("kubectl cp requires a private source path without colons.")
    return (
        "cp",
        "--retries=0",
        "--no-preserve",
        f"--container={intent.target.container}",
        str(snapshot),
        f"{intent.target.namespace}/{intent.target.name}:{intent.remote}",
    )
