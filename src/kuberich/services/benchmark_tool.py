"""Private bounded Vegeta execution; no cluster or replayable result authority."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections import deque
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from kuberich.domain.benchmark_results import BenchmarkMetrics, parse_vegeta_report
from kuberich.domain.benchmarks import (
    LoadOptions,
    RequestOptions,
    attack_argv,
    minimal_environment,
    parse_vegeta_version,
    report_argv,
    targets_json,
)
from kuberich.domain.processes import (
    ProcessMode,
    ProcessPurpose,
    ProcessStatus,
    capture_command,
)
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import parse_owned


class BenchmarkToolError(AppError):
    """Fixed classification; raw process output is never part of the exception."""

    def __init__(self, code: str = "tool_failed") -> None:
        self.reason = code
        super().__init__(
            "The benchmark report was invalid; no trustworthy metrics are available."
            if code == "malformed_output"
            else "The benchmark executable failed or exceeded its output/time limit."
        )


class BenchmarkCleanupError(AppError):
    def __init__(self) -> None:
        super().__init__("Private benchmark files could not be removed; cleanup is incomplete.")


def _private_directory(parent: Path) -> Path:
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise AppError("Cannot create private benchmark request files.")
    return Path(tempfile.mkdtemp(prefix="benchmark-", dir=parent))


def _write_private(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


class BenchmarkTool:
    """Run only the configured executable, draining every child and worker on cancel."""

    def __init__(
        self,
        executable: Path,
        policy: AccessPolicy,
        directory: Path,
        guard: Callable[[], None],
    ) -> None:
        if not isinstance(executable, Path) or not executable.is_absolute():
            raise AppError("Benchmark executable must be an explicitly configured absolute path.")
        self.executable, self.policy, self.directory, self.guard = (
            executable,
            policy,
            directory.absolute(),
            guard,
        )
        self._busy = False
        self._pids: deque[int] = deque(maxlen=3)

    @property
    def process_ids(self) -> tuple[int, ...]:
        """Only this run's finite children, retained for owned cleanup verification."""
        return tuple(self._pids)

    def _require(self) -> None:
        self.policy.require(Action.BENCHMARK)
        self.guard()

    async def _capture(self, argv: tuple[str, ...], *, limit: int, timeout: float) -> bytes:
        self._require()
        command = capture_command(
            argv,
            environment=minimal_environment(),
            directory=self.directory,
            mode=ProcessMode.BACKGROUND,
            purpose=ProcessPurpose.BENCHMARK,
        )
        async with ProcessRunner(self.policy, output_limit=limit) as runner:
            process = await runner.background(command, timeout=timeout, guard=self._require)
            self._pids.append(process.pid)
            result = await process.wait()
        self._require()
        if result.status is not ProcessStatus.SUCCEEDED:
            raise BenchmarkToolError()
        return result.stdout

    async def probe(self) -> str:
        """Explicit Run calls this before any forwarding or load, never startup/browse."""
        data = await self._capture((str(self.executable), "-version"), limit=16384, timeout=5)
        try:
            return await parse_owned(lambda: parse_vegeta_version(data))
        except AppError:
            raise BenchmarkToolError() from None

    async def execute(
        self,
        request: RequestOptions,
        load: LoadOptions,
        port: int,
        *,
        version: str,
        reporting: Callable[[], None] = lambda: None,
    ) -> BenchmarkMetrics:
        if self._busy:
            raise AppError("A benchmark process is already owned; wait for cleanup.")
        self._require()
        self._busy = True
        # The worker records ownership before returning. Cancellation can arrive
        # between its completion and this coroutine resuming to receive a value.
        owned: list[Path] = []
        try:
            await parse_owned(lambda: owned.append(_private_directory(self.directory)))
            private = owned[0]
            target = private / str(uuid4())
            payload = await parse_owned(lambda: targets_json(request, port))
            await parse_owned(lambda: _write_private(target, payload))
            self._require()
            raw = await self._capture(
                attack_argv(self.executable, target, load),
                limit=2 * 1024 * 1024,
                timeout=load.duration_seconds + load.timeout_seconds + 2,
            )
            result = private / str(uuid4())
            await parse_owned(lambda: _write_private(result, raw))
            self._require()
            reporting()
            data = await self._capture(report_argv(self.executable, result), limit=65536, timeout=5)
            try:
                metrics = await parse_owned(
                    lambda: parse_vegeta_report(data, load, version=version)
                )
            except AppError:
                raise BenchmarkToolError("malformed_output") from None
            self._require()
            return metrics
        finally:
            try:
                if owned:
                    try:
                        await parse_owned(lambda: shutil.rmtree(owned[0]))
                    except OSError:
                        raise BenchmarkCleanupError() from None
            finally:
                self._busy = False
