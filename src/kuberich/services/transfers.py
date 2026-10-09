"""Reviewed captured transfers with private snapshots, bounded streams and owned cleanup."""

import asyncio
import tarfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO, Any

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.adapters.transfer_files import DownloadDestination, FileInventory, snapshot_upload
from kuberich.domain.attach import verify_attach_target
from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessResult, ProcessStatus
from kuberich.domain.resources import api_segment, resource_record
from kuberich.domain.targets import ResourceTarget
from kuberich.domain.transfers import (
    MAX_ARCHIVE_BYTES,
    TransferDirection,
    TransferIntent,
    download_arguments,
    remote_exec,
    remote_path,
    remote_test_result,
    transfer_command,
    upload_arguments,
)
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import Delegation, capture_delegation, stage_connection
from kuberich.services.logs import PODS
from kuberich.services.processes import ProcessRunner, _finish_owned


async def owned_file_work[T](
    function: Callable[..., T],
    *arguments: Any,
    on_cancel: Callable[[], None] | None = None,
) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *arguments))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel()
        await _finish_owned(asyncio.gather(task, return_exceptions=True))
        raise


@dataclass(slots=True, repr=False)
class _TransferState:
    inventory: FileInventory | None = None
    destination: DownloadDestination | None = None
    used: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class TransferReview:
    intent: TransferIntent
    connection: Delegation
    temporary: TemporaryDirectory[str]
    snapshot: Path
    _state: _TransferState = field(default_factory=_TransferState, init=False)

    @property
    def inventory(self) -> FileInventory | None:
        return self._state.inventory

    @property
    def destination(self) -> DownloadDestination | None:
        return self._state.destination

    @property
    def used(self) -> bool:
        return self._state.used

    def close(self) -> None:
        try:
            if self.destination is not None:
                self.destination.close()
        finally:
            self.temporary.cleanup()


