"""Actual terminal shutdown must cleanly unwind after external POSIX signals."""

import os
import signal
import sys

import pytest

from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("signum,code", [(signal.SIGHUP, 129), (signal.SIGTERM, 143)])
def test_external_signal_restores_workspace_terminal(tmp_path, signum, code):
    script = (
        "import os\nfrom pathlib import Path\nfrom kuberich.cli import main\n"
        "Path('application.pid').write_text(str(os.getpid()))\n"
        "raise SystemExit(main())\n"
    )
    with TerminalSession([sys.executable, "-c", script], tmp_path) as terminal:
        terminal.wait_for_screen("Disconnected")
        os.kill(int((tmp_path / "application.pid").read_text()), signum)
        terminal.finish(expected=code)
        terminal.save_evidence(f"workspace-signal-{signum.name.lower()}")
