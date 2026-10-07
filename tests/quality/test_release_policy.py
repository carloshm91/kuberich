"""Publication decisions reject incomplete qualification and ambiguous retries."""

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts.release_policy import (
    APPLICATION_JOBS,
    HASH,
    REPOSITORY,
    milestone_readiness,
    missing_files,
    protection,
    qualified_run,
    release_preflight,
    release_tag,
    require_sha,
    reuse_artifact,
    successful_jobs,
)

SHA = "a" * 40
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "version,tag",
    [
        ("0.0.1", "v0.0.1"),
        ("12.34.56", "v12.34.56"),
        ("0.0.1rc1", "v0.0.1-rc.1"),
        ("1.2.3rc24", "v1.2.3-rc.24"),
    ],
)
def test_release_version_tag_contract(version, tag):
    assert release_tag(version) == tag


@pytest.mark.parametrize(
    "version",
    [
        "0.0.1.dev0",
        "v0.0.1",
        "1.2",
        "1.2.3.post1",
        "1.2.3+local",
        "01.2.3",
        "1.2.3RC1",
        "1.2.3-rc.1",
        "1.2.3rc0",
        "1.2.3rc01",
        "1.2.3a1",
        "1.2.3b1",
        "1.2.3\n",
        "1.2.3;touch x",
        "1" * 65,
    ],
)
def test_nonrelease_versions_cannot_publish(version):
    with pytest.raises(ValueError):
        release_tag(version)


@pytest.mark.parametrize("sha", ["a" * 7, "A" * 40, "a" * 39, "a" * 41, "z" * 40, SHA + "\n"])
def test_full_commit_identity_is_required(sha):
    with pytest.raises(ValueError):
        require_sha(sha)


def main_protection():
    return {
        "required_status_checks": {
            "strict": True,
            "contexts": ["Quality gate", "Repository checks", "DCO"],
        },
        "enforce_admins": {"enabled": True},
        "required_pull_request_reviews": {"require_code_owner_reviews": False},
        "required_conversation_resolution": {"enabled": True},
        "required_linear_history": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }


def release_environment():
    return {
        "can_admins_bypass": False,
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
        "protection_rules": [
            {
                "type": "required_reviewers",
                "reviewers": [{"type": "User", "reviewer": {"login": "carloshm91"}}],
            }
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        "strict",
        "contexts",
        "admins",
        "reviews",
        "conversation",
        "linear",
        "force",
        "delete",
        "bypass",
        "reviewer",
        "rules",
        "protected",
        "custom",
        "missing",
    ],
)
def test_unenforced_main_or_environment_cannot_publish(change):
    main, env = main_protection(), release_environment()
    protection(main, env)
    if change in {"strict", "contexts"}:
        main["required_status_checks"][change] = False if change == "strict" else []
    elif change == "admins":
        main["enforce_admins"]["enabled"] = False
    elif change == "reviews":
        main["required_pull_request_reviews"] = None
    elif change in {"conversation", "linear"}:
        main[
            f"required_{'conversation_resolution' if change == 'conversation' else 'linear_history'}"
        ]["enabled"] = False
    elif change in {"force", "delete"}:
        main[f"allow_{'force_pushes' if change == 'force' else 'deletions'}"]["enabled"] = True
    elif change == "bypass":
        env["can_admins_bypass"] = True
    elif change == "reviewer":
        env["protection_rules"][0]["reviewers"][0]["reviewer"]["login"] = "someone-else"
    elif change == "rules":
        env["protection_rules"] = []
    elif change in {"protected", "custom"}:
        env["deployment_branch_policy"][
            f"{change}_branches" if change == "protected" else "custom_branch_policies"
        ] = change == "custom"
    else:
        main = None
    with pytest.raises(ValueError):
        protection(main, env)


@pytest.mark.parametrize(
    "conclusion",
    [None, "skipped", "failure", "cancelled", "timed_out", "neutral", "action_required"],
)
def test_required_jobs_must_actually_succeed(conclusion):
    with pytest.raises(ValueError):
        successful_jobs([{"name": "gate", "conclusion": conclusion}], {"gate"})
    with pytest.raises(ValueError):
        successful_jobs([], {"gate"})
    with pytest.raises(ValueError):
        successful_jobs([{"name": "gate", "conclusion": "success"}] * 2, {"gate"})


