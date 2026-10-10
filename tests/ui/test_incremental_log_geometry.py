"""Incremental history must preserve Rich output through eviction and cancellation."""

import asyncio

import pytest
from rich.cells import cell_len
from rich.segment import Segment
from rich.text import Text
from textual.app import App, ComposeResult
from textual.strip import Strip

from kuberich.domain.log_view import LogEntry
from kuberich.domain.logs import LogLine
from kuberich.ui.log_body import LogBody


class BodyApp(App):
    def compose(self) -> ComposeResult:
        yield LogBody()


def history(start, stop, prepared):
    entries = tuple(
        LogEntry(
            number,
            LogLine(
                f"2026-10-10T00:00:00Z line-{number} "
                + ("needle " if number % 3 == 0 else "ordinary ")
                + "wide 你好 e\u0301 " * 8
            ),
        )
        for number in range(start, stop)
    )
    return tuple((entry.number, entry.line.text) for entry in entries) if prepared else entries


def rich_reference(body, entries, *, width, wrap, timestamps, query, marks):
    rows, starts, matches, strips = [], [], [], []
    height = 0
    for entry in entries:
        number, value = (
            (entry.number, entry.text(timestamps)) if isinstance(entry, LogEntry) else entry
        )
        text = Text(("* " if number in marks else "  ") + value, style=body.rich_style)
        if query:
            text.highlight_words([query], style="reverse bold", case_sensitive=True)
        parts = text.wrap(body.app.console, width, overflow="fold") if wrap else [text]
        rows.append((number, tuple((part.plain, cell_len(part.plain)) for part in parts)))
        starts.append(height)
        height += len(parts)
        if query and query in value:
            matches.append(number)
        strips.extend(
            Strip(Segment.apply_style(part.render(body.app.console), body.rich_style))
            for part in parts
        )
    return rows, starts, matches, strips


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared", [False, True])
async def test_append_evict_reorder_resize_and_display_changes_preserve_rich_output(prepared):
    app = BodyApp()
    async with app.run_test(size=(46, 12)) as pilot:
        body = app.query_one(LogBody)
        body.follow = False
        initial = history(1, 81, prepared)
        incoming = history(81, 101, prepared)
        scenarios = (
            (initial, False, True, "", frozenset()),
            (initial, True, True, "", frozenset()),
            (initial, False, True, "", frozenset()),
            (initial[20:] + incoming, False, True, "", frozenset()),
            (initial[20:] + incoming, True, True, "", frozenset()),
            (initial[20:40] + initial[50:70] + incoming, True, True, "", frozenset()),
            (initial[40:] + incoming, True, True, "needle", frozenset({42, 99})),
            (initial[40:] + incoming, True, True, "needle", frozenset({45, 96})),
            (initial[40:] + incoming, False, True, "needle", frozenset({45, 96})),
            (tuple(reversed(initial[40:] + incoming)), True, True, "needle", frozenset({45, 96})),
            (tuple(reversed(initial[40:] + incoming)), True, False, "needle", frozenset()),
            (initial[50:] + incoming, True, False, "", frozenset()),
            (history(501, 521, prepared), True, False, "", frozenset()),
            ((), False, True, "", frozenset()),
            (incoming, True, True, "needle", frozenset({99})),
        )
        for index, (entries, wrap, timestamps, query, marks) in enumerate(scenarios):
            if index == len(scenarios) - 4:
                await pilot.resize_terminal(32, 9)
                await pilot.pause()
            width = max(1, body.scrollable_content_region.width)
            references = rich_reference(
                body,
                entries,
                width=width,
                wrap=wrap,
                timestamps=timestamps,
                query=query,
                marks=marks,
            )
            await body.load(
                entries,
                wrap=wrap,
                timestamps=timestamps,
                query=query,
                marks=marks,
                valid=lambda: True,
            )
            await pilot.pause()
            actual = [
                (number, tuple((line[0], line[1]) for line in lines)) for number, lines in body.rows
            ]
            assert actual == references[0]
            assert body.starts == references[1] and body.matches == references[2]
            assert body.virtual_size.height == len(references[3])
            retained = {
                entry.number if isinstance(entry, LogEntry) else entry[0] for entry in entries
            }
            assert set(body._cache) <= retained and set(body._alternates) <= retained
            assert len(body._geometries) <= 2
            assert all(
                {number for number, _ in geometry.rows} <= retained
                for geometry in body._geometries.values()
            )
            body.scroll_to(x=0, y=0, animate=False, immediate=True)
            for y, expected in enumerate(references[3][: body.size.height]):
                assert tuple(body.render_line(y)) == tuple(
                    expected.crop_extend(0, body.size.width, body.rich_style)
                )
        body.invalidate()
        assert not body._geometries and not body._cache and not body._alternates


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["generation", "task"])
async def test_cancelled_first_wrap_repairs_missing_layouts_before_reuse(monkeypatch, interruption):
    app = BodyApp()
    entries = history(1, 301, False)
    async with app.run_test(size=(40, 12)) as pilot:
        body = app.query_one(LogBody)

        async def load(wrap, valid=lambda: True):
            await body.load(
                entries,
                wrap=wrap,
                timestamps=True,
                query="",
                marks=frozenset(),
                valid=valid,
            )

        await load(False)
        await pilot.pause()
        before, valid = body.rows, [True]
        original = body._prepare
        wrapped_calls = 0
        worker = None

        def prepare(value, marked, wrap, width, query, style):
            nonlocal wrapped_calls
            result = original(value, marked, wrap, width, query, style)
            if wrap:
                wrapped_calls += 1
                if wrapped_calls == 20:
                    if interruption == "task":
                        worker.cancel()
                    else:
                        valid[0] = False
            return result

        monkeypatch.setattr(body, "_prepare", prepare)
        worker = asyncio.create_task(load(True, lambda: valid[0]))
        if interruption == "task":
            with pytest.raises(asyncio.CancelledError):
                await worker
        else:
            await worker
        assert worker.done() and body.rows is before
        assert 20 <= wrapped_calls < len(entries)
        monkeypatch.setattr(body, "_prepare", original)
        await load(False)
        await pilot.pause()

        def unexpected_wrap(*args, **kwargs):
            pytest.fail("The cancelled wrap's missing layouts must have been prepared")

        monkeypatch.setattr(Text, "wrap", unexpected_wrap)
        await load(True)
        assert len(body.rows) == len(entries) and body.virtual_size.height > len(entries)
        assert len(body._cache) == len(body._alternates) == len(entries)
        assert all(
            number in body._cache and lines is body._cache[number][1] for number, lines in body.rows
        )
