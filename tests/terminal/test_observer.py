"""Regression witnesses for the real-terminal observer and restoration oracle."""

from copy import deepcopy

import pyte
import pytest

from tests.support.terminal_modes import DARWIN_PENDIN, restored_modes
from tests.terminal.pty_support import ObserverScreen


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
