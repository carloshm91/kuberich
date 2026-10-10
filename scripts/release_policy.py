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
FIRST_PUBLIC_VERSION = "0.1.0"
RELEASE_GATES = {"D10"}
QUALIFICATION_GATES = {"D04", "D06", "D07", "D08", "D09", "D11"}
PHASE_GATES = {
    "0.1.0": "D06",
    "0.2.0": "D07",
    "0.3.0": "D08",
    "0.4.0": "D09",
    "0.5.0": "D11",
    "1.0.0": "Q06",
}
# Original plan issue creation order, #13 through #91. Phase changes cannot remap IDs.
TASK_ISSUE_IDS = (
    "F00",
    "F01",
    "F02",
    "F03",
    "B01",
    "F04",
    "F05",
    "C01",
    "C06",
    "C07",
    "C02",
    "C03",
    "C04",
    "B02",
    "B03",
    "B04",
    "S01",
    "S02",
    "S03",
    "S04",
    "Q02",
    "D01",
    "Q04",
    "D02",
    "D03",
    "Q01",
    "W01",
    "D04",
    "B05",
    "S05",
    "M01",
    "M02",
    "M03",
    "M04",
    "C08",
    "S07",
    "D05",
    "Q03",
    "D06",
    "C05",
    "B06",
    "S06",
    "M05",
    "U01",
    "U02",
    "U03",
    "U04",
    "U05",
    "B07",
    "S08",
    "M08",
    "U06",
    "D07",
    "M06",
    "M07",
    "O01",
    "O02",
    "O03",
    "O04",
    "O05",
    "O06",
    "O07",
    "D08",
    "A01",
    "A02",
    "A03",
    "A04",
    "A05",
    "Q07",
    "D09",
    "D12",
    "D13",
    "D14",
    "D11",
    "Q05",
    "Q06",
    "D10",
    "W02",
    "W03",
)


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
        raise ValueError("Public publication requires 0.1.0 or a later release base")
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


