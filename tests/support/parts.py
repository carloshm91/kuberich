"""Split the suite into balanced parts by test file so CI can run them in parallel."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

TIMINGS = Path(__file__).with_name("part_timings.json")
MAX_PARTS = 16
UNKNOWN_SECONDS = 10.0


def parse_part(value: str) -> tuple[int, int]:
    """Read `INDEX/COUNT`, for example `2/4`."""
    index, separator, count = value.partition("/")
    if (
        separator != "/"
        or not index.isdigit()
        or not count.isdigit()
        or not 1 <= int(index) <= int(count) <= MAX_PARTS
    ):
        raise ValueError(
            f"KUBERICH_TEST_PART must be INDEX/COUNT with 1 <= INDEX <= COUNT <= {MAX_PARTS}."
        )
    return int(index), int(count)


def load_timings(path: Path = TIMINGS) -> dict[str, float]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and type(seconds) in (int, float) and seconds >= 0
        for name, seconds in value.items()
    ):
        raise ValueError("Test timings must map file names to non-negative seconds.")
    return {name: float(seconds) for name, seconds in value.items()}


def assign(files: Iterable[str], count: int, timings: Mapping[str, float]) -> dict[str, int]:
    """Give each file one part, slowest first into the lightest part; the result is stable."""
    loads = [0.0] * count
    parts = {}
    for name in sorted(set(files), key=lambda item: (-timings.get(item, UNKNOWN_SECONDS), item)):
        lightest = min(range(count), key=lambda part: (loads[part], part))
        loads[lightest] += timings.get(name, UNKNOWN_SECONDS)
        parts[name] = lightest + 1
    return parts
