"""Report 0.x latency honestly; keep unchanged strict controls and stable gates."""

import math
import os
import tomllib
from pathlib import Path
from typing import Any

from packaging.version import Version

LIMIT_SECONDS = 0.15
STRICT = "KUBERICH_STRICT_RUNTIME_BUDGETS"
VERSION = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())[
    "project"
]["version"]


def enforce_budget(version: str, *, strict: bool = False) -> bool:
    """Stable and prerelease 1.x candidates cannot opt out of the original limit."""
    return strict or Version(version).major >= 1


def budget_enforced(mode: str) -> bool:
    if mode not in {"positive", "negative", "coverage"}:
        raise ValueError("Unknown runtime measurement mode.")
    value = os.environ.get(STRICT, "0")
    if value not in {"0", "1"}:
        raise ValueError(f"{STRICT} must be 0 or 1.")
    return mode != "coverage" and (
        mode == "negative" or enforce_budget(VERSION, strict=value == "1")
    )


def budget_observation(gap: float | None, *, mode: str) -> dict[str, Any]:
    """Missing samples stay visible in failed originals instead of masking them."""
    return {
        "version": VERSION,
        "enforced": budget_enforced(mode),
        "met": type(gap) in (float, int) and gap is not None and 0 < gap < LIMIT_SECONDS,
    }


def verify_budget(observation: Any, gap: float, *, mode: str) -> None:
    """Refuse receipt/env downgrades and distinguish an advisory result from a pass."""
    required = budget_enforced(mode)
    if (
        not isinstance(observation, dict)
        or set(observation) != {"version", "enforced", "met"}
        or observation["version"] != VERSION
        or type(observation["enforced"]) is not bool
        or type(observation["met"]) is not bool
        or type(gap) not in (float, int)
        or not math.isfinite(gap)
        or gap <= 0
        or observation["met"] is not (gap < LIMIT_SECONDS)
        or (required and not observation["enforced"])
        or (mode == "coverage" and observation["enforced"])
        or (mode == "positive" and observation["enforced"] and not observation["met"])
    ):
        raise ValueError("Invalid or unmet runtime budget policy/observation.")