def trusted_run(path=".github/workflows/quality.yml"):
    return {
        "id": 12,
        "head_sha": SHA,
        "path": path,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_repository": {"full_name": REPOSITORY},
        "run_number": 3,
        "run_attempt": 1,
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("head_sha", "b" * 40),
        ("path", ".github/workflows/other.yml"),
        ("head_branch", "feature"),
        ("event", "pull_request"),
        ("status", "queued"),
        ("conclusion", "skipped"),
        ("head_repository", {"full_name": "fork/kubetrol"}),
    ],
)
def test_qualification_cannot_come_from_fork_wrong_workflow_or_commit(key, value):
    run = trusted_run()
    qualified_run(run, SHA, run["path"])
    run[key] = value
    with pytest.raises(ValueError):
        qualified_run(run, SHA, ".github/workflows/quality.yml")


def trusted_api():
    prefix = f"repos/{REPOSITORY}"
    return {
        prefix: {"full_name": REPOSITORY, "private": False},
        f"{prefix}/branches/main/protection": main_protection(),
        f"{prefix}/environments/release": release_environment(),
        f"{prefix}/environments/release-test": release_environment(),
        f"{prefix}/compare/{SHA}...main": {"merge_base_commit": {"sha": SHA}},
        f"{prefix}/commits/{SHA}": {
            "commit": {
                "message": "Signed-off-by: Carlos Herrera <carloshm91@gmail.com>",
                "tree": {"sha": "c" * 40},
            }
        },
        f"{prefix}/commits/{SHA}/pulls": [
            {
                "merged_at": "2026-10-07",
                "merge_commit_sha": SHA,
                "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
                "head": {"sha": "b" * 40, "repo": {"full_name": REPOSITORY}},
            }
        ],
        f"{prefix}/commits/{'b' * 40}": {"commit": {"tree": {"sha": "c" * 40}}},
        f"{prefix}/commits/{'b' * 40}/check-runs?per_page=100": {
            "check_runs": [{"name": "DCO", "conclusion": "success", "app": {"id": 1861}}]
        },
        f"{prefix}/actions/workflows/quality.yml/runs?head_sha={SHA}&event=push&per_page=100": {
            "workflow_runs": [trusted_run()]
        },
        f"{prefix}/actions/workflows/repository.yml/runs?head_sha={SHA}&event=push&per_page=100": {
            "workflow_runs": [dict(trusted_run(".github/workflows/repository.yml"), id=13)]
        },
        f"{prefix}/actions/runs/12/jobs?filter=latest&per_page=100": {
            "jobs": [{"name": name, "conclusion": "success"} for name in APPLICATION_JOBS]
        },
        f"{prefix}/actions/runs/13/jobs?filter=latest&per_page=100": {
            "jobs": [{"name": "Repository checks", "conclusion": "success"}]
        },
        f"{prefix}/actions/runs/12/artifacts?per_page=100": {
            "artifacts": [{"name": "quality-ubuntu-latest-python-3.12", "id": 18, "expired": False}]
        },
    }