class TransferService:
    def __init__(
        self,
        client: KubernetesSession,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
        *,
        environment: Mapping[str, str],
        directory: Path,
    ) -> None:
        self.client, self.target, self.policy, self.current = client, target, policy, current
        self.environment, self.directory = dict(environment), directory.absolute()
        self.review: TransferReview | None = None
        self._prepared_intent: TransferIntent | None = None
        self._preparing = False
        self.last_message = "No transfer started."

    def require_current(self, direction: TransferDirection) -> None:
        self.policy.require(Action.MUTATE if direction is TransferDirection.UPLOAD else Action.READ)
        if not self.current() or self.target.session.context != self.client.context.name:
            raise AppError("Transfer target is stale; select and review the container again.")

    async def _pod(self, intent: TransferIntent) -> None:
        self.require_current(intent.direction)
        assert intent.target.namespace is not None
        payload = await self.client.get_json(
            PODS.path(intent.target.namespace) + "/" + api_segment(intent.target.name)
        )
        self.require_current(intent.direction)
        verify_attach_target(intent.target, resource_record(PODS, payload, intent.target.namespace))

    def _local_review(self, intent: TransferIntent, connection: Delegation) -> TransferReview:
        temporary = TemporaryDirectory(prefix="copy-", dir=connection.path.parent)
        review = TransferReview(intent, connection, temporary, Path(temporary.name) / "payload")
        self.review = review  # retain ownership even if the awaiting task is cancelled
        self._prepared_intent = intent
        try:
            if intent.direction is TransferDirection.UPLOAD:
                review._state.inventory = snapshot_upload(intent.local, review.snapshot)
            else:
                review._state.destination = DownloadDestination(intent.local, intent.overwrite)
            return review
        except BaseException:
            review.close()
            self.review = None
            raise

    async def prepare(
        self,
        direction: TransferDirection,
        container: str,
        local: str,
        remote: str,
        *,
        overwrite: bool,
    ) -> TransferReview:
        self.require_current(direction)
        if self.review is not None or self._preparing:
            raise AppError("Another transfer review is owned. Close it before reviewing again.")
        self._preparing = True
        try:
            intent = TransferIntent(
                direction,
                replace(self.target, container=container),
                Path(local).expanduser(),
                remote_path(remote),
                overwrite,
            )
            await self._pod(intent)
            connection = capture_delegation(
                self.client, self.environment, self.directory, prefix="copy"
            )
            review = await owned_file_work(self._local_review, intent, connection)
            self.require_current(direction)
            return review
        except BaseException:
            await self.close()
            raise
        finally:
            self._preparing = False

    def _command(
        self,
        review: TransferReview,
        arguments: tuple[str, ...],
        *,
        mode: ProcessMode = ProcessMode.CAPTURE,
    ) -> ProcessCommand:
        material = review.connection
        return transfer_command(
            review.intent,
            material.path,
            arguments,
            environment=dict(material.environment),
            directory=material.directory,
            mode=mode,
        )

    async def _test(
        self, runner: ProcessRunner, review: TransferReview, flag: str, path: str
    ) -> bool:
        command = self._command(review, remote_exec(review.intent, ("test", flag, path)))
        result = await runner.capture(
            command, timeout=30, guard=lambda: self.require_current(review.intent.direction)
        )
        return remote_test_result(result)

    async def _upload(self, runner: ProcessRunner, review: TransferReview) -> ProcessResult:
        intent = review.intent
        for ancestor in reversed(intent.remote.parents):
            if await self._test(runner, review, "-L", str(ancestor)):
                raise AppError("Remote destination ancestors cannot be symbolic links.")
        if not await self._test(runner, review, "-d", str(intent.remote.parent)):
            raise AppError("Remote destination parent must be an existing directory.")
        if await self._test(runner, review, "-L", str(intent.remote)):
            raise AppError("Remote destination cannot be a symbolic link.")
        exists = await self._test(runner, review, "-e", str(intent.remote))
        if exists and not intent.overwrite:
            raise AppError(
                "Remote destination exists. Review explicit overwrite or choose another path."
            )
        if exists and not await self._test(runner, review, "-f", str(intent.remote)):
            raise AppError(
                "Remote overwrite accepts regular files; directory merges and special files are refused."
            )
        if exists and review.inventory is not None and review.inventory.directory:
            raise AppError("An uploaded directory cannot replace an existing file.")
        await self._pod(intent)
        self.last_message = (
            "Upload started; interruption can leave remote partial files. No automatic retry."
        )
        return await runner.capture(
            self._command(review, upload_arguments(intent, review.snapshot)),
            timeout=300,
            guard=lambda: self.require_current(intent.direction),
        )

    async def _download(self, runner: ProcessRunner, review: TransferReview) -> ProcessResult:
        archive = Path(review.temporary.name) / "download.tar"
        command = self._command(
            review, download_arguments(review.intent), mode=ProcessMode.BACKGROUND
        )
        session = await runner.background(
            command, timeout=300, guard=lambda: self.require_current(review.intent.direction)
        )
        total = errors = 0
        output: IO[bytes] | None = None

        def open_output() -> None:
            nonlocal output
            output = archive.open("xb", buffering=0)
            archive.chmod(0o600)

        def write_output(data: bytes) -> None:
            assert output is not None
            written = 0
            while written < len(data):
                count = output.write(data[written:])
                if count <= 0:
                    raise OSError("Cannot write the private download archive.")
                written += count

        try:
            await owned_file_work(open_output)
            assert output is not None
            while True:
                self.require_current(review.intent.direction)
                finished = session.task.done()
                if finished:
                    result = await session.wait()
                    stdout, stderr = result.stdout, result.stderr
                else:
                    stdout, stderr = session.drain_output()
                total += len(stdout)
                errors += len(stderr)
                if total > MAX_ARCHIVE_BYTES or errors > 1024 * 1024:
                    raise AppError(
                        "Transfer exceeds its archive/error-output limit; local destination retained."
                    )
                if stdout:
                    await owned_file_work(write_output, stdout)
                if finished:
                    break
                await asyncio.sleep(0 if stdout else 0.005)
        finally:
            await session.close()
            if output is not None:
                await owned_file_work(output.close)
        if result.status is not ProcessStatus.SUCCEEDED:
            return result
        assert review.destination is not None
        review._state.inventory = await owned_file_work(
            review.destination.extract, archive, review.intent.remote.name
        )
        self.require_current(review.intent.direction)
        await owned_file_work(
            review.destination.publish,
            review.intent.remote.name,
            review.inventory,
            on_cancel=review.destination.cancelled.set,
        )
        return result

    async def execute(self, review: TransferReview) -> str:
        if review is not self.review or review.used or review.intent != self._prepared_intent:
            raise AppError("Transfer requires the owned unused reviewed intent.")
        review._state.used = True
        intent = review.intent
        try:
            self.require_current(intent.direction)
            await self._pod(intent)
            async with (
                stage_connection(review.connection.path, review.connection.configuration),
                ProcessRunner(self.policy, output_limit=8 * 1024 * 1024) as runner,
            ):
                result = (
                    await self._upload(runner, review)
                    if intent.direction is TransferDirection.UPLOAD
                    else await self._download(runner, review)
                )
            if result.status is ProcessStatus.SUCCEEDED:
                inventory = review.inventory
                assert inventory is not None
                self.last_message = f"{intent.direction.value} complete: {inventory.size} bytes, {inventory.entries} entries."
            elif intent.direction is TransferDirection.UPLOAD:
                self.last_message = (
                    f"Upload incomplete (exit {result.returncode}, {result.status.name.lower()}). "
                    "Remote partial files may remain. Check tar, pods/exec and connectivity; no retry was sent."
                )
            else:
                self.last_message = (
                    f"Download incomplete (exit {result.returncode}, {result.status.name.lower()}). "
                    "Local destination retained. Check tar, pods/exec and connectivity."
                )
            return self.last_message
        except asyncio.CancelledError:
            self.last_message = (
                "Download completed while cancellation was being drained."
                if review.destination is not None and review.destination.published
                else "Transfer cancelled; remote partial files may remain. No automatic retry."
                if intent.direction is TransferDirection.UPLOAD
                else "Download cancelled; local destination retained and private partial archive removed."
            )
            raise
        except (AppError, ConnectionProblem, OSError, tarfile.TarError) as error:
            self.last_message = (
                "Upload stopped; inspect the remote destination for partial files. No automatic retry."
                if intent.direction is TransferDirection.UPLOAD
                else "Download refused; local destination retained and private partial archive removed."
            )
            if isinstance(error, (AppError, ConnectionProblem)):
                self.last_message = f"{error} {self.last_message}"
            raise
        finally:
            await self.close()

    async def close(self) -> None:
        review = self.review
        if review is not None:
            try:
                await owned_file_work(review.close)
            finally:
                self.review = None
                self._prepared_intent = None
