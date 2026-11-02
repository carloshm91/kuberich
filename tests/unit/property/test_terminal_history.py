"""Generated terminal sequences obey an independent retained-window model."""

from hypothesis import given
from hypothesis import strategies as st

from kuberich.domain.terminal_history import TerminalHistory, TerminalReview, TerminalRow
from tests.support.properties import NAMES, PROPERTY


@PROPERTY
@given(limit=st.integers(1, 20), values=st.lists(NAMES, max_size=80))
def test_ring_retains_exactly_the_last_rows_and_counts_all_evictions(limit, values):
    history = TerminalHistory(limit)
    for value in values:
        history.append(TerminalRow((), value))
    assert tuple(row.text for row in history.rows) == tuple(values[-limit:])
    assert history.dropped == max(0, len(values) - limit)
    frozen = tuple(history.rows)
    history.clear()
    assert tuple(row.text for row in frozen) == tuple(values[-limit:])
    assert not history.rows and history.dropped == 0


@PROPERTY
@given(
    values=st.lists(NAMES, min_size=1, max_size=30),
    steps=st.lists(st.integers(-50, 50), max_size=30),
    height=st.integers(0, 40),
)
def test_review_cursor_and_viewport_stay_inside_the_frozen_rows(values, steps, height):
    rows = tuple(TerminalRow((), value) for value in values)
    review = TerminalReview(rows)
    expected = len(rows) - 1
    for delta in steps:
        expected = min(len(rows) - 1, max(0, expected + delta))
        review.move(delta, height)
        assert review.cursor == expected
        assert 0 <= review.top <= max(0, len(rows) - max(1, height))
        assert review.top <= review.cursor < review.top + max(1, height)
    assert review.rows is rows


@PROPERTY
@given(
    values=st.lists(NAMES, min_size=1, max_size=30),
    first=st.integers(0, 29),
    last=st.integers(0, 29),
)
def test_marked_copy_is_the_exact_inclusive_interval_in_either_direction(values, first, last):
    review = TerminalReview(tuple(TerminalRow((), value) for value in values))
    first, last = min(first, len(values) - 1), min(last, len(values) - 1)
    review.edge(False, 10)
    review.move(first, 10)
    review.toggle_mark()
    review.move(last - first, 10)
    lower, upper = sorted((first, last))
    assert review.copy() == "\n".join(values[lower : upper + 1])
    assert {index for index in range(len(values)) if review.selected(index)} == set(
        range(lower, upper + 1)
    )
