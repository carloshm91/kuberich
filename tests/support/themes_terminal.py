"""Real source/installed CLI preview, save, narrow About and terminal restoration."""

from kuberich.config.schema import ConfigDocument
from kuberich.config.store import read_config, write_config
from tests.terminal.pty_support import TerminalSession


def terminal_themes(command, directory, evidence):
    path, kube = (
        directory / (evidence + "-preferences.yaml"),
        directory / (evidence + "-empty-kubeconfig"),
    )
    write_config(path, ConfigDocument(unknown={"owned-retained": True}))
    kube.write_text("apiVersion: v1\nkind: Config\ncontexts: []\nclusters: []\nusers: []\n")
    original = kube.read_bytes()
    with TerminalSession(
        [
            *command,
            "--config",
            str(path),
            "--kubeconfig",
            str(kube),
            "--readonly",
            "--invert",
            "--command",
            "themes",
        ],
        directory,
        environment={"NO_COLOR": "1"},
    ) as terminal:
        terminal.wait_for_screen("Theme")
        terminal.wait_for_screen("Selected")
        terminal.send(b"\x1b[B")
        terminal.wait_for_screen("Preview: kuberich-mono")
        # Separate focus changes from the requested write; both are real terminal keys.
        terminal.send(b"\t")
        terminal._read(0.2)
        terminal.send(b"\t")
        terminal._read(0.2)
        terminal.send(b"\r")
        terminal.wait_for_screen("Saved globally")
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Resources", absent=("Theme",))
        marker = terminal.send(b":about\r")
        terminal.wait_for_screen("An independent Python", since=marker)
        terminal.resize(40, 12)
        terminal.send(b"\x1b[F")
        terminal.wait_for_screen("Version checks disabled")
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Resources", absent=("Apache-2.0",))
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
    saved = read_config(path)
    assert saved.settings.theme == "kuberich-mono" and not saved.settings.read_only
    assert saved.unknown == {"owned-retained": True}
    assert saved.extensions["appearance"]["check_updates"] is False
    assert kube.read_bytes() == original
