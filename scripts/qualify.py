"""Run or collect phase gates: uv run python scripts/qualify.py 0.3.0."""

import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    if __package__ in {None, ""}:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.qualification_runner import main as qualify

    return qualify(argv)


if __name__ == "__main__":
    raise SystemExit(main())
