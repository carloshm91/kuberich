"""Late driver size events must not override the current physical terminal size."""

import sys

from tests.terminal.pty_support import TerminalSession

APP = """
import logging
from textual.binding import Binding
from textual.events import Resize
from textual.geometry import Size
from kubetrol.config.schema import Settings
from kubetrol.ui.app import KubetrolApp

class ResizeApp(KubetrolApp):
    BINDINGS=[Binding('f12','late_resize','Late resize',priority=True)]
    injected=False
    def action_late_resize(self):
        self.injected=True
        size=Size(140,44)
        self.post_message(Resize(size,size))
    def on_resize(self,event):
        if self.injected:
            self.call_after_refresh(lambda: self._set_status('PHYSICAL SIZE '+str(self.size.width)+' '+str(self.size.height)))

app=ResizeApp(Settings(),logging.getLogger('owned-resize'))
app.run()
raise SystemExit(app.return_code or 0)
"""


def test_native_workspace_rejects_a_late_size_event_from_the_driver(tmp_path):
    with TerminalSession([sys.executable, "-c", APP], tmp_path) as terminal:
        terminal.wait_for_screen("Disconnected")
        terminal.send(b"\x1b[24~")
        terminal.wait_for_screen("PHYSICAL SIZE 100 30")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("workspace-late-resize")
