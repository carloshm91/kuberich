"""Owned native clipboard writers; clipboard contents never enter diagnostics."""

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

from kuberich.domain.clipboard import ClipboardBackend
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.errors import AppError
from kuberich.services.processes import ProcessRunner, ProcessSession, _finish_owned

# Constant program: payload travels on stdin, never as code or command arguments.
MACOS_WRITE = """ObjC.import('AppKit'); ObjC.import('Foundation');
var data = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
var text = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
var board = $.NSPasteboard.generalPasteboard; board.clearContents;
if (!board.setStringForType(text, $.NSPasteboardTypeString)) { throw Error('Clipboard write failed'); }
"""

WAYLAND_FAILURE = (
    "Native clipboard write failed; install wl-copy and check the Wayland session, "
    "or set KUBERICH_CLIPBOARD=osc52."
)


class NativeClipboard:
    def __init__(
        self, runner: ProcessRunner, environment: Mapping[str, str], directory: Path
    ) -> None:
        self.runner, self.environment, self.directory = runner, dict(environment), directory
        self.owner: ProcessSession | None = None
        self.monitor: asyncio.Task[None] | None = None

    async def close(self) -> None:
        owner, self.owner = self.owner, None
        monitor, self.monitor = self.monitor, None
        if owner is not None:
            await owner.close()
        if monitor is not None:
            if not monitor.done() and not monitor.cancelling():
                monitor.cancel()
            await _finish_owned(asyncio.gather(monitor, return_exceptions=True))

    async def write(
        self,
        data: bytes,
        backend: ClipboardBackend,
        *,
        failed: Callable[[AppError], None] | None = None,
    ) -> None:
        await self.close()
        x11 = backend is ClipboardBackend.X11
        wayland = backend is ClipboardBackend.WAYLAND
        selection_owner = x11 or wayland
        command = capture_command(
            ("wl-copy", "--foreground", "--type", "text/plain;charset=utf-8")
            if wayland
            else ("xclip", "-quiet", "-selection", "clipboard")
            if x11
            else (
                "/usr/bin/osascript",
                "-l",
                "JavaScript",
                "-e",
                " ".join(MACOS_WRITE.splitlines()),
            ),
            environment=self.environment,
            directory=self.directory,
            purpose=ProcessPurpose.CLIPBOARD,
            mode=ProcessMode.BACKGROUND if selection_owner else ProcessMode.CAPTURE,
            input_data=data,
        )
        if selection_owner:
            try:
                self.owner = await self.runner.background(command)
            except AppError:
                if wayland:
                    raise AppError(WAYLAND_FAILURE) from None
                raise
            # X11 and Wayland keep a foreground selection owner alive. Detect startup
            # rejection without waiting for that owner's intentional lifetime.
            await asyncio.sleep(0.05)
            if not self.owner.running:
                result = await self.owner.wait()
                if result.status is not ProcessStatus.SUCCEEDED:
                    raise AppError(
                        WAYLAND_FAILURE
                        if wayland
                        else "Native clipboard write failed; check the X11 display."
                    )
            elif failed is not None:
                self.monitor = asyncio.create_task(self._observe(self.owner, failed, backend))
        else:
            result = await self.runner.capture(command, timeout=5)
            if result.status is not ProcessStatus.SUCCEEDED:
                raise AppError("Native clipboard write failed; check local clipboard availability.")

    async def _observe(
        self,
        owner: ProcessSession,
        failed: Callable[[AppError], None],
        backend: ClipboardBackend,
    ) -> None:
        result = await owner.wait()
        if self.owner is owner and result.status not in {
            ProcessStatus.SUCCEEDED,
            ProcessStatus.CANCELLED,
        }:
            failed(
                AppError(
                    WAYLAND_FAILURE
                    if backend is ClipboardBackend.WAYLAND
                    else "Native clipboard writer stopped; check the X11 display."
                )
            )
