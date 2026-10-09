"""Real terminal copy forms, review/default Cancel and return to retained resources."""

from kuberich.domain.transfers import TransferDirection
from tests.support.connections import catalog_fixture
from tests.support.transfers import executable
from tests.terminal.pty_support import TerminalSession


def terminal_transfer(command, directory, url, direction, evidence):
    catalog_fixture(directory, url)
    config = directory / "fixture-config"
    before = config.read_bytes()
    environment = executable(directory / "tools")
    local = directory / "space local.bin"
    remote = directory / "tools/remote/tmp/space remote.bin"
    (local if direction is TransferDirection.UPLOAD else remote).write_bytes(b"actual\x00binary")
    with TerminalSession(
        [
            *command,
            "--kubeconfig",
            str(config),
            "--context",
            "kuberich-test-one",
            "--namespace",
            "team",
            "--write",
        ],
        directory,
        environment=environment,
    ) as terminal:
        terminal.wait_for_screen("pods(team)[1]")
        terminal.send(b"\r")
        terminal.wait_for_screen("Containers")
        key = b"u" if direction is TransferDirection.UPLOAD else b"d"

        def review():
            terminal.send(key)
            terminal.wait_for_screen(direction.value + " · review before copying")
            terminal.send(str(local).encode() + b"\t/tmp/space remote.bin\r")
            terminal.wait_for_screen("Review paths and overwrite intent")
            assert not (directory / "tools/arguments").exists()

        review()
        terminal.send(b"\r")  # reviewed form defaults to Cancel, no child started
        terminal.wait_for_screen(
            "Containers", absent=(direction.value + " · review before copying",)
        )
        assert not (directory / "tools/arguments").exists()
        review()
        terminal.send(b"\x1b[Z\r")  # Confirm from default Cancel
        terminal.wait_for_screen(direction.value + " complete: 13 bytes")
        destination = remote if direction is TransferDirection.UPLOAD else local
        assert destination.read_bytes() == b"actual\x00binary"
        terminal.resize(40, 12)
        terminal.wait_for_screen("complete: 13 bytes")
        terminal.resize(100, 30)
        terminal.send(b"\x1b")
        terminal.wait_for_screen("Containers", absent=("review before copying",))
        terminal.send(b"\x1b")
        terminal.wait_for_screen("pods(team)[1]", absent=("Containers ·",))
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
    assert config.read_bytes() == before
    assert not list(directory.glob(".kuberich-copy-*"))
