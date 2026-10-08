"""Reject missing, failed, cancelled, or skipped application matrix jobs."""

import json
import os
import sys

from scripts.ci_policy import matrix

REQUIRED_JOBS = {"plan", "application"}


def main() -> int:
    try:
        results = json.loads(os.environ["KUBERICH_JOB_RESULTS"])
        if not isinstance(results, dict) or results.keys() != REQUIRED_JOBS:
            raise ValueError("the complete required job set must be present")
        for name, job in results.items():
            if not isinstance(job, dict) or job.get("result") != "success":
                raise ValueError(f"required job did not succeed: {name}")
        expected = matrix(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"])
        outputs = results["plan"].get("outputs")
        if not isinstance(outputs, dict) or not isinstance(outputs.get("matrix"), str):
            raise ValueError("the planned matrix output must be present")
        planned = json.loads(outputs["matrix"])
        if planned != expected:
            raise ValueError("the verified event's complete matrix must be planned")
    except (KeyError, ValueError) as error:
        print(f"Quality gate failed: {error}", file=sys.stderr)
        return 1
    print("Quality gate passed: the complete application matrix succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
