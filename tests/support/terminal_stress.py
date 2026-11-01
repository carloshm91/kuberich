"""Fresh-process measurements of bounded history and production terminal rendering."""

import argparse
import asyncio
import hashlib
import json
import sys
import time
import tracemalloc
from pathlib import Path

from textual.app import App, ComposeResult

from kuberich.adapters.emulator import TerminalModel
from kuberich.domain.terminal_history import TerminalReview
from kuberich.ui.terminal import TerminalWidget
from tests.support.runtime_budget import budget_enforced, budget_observation


def memory() -> dict:
    results = []
    for width, height in [(100, 30), (400, 150)]:
        tracemalloc.start()
        model = TerminalModel(width, height, lambda _: None)
        line = ("café界 " + "x" * (width - 8) + "\r\n").encode()
        for _ in range(height):
            model.feed(line)
        model.clear_history()
        live_screen_baseline = tracemalloc.get_traced_memory()[0]
        for _ in range(1200):
            model.feed(line)
        review = TerminalReview(model.review_rows())
        frozen = review.rows
        samples = []
        for _ in range(4):
            for _ in range(1200):
                model.feed(line)
            samples.append(tracemalloc.get_traced_memory()[0])
            assert len(model.history.rows) == 1000 and model.history.dropped > 0
            assert review.rows is frozen and len(frozen) <= 1000 + height
        # Equal later workloads must plateau despite another 3,600 scrolled rows.
        assert max(samples[1:]) - min(samples[1:]) < 1024 * 1024, samples
        peak = tracemalloc.get_traced_memory()[1]
        model.clear_history()
        del frozen, review
        cleared = tracemalloc.get_traced_memory()[0]
        # Keep the live 400x150 screen; release only the owned history/capture.
        assert cleared <= live_screen_baseline + 128 * 1024, (cleared, live_screen_baseline)
        results.append(
            {
                "geometry": [width, height],
                "rows_fed": 6000,
                "retained_rows": 1000,
                "python_bytes": samples,
                "peak_python_bytes": peak,
                "after_clear_python_bytes": cleared,
                "live_screen_baseline_bytes": live_screen_baseline,
            }
        )
        tracemalloc.stop()
    return {"measure": "traced Python allocations; not RSS or latency", "runs": results}


class Probe(App):
    def compose(self) -> ComposeResult:
        yield TerminalWidget()


async def latency() -> dict:
    assert sys.gettrace() is None and sys.getprofile() is None and not tracemalloc.is_tracing()
    app = Probe()
    delays, feeds = [], []
    done = False

    async def heartbeat():
        previous = time.monotonic()
        while not done:
            await asyncio.sleep(0.005)
            now = time.monotonic()
            delays.append(now - previous)
            previous = now

    async with app.run_test(size=(100, 30)) as pilot:
        terminal = app.query_one(TerminalWidget)
        terminal.model.resize(100, 30)
        line = "\x1b[31mcafé界 \x1b[0m" + "x" * 70 + "\r\n"
        payload = (line * 150).encode()
        assert len(payload) <= 16384
        task = asyncio.create_task(heartbeat())
        try:
            for round_ in range(60):
                started = time.monotonic()
                terminal.model.feed(payload)
                feeds.append(time.monotonic() - started)
                terminal.refresh()
                if round_ == 10:
                    terminal.begin_review()
                if round_ > 10:
                    terminal.review.move(-1, 30)
                    terminal.review.find("café", height=30)
                await asyncio.sleep(0.005)
            await pilot.pause()
        finally:
            done = True
            await task
        assert len(terminal.model.history.rows) == 1000
        assert terminal.review is not None
        terminal.clear_history()
    assert delays
    if budget_enforced("positive"):
        assert max(delays) < 0.150, max(delays)
    return {
        "measure": "uninstrumented real mounted terminal",
        "geometry": [100, 30],
        "rows_fed": 9000,
        "max_heartbeat_ms": max(delays) * 1000,
        "max_gap_seconds": max(delays),
        "limit_seconds": 0.15,
        "runtime_budget": budget_observation(max(delays), mode="positive"),
        "max_feed_ms": max(feeds) * 1000,
        "review_during_output": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["memory", "latency"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = memory() if args.mode == "memory" else asyncio.run(latency())
    root = Path(__file__).resolve().parents[2]
    result["source_hashes"] = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "src/kuberich/adapters/emulator.py",
            "src/kuberich/ui/terminal.py",
            "src/kuberich/domain/terminal_history.py",
        )
    }
    result["python"] = sys.version
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
