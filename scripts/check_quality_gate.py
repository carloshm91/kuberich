"""Reject missing, failed, cancelled, or skipped application matrix jobs."""

import json
import os
import sys

REQUIRED_JOBS = {"application"}


def main() -> int:
    try:
        results = json.loads(os.environ["KUBETROL_JOB_RESULTS"])
        if not isinstance(results, dict) or results.keys() != REQUIRED_JOBS:
            raise ValueError("the complete required job set must be present")
        for name, job in results.items():
            if not isinstance(job, dict) or job.get("result") != "success":
                raise ValueError(f"required job did not succeed: {name}")
    except (KeyError, ValueError) as error:
        print(f"Quality gate failed: {error}", file=sys.stderr)
        return 1
    print("Quality gate passed: the complete application matrix succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
