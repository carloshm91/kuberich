"""Select explicit development/release matrices; unknown events fail closed."""

import json
import os
import sys
from pathlib import Path

PYTHONS = ("3.12", "3.13", "3.14")


def matrix(event: str, ref: str) -> dict[str, list[dict[str, str]]]:
    if event == "pull_request":
        if not ref.startswith("refs/pull/") or not ref.endswith("/merge"):
            raise ValueError("PR verification requires the pull-request merge ref")
    elif event in {"push", "workflow_dispatch"}:
        if ref != "refs/heads/main":
            raise ValueError("Main verification requires refs/heads/main")
    else:
        raise ValueError("Unsupported quality event")
    jobs = [{"os": "ubuntu-latest", "python": python} for python in PYTHONS]
    if event == "pull_request":
        jobs.append({"os": "macos-latest", "python": "3.12"})
    elif event == "workflow_dispatch":
        jobs.extend({"os": "macos-latest", "python": python} for python in PYTHONS)
    return {"include": jobs}


def main() -> int:
    try:
        selected = matrix(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"matrix={json.dumps(selected, separators=(',', ':'))}\n")
    except (KeyError, ValueError, OSError) as error:
        print(f"Quality planning failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