def phase_requirements(
    version: str, plan: dict[str, Any], index: dict[str, Any]
) -> tuple[int, list[int]]:
    """Validate the entire reviewed graph before requesting any live issue."""
    publication_tag(version)
    try:
        if plan["repository"] != REPOSITORY or index["repository"] != REPOSITORY:
            raise ValueError("Release plan and issue index belong to another repository")
        delivery = plan["delivery"]
        if (
            delivery["first_public_version"] != FIRST_PUBLIC_VERSION
            or delivery["stable_public_version"] != "1.0.0"
            or delivery["publication_gate"] != "D10"
            or delivery["feature_first"] is not False
        ):
            raise ValueError("Release delivery policy differs from the reviewed phases")
        milestones = [item["title"] for item in plan["milestones"]]
        if any(not isinstance(item, str) for item in milestones) or len(set(milestones)) != len(
            milestones
        ):
            raise ValueError("Release milestones must have unique titles")
        tasks: dict[str, dict[str, Any]] = {}
        for task in plan["tasks"]:
            identifier = task["id"]
            if not isinstance(identifier, str) or not identifier or identifier in tasks:
                raise ValueError("Duplicate or invalid release task identity")
            dependencies = task["requires"]
            if (
                task["milestone"] not in milestones
                or not isinstance(dependencies, list)
                or any(not isinstance(item, str) for item in dependencies)
                or len(set(dependencies)) != len(dependencies)
            ):
                raise ValueError("Invalid release task milestone or dependencies")
            tasks[identifier] = task
        if set(tasks) != set(TASK_ISSUE_IDS):
            raise ValueError("Release plan must preserve all 79 reviewed task identities")
        issues = index["issues"]
        expected_numbers = dict(zip(TASK_ISSUE_IDS, range(13, 92), strict=True))
        expected_numbers.update({f"E{number:02}": number for number in range(1, 13)})
        if set(issues) != set(expected_numbers):
            raise ValueError("Release issue index must preserve reviewed epic/task identities")
        issue_numbers: dict[str, int] = {}
        for identifier, issue in issues.items():
            number = issue["number"]
            if (
                not isinstance(identifier, str)
                or not identifier
                or type(number) is not int
                or number <= 0
                or number in issue_numbers.values()
            ):
                raise ValueError("Issue identities must be distinct positive integers")
            if (
                number != expected_numbers[identifier]
                or issue["url"] != f"https://github.com/{REPOSITORY}/issues/{number}"
            ):
                raise ValueError(
                    "Release issue identity or canonical URL differs from the reviewed plan"
                )
            issue_numbers[identifier] = number
        if not tasks.keys() <= issue_numbers.keys() or "D10" not in tasks:
            raise ValueError("Release tasks must trace to their issue identities")
        if tasks["D10"]["milestone"] != "v0.1.0" or tasks["D10"]["requires"] != ["D06"]:
            raise ValueError("D10 must own initial publication after the reviewed D06 phase")
        seen: set[str] = set()
        visiting: set[str] = set()

        def visit(identifier: str) -> None:
            if identifier not in tasks:
                raise ValueError(f"Unknown release dependency: {identifier}")
            if identifier in visiting:
                raise ValueError(f"Release dependency cycle: {identifier}")
            if identifier in seen:
                return
            visiting.add(identifier)
            for dependency in tasks[identifier]["requires"]:
                visit(dependency)
            visiting.remove(identifier)
            seen.add(identifier)

        for identifier in tasks:
            visit(identifier)
        execution = delivery["execution_order"]
        if not isinstance(execution, list) or any(not isinstance(item, str) for item in execution):
            raise ValueError("Release execution order must list task identities")
        if len(execution) != len(tasks) or set(execution) != tasks.keys():
            raise ValueError("Release execution must retain every task exactly once")
        positions = {identifier: position for position, identifier in enumerate(execution)}
        if any(
            positions[dependency] >= positions[identifier]
            for identifier, task in tasks.items()
            for dependency in task["requires"]
        ):
            raise ValueError("Release execution violates a task dependency")

        def extras(values: Any) -> list[int]:
            if (
                not isinstance(values, list)
                or any(type(number) is not int or number <= 0 for number in values)
                or len(set(values)) != len(values)
            ):
                raise ValueError("Release extras must be distinct positive issue numbers")
            return values

        common = extras(delivery["publication_extra_issues"])
        if not {149, 150, 154, 155, 157, 162, 166} <= set(common):
            raise ValueError("Release launch prerequisites are missing")
        phases = delivery["release_phases"]
        if not isinstance(phases, list) or len(phases) != len(PHASE_GATES):
            raise ValueError("Require every explicitly reviewed release phase")
        for phase, (base, gate) in zip(phases, PHASE_GATES.items(), strict=True):
            if (
                set(phase) != {"version", "qualification_gate", "extra_issues"}
                or phase["version"] != base
                or phase["qualification_gate"] != gate
                or gate not in tasks
                or tasks[gate]["milestone"] != f"v{base}"
            ):
                raise ValueError("Release phase version, order or qualifier differs")
            extras(phase["extra_issues"])
        if (
            not {53, 54, 123} <= set(phases[0]["extra_issues"])
            or 124 not in phases[1]["extra_issues"]
        ):
            raise ValueError("Required phase-specific behavior is missing")
        selected = [
            position
            for position, phase in enumerate(phases)
            if Version(phase["version"]).release[:2] == Version(version).release[:2]
        ]
        if len(selected) != 1:
            raise ValueError("No explicitly reviewed release phase exists for this minor version")
        required: set[str] = set()

        def include(identifier: str) -> None:
            if identifier in required:
                return
            required.add(identifier)
            for dependency in tasks[identifier]["requires"]:
                include(dependency)

        numbers = list(common)
        for phase in phases[: selected[0] + 1]:
            include(phase["qualification_gate"])
            numbers.extend(phase["extra_issues"])
        # D10 owns first activation; every patch or subsequent phase requires it closed.
        if Version(version).base_version != FIRST_PUBLIC_VERSION:
            include("D10")
        else:
            for dependency in tasks["D10"]["requires"]:
                include(dependency)
        for identifier in tasks:
            if issue_numbers[identifier] in numbers:
                include(identifier)
        numbers.extend(issue_numbers[identifier] for identifier in sorted(required))
        return issue_numbers["D10"], list(dict.fromkeys(numbers))
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed or untraceable release phase plan") from error


def milestone_readiness(api: API, version: str, plan: dict[str, Any], index: dict[str, Any]) -> int:
    gate, numbers = phase_requirements(version, plan, index)
    for number in numbers:
        issue = api(f"repos/{REPOSITORY}/issues/{number}")
        if (
            issue.get("number") != number
            or issue.get("state") != "closed"
            or "pull_request" in issue
        ):
            raise ValueError(f"Release prerequisite is incomplete: #{number}")
    return gate
