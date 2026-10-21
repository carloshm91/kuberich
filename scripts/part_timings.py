"""Write per-file test durations from a JUnit report, to balance the parallel test parts."""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

from tests.support.parts import TIMINGS


def timings(report: Path) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for case in ElementTree.parse(report).getroot().iter("testcase"):
        module = case.get("classname", "").split(".")
        # A class name ends in its test class (for example tests.unit.test_x.TestY).
        while module and not module[-1].startswith("test_"):
            module.pop()
        if module:
            totals["/".join(module) + ".py"] += float(case.get("time", "0"))
    if not totals:
        raise ValueError("The JUnit report contains no test cases.")
    return {name: round(seconds, 1) for name, seconds in sorted(totals.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, default=TIMINGS)
    args = parser.parse_args()
    try:
        measured = timings(args.report)
    except (ValueError, OSError, ElementTree.ParseError) as error:
        print(f"Reading test timings failed: {error}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(measured, indent=2) + "\n")
    print(f"Wrote timings for {len(measured)} test files ({sum(measured.values()):.0f} s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
