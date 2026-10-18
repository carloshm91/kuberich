"""Owned source PTYs verify actual navigation bytes and remote clipboard framing."""

import sys

import pytest

from tests.support.interactions_terminal import terminal_interactions
from tests.support.transports import TerminalTransport


@pytest.mark.parametrize("kind", [None, "ssh", "tmux", "ssh_tmux"])
def test_navigation_and_exact_clipboard_receipt_over_owned_transport(tmp_path, kind):
    command = [sys.executable, "-m", "kuberich"]
    if kind is None:
        terminal_interactions(command, tmp_path, evidence="interactions-native")
    else:
        with TerminalTransport(
            tmp_path / "transport", kind, clipboard_passthrough=True
        ) as transport:
            terminal_interactions(
                command, tmp_path, evidence="interactions-" + kind, transport=transport
            )


@pytest.mark.parametrize("mouse", [False, True])
def test_actual_mouse_reporting_requires_opt_in_and_restores_terminal(tmp_path, mouse):
    from tests.terminal.pty_support import TerminalSession

    (tmp_path / "preferences.yaml").write_text(
        "schema_version: 1\nnavigation:\n  schema_version: 1\n  mouse: " + str(mouse).lower() + "\n"
    )
    with TerminalSession([sys.executable, "-m", "kuberich"], tmp_path) as terminal:
        terminal.wait_for_screen("Disconnected")
        if mouse:
            terminal.wait_for(b"\x1b[?1000h")
            marker = terminal.send(b"\x1b[<0;6;7M\x1b[<0;6;7mowned-mouse-intent")
            terminal.wait_for_screen("owned-mouse-intent", since=marker, row=6)
        else:
            assert b"\x1b[?1000h" not in terminal.transcript
            terminal.wait_for(b"\x1b[?1000l")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence("mouse-opt-in-" + str(mouse).lower())
