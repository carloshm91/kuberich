"""The owned editor declares Ctrl+C handling independently of its launcher."""

import json
import sys

from tests.support import editing_terminal


def test_editor_ctrl_c_with_an_ignored_parent_signal(tmp_path):
    launcher = tmp_path / "ignored-sigint-cli.py"
    launcher.write_text(
        "import signal\n"
        "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
        "from kuberich.cli import main\n"
        "raise SystemExit(main())\n"
    )
    editing_terminal.terminal_editing(
        [sys.executable, str(launcher)],
        tmp_path,
        "editor-inherited-ignored-sigint",
        scenario="ctrl_c",
    )
    state = json.loads((tmp_path / "owned-editor-path.signals").read_text())
    assert state == {
        "inherited_sigint_ignored": True,
        "python_sigint_handler": True,
        "foreground": True,
        "isig": True,
        "canonical": True,
    }