@pytest.mark.parametrize("index,environment", [("pypi", "release"), ("testpypi", "release-test")])
def test_complete_main_qualification_selects_exact_artifact(index, environment):
    values = trusted_api()
    result = release_preflight(values.__getitem__, SHA, "0.0.1rc1", index)
    assert result == {
        "commit": SHA,
        "version": "0.0.1rc1",
        "tag": "v0.0.1-rc.1",
        "index": index,
        "environment": environment,
        "quality_run_id": 12,
        "artifact_id": 18,
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "private",
        "repository",
        "protection",
        "ancestor",
        "signoff",
        "pull_missing",
        "pull_duplicate",
        "pull_fork",
        "pull_unmerged",
        "tree",
        "dco_app",
        "dco_skipped",
        "dco_missing",
        "dco_duplicate",
        "run_missing",
        "run_latest_failed",
        "run_fork",
        "job_missing",
        "job_skipped",
        "artifact_missing",
        "artifact_expired",
        "artifact_duplicate",
    ],
)
def test_incomplete_or_ambiguous_release_qualification_is_rejected(mutation):
    data = deepcopy(trusted_api())
    prefix = f"repos/{REPOSITORY}"
    if mutation == "private":
        data[prefix]["private"] = True
    elif mutation == "repository":
        data[prefix]["full_name"] = "fork/kubetrol"
    elif mutation == "protection":
        data[f"{prefix}/branches/main/protection"] = None
    elif mutation == "ancestor":
        data[f"{prefix}/compare/{SHA}...main"]["merge_base_commit"]["sha"] = "d" * 40
    elif mutation == "signoff":
        data[f"{prefix}/commits/{SHA}"]["commit"]["message"] = "unsigned"
    elif mutation.startswith("pull_"):
        pulls = data[f"{prefix}/commits/{SHA}/pulls"]
        if mutation == "pull_missing":
            pulls.clear()
        elif mutation == "pull_duplicate":
            pulls.append(deepcopy(pulls[0]))
        elif mutation == "pull_fork":
            pulls[0]["head"]["repo"]["full_name"] = "fork/kubetrol"
        else:
            pulls[0]["merged_at"] = None
    elif mutation == "tree":
        data[f"{prefix}/commits/{'b' * 40}"]["commit"]["tree"]["sha"] = "d" * 40
    elif mutation.startswith("dco_"):
        checks = data[f"{prefix}/commits/{'b' * 40}/check-runs?per_page=100"]["check_runs"]
        if mutation == "dco_app":
            checks[0]["app"]["id"] = 15368
        elif mutation == "dco_skipped":
            checks[0]["conclusion"] = "skipped"
        elif mutation == "dco_missing":
            checks.clear()
        else:
            checks.append(deepcopy(checks[0]))
    elif mutation.startswith("run_"):
        runs = data[
            f"{prefix}/actions/workflows/quality.yml/runs?head_sha={SHA}&event=push&per_page=100"
        ]["workflow_runs"]
        if mutation == "run_missing":
            runs.clear()
        elif mutation == "run_fork":
            runs[0]["head_repository"]["full_name"] = "fork/kubetrol"
        else:
            runs.append(dict(runs[0], run_attempt=2, conclusion="failure"))
    elif mutation.startswith("job_"):
        jobs = data[f"{prefix}/actions/runs/12/jobs?filter=latest&per_page=100"]["jobs"]
        if mutation == "job_missing":
            jobs.pop()
        else:
            jobs[0]["conclusion"] = "skipped"
    else:
        artifacts = data[f"{prefix}/actions/runs/12/artifacts?per_page=100"]["artifacts"]
        if mutation == "artifact_missing":
            artifacts.clear()
        elif mutation == "artifact_expired":
            artifacts[0]["expired"] = True
        else:
            artifacts.append(deepcopy(artifacts[0]))
    with pytest.raises(ValueError):
        release_preflight(data.__getitem__, SHA, "0.0.1", "pypi")


def test_retry_uses_only_original_qualified_dispatch_artifact():
    prefix = f"repos/{REPOSITORY}"
    run = dict(trusted_run(".github/workflows/release.yml"), event="workflow_dispatch")
    data = {
        f"{prefix}/actions/runs/25": run,
        f"{prefix}/actions/runs/25/jobs?filter=latest&per_page=100": {
            "jobs": [{"name": "Validate release", "conclusion": "success"}]
        },
        f"{prefix}/actions/runs/25/artifacts?per_page=100": {
            "artifacts": [{"id": 55, "name": f"release-candidate-{SHA}-0.0.1", "expired": False}]
        },
    }
    assert reuse_artifact(data.__getitem__, SHA, "0.0.1", 25) == 55
    run["event"] = "pull_request"
    with pytest.raises(ValueError):
        reuse_artifact(data.__getitem__, SHA, "0.0.1", 25)
    with pytest.raises(ValueError):
        reuse_artifact(data.__getitem__, SHA, "0.0.1", 0)


