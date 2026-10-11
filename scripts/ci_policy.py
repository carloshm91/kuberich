"""Select explicit development/release matrices; unknown events fail closed."""

import json
import os
import sys
from pathlib import Path

PYTHONS = ("3.12", "3.13", "3.14")
LINUX_RUNNER = "ubuntu-24.04"
MACOS_RUNNER = "macos-latest"
NATIVE_JOBS = (
    {
        "os": "ubuntu-22.04",
        "target": "linux-x86_64",
        "tool_arch": "amd64",
        "kind_sha256": "aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d",
        "kubectl_sha256": "8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a",
    },
    {
        "os": "ubuntu-22.04-arm",
        "target": "linux-arm64",
        "tool_arch": "arm64",
        "kind_sha256": "20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2",
        "kubectl_sha256": "0ecf44450ee6063bf19dd166a103ee6df4a9034455c2abce626e6eea657d73fb",
    },
    {
        "os": "macos-15-intel",
        "target": "macos-x86_64",
        "tool_arch": "amd64",
        "kind_sha256": "",
        "kubectl_sha256": "",
    },
    {
        "os": "macos-14",
        "target": "macos-arm64",
        "tool_arch": "arm64",
        "kind_sha256": "",
        "kubectl_sha256": "",
    },
)


def matrix(event: str, ref: str) -> dict[str, list[dict[str, str]]]:
    if event == "pull_request":
        if not ref.startswith("refs/pull/") or not ref.endswith("/merge"):
            raise ValueError("PR verification requires the pull-request merge ref")
    elif event in {"push", "workflow_dispatch"}:
        if ref != "refs/heads/main":
            raise ValueError("Main verification requires refs/heads/main")
    else:
        raise ValueError("Unsupported quality event")
    jobs = [{"os": LINUX_RUNNER, "python": python} for python in PYTHONS]
    if event == "pull_request":
        jobs.append({"os": MACOS_RUNNER, "python": "3.12"})
    elif event == "workflow_dispatch":
        jobs.extend({"os": MACOS_RUNNER, "python": python} for python in PYTHONS)
    return {"include": jobs}


def main() -> int:
    try:
        selected = matrix(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])
        native = native_matrix(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"matrix={json.dumps(selected, separators=(',', ':'))}\n")
            output.write(f"native_matrix={json.dumps(native, separators=(',', ':'))}\n")
    except (KeyError, ValueError, OSError) as error:
        print(f"Quality planning failed: {error}", file=sys.stderr)
        return 1
    return 0


def native_matrix(event: str, ref: str) -> dict[str, list[dict[str, str]]]:
    matrix(event, ref)  # Share the exact event/ref validation; no alternative publication event.
    return {"include": [dict(job) for job in NATIVE_JOBS]}


if __name__ == "__main__":
    raise SystemExit(main())
