"""Deliver the actual non-bubbling root-screen lifecycle to its rendering owner."""

from textual.events import ScreenResume, ScreenSuspend
from textual.screen import Screen

from kuberich.ui.foreground import ForegroundGate


class WorkspaceScreen(Screen[None]):
    def __init__(self, foreground: ForegroundGate) -> None:
        super().__init__(id="_default")
        self.foreground = foreground

    def on_screen_resume(self, event: ScreenResume) -> None:
        # is_current also includes visible background screens beneath a modal.
        # A queued lifecycle message must agree with the actual foreground top.
        if self.app.screen_stack and self.app.screen_stack[-1] is self:
            self.foreground.resume()

    def on_screen_suspend(self, event: ScreenSuspend) -> None:
        if not self.app.screen_stack or self.app.screen_stack[-1] is not self:
            self.foreground.suspend()

    def on_unmount(self) -> None:
        self.foreground.close()
