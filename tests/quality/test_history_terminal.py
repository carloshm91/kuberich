"""History input waits for a positive parent frame through fragmented repaint."""

import json
import stat
from pathlib import Path
from types import SimpleNamespace

import pyte
import pytest

from tests.support import history_terminal
from tests.support.history_explorer import POD_NAME
from tests.terminal.pty_support import ObserverScreen, TerminalSession


class FragmentedParent(TerminalSession):
    """Real observer/wait logic; delay Escape dispatch until the third paint."""

    def __init__(self):
        self.screen = ObserverScreen(100, 30)
        self.screen_stream = pyte.Stream(self.screen)
        self.transcript = bytearray(b"old history output")
        self.completion = None
        self.process = SimpleNamespace(poll=lambda: None)
        self.read_size = 65536
        self.inputs = []
        self.parent_ready = False
        self.paints = iter(
            (
                f"\x1b[2J\x1b[HRequested pod team/{POD_NAME} · resize paint",
                "\x1b[11;1HMetric history · 24h · filesystem",
                f"\x1b[2J\x1b[Hpods(team)[1]\r\nNAME\r\n{POD_NAME}",
            )
        )

    def send(self, data):
        marker = len(self.transcript)
        if data == b"\r":
            assert self.parent_ready, (
                "Enter sent before Escape dispatched and actual parent painted"
            )
        self.inputs.append(data)
        return marker

    def _read(self, timeout=0.1):
        paint = next(self.paints)
        self.parent_ready = paint.startswith("\x1b[2J\x1b[Hpods(team)[1]")
        self.transcript.extend(paint.encode())
        self.screen_stream.feed(paint)


def test_legacy_shared_name_and_title_absence_can_accept_a_history_resize_fragment():
    terminal = FragmentedParent()
    marker = terminal.send(b"\x1b")
    terminal.wait_for_screen(POD_NAME, since=marker, absent=("Metric history ·",))
    assert "Requested pod" in "\n".join(terminal.screen.display)
    assert not terminal.parent_ready
    with pytest.raises(AssertionError, match="Enter sent before Escape"):
        terminal.send(b"\r")


def test_history_back_requires_actual_parent_and_selected_row_before_enter():
    terminal = FragmentedParent()
    history_terminal.return_to_parent(terminal, "pods(team)[1]", POD_NAME)
    terminal.send(b"\r")
    assert terminal.parent_ready and terminal.inputs == [b"\x1b", b"\r"]


@pytest.mark.parametrize("case", ["ready", "expired-before-row", "expired-after-row"])
def test_parent_title_and_selected_row_share_the_original_fifteen_second_deadline(
    monkeypatch, case
):
    moments = iter(
        [0, 0.1, 4, 4.1]
        if case == "ready"
        else [0, 0.1, 16]
        if case == "expired-before-row"
        else [0, 0.1, 14, 15.1]
    )
    monkeypatch.setattr(history_terminal, "time", SimpleNamespace(monotonic=lambda: next(moments)))
    waits = []
    terminal = SimpleNamespace(
        send=lambda data: 0,
        screen=SimpleNamespace(display=["pods(team)[1]", POD_NAME]),
        wait_for_screen=lambda text, **kwargs: waits.append((text, kwargs["timeout"])),
    )
    if case == "ready":
        history_terminal.return_to_parent(terminal, "pods(team)[1]", POD_NAME)
        assert waits == [("pods(team)[1]", 14.9), (POD_NAME, 11)]
    else:
        with pytest.raises(AssertionError, match="deadline"):
            history_terminal.return_to_parent(terminal, "pods(team)[1]", POD_NAME)
        assert len(waits) == (1 if case == "expired-before-row" else 2)


@pytest.mark.parametrize("archive_failure", [None, "write", "chmod", "json"])
def test_failed_history_stage_keeps_original_failure_even_when_its_archive_fails(
    tmp_path, monkeypatch, archive_failure
):
    servers = []
    original_server = history_terminal._Server

    def server():
        owned = original_server()
        servers.append(owned)
        return owned

    class FailedTerminal:
        def __init__(self, *args, **kwargs):
            self.transcript = bytearray(b"synthetic interrupted terminal paint")
            self.screen = SimpleNamespace(display=["Requested pod team/history-pod"])
            self.completion = self.cleanup = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            # A cleanup-observed zero status cannot stand in for finish() verification.
            self.completion = {"exit": 0}
            self.cleanup = {"status": "complete"}

        def wait_for_screen(self, *args, **kwargs):
            raise AssertionError("controlled missing parent frame")

    monkeypatch.setattr(history_terminal, "ROOT", tmp_path)
    monkeypatch.setattr(history_terminal, "_source_hashes", lambda: {})
    monkeypatch.setattr(history_terminal, "_Server", server)
    monkeypatch.setattr(history_terminal, "TerminalSession", FailedTerminal)
    write_bytes, chmod, write_text = Path.write_bytes, Path.chmod, Path.write_text

    def archive_bytes(path, data):
        if archive_failure == "write" and path.name == "failed-history.ansi":
            raise OSError("owned archive write control")
        return write_bytes(path, data)

    def archive_mode(path, mode, **kwargs):
        if archive_failure == "chmod" and path.name == "failed-history.ansi":
            raise OSError("owned archive chmod control")
        return chmod(path, mode, **kwargs)

    def archive_text(path, data, **kwargs):
        if archive_failure == "json" and path.name == "failed-history.json":
            raise OSError("owned archive JSON control")
        return write_text(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_bytes", archive_bytes)
    monkeypatch.setattr(Path, "chmod", archive_mode)
    monkeypatch.setattr(Path, "write_text", archive_text)
    with pytest.raises(AssertionError, match="controlled missing parent frame") as caught:
        history_terminal.terminal_history(
            ["owned-no-child"], tmp_path / "owned", evidence="failed-history"
        )
    if archive_failure:
        assert any(
            "History terminal archive failed: OSError" in note for note in caught.value.__notes__
        )
    else:
        output = tmp_path / "artifacts/terminal"
        raw = output / "failed-history.ansi"
        assert raw.read_bytes() == b"synthetic interrupted terminal paint"
        assert stat.S_IMODE(raw.stat().st_mode) == 0o600
        record = json.loads((output / "failed-history.json").read_text())
        assert record["result"] == "failed" and record["failed_stage"] == "initial-pod-frame"
        assert record["normal_finish_observed"] is False
        assert record["terminal_completion"] == {"exit": 0}
        assert record["cleanup"] == {"status": "complete"}
    assert len(servers) == 1 and servers[0].stopping.is_set() and servers[0].fileno() == -1
