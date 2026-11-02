"""Bounded selection receipt on a disposable X11 display, using synthetic bytes."""

import asyncio
import json
import os
import subprocess
from collections import deque
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from kuberich.adapters.editing import file_worker
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.services.processes import ProcessRunner


@asynccontextmanager
async def owned_x11_display() -> AsyncIterator[dict[str, str]]:
    read_fd, initial_write_fd = os.pipe()
    write_fd: int | None = initial_write_fd
    server = None
    first: BaseException | None = None
    try:
        # A replacement can leave no X11 clients while the next writer starts.
        # Keep this fixture's server generation until its explicit shutdown.
        server = subprocess.Popen(
            ["Xvfb", "-noreset", "-displayfd", str(initial_write_fd), "-nolisten", "tcp"],
            pass_fds=(initial_write_fd,),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        write_fd = None
        os.close(initial_write_fd)
        os.set_blocking(read_fd, False)
        display = bytearray()
        async with asyncio.timeout(10):
            while b"\n" not in display:
                try:
                    chunk = os.read(read_fd, 32)
                except BlockingIOError:
                    await asyncio.sleep(0.005)
                    continue
                if not chunk:
                    raise RuntimeError("Owned Xvfb closed its readiness pipe.")
                display.extend(chunk)
                if len(display) > 32:
                    raise RuntimeError("Owned Xvfb readiness exceeded its bound.")
        number = display.decode("ascii").strip()
        if not number.isdecimal():
            raise RuntimeError("Owned Xvfb did not provide a display number.")
        yield {**os.environ, "DISPLAY": ":" + number}
    except BaseException as error:
        first = error
        raise
    finally:
        errors: list[BaseException] = []
        for descriptor in (read_fd, write_fd):
            if descriptor is None:
                continue
            try:
                os.close(descriptor)
            except BaseException as close_error:
                errors.append(close_error)
        if server is not None:

            def stop() -> None:
                assert server is not None
                if server.poll() is None:
                    server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=2)

            try:
                await file_worker(stop)
            except BaseException as server_error:
                errors.append(server_error)
        if first is not None:
            for cleanup_error in errors:
                first.add_note(f"Owned X11 cleanup failed: {type(cleanup_error).__name__}")
        elif errors:
            raise BaseExceptionGroup("Owned X11 cleanup failed", errors)


async def read_x11_selection(
    runner: ProcessRunner,
    environment: Mapping[str, str],
    directory: Path,
    expected: bytes,
    *,
    receipt: Path,
    timeout: float = 5,
) -> bytes:
    """Observe receipt without treating process launch as selection readiness."""
    deadline = asyncio.get_running_loop().time() + timeout
    attempts = 0
    observations: deque[dict[str, object]] = deque(maxlen=16)
    ready = False
    first: BaseException | None = None
    try:
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("Owned X11 selection did not serve the expected bytes in time.")
            result = await runner.capture(
                capture_command(
                    ("xclip", "-selection", "clipboard", "-o"),
                    environment=environment,
                    directory=directory,
                    purpose=ProcessPurpose.CLIPBOARD,
                    mode=ProcessMode.CAPTURE,
                ),
                timeout=remaining,
            )
            attempts += 1
            ready = (
                result.status is ProcessStatus.SUCCEEDED
                and result.returncode == 0
                and result.stdout == expected
            )
            observations.append(
                {
                    "status": result.status.name,
                    "returncode": result.returncode,
                    "stdout_bytes": len(result.stdout),
                    "stderr_bytes": len(result.stderr),
                    "matched": ready,
                }
            )
            if ready:
                return result.stdout
            await asyncio.sleep(min(0.01, max(0, deadline - asyncio.get_running_loop().time())))
    except BaseException as error:
        first = error
        raise
    finally:
        try:
            receipt.write_text(
                json.dumps(
                    {"ready": ready, "attempts": attempts, "recent": list(observations)}, indent=2
                )
                + "\n"
            )
        except OSError as evidence_error:
            if first is None:
                raise
            first.add_note(f"Selection readiness receipt failed: {type(evidence_error).__name__}")
