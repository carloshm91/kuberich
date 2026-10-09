"""Explicit copy paths, review/default Cancel and cancellation-owned transfer progress."""

import asyncio
import tarfile
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Static

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.transfers import TransferDirection
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.processes import _finish_owned
from kuberich.services.transfers import TransferReview, TransferService
from kuberich.ui.port_forwards import ForwardInput


class TransferScreen(ModalScreen[str]):
    AUTO_FOCUS = "#copy-local"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    TransferScreen { align: center middle; background: $background 80%; }
    #copy-form { width: 96%; max-width: 100; height: 94%; max-height: 29;
        border: round $primary; padding: 0 1; background: $surface; }
    #copy-title { height: 1; text-overflow: ellipsis; }
    #copy-fields { height: 1fr; }
    #copy-fields Static { height: auto; }
    #copy-overwrite { height: 3; border: none; }
    #copy-feedback { height: auto; max-height: 3; }
    #copy-buttons { height: 1; }
    #copy-buttons Button { height: 1; border: none; min-width: 9; }
    """

    def __init__(
        self, source: TransferService, container: str, direction: TransferDirection
    ) -> None:
        super().__init__()
        self.source, self.container, self.direction = source, container, direction
        self.review: TransferReview | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._transferring = False

    def compose(self) -> ComposeResult:
        target = self.source.target
        with Vertical(id="copy-form"):
            yield Static(
                f"{self.direction.value} · review before copying", markup=False, id="copy-title"
            )
            with VerticalScroll(id="copy-fields"):
                yield Static(
                    safe_text(
                        f"Context: {target.session.context}\nPod: {target.namespace}/{target.name}\n"
                        f"Container: {self.container}\nUID: {target.uid}",
                        multiline=True,
                    ),
                    id="copy-target",
                )
                yield Static("Absolute local path · exact source/destination", markup=False)
                yield ForwardInput(max_length=4096, placeholder="/absolute/path", id="copy-local")
                yield Static("Absolute remote path · exact source/destination", markup=False)
                yield ForwardInput(max_length=4096, placeholder="/tmp/file", id="copy-remote")
                yield Checkbox("Allow replacement of an existing regular file", id="copy-overwrite")
                yield Static("", markup=False, id="copy-preview")
            yield Static(
                "Requires tar in the container; uploads also require test. 512 MiB / 2,048 entries."
                " Symlinks/special files and directory merges are refused.",
                markup=False,
                id="copy-feedback",
            )
            with Horizontal(id="copy-buttons"):
                yield Button("Review", variant="primary", compact=True, id="copy-review")
                yield Button(
                    "Confirm", variant="warning", compact=True, id="copy-confirm", disabled=True
                )
                yield Button("Cancel", compact=True, id="copy-cancel")

    def _status(self, message: str) -> None:
        self.query_one("#copy-feedback", Static).update(safe_text(message, multiline=True))

    def _fields(self) -> tuple[str, str, bool]:
        return (
            self.query_one("#copy-local", Input).value,
            self.query_one("#copy-remote", Input).value,
            self.query_one("#copy-overwrite", Checkbox).value,
        )

    @on(Input.Changed)
    @on(Checkbox.Changed)
    def changed(self) -> None:
        self.review = None
        self.query_one("#copy-confirm", Button).disabled = True
        self.query_one("#copy-preview", Static).update("")

    @on(Input.Submitted)
    @on(Button.Pressed, "#copy-review")
    def prepare(self) -> None:
        if self._operation_task is not None and not self._operation_task.done():
            return
        self.review = None
        self.query_one("#copy-confirm", Button).disabled = True
        self._operation_task = asyncio.create_task(self._prepare(self._fields()))

    async def _prepare(self, fields: tuple[str, str, bool]) -> None:
        await self.source.close()
        self._status("Checking the captured pod and preparing protected local state…")
        try:
            local, remote, overwrite = fields
            review = await self.source.prepare(
                self.direction, self.container, local, remote, overwrite=overwrite
            )
        except (AppError, OSError, ConnectionProblem):
            self._status(
                "Review refused. Check absolute paths, links, file limits, permissions and running container."
            )
            return
        if fields != self._fields():
            await self.source.close()
            self._status("Paths changed during preparation. Review the current fields again.")
            return
        self.review = review
        size = (
            f"{review.inventory.size} bytes / {review.inventory.entries} entries in a frozen snapshot"
            if review.inventory is not None
            else "Remote size unknown; at most 512 MiB / 2,048 entries"
        )
        intent = review.intent
        source = (
            str(intent.local) if self.direction is TransferDirection.UPLOAD else str(intent.remote)
        )
        destination = (
            str(intent.remote) if self.direction is TransferDirection.UPLOAD else str(intent.local)
        )
        self.query_one("#copy-preview", Static).update(
            safe_text(
                f"{self.direction.value}\nSource: {source}\nDestination: {destination}\nSize: {size}\n"
                f"Overwrite: {'explicit regular-file replacement' if intent.overwrite else 'refuse existing destination'}\n"
                "Requires tar; no automatic retry. Upload cancellation may leave remote partial files."
                " Download staging is removed on cancellation.",
                multiline=True,
            )
        )
        self.query_one("#copy-confirm", Button).disabled = False
        self.set_focus(self.query_one("#copy-cancel", Button))
        self._status("Review paths and overwrite intent. Confirm performs one transfer.")

    @on(Button.Pressed, "#copy-confirm")
    def confirm(self) -> None:
        if (
            self.review is None
            or self._transferring
            or (self._operation_task is not None and not self._operation_task.done())
        ):
            return
        self._transferring = True
        for name in ("local", "remote", "overwrite", "review", "confirm"):
            self.query_one(f"#copy-{name}").disabled = True
        self._operation_task = asyncio.create_task(self._execute(self.review))

    async def _execute(self, review: TransferReview) -> None:
        self._status("Transferring the captured paths… Cancel stops and drains owned local work.")
        try:
            message = await self.source.execute(review)
        except (AppError, OSError, ConnectionProblem, tarfile.TarError):
            message = self.source.last_message
        self._status(message)
        self._transferring = False
        self.query_one("#copy-cancel", Button).label = "Back"

    @on(Button.Pressed, "#copy-cancel")
    async def cancel(self) -> None:
        if self._transferring:
            self._status("Cancelling and draining owned local work…")
        await self.stop_owned()
        self.dismiss(self.source.last_message)

    async def stop_owned(self) -> None:
        if self._operation_task is not None:
            if not self._operation_task.done() and not self._operation_task.cancelling():
                self._operation_task.cancel()
            await _finish_owned(asyncio.gather(self._operation_task, return_exceptions=True))
        await self.source.close()

    async def on_unmount(self) -> None:
        await self.stop_owned()
