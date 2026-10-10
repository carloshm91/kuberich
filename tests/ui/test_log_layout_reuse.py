"""Repeated display controls reuse bounded layouts while retaining literal geometry."""

import asyncio

import pytest
from rich.text import Text
from textual.app import App, ComposeResult

from kuberich.domain.log_view import LogEntry
from kuberich.domain.logs import LogLine
from kuberich.ui.log_body import LogBody


class BodyApp(App):
    def compose(self) -> ComposeResult:
        yield LogBody()


async def load(body, entries, *, wrap=False, query="", marks=frozenset(), valid=lambda: True):
    await body.load(entries, wrap=wrap, timestamps=True, query=query, marks=marks, valid=valid)


@pytest.mark.asyncio
async def test_repeated_wrap_retains_both_geometries_without_reformatting(tmp_path, monkeypatch):
    app = BodyApp()
    entries = tuple(
        LogEntry(number, LogLine(f"owned-{number} " + "word " * 25 + "尾e\u0301"))
        for number in range(1, 151)
    )
    async with app.run_test(size=(40, 12)) as pilot:
        body = app.query_one(LogBody)
        layouts = {}
        for wrap in (False, True):
            await load(body, entries, wrap=wrap)
            await pilot.pause()
            layouts[wrap] = tuple(body.rows)
        assert body.virtual_size.height > len(entries)
        original_wrap = Text.wrap

        def unexpected_wrap(*args, **kwargs):
            pytest.fail("Unchanged retained lines must not be formatted again on wrap toggle")

        monkeypatch.setattr(Text, "wrap", unexpected_wrap)
        for wrap in (False, True, False, True):
            await load(body, entries, wrap=wrap)
            assert tuple(body.rows) == layouts[wrap]
            assert all(
                actual is original
                for actual, original in zip(body.rows, layouts[wrap], strict=True)
            )
        monkeypatch.setattr(Text, "wrap", original_wrap)
        await load(body, entries, wrap=True, query="word", marks=frozenset({1}))
        assert body.matches == list(range(1, 151))
        assert body.rows[0][1][0][0].startswith("* ")
        assert any(span[2] for line in body.rows[0][1] for span in line[2])
        await load(body, entries[100:], wrap=False)
        assert [number for number, _ in body.rows] == list(range(101, 151))
        assert len(body._cache) == len(body._alternates) == 50
        body.invalidate()
        assert not body._cache and not body._alternates and not body._strips
        await load(body, entries[100:], wrap=False)
        assert not body._alternates


@pytest.mark.asyncio
async def test_cached_history_still_yields_to_invalidation_without_publishing_old_layout():
    app = BodyApp()
    entries = tuple(LogEntry(number, LogLine("owned " * 20)) for number in range(1, 1001))
    async with app.run_test(size=(40, 12)):
        body = app.query_one(LogBody)
        await load(body, entries)
        await load(body, entries, wrap=True)
        before = body.rows
        valid = [True]
        asyncio.get_running_loop().call_soon(lambda: valid.__setitem__(0, False))
        await load(body, entries, valid=lambda: valid[0])
        assert not valid[0] and body.rows is before


@pytest.mark.asyncio
async def test_lines_arriving_without_wrap_are_ready_for_an_already_used_wrap_mode(monkeypatch):
    app = BodyApp()
    entries = tuple(
        LogEntry(number, LogLine(f"owned-{number} " + "words " * 25 + "尾e\u0301"))
        for number in range(1, 44)
    )
    async with app.run_test(size=(40, 12)) as pilot:
        body = app.query_one(LogBody)
        await load(body, entries[:18], wrap=True)
        await pilot.pause()
        await load(body, entries[:18], wrap=True)
        await load(body, entries, wrap=False)
        await pilot.pause()
        assert len(body.rows) == 43 and body.virtual_size.height == 43

        def unexpected_wrap(*args, **kwargs):
            pytest.fail("New lines must already have the previously used wrap geometry")

        monkeypatch.setattr(Text, "wrap", unexpected_wrap)
        await load(body, entries, wrap=True)
        assert len(body.rows) == 43 and body.virtual_size.height > 43
        assert "".join(part[0] for part in body.rows[-1][1]).strip() == entries[-1].line.text


@pytest.mark.asyncio
async def test_a_new_search_or_invalidated_history_does_not_prewarm_unrequested_wrap(monkeypatch):
    app = BodyApp()
    entries = (LogEntry(1, LogLine("owned " * 25)),)
    async with app.run_test(size=(40, 12)):
        body = app.query_one(LogBody)
        await load(body, entries, wrap=True, query="owned")

        def unexpected_wrap(*args, **kwargs):
            pytest.fail("A changed display context must not inherit wrap preparation")

        monkeypatch.setattr(Text, "wrap", unexpected_wrap)
        await load(body, entries)
        assert body.matches == [] and body.virtual_size.height == 1
        body.invalidate()
        await load(body, entries, query="owned")
        assert body.matches == [1] and body.virtual_size.height == 1


@pytest.mark.asyncio
async def test_follow_paints_new_tail_without_waiting_for_an_extra_refresh():
    app = BodyApp()
    entries = tuple(
        LogEntry(number, LogLine(f"owned-{number} " + "words " * 25 + "尾e\u0301"))
        for number in range(1, 81)
    )
    async with app.run_test(size=(40, 12)) as pilot:
        body = app.query_one(LogBody)
        for wrap in (False, True, False, True):
            await load(body, entries, wrap=wrap)
            assert body.scroll_y == body.max_scroll_y > 0
            assert body.first_visible[0] > 60
            await pilot.pause()
            assert body.scroll_y == body.max_scroll_y
        body.action_beginning()
        assert not body.follow and body.first_visible == (1, 0)
        await load(body, entries[30:], wrap=False)
        await pilot.pause()
        assert not body.follow and body.first_visible == (31, 0)


@pytest.mark.asyncio
async def test_queued_tail_restore_cannot_override_new_manual_navigation():
    app = BodyApp()
    entries = tuple(LogEntry(number, LogLine("owned " * 20)) for number in range(1, 81))
    async with app.run_test(size=(40, 12)) as pilot:
        body = app.query_one(LogBody)
        await load(body, entries, wrap=True)
        assert body.scroll_y == body.max_scroll_y > 0
        body.action_beginning()
        await pilot.pause()
        assert not body.follow and body.first_visible == (1, 0)
