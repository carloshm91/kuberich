"""Retention, frozen review, literal Unicode search and safe explicit selection."""

import pytest

from kuberich.adapters.emulator import TerminalModel
from kuberich.domain.terminal_history import TerminalHistory, TerminalReview, TerminalRow
from kuberich.errors import AppError


def rows(*text):
    return tuple(TerminalRow((), value) for value in text)


@pytest.mark.parametrize("limit", [0, -1, 1001, True, 1.5, "1"])
def test_invalid_history_capacity_is_refused(limit):
    with pytest.raises(AppError, match="limit"):
        TerminalHistory(limit)


def test_bounded_retention_reports_drops_and_releases_owned_rows():
    history = TerminalHistory(2)
    for row in rows("first", "second", "third"):
        history.append(row)
    assert tuple(row.text for row in history.rows) == ("second", "third")
    assert history.dropped == 1
    history.clear()
    assert not history.rows and history.dropped == 0


def test_empty_review_is_refused():
    with pytest.raises(AppError, match="No terminal"):
        TerminalReview(())


def test_navigation_marks_copy_literal_search_wraps_and_resizes():
    review = TerminalReview(rows("first", "café 界", "third", "FOUR"))
    review.fit(2)
    assert (review.cursor, review.top) == (3, 2)
    review.move(-100, 0)
    assert (review.cursor, review.top) == (0, 0)
    assert review.selected(0) and not review.selected(1)
    review.toggle_mark()
    review.move(2, 2)
    assert review.selected(0) and review.selected(2) and not review.selected(3)
    assert review.copy() == "first\ncafé 界\nthird"
    review.toggle_mark()
    assert review.mark is None and review.copy() == "third"
    assert review.find("CAFÉ", height=3) and review.cursor == 1
    assert review.find("FOUR", backwards=True, height=2) and review.cursor == 3
    assert review.find("FOUR", height=2) and review.cursor == 3
    assert not review.find(".*", height=1) and not review.find("", height=1)
    with pytest.raises(AppError, match="256"):
        review.find("a" * 257, height=1)
    review.edge(False, 2)
    assert review.cursor == 0
    review.edge(True, 100)
    assert (review.cursor, review.top) == (3, 0)
    review.move(100, 1)
    assert review.cursor == 3


def test_copy_redacts_credentials_escapes_controls_and_refuses_oversized_utf8():
    review = TerminalReview(rows("Bearer owned-secret\x1b]52;c;bad", "password=secret"))
    review.toggle_mark()
    review.edge(False, 2)
    text = review.copy()
    assert "owned-secret" not in text and "password=[REDACTED]" in text and "\x1b" not in text
    for text, message in [("界" * 22000, "too large"), ("\x00" * 65000, "Escaped")]:
        with pytest.raises(AppError, match=message):
            TerminalReview(rows(text)).copy()
    assert len(TerminalReview(rows("x" * 65536)).copy().encode()) == 65536
    with pytest.raises(AppError, match="too large"):
        TerminalReview(rows("x" * 65537)).copy()


def test_actual_emulator_scroll_rows_and_frozen_review_do_not_change_remote_cursor():
    model = TerminalModel(12, 3, lambda _: None)
    model.feed("\x1b[31mFIRST café界\x1b[0m\r\nsecond\r\nthird\r\nfourth".encode())
    assert model.history.rows[0].text == "FIRST café界"
    assert model.history.rows[0].cells[0].fg == "red"
    assert not model.history.rows[0].cells[-1].data  # CJK continuation cell.
    review = TerminalReview(model.review_rows())
    original = review.rows
    cursor = (model.screen.cursor.x, model.screen.cursor.y)
    review.edge(False, 2)
    review.find("FIRST", height=2)
    assert cursor == (model.screen.cursor.x, model.screen.cursor.y)
    model.feed(b"\r\nchanged output\r\n")
    assert review.rows is original and review.rows[0].text == "FIRST café界"


def test_alternate_editor_and_partial_scroll_regions_never_pollute_normal_history():
    model = TerminalModel(10, 4, lambda _: None)
    model.feed(b"normal\r\n\x1b[?1049hEDITOR\r\n1\r\n2\r\n3\r\n4\r\n")
    assert not model.history.rows and "EDITOR" not in "\n".join(
        row.text for row in model.review_rows()
    )
    model.feed(b"\x1b[?1049l\x1b[2;4r\x1b[4;1Hpartial\r\n")
    assert not model.history.rows
    model.feed(b"\x1b[r\x1b[4;1Hfull\r\n")
    assert model.history.rows[0].text == "normal"


def test_shrinking_retains_only_rows_displaced_to_preserve_the_live_cursor():
    model = TerminalModel(12, 4, lambda _: None)
    model.feed(b"first\r\nsecond\r\nthird\r\nfourth")
    model.resize(8, 2)
    assert [row.text for row in model.history.rows] == ["first", "second"]
    assert model.screen.display == ["third   ", "fourth  "]
    model.resize(8, 1)
    assert model.history.rows[-1].text == "third"


def test_session_owned_cell_cache_remains_bounded_and_never_mutates_frozen_styles():
    model = TerminalModel(10, 2, lambda _: None)
    model.feed(b"\x1b[31mXXXXX\r\nsecond\r\n")
    first = model.history.rows[0]
    assert first.cells[0] is first.cells[1]
    for color in range(1100):
        model.feed(f"\x1b[38;2;{color // 256};{color % 256};0mX\r\n".encode())
        assert max(model.style_cache_sizes) <= 1024
    assert first.cells[0].fg == "red" and first.text == "XXXXX"
    model.clear_history()
    assert not model.history.rows and model.style_cache_sizes == (0, 0)
