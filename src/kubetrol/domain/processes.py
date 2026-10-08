"""Immutable local commands, explicit Kubernetes scope and faithful exit decisions."""

import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from kubetrol.domain.targets import ResourceTarget
from kubetrol.errors import AppError
from kubetrol.security.arguments import freeze_arguments, validate_argument
from kubetrol.services.access import Action


class ProcessMode(Enum):
    CAPTURE = auto()
    BACKGROUND = auto()
    FOREGROUND = auto()


class ProcessPurpose(Enum):
    EXEC = auto()
    ATTACH = auto()
    PORT_FORWARD = auto()
    EDITOR = auto()
    PLUGIN = auto()
    AUTHENTICATE = auto()

    @property
    def action(self) -> Action:
        return {
            ProcessPurpose.EXEC: Action.EXEC,
            ProcessPurpose.ATTACH: Action.ATTACH,
            ProcessPurpose.PORT_FORWARD: Action.PORT_FORWARD,
            ProcessPurpose.EDITOR: Action.MUTATE,
            ProcessPurpose.PLUGIN: Action.PLUGIN,
            ProcessPurpose.AUTHENTICATE: Action.READ,
        }[self]


class ProcessStatus(Enum):
    SUCCEEDED = auto()
    FAILED = auto()
    SIGNALLED = auto()
    TIMED_OUT = auto()
    OUTPUT_LIMIT = auto()
    IO_ERROR = auto()
    CANCELLED = auto()


def exit_status(returncode: int) -> ProcessStatus:
    if returncode == 0:
        return ProcessStatus.SUCCEEDED
    return ProcessStatus.SIGNALLED if returncode < 0 else ProcessStatus.FAILED


def process_timeout(value: float | None) -> float | None:
    if value is not None and (
        isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= 86400
    ):
        raise AppError("Process timeout must be greater than zero and at most one day.")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class ProcessCommand:
    argv: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    directory: Path
    mode: ProcessMode
    purpose: ProcessPurpose
    target: ResourceTarget | None = None
    terminal_input: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", freeze_arguments(self.argv))
        limit = 257 if self.purpose is ProcessPurpose.AUTHENTICATE else 256
        if len(self.argv) > limit:
            raise AppError("Commands exceed their argument count limit.")
        if not isinstance(self.mode, ProcessMode) or not isinstance(self.purpose, ProcessPurpose):
            raise AppError("Commands require an explicit process mode and purpose.")
        if not isinstance(self.directory, Path) or not self.directory.is_absolute():
            raise AppError("Commands require an absolute captured working directory.")
        if self.target is not None and not isinstance(self.target, ResourceTarget):
            raise AppError("Commands require a valid captured target.")
        if type(self.terminal_input) is not bool:
            raise AppError("Terminal input availability must be true or false.")
        environment = tuple((key, value) for key, value in self.environment)
        if len(environment) > 4096 or len({key for key, _ in environment}) != len(environment):
            raise AppError("Process environment must have bounded, unique names.")
        for key, value in environment:
            validate_argument(key)
            if "=" in key or not isinstance(value, str) or "\0" in value:
                raise AppError("Invalid process environment name or value.")
        object.__setattr__(self, "environment", environment)


@dataclass(frozen=True, slots=True, repr=False)
class ProcessResult:
    status: ProcessStatus
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


def capture_command(
    argv: Sequence[str],
    *,
    environment: Mapping[str, str],
    directory: Path,
    mode: ProcessMode,
    purpose: ProcessPurpose,
    target: ResourceTarget | None = None,
) -> ProcessCommand:
    return ProcessCommand(
        freeze_arguments(argv),
        tuple(environment.items()),
        directory.absolute(),
        mode,
        purpose,
        target,
    )


def capture_kubeconfigs(
    explicit: str | None, environment: Mapping[str, str], directory: Path
) -> tuple[Path, ...]:
    values = (
        [explicit]
        if explicit is not None
        else [value for value in environment.get("KUBECONFIG", "").split(os.pathsep) if value]
    )
    if not values:
        values = [str(Path.home() / ".kube/config")]
    if len(values) > 32:
        raise AppError("KUBECONFIG supports at most 32 file entries.")
    paths = [Path(validate_argument(value)).expanduser() for value in values]
    return tuple(dict.fromkeys(path if path.is_absolute() else directory / path for path in paths))


def kubectl_exec_command(
    target: ResourceTarget,
    kubeconfigs: Sequence[Path],
    shell: Sequence[str],
    *,
    environment: Mapping[str, str],
    directory: Path,
    executable: str = "kubectl",
) -> ProcessCommand:
    if (
        target.group != ""
        or target.resource != "pods"
        or target.namespace is None
        or target.container is None
    ):
        raise AppError("Exec requires a captured pod, namespace and container.")
    command = freeze_arguments(shell)
    if command[0].startswith("-"):
        raise AppError("The selected shell cannot be a command option.")
    paths = tuple(dict.fromkeys(validate_argument(str(path)) for path in kubeconfigs))
    if not paths or len(paths) > 32 or any(not Path(path).is_absolute() for path in paths):
        raise AppError("Exec requires explicit absolute kubeconfig paths.")
    if len(paths) > 1 and any(os.pathsep in path for path in paths):
        raise AppError("Merged kubeconfig paths cannot contain the path separator.")
    variables = dict(environment)
    variables["KUBECONFIG"] = os.pathsep.join(paths)
    config_flag = (f"--kubeconfig={paths[0]}",) if len(paths) == 1 else ()
    return capture_command(
        (
            executable,
            *config_flag,
            f"--context={target.session.context}",
            f"--namespace={target.namespace}",
            "exec",
            "--stdin",
            "--tty",
            f"--container={target.container}",
            target.name,
            "--",
            *command,
        ),
        environment=variables,
        directory=directory,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.EXEC,
        target=target,
    )


def editor_command(
    argv: Sequence[str], filename: Path, *, environment: Mapping[str, str], directory: Path
) -> ProcessCommand:
    path = filename if filename.is_absolute() else directory / filename
    return capture_command(
        (*freeze_arguments(argv), "--", str(path)),
        environment=environment,
        directory=directory,
        mode=ProcessMode.FOREGROUND,
        purpose=ProcessPurpose.EDITOR,
    )