def test_retries_only_stage_missing_identical_files_and_never_overwrite():
    expected = {"wheel.whl": "a" * 64, "source.tar.gz": "b" * 64}
    assert missing_files(expected, {}) == ["source.tar.gz", "wheel.whl"]
    assert missing_files(expected, {"wheel.whl": "a" * 64}) == ["source.tar.gz"]
    assert missing_files(expected, expected) == []
    for existing in ({"wheel.whl": "c" * 64}, {"other.whl": "d" * 64}):
        with pytest.raises(ValueError):
            missing_files(expected, existing)
    with pytest.raises(ValueError):
        missing_files({"wheel.whl": "bad"}, {})
    assert HASH.fullmatch(expected["wheel.whl"])


def test_workflow_has_readonly_dry_run_serialization_and_owner_protected_oidc():
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    assert list(workflow["on"]) == ["workflow_dispatch"]
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert inputs["dry_run"]["default"] is True
    assert workflow["concurrency"] == {"group": "kubetrol-release", "cancel-in-progress": False}
    assert workflow["permissions"] == {"contents": "read"}
    validate, publish = workflow["jobs"]["validate"], workflow["jobs"]["publish"]
    assert validate["permissions"] == {"contents": "read", "actions": "read"}
    assert "github.actor == 'carloshm91'" in validate["if"] and "refs/heads/main" in validate["if"]
    assert publish["if"] == "${{ !inputs.dry_run }}"
    assert publish["environment"]["name"] == "${{ needs.validate.outputs.environment }}"
    assert publish["permissions"]["id-token"] == "write"
    assert publish["permissions"]["attestations"] == "write"
    assert not any(
        "uv build" in step.get("run", "") for step in validate["steps"] + publish["steps"]
    )
    publisher = next(
        step
        for step in publish["steps"]
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")
    )
    assert (
        publisher["with"]["packages-dir"] == "missing/"
        and publisher["with"]["attestations"] is True
    )
    assert not {"password", "user"} & publisher["with"].keys()


@pytest.mark.parametrize("version", ["0.0.1", "0.0.1rc1", "0.0.2"])
def test_release_and_patch_require_closed_milestone_prerequisites(version):
    plan = {
        "milestones": [{"title": "v0.0.1"}, {"title": "v0.1.0"}],
        "tasks": [{"id": "D04", "milestone": "v0.0.1", "requires": ["F01"]}],
    }
    index = {"issues": {"F01": {"number": 14}, "D04": {"number": 40}}}
    issue = {"number": 14, "state": "closed"}
    calls = []

    def api(path):
        calls.append(path)
        return issue

    assert milestone_readiness(api, version, plan, index) == 40
    assert calls == [f"repos/{REPOSITORY}/issues/14"]
    issue["state"] = "open"
    with pytest.raises(ValueError, match="#14"):
        milestone_readiness(api, version, plan, index)


@pytest.mark.parametrize(
    "mutation", ["no_milestone", "no_gate", "duplicate_gate", "wrong_issue", "pr"]
)
def test_missing_or_ambiguous_release_readiness_cannot_pass(mutation):
    plan = {
        "milestones": [{"title": "v0.0.1"}],
        "tasks": [{"id": "D04", "milestone": "v0.0.1", "requires": ["F01"]}],
    }
    index = {"issues": {"F01": {"number": 14}, "D04": {"number": 40}}}
    issue = {"number": 14, "state": "closed"}
    if mutation == "no_milestone":
        plan["milestones"] = []
    elif mutation == "no_gate":
        plan["tasks"] = []
    elif mutation == "duplicate_gate":
        plan["tasks"].append(deepcopy(plan["tasks"][0]))
    elif mutation == "wrong_issue":
        issue["number"] = 15
    else:
        issue["pull_request"] = {}
    with pytest.raises(ValueError):
        milestone_readiness(lambda _: issue, "0.0.1", plan, index)
