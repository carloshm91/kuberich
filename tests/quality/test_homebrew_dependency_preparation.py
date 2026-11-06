"""Owned-host guards, bounded failure evidence and exact-job dependency receipts."""

import json
import subprocess

import pytest
import yaml

from scripts.homebrew import RUNTIME_FORMULAE
from tests.support import homebrew_dependencies as dependencies
from tests.support.distribution import ROOT


@pytest.fixture
def owned(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    for name in dependencies.IDENTITY_KEYS:
        monkeypatch.setenv(name, "owned-" + name)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setattr(dependencies, "source_identity", lambda: {"commit": "a" * 40})
    monkeypatch.setattr(dependencies, "clean_environment", lambda _: {"PATH": "/owned/path"})
    calls = []

    def run(command, directory, timeout=120, **kwargs):
        calls.append((command, timeout, kwargs))
        if command[1:] == ["--prefix"]:
            output = str(tmp_path / "brew") + "\n"
        elif command[1:] == ["list", "--versions", "--formula"]:
            output = "".join(name + " 1.0\n" for name in RUNTIME_FORMULAE)
        else:
            output = "owned command output\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(dependencies, "run", run)
    return tmp_path / "receipt.json", calls


def test_preparation_and_application_share_exact_source_job_and_dependency_evidence(owned):
    output, calls = owned
    receipt = dependencies.prepare_dependencies("/owned/brew", output)
    assert receipt["result"] == "passed" and receipt["missing_before"] == []
    assert receipt["application_install_included"] is False
    assert receipt["end_to_end_cold_install"] is False
    command, timeout, settings = next(call for call in calls if "install" in call[0])
    assert command == ["/owned/brew", "install", "--formula", *RUNTIME_FORMULAE]
    assert timeout == 4500 and settings["environment"]["HOMEBREW_NO_AUTO_UPDATE"] == "1"
    assert dependencies.prepared_dependencies("/owned/brew", output) == receipt
    with pytest.raises(ValueError, match="fresh output"):
        dependencies.prepare_dependencies("/owned/brew", output)


@pytest.mark.parametrize("kind", ["failure", "timeout", "missing-dependencies"])
def test_failed_or_incomplete_dependency_setup_preserves_failed_receipt(owned, monkeypatch, kind):
    output, _ = owned
    original = dependencies.run

    def run(command, *args, **kwargs):
        if "install" in command:
            if kind == "timeout":
                raise subprocess.TimeoutExpired(command, 4500, b"partial stdout", b"partial stderr")
            if kind == "failure":
                return subprocess.CompletedProcess(command, 7, "failed stdout", "failed stderr")
        result = original(command, *args, **kwargs)
        if kind == "missing-dependencies" and command[1:2] == ["list"]:
            result.stdout = "libyaml 1.0\n"
        return result

    monkeypatch.setattr(dependencies, "run", run)
    with pytest.raises((ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        dependencies.prepare_dependencies("/owned/brew", output)
    receipt = json.loads(output.read_text())
    assert receipt["result"] == "failed" and receipt["elapsed_seconds"] >= 0
    if kind != "missing-dependencies":
        command = next(item for item in receipt["commands"] if "install" in item["command"])
        assert command["stdout"] and command["stderr"] and command["error"]
    with pytest.raises(ValueError, match="does not match"):
        dependencies.prepared_dependencies("/owned/brew", output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runner", {}),
        ("source", {"commit": "b" * 40}),
        ("brew", "/different/brew"),
        ("prefix", "/different/prefix"),
        ("required_formulae", ["different"]),
        ("installed_after", "libyaml 1.0\n"),
        ("application_install_included", True),
        ("end_to_end_cold_install", True),
    ],
)
def test_wrong_source_runner_tools_or_cold_claim_cannot_qualify_application(owned, field, value):
    output, _ = owned
    receipt = dependencies.prepare_dependencies("/owned/brew", output)
    receipt[field] = value
    output.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="does not match"):
        dependencies.prepared_dependencies("/owned/brew", output)


def test_personal_host_and_missing_job_identity_refused_before_homebrew(owned, monkeypatch):
    output, calls = owned
    monkeypatch.delenv("GITHUB_ACTIONS")
    with pytest.raises(ValueError, match="owned Actions"):
        dependencies.prepare_dependencies("/owned/brew", output)
    assert not calls and not output.exists()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.delenv("GITHUB_JOB")
    with pytest.raises(ValueError, match="job identity"):
        dependencies.prepare_dependencies("/owned/brew", output)
    assert not calls and not output.exists()


def test_source_mutation_during_dependency_setup_remains_failed(owned, monkeypatch):
    output, _ = owned
    identities = iter(({"commit": "a" * 40}, {"commit": "b" * 40}))
    monkeypatch.setattr(dependencies, "source_identity", lambda: next(identities))
    with pytest.raises(ValueError, match="Source changed"):
        dependencies.prepare_dependencies("/owned/brew", output)
    assert json.loads(output.read_text())["result"] == "failed"


@pytest.mark.parametrize("sha", ["not-a-commit", "b" * 40])
def test_workflow_source_commit_must_match_checkout_before_any_homebrew(owned, monkeypatch, sha):
    output, calls = owned
    monkeypatch.setenv("GITHUB_SHA", sha)
    for action in (dependencies.prepare_dependencies, dependencies.prepared_dependencies):
        with pytest.raises(ValueError, match=r"source commit|workflow commit"):
            action("/owned/brew", output)
    assert not calls and not output.exists()


def test_native_workflow_keeps_individual_application_limits_and_separate_dependency_budget():
    jobs = yaml.safe_load((ROOT / ".github/workflows/installation.yml").read_text())["jobs"]
    for name, application_limit in (("homebrew", 60), ("bottle", 90)):
        job = jobs[name]
        steps = job["steps"]
        setup = next(
            step
            for step in steps
            if step.get("run", "").endswith("tests.support.homebrew_dependencies")
        )
        application = next(step for step in steps if "pytest -q" in step.get("run", ""))
        assert setup["timeout-minutes"] == 80
        assert application["timeout-minutes"] == application_limit
        assert job["timeout-minutes"] == 80 + application_limit + 15
        assert steps.index(setup) < steps.index(application)
        assert "continue-on-error" not in setup and "continue-on-error" not in application
        assert len(job["strategy"]["matrix"]["os"]) == 3
