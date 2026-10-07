"""Resume public Textual suspension before propagating errors or cancellation."""

import asyncio
import os
import signal
import sys
from typing import Any

from textual.app import App

from kubetrol.adapters.terminal import RevokedTerminalOutput, TerminalLease
from kubetrol.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, ProcessResult
from kubetrol.domain.shell import shell_banner
from kubetrol.errors import AppError, ExitCode
from kubetrol.services.processes import ProcessRunner, TargetGuard
from kubetrol.ui.shutdown import TERMINAL_SIGNALS, terminal_exit_code


async def terminal_handoff(
    app: App[Any],
    runner: ProcessRunner,
    command: ProcessCommand,
    *,
    guard: TargetGuard | None = None,
    timeout: float | None = None,
) -> ProcessResult:
    runner.require(command, ProcessMode.FOREGROUND, guard)
    if app.is_headless or app.is_web or sys.__stdin__ is None:
        raise AppError("Terminal handoff requires the native terminal application.")
    owner = asyncio.current_task()
    assert owner is not None
    loop = asyncio.get_running_loop()
    previous = {signum: signal.getsignal(signum) for signum in TERMINAL_SIGNALS}
    termination_requested: ExitCode | None = None
    output = RevokedTerminalOutput()

    def terminate(signum: int, frame: object) -> None:
        nonlocal termination_requested
        if signum == signal.SIGHUP:
            output.discard_revoked()
        if termination_requested is None:
            termination_requested = terminal_exit_code(signum)
            loop.call_soon_threadsafe(owner.cancel)

    result: ProcessResult | None = None
    failure: BaseException | None = None
    with runner.reserve_terminal():
        try:
            for signum in TERMINAL_SIGNALS:
                signal.signal(signum, terminate)
            with app.suspend():
                try:
                    with TerminalLease(sys.__stdin__.fileno()) as terminal:
                        if command.purpose is ProcessPurpose.EXEC and command.target is not None:
                            terminal.present(
                                shell_banner(
                                    command.target,
                                    os.get_terminal_size(terminal.descriptor).columns,
                                )
                            )
                        elif command.purpose is ProcessPurpose.AUTHENTICATE:
                            terminal.present(
                                "Kubetrol · configured Azure authentication\r\nCtrl+C cancels login and returns to the workspace.\r\n\r\n"
                            )
                        result = await runner.foreground(
                            command,
                            descriptor=terminal.descriptor,
                            claim=terminal.claim,
                            guard=guard,
                            timeout=timeout,
                        )
                except BaseException as error:
                    # Textual 8.2.8 resumes after yield, without a finally block.
                    # Let its context exit normally, then re-raise outside suspension.
                    failure = error
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    if termination_requested:
        # Exiting before App.suspend resumes races driver shutdown/restart.
        app.exit(return_code=termination_requested)
    if failure is not None:
        raise failure
    assert result is not None
    return result
