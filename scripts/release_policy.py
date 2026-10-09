"""Release decisions over exact versions, qualified runs and immutable bytes."""

import re
from collections.abc import Callable
from typing import Any

from packaging.version import Version

from scripts.ci_policy import LINUX_RUNNER, matrix

REPOSITORY = "carloshm91/kuberich"
OWNER = "carloshm91"
QUALITY_WORKFLOW = ".github/workflows/quality.yml"
RELEASE_WORKFLOW = ".github/workflows/release.yml"
APPLICATION_JOBS = {
    f"Application ({job['os']}, Python {job['python']})": job["os"]
    for job in matrix("workflow_dispatch", "refs/heads/main")["include"]
} | {"Verification plan": LINUX_RUNNER, "Quality gate": LINUX_RUNNER}
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
API = Callable[[str], Any]
FIRST_PUBLIC_VERSION = "1.0.0"
RELEASE_GATES = {"D10"}
QUALIFICATION_GATES = {"D04", "D06", "D07", "D08", "D09", "D11"}


def release_tag(value: str) -> str:
    number = r"(?:0|[1-9][0-9]*)"
    if len(value) > 64 or not re.fullmatch(
        rf"{number}\.{number}\.{number}(?:rc[1-9][0-9]*)?", value
    ):
        raise ValueError("Release version must be canonical X.Y.Z or X.Y.ZrcN")
    version = Version(value)
    if str(version) != value:
        raise ValueError("Release version is not normalized")
    base = ".".join(map(str, version.release))
    return f"v{base}-rc.{version.pre[1]}" if version.pre else f"v{base}"


def require_sha(value: str) -> None:
    if not SHA.fullmatch(value):
        raise ValueError("Use the full 40-character commit SHA")


def publication_tag(value: str) -> str:
    """Keep local candidate versions distinct from approved public releases."""
    tag = release_tag(value)
    if Version(value).release < Version(FIRST_PUBLIC_VERSION).release:
        raise ValueError("Public publication requires 1.0.0 or a later release base")
    return tag


def successful_jobs(jobs: list[dict[str, Any]], expected: dict[str, str]) -> None:
    for name, runner in expected.items():
        matching = [job for job in jobs if job.get("name") == name]
        if (
            len(matching) != 1
            or matching[0].get("status") != "completed"
            or matching[0].get("conclusion") != "success"
        ):
            raise ValueError(f"Required job did not succeed: {name}")
        if matching[0].get("labels") != [runner]:
            raise ValueError(f"Required job used a different runner: {name}; require {runner}")


