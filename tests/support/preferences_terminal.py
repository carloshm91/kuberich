"""Actual configured CLI keys, alias completion and private view saves through a PTY."""

import threading

from kuberich.config.navigation import navigation_from
from kuberich.config.schema import parse_document
from kuberich.config.store import read_config, write_config
from tests.support.terminal_api import Server, config
from tests.terminal.pty_support import TerminalSession


def terminal_preferences(command, directory, evidence):
    server = Server()
    server.pod_table.set()
    server.quiet_watches.set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    kube = config(
        directory / (evidence + "-kubeconfig"),
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    before = kube.read_bytes()
    path = directory / (evidence + "-preferences.yaml")
    write_config(
        path,
        parse_document(
            {
                "schema_version": 1,
                "opaque": "retained",
                "navigation": {
                    "schema_version": 1,
                    "keys": {"resources": {"first": "H", "last": "K"}},
                    "aliases": {"work": "pods"},
                },
            }
        ),
    )
    try:
        with TerminalSession(
            [
                *command,
                "--config",
                str(path),
                "--kubeconfig",
                str(kube),
                "--readonly",
                "--command",
                "work",
            ],
            directory,
        ) as terminal:
            terminal.wait_for_screen("80 pods")
            marker = terminal.send(b"K")
            terminal.wait_for_screen("owned-pty-pod-079", since=marker)
            marker = terminal.send(b"H")
            terminal.wait_for_screen("owned-pty-pod-000", since=marker)
            marker = terminal.send(b"?")
            terminal.wait_for_screen("Keyboard help", since=marker)
            terminal.send(b"\x1b")
            terminal.wait_for_screen("pods(", absent=("Keyboard help",))
            marker = terminal.send(b":wor")
            terminal.wait_for_screen(": work", since=marker)
            terminal.send(b"\t\r")
            terminal.wait_for_screen("pods(")
            marker = terminal.send(b":views\r")
            terminal.wait_for_screen("View · v1/pods", since=marker)
            terminal.wait_for_screen("Available:", since=marker)
            marker = terminal.send(b"\x01\x0bname:24:center age:8")
            terminal.wait_for_screen("name:24:center age:8", since=marker)
            marker = terminal.send(b"\t\x01\x0brestarts")
            terminal.wait_for_screen("restarts", since=marker)
            # Sort input -> descending -> session -> global -> context.
            terminal.send(b"\t \t\t\t\r")
            terminal.wait_for_screen("View saved for the captured context.", absent=("Available:",))
            terminal.wait_for_screen("Sort RESTARTS ↓")
            marker = terminal.resize(40, 12)
            terminal.wait_for_screen("pods(", since=marker)
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            assert b"synthetic-pty" not in terminal.transcript
        saved = read_config(path)
        selected = navigation_from(saved).choices("v1/pods", "kuberich-test-pty")[0]
        assert [column.key for column in selected.columns] == ["name", "age"]
        assert selected.columns[0].width == 24 and selected.columns[0].alignment == "center"
        assert selected.sort == "restarts" and selected.descending
        assert not saved.settings.read_only and saved.unknown == {"opaque": "retained"}
        assert path.stat().st_mode & 0o777 == 0o600 and kube.read_bytes() == before
        with TerminalSession(
            [*command, "--config", str(path), "--kubeconfig", str(kube), "--readonly"], directory
        ) as terminal:
            terminal.wait_for_screen("80 pods")
            terminal.wait_for_screen("Sort RESTARTS ↓")
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence + "-reopened")
    finally:
        server.stopping.set()
        server.pod_gate.set()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        assert not thread.is_alive()
