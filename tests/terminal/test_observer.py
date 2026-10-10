"""Regression witnesses for the real-terminal observer and restoration oracle."""

import json
import os
import sys
from contextlib import ExitStack
from copy import deepcopy

import pyte
import pytest

from tests.support.terminal_modes import DARWIN_PENDIN, restored_modes
from tests.support.transports import TerminalTransport
from tests.terminal.pty_support import ObserverScreen, TerminalSession

MALFORMED_CURSOR = b"\x1b[1;2;3;4;5C"


@pytest.mark.parametrize("transported", [False, True])
def test_healthy_terminal_rejects_malformed_projection_and_retains_raw_evidence(
    tmp_path, transported
):
    # A valid outer restoration transcript does not excuse malformed live output.
    raw = (
        b"\x1b[?1049hbefore"
        + MALFORMED_CURSOR
        + b"after\x1b[?1049l\x1b[?25h"
        + b"".join(f"\x1b[?{mode}l".encode() for mode in (1000, 1003, 1004, 1006, 2004))
    )
    command = [sys.executable, "-c", f"import os; os.write(1, {raw!r})"]
    with ExitStack() as stack:
        transport = (
            stack.enter_context(TerminalTransport(tmp_path / "transport", "ssh"))
            if transported
            else None
        )
        terminal = stack.enter_context(TerminalSession(command, tmp_path, transport=transport))
        with pytest.raises(TypeError, match="cursor_forward"):
            terminal.wait_for(raw)
        assert raw in terminal.transcript
        terminal.finish()
        assert terminal.completion["exit"] == 0
        if transport is not None:
            assert transport.disconnected is False
            assert transport.record["connection_lost"] is False
    assert terminal.process.poll() == 0
    with pytest.raises(OSError):
        os.fstat(terminal.master)


def test_owned_disconnect_retains_late_malformed_bytes_and_actual_cleanup(tmp_path):
    # The inner process exits on real SSH loss; the outer owned PTY then receives
    # a deterministic witness of the truncated/interleaved bytes from that loss.
    child = (
        "import os,signal\n"
        "signal.signal(signal.SIGHUP, lambda *_: os._exit(0))\n"
        "os.write(1,b'\\x1b[?1049hobserver-ready')\n"
        "while True: signal.pause()\n"
    )
    with TerminalTransport(tmp_path / "transport", "ssh") as transport:
        with TerminalSession(
            [sys.executable, "-c", child], tmp_path, transport=transport
        ) as terminal:
            terminal.wait_for_screen("observer-ready")
            ready = json.loads((transport.directory / "ready.json").read_text())
            before = tuple(terminal.screen.display)
            marker = len(terminal.transcript)
            transport.disconnect()
            assert transport.disconnected
            late = MALFORMED_CURSOR + b"late-after-disconnect"
            os.write(terminal.slave, late)
            terminal.finish()
            assert late in terminal.transcript[marker:]
            assert tuple(terminal.screen.display) == before
            assert terminal.completion["exit"] == 255
            assert restored_modes(terminal.completion["before"], terminal.completion["after"])
            assert transport.record["connection_lost"] is True
            assert transport.record["exit"] == 0
            with pytest.raises(ProcessLookupError):
                os.kill(ready["application"], 0)
            terminal.save_evidence("observer-disconnected-raw-cleanup")
        assert terminal.process.poll() == 0
        with pytest.raises(OSError):
            os.fstat(terminal.master)
    assert transport.server.poll() is not None


@pytest.mark.parametrize("private", [False, True])
def test_status_queries_preserve_following_output_without_changing_input(private):
    screen = ObserverScreen(40, 12)
    stream = pyte.Stream(screen)
    prefix = "?" if private else ""
    for fragment in ["\x1b[3;8H\x1b[", prefix, "6", "n", "after-query"]:
        stream.feed(fragment)
    assert screen.display[2][7:18] == "after-query"


def test_unknown_private_status_does_not_poison_the_observer_or_invent_capabilities():
    screen = ObserverScreen(40, 12)
    pyte.Stream(screen).feed("before\x1b[?996nafter\x1b[5n")
    assert screen.display[0].startswith("beforeafter")


@pytest.mark.parametrize("system", ["linux", "darwin"])
@pytest.mark.parametrize("before_pending", [False, True])
def test_kernel_pending_input_normalization_is_specific_to_darwin(system, before_pending):
    before = [1, 2, 3, 1483 | (DARWIN_PENDIN if before_pending else 0), 9600, 9600, ["04", "03"]]
    after = deepcopy(before)
    after[3] ^= DARWIN_PENDIN
    assert restored_modes(before, before, system=system)
    assert restored_modes(before, after, system=system) is (system == "darwin")
    assert before[3] == 1483 | (DARWIN_PENDIN if before_pending else 0)


@pytest.mark.parametrize("index", range(7))
def test_every_operator_setting_still_blocks_restoration_when_changed(index):
    before = [1, 2, 3, 1483, 9600, 9600, ["04", "03"]]
    after = deepcopy(before)
    after[3] |= DARWIN_PENDIN
    if index == 6:
        after[index][0] = "00"
    else:
        after[index] ^= 1
    assert not restored_modes(before, after, system="darwin")


@pytest.mark.parametrize("invalid", [None, {}, [], [0] * 7, [0, 0, 0, True, 0, 0, []]])
def test_malformed_evidence_cannot_claim_restoration_even_when_equal(invalid):
    assert not restored_modes(invalid, invalid, system="darwin")
