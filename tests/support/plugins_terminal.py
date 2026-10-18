"""Original harmless plugin programs and real source/wheel/native CLI interactions."""

import threading
from pathlib import Path

import yaml

from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession

PROGRAM = """#!/bin/sh
set -eu
[ -r "$KUBECONFIG" ]
[ "$KUBERICH_CONTEXT" = kuberich-test-pty ]
if [ -f "$1" ]; then
    IFS= read -r previous < "$1"
    [ ! -e "$previous" ] || exit 24
fi
case "$2" in
    probe) printf 'PLUGIN_CLEAN\\n'; exit 0 ;;
    background) printf 'PLUGIN_BACKGROUND\\n'; exit 0 ;;
esac
printf '%s\\n' "$KUBECONFIG" > "$1"
printf 'PLUGIN_READY\\n'
IFS= read -r reply
printf 'PLUGIN_INPUT %s\\n' "$reply"
"""


def plugin_definitions(directory: Path) -> dict[str, dict[str, object]]:
    program = directory / "owned-plugin.sh"
    program.write_text(PROGRAM)
    marker = directory / "owned-plugin-config-path"
    return {
        name: {
            "command": "/bin/sh",
            "args": [str(program), str(marker), kind],
            "scopes": ["v1/pods"],
            "mode": mode,
            "dangerous": False,
            "trusted_read_only": True,
            "confirm": True,
            "timeout": 20,
        }
        for name, kind, mode in (
            ("trial-interactive", "interactive", "foreground"),
            ("trial-probe", "probe", "capture"),
            ("trial-background", "background", "background"),
        )
    }


def review_and_run(terminal: TerminalSession, name: str) -> int:
    marker = terminal.send(f":plugin {name}\r".encode())
    terminal.wait_for_screen("Plugin: " + name, since=marker)
    # Default focus is Cancel: reverse Tab reaches Review, then Run once enabled.
    terminal.send(b"\x1b[Z\r")
    terminal.wait_for_screen("Review complete")
    return terminal.send(b"\x1b[Z\r")


def exercise_view_preferences(terminal: TerminalSession) -> None:
    marker = terminal.send(b":views\r")
    terminal.wait_for_screen("View · v1/pods", since=marker)
    terminal.wait_for_screen("Available:", since=marker)
    marker = terminal.send(b"\x1b")
    terminal.wait_for_screen("Sort NAME", since=marker, absent=("Available:", "View · v1/pods"))


def exercise_plugins(terminal: TerminalSession) -> None:
    for _ in range(2):
        marker = review_and_run(terminal, "trial-interactive")
        terminal.wait_for(b"PLUGIN_READY", since=marker)
        terminal.send(b"owned-input\n")
        terminal.wait_for(b"PLUGIN_INPUT owned-input", since=marker)
        terminal.wait_for_screen("Succeeded")
        close_plugin_view(terminal)
    # The same native child checks the previous invocation's private path after
    # return, including Linux containers where host-side stat cannot observe it.
    review_and_run(terminal, "trial-probe")
    terminal.wait_for_screen("PLUGIN_CLEAN")
    close_plugin_view(terminal)
    review_and_run(terminal, "trial-background")
    terminal.wait_for_screen("Background job")
    close_plugin_view(terminal)
    terminal.send(b":pluginjobs\r")
    terminal.wait_for_screen("Owned plugin jobs")
    terminal.wait_for_screen("trial-background")
    terminal.send(b"G\r")
    terminal.wait_for_screen("PLUGIN_BACKGROUND")
    close_plugin_view(terminal)


def close_plugin_view(terminal: TerminalSession) -> None:
    marker = terminal.send(b"\x1b")
    terminal.wait_for_screen("80 pods", since=marker, absent=("Plugin:", "Owned plugin jobs"))


def terminal_plugins(
    command: list[str], directory: Path, evidence: str, *, read_size: int = 65536
) -> None:
    preferences = directory / "preferences.yaml"
    preferences.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "plugins": {"schema_version": 1, "commands": plugin_definitions(directory)},
            }
        )
    )
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        kubeconfig = config(
            directory / "kubeconfig",
            f"http://127.0.0.1:{server.server_port}",
            {"token": "synthetic-pty"},
        )
        original = kubeconfig.read_bytes()
        with TerminalSession(
            [
                *command,
                "--config",
                str(preferences),
                "--kubeconfig",
                str(kubeconfig),
                "--context",
                "kuberich-test-pty",
            ],
            directory,
        ) as terminal:
            terminal.wait_for_screen("80 pods")
            terminal.read_size = read_size
            try:
                exercise_view_preferences(terminal)
            finally:
                terminal.read_size = 65536
            exercise_plugins(terminal)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        assert kubeconfig.read_bytes() == original
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        assert not thread.is_alive()
