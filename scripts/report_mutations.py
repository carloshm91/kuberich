"""Report actual mutation kills without counting timeouts as successful tests."""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

OUTCOMES = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)
EXIT_CODES = {
    0: "survived",
    1: "killed",
    3: "killed",
    5: "no_tests",
    33: "no_tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    -24: "timeout",
    24: "timeout",
    152: "timeout",
    255: "timeout",
    2: "check_was_interrupted_by_user",
    -11: "segfault",
    -9: "segfault",
}


def report(value: object, *, internal_errors: int = 0) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Mutation statistics must be a JSON object.")
    counts: dict[str, int] = {}
    for key in ("total", *OUTCOMES):
        count = value.get(key)
        if type(count) is not int or count < 0:
            raise ValueError("Mutation statistics require every nonnegative integer count.")
        counts[key] = count
    assessed = sum(counts[key] for key in OUTCOMES)
    if not counts["total"] or assessed > counts["total"]:
        raise ValueError("Mutation statistics have an empty or inconsistent population.")
    incomplete = counts["total"] - assessed
    if type(internal_errors) is not int or not 0 <= internal_errors <= counts["killed"]:
        raise ValueError("Pytest internal errors cannot exceed reported kills.")
    actual_kills = counts["killed"] - internal_errors
    tool_errors = (
        sum(counts[key] for key in ("suspicious", "check_was_interrupted_by_user", "segfault"))
        + internal_errors
    )
    unattempted = incomplete + counts["no_tests"] + counts["skipped"]
    complete = unattempted == tool_errors == 0
    return {
        "schema_version": 1,
        "counts": counts,
        "unassessed": incomplete,
        "unattempted": unattempted,
        "normal_test_failure_kills": actual_kills,
        "pytest_internal_errors": internal_errors,
        "completed_without_tool_errors": complete,
        "clean_assertion_outcomes": complete and counts["timeout"] == 0,
        "timeout_review_required": counts["timeout"] > 0,
        "kill_percentage": 100 * actual_kills / counts["total"],
        "target_percentage": 85,
        "target_met": complete and 100 * actual_kills >= 85 * counts["total"],
        "timeout_counts_as_killed": False,
    }


def metadata_errors(directory: Path, expected: Mapping[str, int]) -> int:
    """Read exact pinned-tool exit codes; INTERNALERROR is not an assertion kill."""
    population = errors = 0
    observed = dict.fromkeys(OUTCOMES, 0)
    for path in directory.glob("src/**/*.meta"):
        data = json.loads(path.read_text())
        values = data.get("exit_code_by_key") if isinstance(data, dict) else None
        if not isinstance(values, dict) or any(
            not isinstance(key, str) or (code is not None and type(code) is not int)
            for key, code in values.items()
        ):
            raise ValueError("Mutation exit metadata is malformed.")
        population += len(values)
        errors += sum(code == 3 for code in values.values())
        for code in values.values():
            if code is not None:
                observed[EXIT_CODES.get(code, "suspicious")] += 1
    if population != expected["total"] or any(observed[key] != expected[key] for key in OUTCOMES):
        raise ValueError("Mutation metadata does not cover the reported population.")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--metadata", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        value = json.loads(arguments.input.read_text())
        result = report(value)
        counts = result["counts"]
        assert isinstance(counts, dict)
        errors = metadata_errors(arguments.metadata, counts)
        result = report(value, internal_errors=errors)
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Mutation report failed: {error}\n")
    print(json.dumps(result, sort_keys=True))
    if not result["target_met"]:
        print(
            "Mutation kill target is unmet; review the retained survivors and outcomes.",
            file=sys.stderr,
        )
    if result["timeout_review_required"]:
        print("Mutant timeouts require review and never count as kills.", file=sys.stderr)
    return 0 if result["completed_without_tool_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
