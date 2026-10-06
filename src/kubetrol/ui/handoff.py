"""Resume public Textual suspension before propagating errors or cancellation."""

import asyncio
import signal
import sys
from typing import Any

from textual.app import App

from kubetrol.adapters.terminal import TerminalLease
from kubetrol.domain.processes import ProcessCommand, ProcessMode, ProcessResult
from kubetrol.errors import AppError
from kubetrol.services.processes import ProcessRunner, TargetGuard


async def terminal_handoff(
    app: App[Any],
    runner: ProcessRunner,
    command: ProcessCommand,
    *,
    guard: TargetGuard | None = None,
) -> ProcessResult:
    runner.require(command, ProcessMode.FOREGROUND, guard)
    if app.is_headless or app.is_web or sys.__stdin__ is None:
        raise AppError("Terminal handoff requires the native terminal application.")
    owner = asyncio.current_task()
    assert owner is not None
    loop = asyncio.get_running_loop()
    previous = signal.getsignal(signal.SIGTERM)
    termination_requested = False

    def terminate(signum: int, frame: object) -> None:
        nonlocal termination_requested
        termination_requested = True
        loop.call_soon_threadsafe(owner.cancel)

    result: ProcessResult | None = None
    failure: BaseException | None = None
    with runner.reserve_terminal():
        signal.signal(signal.SIGTERM, terminate)
        try:
            with app.suspend():
                try:
                    with TerminalLease(sys.__stdin__.fileno()) as terminal:
                        result = await runner.foreground(
                            command,
                            descriptor=terminal.descriptor,
                            claim=terminal.claim,
                            guard=guard,
                        )
                except BaseException as error:
                    # Textual 8.2.8 resumes after yield, without a finally block.
                    # Let its context exit normally, then re-raise outside suspension.
                    failure = error
        finally:
            signal.signal(signal.SIGTERM, previous)
    if termination_requested:
        # Exiting before App.suspend resumes races driver shutdown/restart.
        app.exit(return_code=143)
    if failure is not None:
        raise failure
    assert result is not None
    return result
