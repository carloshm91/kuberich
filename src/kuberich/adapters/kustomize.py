"""Explicit local-only rendering inside an owned private frozen source tree."""

import asyncio
import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from kuberich.adapters.editing import file_worker
from kuberich.domain.kustomize import (
    KUSTOMIZATION_NAMES,
    kustomize_argv,
    kustomize_references,
    local_reference,
)
from kuberich.domain.manifests import MAX_MANIFEST_FILES, MAX_SOURCE_BYTES, ManifestFileSnapshot
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner


class _Staging:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="kuberich-kustomize-")
        self.root = Path(self.temporary.name)

    def prepare(self, files: tuple[ManifestFileSnapshot, ...], relative: str) -> None:
        if (
            not files
            or len(files) > MAX_MANIFEST_FILES
            or sum(len(item.data) for item in files) > MAX_SOURCE_BYTES
        ):
            raise AppError("Kustomize frozen source exceeds its file/byte budget.")
        paths = {item.relative_path for item in files}
        if len(paths) != len(files) or local_reference("", relative or ".") != relative:
            raise AppError("Kustomize staging paths must be unique root-relative entries.")
        for item in files:
            if (
                local_reference("", item.relative_path) != item.relative_path
                or not item.relative_path
                or hashlib.sha256(item.data).hexdigest() != item.sha256
            ):
                raise AppError("Kustomize frozen dependency identity is invalid.")
            if Path(item.relative_path).name in KUSTOMIZATION_NAMES:
                parent = str(Path(item.relative_path).parent)
                parent = "" if parent == "." else parent
                for reference in kustomize_references(item.data):
                    path = local_reference(parent, reference.path)
                    if path not in paths and not any(
                        candidate.startswith(path + "/" if path else "") for candidate in paths
                    ):
                        raise AppError(
                            "Kustomize dependency was not frozen in the selected local closure."
                        )
            destination = self.root / "source" / item.relative_path
            directory = self.root
            for part in ("source", *Path(item.relative_path).parts[:-1]):
                directory /= part
                directory.mkdir(exist_ok=True, mode=0o700)
                directory.chmod(0o700)
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(item.data)
        self.target = self.root / "source" / relative
        if sum((self.target / name).is_file() for name in KUSTOMIZATION_NAMES) != 1:
            raise AppError("Select exactly one frozen local Kustomization.")
        self.config = self.root / "empty-config.yaml"
        descriptor = os.open(self.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(
                b"apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\ncurrent-context: ''\n"
            )
        self.cache = self.root / "cache"
        self.cache.mkdir(mode=0o700)
        self.cache.chmod(0o700)

    def close(self) -> None:
        self.temporary.cleanup()


class KustomizeRenderer:
    def __init__(
        self, policy: AccessPolicy, environment: Mapping[str, str], directory: Path
    ) -> None:
        self.policy, self.environment, self.directory = (
            policy,
            dict(environment),
            directory.absolute(),
        )
        self.runner = ProcessRunner(policy, output_limit=MAX_SOURCE_BYTES)
        self._tasks: set[asyncio.Task[bytes]] = set()
        self._stages: set[_Staging] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None

    @property
    def operation_count(self) -> int:
        return len(self._tasks) + self.runner.active_count + len(self._stages)

    async def render(
        self,
        files: tuple[ManifestFileSnapshot, ...],
        relative_directory: str,
        *,
        guard: Callable[[], None],
    ) -> bytes:
        if self._closed:
            raise AppError("Local Kustomize renderer is closed.")
        task = asyncio.create_task(self._render(files, relative_directory, guard))
        self._tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
            raise
        finally:
            self._tasks.discard(task)

    async def _render(
        self, files: tuple[ManifestFileSnapshot, ...], relative: str, guard: Callable[[], None]
    ) -> bytes:
        def current() -> None:
            self.policy.require(Action.READ)
            guard()
            if self._closed:
                raise AppError("Local Kustomize renderer is closed.")

        current()
        try:
            staged = await file_worker(_Staging, discard=lambda stage: stage.close())
        except OSError:
            raise AppError("Cannot prepare private local Kustomize staging.") from None
        self._stages.add(staged)
        try:
            try:
                await file_worker(lambda: staged.prepare(files, relative))
            except OSError:
                raise AppError("Cannot prepare private local Kustomize staging.") from None
            current()

            def resolve() -> str:
                search = os.pathsep.join(
                    str(Path(part) if Path(part).is_absolute() else self.directory / part)
                    for part in os.get_exec_path(self.environment)
                )
                executable = shutil.which("kubectl", path=search)
                if executable is None:
                    raise ExecutableUnavailable(
                        "kubectl is unavailable; install it before explicit Kustomize rendering."
                    )
                return str(Path(executable).absolute())

            executable = await file_worker(resolve)
            current()
            environment = {
                **self.environment,
                "KUBECONFIG": str(staged.config),
                "KUBECTL_KUBERC": "false",
            }
            command = capture_command(
                kustomize_argv(executable, staged.target, staged.config, staged.cache),
                environment=environment,
                directory=staged.root,
                mode=ProcessMode.CAPTURE,
                purpose=ProcessPurpose.MANIFEST_RENDER,
            )
            result = await self.runner.capture(command, timeout=30, guard=current)
            current()
            if result.status is not ProcessStatus.SUCCEEDED:
                categories = {
                    ProcessStatus.TIMED_OUT: "timed out",
                    ProcessStatus.OUTPUT_LIMIT: "exceeded the 8 MiB output limit",
                    ProcessStatus.CANCELLED: "was cancelled",
                }
                category = categories.get(
                    result.status, "failed or uses unsupported local Kustomize features"
                )
                raise AppError(f"Kustomize render {category}; helper details withheld.")
            # Source and captured stdout/stderr each enforce 8 MiB independently,
            # bounding their combined retained bytes to 16 MiB.
            return result.stdout
        finally:
            cleanup = asyncio.create_task(file_worker(staged.close))
            try:
                await finish_owned(cleanup)
                self._stages.discard(staged)
            except OSError:
                raise AppError(
                    "Private Kustomize staging cleanup could not be confirmed."
                ) from None

    async def _shutdown(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.runner.close()
        for staged in tuple(self._stages):
            try:
                await file_worker(staged.close)
            except OSError:
                raise AppError(
                    "Private Kustomize staging cleanup could not be confirmed."
                ) from None
            self._stages.discard(staged)

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.create_task(self._shutdown())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await finish_owned(self._closing)
            raise
