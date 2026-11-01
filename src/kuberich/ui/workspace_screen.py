"""Deliver the actual non-bubbling root-screen lifecycle to its rendering owner."""

from textual.events import ScreenResume, ScreenSuspend
from textual.screen import Screen

from kuberich.ui.foreground import ForegroundGate


class WorkspaceScreen(Screen[None]):
    def __init__(self, foreground: ForegroundGate) -> None:
        super().__init__(id="_default")
        self.foreground = foreground

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.foreground.resume()

    def on_screen_suspend(self, event: ScreenSuspend) -> None:
        self.foreground.suspend()

    def on_unmount(self) -> None:
        self.foreground.close()
