"""Actual CLI keystrokes and inner/outer terminal restoration over SSH/tmux."""

import re
import sys

import pytest

from tests.support.handoff import terminal_handoff_trial
from tests.support.log_viewer import terminal_logs
from tests.support.shell import terminal_shell
from tests.support.transports import TerminalTransport
from tests.terminal.pty_support import TerminalSession


@pytest.mark.parametrize("kind", ["tmux", "ssh_tmux"])
def test_tmux_transport_owns_a_short_socket_under_long_temporary_paths(tmp_path, kind):
    long = tmp_path / ("a" * 80) / ("b" * 80)
    long.mkdir(parents=True)
    with (
        TerminalTransport(long / "transport", kind) as transport,
        TerminalSession(
            [sys.executable, "-m", "kubetrol"], tmp_path, transport=transport
        ) as terminal,
    ):
        assert len(str(transport.socket).encode()) < 90
        socket_directory = transport.socket.parent
        terminal.wait_for_screen("Disconnected")
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(f"transport-{kind}-long-path")
    assert not socket_directory.exists()


@pytest.mark.parametrize("kind", ["ssh", "tmux", "ssh_tmux"])
def test_log_scroll_search_pause_focus_and_return_over_real_transport(tmp_path, kind):
    with TerminalTransport(tmp_path / "transport", kind) as transport:
        terminal_logs(
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            evidence=f"transport-{kind}-logs",
            transport=transport,
        )


@pytest.mark.parametrize("kind", ["ssh", "tmux", "ssh_tmux"])
def test_real_transport_workspace_resize_unicode_focus_and_quit(tmp_path, kind):
    with (
        TerminalTransport(tmp_path / "transport", kind) as transport,
        TerminalSession(
            [sys.executable, "-m", "kubetrol"], tmp_path, transport=transport
        ) as terminal,
    ):
        terminal.wait_for_screen("Disconnected")
        # Mount's title is replaced by the first asynchronous view projection.
        # Observe that settled view before resizing.
        terminal.wait_for_screen("pods(all)[0]")
        marker = terminal.send(b"?")
        terminal.wait_for_screen("Keyboard help", since=marker)
        marker = terminal.send(b"\x1b")
        terminal.wait_for_screen("pods(all)[0]", since=marker, absent=("Keyboard help",))
        for width, height in ((40, 12), (120, 40), (60, 18), (100, 30)):
            terminal.resize(width, height)
        terminal.wait_for_screen("Stay in pods", row=28)
        terminal.wait_for_screen("pods(all)[0]")
        marker = terminal.send(b"/\x1b[200~" + "café 你好🙂".encode() + b"\x1b[201~")
        terminal.wait_for("café 你好🙂".encode(), since=marker)
        marker = terminal.send(b"\r")
        terminal.wait_for_screen("Esc → Clear filter", since=marker)
        marker = terminal.send(b"\x1b")
        terminal.wait_for_screen("Esc → Stay in pods", since=marker)
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(f"transport-{kind}-workspace")


@pytest.mark.parametrize("kind", ["ssh", "tmux", "ssh_tmux"])
@pytest.mark.parametrize("scenario", ["success", "ctrl_c", "spawn_error", "hangup"])
def test_real_transport_native_handoff(tmp_path, kind, scenario):
    with TerminalTransport(tmp_path / "transport", kind) as transport:
        terminal_handoff_trial(
            sys.executable,
            tmp_path,
            scenario,
            name=f"transport-{kind}-native-{scenario}",
            transport=transport,
        )


@pytest.mark.parametrize("kind", ["ssh", "tmux", "ssh_tmux"])
@pytest.mark.parametrize(
    "scenario", ["success", "fullscreen", "close", "protocol", "early_close", "hangup"]
)
def test_real_transport_embedded_container_shell(tmp_path, kind, scenario):
    with TerminalTransport(tmp_path / "transport", kind) as transport:
        terminal_shell(
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            scenario,
            evidence=f"transport-{kind}-embedded-{scenario}",
            transport=transport,
        )


def test_lost_ssh_connection_reaps_workspace_and_restores_the_local_terminal(tmp_path):
    with (
        TerminalTransport(tmp_path / "transport", "ssh") as transport,
        TerminalSession(
            [sys.executable, "-m", "kubetrol"], tmp_path, transport=transport
        ) as terminal,
    ):
        terminal.wait_for_screen("Disconnected")
        transport.disconnect()
        terminal.finish(expected=129)
        terminal.save_evidence("transport-ssh-lost-workspace")


def test_lost_ssh_connection_during_native_handoff_reaps_foreground_child(tmp_path):
    with TerminalTransport(tmp_path / "transport", "ssh") as transport:
        terminal_handoff_trial(
            sys.executable,
            tmp_path,
            "lost_ssh",
            name="transport-ssh-lost-native",
            transport=transport,
        )


def test_lost_ssh_connection_during_embedded_shell_reaps_child_and_private_config(tmp_path):
    with TerminalTransport(tmp_path / "transport", "ssh") as transport:
        terminal_shell(
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            "lost_ssh",
            evidence="transport-ssh-lost-embedded",
            transport=transport,
        )


def test_tmux_preserves_embedded_shell_after_ssh_loss_and_reattaches(tmp_path):
    with TerminalTransport(tmp_path / "transport", "ssh_tmux") as transport:
        terminal_shell(
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            "lost_ssh_tmux",
            evidence="transport-ssh-tmux-reattached-embedded",
            transport=transport,
        )


@pytest.mark.parametrize("kind", ["ssh", "tmux", "ssh_tmux"])
@pytest.mark.parametrize("no_color", [False, True])
def test_terminal_color_fallback_remains_readable_and_accepts_keyboard(tmp_path, kind, no_color):
    environment = {"TERM": "xterm", "TEXTUAL_COLOR_SYSTEM": "standard"}
    if no_color:
        environment["NO_COLOR"] = "1"
    with (
        TerminalTransport(tmp_path / "transport", kind) as transport,
        TerminalSession(
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            transport=transport,
            environment=environment,
        ) as terminal,
    ):
        terminal.wait_for_screen("Disconnected")
        terminal.send(b"?")
        terminal.wait_for_screen("Keyboard help")
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Stay in pods", absent=("Keyboard help",))
        terminal.send(b"\x11")
        terminal.finish()
        assert not re.search(rb"\x1b\[[0-9;]*(?:38|48);2;", terminal.transcript)
        terminal.save_evidence(f"transport-{kind}-color-{'off' if no_color else 'standard'}")


def test_tmux_preserves_workspace_after_ssh_loss_and_reattaches_to_the_same_app(tmp_path):
    with TerminalTransport(tmp_path / "transport", "ssh_tmux") as transport:
        with TerminalSession(
            [sys.executable, "-m", "kubetrol"], tmp_path, transport=transport
        ) as terminal:
            terminal.wait_for_screen("Disconnected")
            terminal.send(b"?")
            terminal.wait_for_screen("Keyboard help")
            transport.disconnect()
            terminal.finish()
            terminal.save_evidence("transport-ssh-tmux-detached")
        with TerminalSession(
            [sys.executable, "-m", "kubetrol"], tmp_path, transport=transport
        ) as terminal:
            terminal.wait_for_screen("Keyboard help")
            terminal.send(b"\x1b")
            terminal.wait_for_screen("Stay in pods", absent=("Keyboard help",))
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence("transport-ssh-tmux-reattached")