def qualified_run(run: dict[str, Any], sha: str, path: str) -> None:
    event = "workflow_dispatch" if path == QUALITY_WORKFLOW else "push"
    if (
        run.get("head_sha") != sha
        or run.get("path") != path
        or run.get("head_branch") != "main"
        or run.get("event") != event
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError(f"Require a successful main {event} run from the exact repository/commit")


def protection(main: dict[str, Any], environment: dict[str, Any]) -> None:
    if not isinstance(main, dict) or not isinstance(environment, dict):
        raise ValueError("Main protection and release environment must exist")
    checks = main.get("required_status_checks") or {}
    required = {item["context"] for item in checks.get("checks", [])}
    required.update(checks.get("contexts", []))
    reviews = main.get("required_pull_request_reviews") or {}
    if (
        checks.get("strict") is not True
        or not {"Quality gate", "Repository checks", "DCO"} <= required
        or main.get("enforce_admins", {}).get("enabled") is not True
        or main.get("required_conversation_resolution", {}).get("enabled") is not True
        or main.get("required_linear_history", {}).get("enabled") is not True
        or not reviews
        or main.get("allow_force_pushes", {}).get("enabled") is not False
        or main.get("allow_deletions", {}).get("enabled") is not False
    ):
        raise ValueError("Main branch protections are not fully enforced")
    rules = environment.get("protection_rules", [])
    reviewer_rules = [rule for rule in rules if rule.get("type") == "required_reviewers"]
    policy = environment.get("deployment_branch_policy") or {}
    if (
        environment.get("can_admins_bypass") is not False
        or len(reviewer_rules) != 1
        or not any(
            reviewer.get("type") == "User" and reviewer.get("reviewer", {}).get("login") == OWNER
            for reviewer in reviewer_rules[0].get("reviewers", [])
        )
        or policy.get("protected_branches") is not True
        or policy.get("custom_branch_policies") is not False
    ):
        raise ValueError(
            "Release environment needs enforced maintainer review and protected branches"
        )


def missing_files(expected: dict[str, str], existing: dict[str, str]) -> list[str]:
    if any(not HASH.fullmatch(value) for value in expected.values()):
        raise ValueError("Expected artifact SHA-256 digest is invalid")
    if any(name not in expected or expected[name] != value for name, value in existing.items()):
        raise ValueError("Existing publication differs; never replace or overwrite it")
    return sorted(expected.keys() - existing.keys())


def release_preflight(api: API, sha: str, version: str, index: str) -> dict[str, Any]:
    require_sha(sha)
    tag = publication_tag(version)
    if index not in {"pypi", "testpypi"}:
        raise ValueError("Unsupported publication index")
    prefix = f"repos/{REPOSITORY}"
    repo = api(prefix)
    if repo.get("full_name") != REPOSITORY or repo.get("private") is not False:
        raise ValueError("Public launch approval and the intended repository are required")
    environment = "release" if index == "pypi" else "release-test"
    protection(
        api(f"{prefix}/branches/main/protection"), api(f"{prefix}/environments/{environment}")
    )
    comparison = api(f"{prefix}/compare/{sha}...main")
    if comparison.get("merge_base_commit", {}).get("sha") != sha:
        raise ValueError("Release commit must belong to main history")
    commit = api(f"{prefix}/commits/{sha}")
    if f"Signed-off-by: Carlos Herrera <{OWNER}@gmail.com>" not in commit["commit"]["message"]:
        raise ValueError("Main release commit lacks the maintainer sign-off")
    pulls = api(f"{prefix}/commits/{sha}/pulls")
    origins = [
        pull
        for pull in pulls
        if pull.get("merged_at")
        and pull.get("merge_commit_sha") == sha
        and pull.get("base", {}).get("ref") == "main"
        and pull.get("base", {}).get("repo", {}).get("full_name") == REPOSITORY
        and pull.get("head", {}).get("repo", {}).get("full_name") == REPOSITORY
    ]
    if len(origins) != 1:
        raise ValueError("Release commit must come from one merged in-repository main PR")
    head = api(f"{prefix}/commits/{origins[0]['head']['sha']}")
    if head["commit"]["tree"]["sha"] != commit["commit"]["tree"]["sha"]:
        raise ValueError("Originating PR contents differ from the release squash")
    dco = api(f"{prefix}/commits/{origins[0]['head']['sha']}/check-runs?per_page=100")["check_runs"]
    approved = [check for check in dco if check.get("name") == "DCO"]
    if (
        len(approved) != 1
        or approved[0].get("conclusion") != "success"
        or approved[0].get("app", {}).get("id") != 1861
    ):
        raise ValueError("Originating PR DCO must succeed from the actual DCO app")
    chosen = {}
    for filename, expected in (
        ("quality.yml", APPLICATION_JOBS),
        ("repository.yml", {"Repository checks": LINUX_RUNNER}),
    ):
        event = "workflow_dispatch" if filename == "quality.yml" else "push"
        runs = api(
            f"{prefix}/actions/workflows/{filename}/runs?head_sha={sha}&event={event}&per_page=100"
        )
        matching = [run for run in runs["workflow_runs"] if run.get("head_sha") == sha]
        if not matching:
            raise ValueError(f"Missing qualification run: {filename}")
        run = max(matching, key=lambda item: (item["run_number"], item["run_attempt"]))
        qualified_run(run, sha, f".github/workflows/{filename}")
        jobs = api(f"{prefix}/actions/runs/{int(run['id'])}/jobs?filter=latest&per_page=100")[
            "jobs"
        ]
        successful_jobs(jobs, expected)
        chosen[filename] = run
    run_id = int(chosen["quality.yml"]["id"])
    artifacts = api(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
    matches = [
        item for item in artifacts if item.get("name") == f"quality-{LINUX_RUNNER}-python-3.12"
    ]
    if len(matches) != 1 or matches[0].get("expired") is not False:
        raise ValueError("Require the retained qualified Linux 3.12 artifact")
    return {
        "commit": sha,
        "version": version,
        "tag": tag,
        "environment": environment,
        "quality_run_id": run_id,
        "artifact_id": int(matches[0]["id"]),
        "index": index,
    }


def reuse_artifact(api: API, sha: str, version: str, run_id: int) -> int:
    if run_id <= 0:
        raise ValueError("Retry source must be an explicit positive release run ID")
    prefix = f"repos/{REPOSITORY}"
    run = api(f"{prefix}/actions/runs/{run_id}")
    if (
        run.get("path") != RELEASE_WORKFLOW
        or run.get("event") != "workflow_dispatch"
        or run.get("head_branch") != "main"
        or run.get("status") != "completed"
        or run.get("head_repository", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("Retry must use a completed in-repository main release dispatch")
    jobs = api(f"{prefix}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")["jobs"]
    successful_jobs(jobs, {"Validate release": LINUX_RUNNER})
    matches = [
        artifact
        for artifact in api(f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100")["artifacts"]
        if artifact.get("name") == f"release-candidate-{sha}-{version}"
    ]
    if len(matches) != 1 or matches[0].get("expired") is not False:
        raise ValueError("Original qualified retry bundle is unavailable")
    return int(matches[0]["id"])


def milestone_readiness(api: API, version: str, plan: dict[str, Any], index: dict[str, Any]) -> int:
    publication_tag(version)
    target = Version(".".join(map(str, Version(version).release)))
    milestones = [
        item["title"]
        for item in plan["milestones"]
        if item["title"].startswith("v") and Version(item["title"][1:]) <= target
    ]
    if not milestones:
        raise ValueError("No reviewed release milestone exists for this version")
    milestone = max(milestones, key=lambda title: Version(title[1:]))
    gates = [
        task
        for task in plan["tasks"]
        if task["id"] in RELEASE_GATES and task["milestone"] == milestone
    ]
    if len(gates) != 1:
        raise ValueError("Release milestone needs one explicit reviewed release gate")
    gate = gates[0]
    tasks = {task["id"]: task for task in plan["tasks"]}
    prerequisites: set[str] = set()
    pending = list(gate["requires"])
    while pending:
        identifier = pending.pop()
        if identifier in prerequisites:
            continue
        prerequisites.add(identifier)
        pending.extend(tasks.get(identifier, {}).get("requires", []))
    numbers = dict.fromkeys(
        [int(index["issues"][identifier]["number"]) for identifier in sorted(prerequisites)]
        + plan.get("delivery", {}).get("publication_extra_issues", [])
    )
    for number in numbers:
        issue = api(f"repos/{REPOSITORY}/issues/{number}")
        if (
            issue.get("number") != number
            or issue.get("state") != "closed"
            or "pull_request" in issue
        ):
            raise ValueError(f"Release prerequisite is incomplete: #{number}")
    return int(index["issues"][gate["id"]]["number"])
