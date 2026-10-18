"""Owned native clipboard writers; clipboard contents never enter diagnostics."""

import asyncio
from collections.abc import Mapping
from pathlib import Path

from kuberich.domain.clipboard import ClipboardBackend
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.errors import AppError
from kuberich.services.processes import ProcessRunner, ProcessSession

# Constant program: payload travels on stdin, never as code or command arguments.
MACOS_WRITE = """ObjC.import('AppKit'); ObjC.import('Foundation');
var data = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
var text = $.NSString.alloc.initWithDataEncoding(data, $.NSUTF8StringEncoding);
var board = $.NSPasteboard.generalPasteboard; board.clearContents;
if (!board.setStringForType(text, $.NSPasteboardTypeString)) { throw Error('Clipboard write failed'); }
"""


class NativeClipboard:
    def __init__(
        self, runner: ProcessRunner, environment: Mapping[str, str], directory: Path
    ) -> None:
        self.runner, self.environment, self.directory = runner, dict(environment), directory
        self.owner: ProcessSession | None = None

    async def close(self) -> None:
        owner, self.owner = self.owner, None
        if owner is not None:
            await owner.close()

    async def write(self, data: bytes, backend: ClipboardBackend) -> None:
        await self.close()
        x11 = backend is ClipboardBackend.X11
        command = capture_command(
            ("xclip", "-quiet", "-selection", "clipboard")
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
            mode=ProcessMode.BACKGROUND if x11 else ProcessMode.CAPTURE,
            input_data=data,
        )
        if x11:
            self.owner = await self.runner.background(command)
            # X11 keeps a foreground selection owner alive. Detect startup
            # rejection without waiting for that owner's intentional lifetime.
            await asyncio.sleep(0.05)
            if not self.owner.running:
                result = await self.owner.wait()
                if result.status is not ProcessStatus.SUCCEEDED:
                    raise AppError("Native clipboard write failed; check the X11 display.")
        else:
            result = await self.runner.capture(command, timeout=5)
            if result.status is not ProcessStatus.SUCCEEDED:
                raise AppError("Native clipboard write failed; check local clipboard availability.")
