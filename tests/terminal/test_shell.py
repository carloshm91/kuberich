"""Start the actual CLI in a real PTY, then verify exit, resize and error restoration."""

import sys
from pathlib import Path

import pytest

from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("exit_key", [b"q", b"\x11", b"\x03"])
def test_real_terminal_navigation_resize_and_quit(tmp_path: Path, exit_key: bytes) -> None:
    with TerminalSession([sys.executable, "-m", "kubetrol"], tmp_path) as terminal:
        terminal.wait_for(b"Disconnected")
        marker = terminal.send(b"?")
        terminal.wait_for(b"Keyboard help", since=marker)
        marker = terminal.send(b"\x1b")
        terminal.wait_for(b"No cluster connection", since=marker)
        marker = terminal.resize(50, 16)
        terminal.wait_for(b"Namespace:", since=marker)
        terminal.send(exit_key)
        terminal.finish()
        terminal.save_evidence(f"quit-{exit_key.hex()}")


@pytest.mark.parametrize("attempt", range(3))
def test_real_terminal_submitted_quit_command(tmp_path: Path, attempt: int) -> None:
    with TerminalSession([sys.executable, "-m", "kubetrol"], tmp_path) as terminal:
        terminal.wait_for(b"Disconnected")
        terminal.send(b":quit\r")
        terminal.finish()
        terminal.save_evidence(f"command-quit-{attempt}")


def test_real_terminal_unicode_filter_paste_and_return(tmp_path: Path) -> None:
    with TerminalSession([sys.executable, "-m", "kubetrol"], tmp_path) as terminal:
        terminal.wait_for(b"Disconnected")
        marker = terminal.send(b"/\x1b[200~" + "café🙂".encode() + b"\x1b[201~")
        terminal.wait_for("café🙂".encode(), since=marker)
        marker = terminal.send(b"\r")
        # The trail changes only when input focus actually returns to the table.
        terminal.wait_for_screen("Esc → Clear filter", since=marker)
        terminal.send(b"q")
        terminal.finish()
        terminal.save_evidence("unicode-paste")


def test_real_terminal_error_restores_tty_and_does_not_expose_values(tmp_path: Path) -> None:
    code = (
        "import sys\n"
        "from kubetrol import cli\n"
        "from kubetrol.ui import launch\n"
        "from kubetrol.ui.app import KubetrolApp\n"
        "class BrokenApp(KubetrolApp):\n"
        "    def on_mount(self):\n"
        "        super().on_mount()\n"
        "        raise RuntimeError('opaque-sensitive-pty-value')\n"
        "launch.KubetrolApp = BrokenApp\n"
        "sys.exit(cli.main())\n"
    )
    with TerminalSession([sys.executable, "-c", code], tmp_path) as terminal:
        terminal.finish(expected=1)
        assert b"Terminal interface failed" in terminal.transcript
        assert b"opaque-sensitive-pty-value" not in terminal.transcript
        terminal.save_evidence("failure")
    contents = (tmp_path / "kubetrol.log").read_text()
    assert "exception=RuntimeError" in contents and "opaque-sensitive-pty-value" not in contents


def test_real_terminal_initial_help_and_readonly_with_hidden_header(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-m",
        "kubetrol",
        "--readonly",
        "--headless",
        "--crumbsless",
        "-c",
        "help",
    ]
    with TerminalSession(command, tmp_path) as terminal:
        terminal.wait_for(b"Keyboard help")
        marker = terminal.send(b"\x1b")
        # Wait for restored workspace bindings, not a background redraw beneath help.
        terminal.wait_for_screen(
            "Resources · no connection", since=marker, absent=("Keyboard help",)
        )
        assert b"Read-only" in terminal.transcript
        marker = terminal.send(b":shell\r")
        terminal.wait_for(b"Read-only mode blocks", since=marker)
        terminal.send(b"q")
        terminal.finish()
        terminal.save_evidence("launch-readonly-help")


def test_real_terminal_initial_quit_restores_tty(tmp_path: Path) -> None:
    with TerminalSession(
        [sys.executable, "-m", "kubetrol", "--command", "quit"], tmp_path
    ) as terminal:
        terminal.finish()
        terminal.save_evidence("launch-initial-quit")
