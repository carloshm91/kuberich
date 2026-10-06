"""Bounded asynchronous subprocess sessions with explicit lifecycle ownership."""

import asyncio
import os
import shutil
import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import cast

from kubetrol.domain.processes import (
    ProcessCommand,
    ProcessMode,
    ProcessResult,
    ProcessStatus,
    exit_status,
    process_timeout,
)
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy

TargetGuard = Callable[[], None]


async def _finish_owned[T](task: asyncio.Future[T]) -> None:
    """Repeated cancellation cannot abandon an already-started cleanup/spawn."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


def _executable(command: ProcessCommand) -> str:
    environment = dict(command.environment)
    path = os.pathsep.join(
        str(Path(part) if Path(part).is_absolute() else command.directory / part)
        for part in os.get_exec_path(environment)
    )
    name = command.argv[0]
    if os.sep in name:
        name = str(Path(name) if Path(name).is_absolute() else command.directory / name)
    resolved = shutil.which(name, path=path)
    if resolved is None:
        raise AppError("Executable is unavailable; check its installation, PATH and permissions.")
    return resolved


def _signal_group(pid: int, value: signal.Signals) -> bool:
    try:
        os.killpg(pid, value)
        return True
    except ProcessLookupError:
        return False


class _Output(asyncio.SubprocessProtocol):
    def __init__(self, limit: int) -> None:
        loop = asyncio.get_running_loop()
        self.exited: asyncio.Future[None] = loop.create_future()
        self.disconnected: asyncio.Future[None] = loop.create_future()
        self.overflow: asyncio.Future[None] = loop.create_future()
        self.failed: asyncio.Future[None] = loop.create_future()
        self.remaining = limit
        self.buffers = {1: bytearray(), 2: bytearray()}
        self.transport: asyncio.SubprocessTransport

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.transport = cast(asyncio.SubprocessTransport, transport)

    def pipe_data_received(self, fd: int, data: bytes) -> None:
        exceeds = len(data) > self.remaining
        self.buffers[fd].extend(data[: self.remaining])
        self.remaining = max(0, self.remaining - len(data))
        if exceeds and not self.overflow.done():
            self.overflow.set_result(None)

    def pipe_connection_lost(self, fd: int, exc: Exception | None) -> None:
        if exc is not None and not self.failed.done():
            self.failed.set_result(None)

    def process_exited(self) -> None:
        self.exited.set_result(None)

    def connection_lost(self, exc: Exception | None) -> None:
        self.disconnected.set_result(None)


class ProcessSession:
    """A background/foreground handle whose waiters cannot detach its owner."""

    def __init__(
        self,
        transport: asyncio.SubprocessTransport,
        output: _Output,
        timeout: float | None,
        grace: float,
    ) -> None:
        self.transport, self.output, self.grace = transport, output, grace
        self.stopping: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._monitor(timeout))

    @property
    def pid(self) -> int:
        return self.transport.get_pid()

    async def _cleanup(self) -> None:
        # The leader may have exited while descendants still own its pipes.
        _signal_group(self.pid, signal.SIGCONT)
        if _signal_group(self.pid, signal.SIGTERM):
            await asyncio.sleep(self.grace)
        _signal_group(self.pid, signal.SIGKILL)
        await asyncio.shield(self.output.exited)
        try:
            await asyncio.wait_for(asyncio.shield(self.output.disconnected), 1)
        except TimeoutError:
            self.transport.close()
            await asyncio.shield(self.output.disconnected)
        finally:
            self.transport.close()

    async def _monitor(self, timeout: float | None) -> ProcessResult:
        status: ProcessStatus | None = None
        try:
            done, _ = await asyncio.wait(
                [self.output.exited, self.output.overflow, self.output.failed, self.stopping],
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if self.stopping in done:
                status = ProcessStatus.CANCELLED
            elif not done:
                status = ProcessStatus.TIMED_OUT
            elif self.output.overflow in done:
                status = ProcessStatus.OUTPUT_LIMIT
            elif self.output.failed in done:
                status = ProcessStatus.IO_ERROR
        except asyncio.CancelledError:
            status = ProcessStatus.CANCELLED
        finally:
            cleanup = asyncio.create_task(self._cleanup())
            await _finish_owned(cleanup)
        code = self.transport.get_returncode()
        assert code is not None
        # Final pipe callbacks may arrive after the leader's exit notification.
        if status is None and self.output.overflow.done():
            status = ProcessStatus.OUTPUT_LIMIT
        if status is None and self.output.failed.done():
            status = ProcessStatus.IO_ERROR
        return ProcessResult(
            status or exit_status(code),
            code,
            bytes(self.output.buffers[1]),
            bytes(self.output.buffers[2]),
        )

    async def wait(self) -> ProcessResult:
        return await asyncio.shield(self.task)

    async def close(self) -> ProcessResult:
        if not self.task.done() and not self.stopping.done():
            self.stopping.set_result(None)
        await _finish_owned(self.task)
        return self.task.result()


class ProcessRunner:
    def __init__(
        self,
        policy: AccessPolicy,
        *,
        output_limit: int = 1024 * 1024,
        terminate_grace: float = 0.15,
    ) -> None:
        if type(output_limit) is not int or not 1 <= output_limit <= 8 * 1024 * 1024:
            raise AppError("Process output limit must be between one byte and 8 MiB.")
        if type(terminate_grace) not in (int, float) or not 0 < terminate_grace <= 5:
            raise AppError(
                "Process termination grace must be greater than zero and at most five seconds."
            )
        self.policy, self.output_limit, self.grace = policy, output_limit, terminate_grace
        self._sessions: set[ProcessSession] = set()
        self._launches: set[asyncio.Task[ProcessSession]] = set()
        self._closed = False
        self._closing: asyncio.Task[None] | None = None
        self._terminal_busy = False

    @contextmanager
    def reserve_terminal(self) -> Iterator[None]:
        if self._terminal_busy:
            raise AppError("Another terminal handoff is already active.")
        self._terminal_busy = True
        try:
            yield
        finally:
            self._terminal_busy = False

    @property
    def active_count(self) -> int:
        return len(self._sessions) + len(self._launches)

    def require(
        self, command: ProcessCommand, mode: ProcessMode, guard: TargetGuard | None
    ) -> None:
        if self._closed:
            raise AppError("Process runner is closed.")
        if command.mode is not mode:
            raise AppError("The command process mode does not match this operation.")
        self.policy.require(command.purpose.action)
        if command.target is not None and guard is None:
            raise AppError("A captured resource process requires a current-target guard.")
        if guard is not None:
            guard()

    async def _launch(
        self,
        command: ProcessCommand,
        timeout: float | None,
        guard: TargetGuard | None,
        terminal_fd: int | None,
    ) -> ProcessSession:
        resolving = asyncio.create_task(asyncio.to_thread(_executable, command))
        try:
            executable = await asyncio.shield(resolving)
        except asyncio.CancelledError:
            await _finish_owned(resolving)
            raise
        self.require(command, command.mode, guard)
        try:
            output = _Output(self.output_limit)
            foreground = terminal_fd is not None
            transport, _ = await asyncio.get_running_loop().subprocess_exec(
                lambda: output,
                executable,
                *command.argv[1:],
                env=dict(command.environment),
                cwd=command.directory,
                stdin=terminal_fd if foreground else asyncio.subprocess.DEVNULL,
                stdout=terminal_fd if foreground else asyncio.subprocess.PIPE,
                stderr=terminal_fd if foreground else asyncio.subprocess.PIPE,
                start_new_session=not foreground,
                process_group=0 if foreground else None,
            )
        except OSError:
            raise AppError(
                "Cannot start the executable; check installation and permissions."
            ) from None
        session = ProcessSession(transport, output, timeout, self.grace)
        self._sessions.add(session)
        session.task.add_done_callback(lambda _: self._sessions.discard(session))
        try:
            self.require(command, command.mode, guard)
        except BaseException:
            await session.close()
            raise
        return session

    async def _start(
        self,
        command: ProcessCommand,
        mode: ProcessMode,
        timeout: float | None,
        guard: TargetGuard | None,
        terminal_fd: int | None = None,
    ) -> ProcessSession:
        self.require(command, mode, guard)
        process_timeout(timeout)
        launching = asyncio.create_task(self._launch(command, timeout, guard, terminal_fd))
        self._launches.add(launching)
        try:
            return await asyncio.shield(launching)
        except asyncio.CancelledError:
            completion = asyncio.gather(launching, return_exceptions=True)
            await _finish_owned(completion)
            result = completion.result()[0]
            if isinstance(result, ProcessSession):
                await result.close()
            raise
        finally:
            self._launches.discard(launching)

    async def capture(
        self,
        command: ProcessCommand,
        *,
        timeout: float = 30,
        guard: TargetGuard | None = None,
    ) -> ProcessResult:
        session = await self._start(command, ProcessMode.CAPTURE, timeout, guard)
        try:
            return await session.wait()
        except asyncio.CancelledError:
            await session.close()
            raise

    async def background(
        self,
        command: ProcessCommand,
        *,
        timeout: float | None = None,
        guard: TargetGuard | None = None,
    ) -> ProcessSession:
        return await self._start(command, ProcessMode.BACKGROUND, timeout, guard)

    async def foreground(
        self,
        command: ProcessCommand,
        *,
        descriptor: int,
        claim: Callable[[int], None],
        guard: TargetGuard | None = None,
    ) -> ProcessResult:
        self.require(command, ProcessMode.FOREGROUND, guard)
        if not os.isatty(descriptor):
            raise AppError("Foreground processes require a real interactive terminal.")
        session = await self._start(command, ProcessMode.FOREGROUND, None, guard, descriptor)
        try:
            if not session.output.exited.done():
                claim(session.pid)
            return await session.wait()
        except BaseException:
            await session.close()
            raise

    async def _shutdown(self) -> None:
        await asyncio.gather(*tuple(self._launches), return_exceptions=True)
        await asyncio.gather(*(session.close() for session in tuple(self._sessions)))

    async def close(self) -> None:
        if self._closing is None:
            self._closed = True
            self._closing = asyncio.create_task(self._shutdown())
        try:
            await asyncio.shield(self._closing)
        except asyncio.CancelledError:
            await _finish_owned(self._closing)
            raise

    async def __aenter__(self) -> "ProcessRunner":
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        await self.close()
