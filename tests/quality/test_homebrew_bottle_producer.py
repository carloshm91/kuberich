"""Execute the producer's real Bash with owned commands, never personal Homebrew."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.support.distribution import ROOT

WORKFLOW = ROOT / ".github/workflows/bottles.yml"

BREW = r"""
import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["OWNED_ROOT"])
tag = os.environ["OWNED_TAG"]
version = os.environ["BOTTLE_VERSION"]
with (root / "commands.jsonl").open("a") as stream:
    stream.write(json.dumps({"args": args, "cwd": os.getcwd()}) + "\n")
if args == ["--repository", "kuberich/tap"]:
    print(root / "tap")
elif args == ["install", "--only-dependencies", "kuberich/tap/kuberich"]:
    if os.environ["OWNED_FAILURE"] == "dependencies": sys.exit(23)
elif args == ["fetch", "--build-from-source", "kuberich/tap/kuberich"]:
    if os.environ["OWNED_FAILURE"] == "fetch": sys.exit(23)
elif args == ["install", "--build-bottle", "kuberich/tap/kuberich"]:
    if os.environ["OWNED_FAILURE"] == "build": sys.exit(23)
elif args[:3] == ["bottle", "--json", "--no-rebuild"]:
    assert args[3:] == [
        "--root-url=https://github.com/kuberich/homebrew-tap/releases/download/kuberich-v" + version,
        "kuberich/tap/kuberich",
    ]
    assert pathlib.Path.cwd() == root / "bottles"
    base = "kuberich--" + version + "." + tag + ".bottle"
    pathlib.Path(base + ".tar.gz").write_bytes(b"owned synthetic bottle\n")
    pathlib.Path(base + ".json").write_text(json.dumps({"root_url": args[3].split("=", 1)[1]}))
elif args[:4] == ["bottle", "--merge", "--write", "--no-commit"]:
    assert len(args) == 5
    assert pathlib.Path(args[4]) == root / "runner" / ("kuberich--" + version + "." + tag + ".bottle.json")
    assert json.loads(pathlib.Path(args[4]).read_text())["root_url"] == (root / "bottles").as_uri()
    assert (root / "bottles" / ("kuberich-" + version + "." + tag + ".bottle.tar.gz")).is_file()
elif args == ["install", "kuberich/tap/kuberich"]:
    shown_tag = "wrong_tag" if os.environ["OWNED_FAILURE"] == "tag" else tag
    print("Pouring kuberich--" + version + "." + shown_tag + ".bottle.tar.gz", flush=True)
    if os.environ["OWNED_FAILURE"] == "resources": print("Resource kuberich--unexpected")
    if os.environ["OWNED_FAILURE"] == "pour": sys.exit(23)
elif args in (["trust", "--formula", "kuberich/tap/kuberich"],
              ["uninstall", "--force", "kuberich/tap/kuberich"],
              ["test", "kuberich/tap/kuberich"]):
    pass
else:
    raise AssertionError("Unexpected owned brew arguments: " + repr(args))
"""


def run_producer(
    tmp_path: Path, failure="", tag="arm64_sequoia", formula="# Source version: 0.4.0\n"
):
    """Run only dependency/application steps; never select a host's real brew."""
    job = yaml.safe_load(WORKFLOW.read_text())["jobs"]["build"]
    binary = tmp_path / "bin"
    binary.mkdir()
    for name, program in {
        "brew": BREW,
        "kuberich": 'import os; print("kuberich " + ("wrong" if os.environ["OWNED_FAILURE"] == "version" else os.environ["BOTTLE_VERSION"]))',
        "git": 'import os, pathlib, sys; root = pathlib.Path(os.environ["OWNED_ROOT"]); assert sys.argv[1:] == ["-C", str(root / "tap"), "checkout", "--", "Formula"]; (root / "reset").touch()',
    }.items():
        command = binary / name
        command.write_text("#!" + sys.executable + "\n" + program + "\n")
        command.chmod(0o700)
    for name in ("runner", "home", "tap"):
        (tmp_path / name).mkdir()
    (tmp_path / "tap/Formula").mkdir()
    (tmp_path / "tap/Formula/kuberich.rb").write_text(formula)
    config = tmp_path / "empty-kubeconfig"
    config.write_text("")
    config.chmod(0o600)
    environment = {
        "PATH": str(binary) + os.pathsep + "/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "KUBECONFIG": str(config),
        "RUNNER_TEMP": str(tmp_path / "runner"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "BOTTLE_VERSION": "0.4.0",
        "OWNED_ROOT": str(tmp_path),
        "OWNED_TAG": tag,
        "OWNED_FAILURE": failure,
    }
    shell = ["bash", "--noprofile", "--norc", "-e"]
    if job.get("defaults", {}).get("run", {}).get("shell") == "bash":
        shell += ["-o", "pipefail"]
    results = []
    steps = [step for step in job["steps"] if "run" in step]
    for index, step in enumerate(steps):
        script = step["run"].replace("${{ matrix.tag }}", tag)
        if index == 0:
            # Run the actual formula guards, avoiding the bootstrap's absolute
            # host-brew selection/update/tap. No real manager is ever invoked.
            script = script[script.index("formula=") :]
        result = subprocess.run(
            [*shell, "-c", script],
            cwd=tmp_path / step.get("working-directory", "."),
            env=environment | step.get("env", {}),
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
        results.append(result)
        if result.returncode:
            break
    commands = [json.loads(line) for line in (tmp_path / "commands.jsonl").read_text().splitlines()]
    return results, commands


@pytest.mark.parametrize("failure", ["dependencies", "fetch", "build", "pour"])
def test_failed_brew_cannot_be_hidden_by_a_successful_summary_or_pour_tee(tmp_path, failure):
    results, commands = run_producer(tmp_path, failure)
    assert results[-1].returncode != 0, results[-1].stdout + results[-1].stderr
    arguments = [command["args"] for command in commands]
    assert ["test", "kuberich/tap/kuberich"] not in arguments
    if failure == "dependencies":
        assert arguments == [
            ["--repository", "kuberich/tap"],
            ["install", "--only-dependencies", "kuberich/tap/kuberich"],
        ]
        assert not (tmp_path / "bottles").exists()
    elif failure in {"fetch", "build"}:
        assert not any(args[:1] == ["bottle"] for args in arguments)
    else:
        # Even a plausible Pouring line must not turn a failed brew into success.
        assert "Pouring kuberich--0.4.0." in (tmp_path / "runner/pour.log").read_text()
        assert arguments[-1] == ["install", "kuberich/tap/kuberich"]


@pytest.mark.parametrize("tag", ["arm64_sequoia", "sequoia", "x86_64_linux"])
def test_success_preserves_creation_directory_local_pour_and_final_test(tmp_path, tag):
    results, commands = run_producer(tmp_path, tag=tag)
    assert all(result.returncode == 0 for result in results), results
    assert sorted(path.name for path in (tmp_path / "bottles").iterdir()) == [
        f"kuberich--0.4.0.{tag}.bottle.json",
        f"kuberich-0.4.0.{tag}.bottle.tar.gz",
    ]
    arguments = [command["args"] for command in commands]
    assert arguments[-2:] == [
        ["test", "kuberich/tap/kuberich"],
        ["uninstall", "--force", "kuberich/tap/kuberich"],
    ]
    assert (
        sum(
            args == ["install", "--only-dependencies", "kuberich/tap/kuberich"]
            for args in arguments
        )
        == 1
    )
    assert (tmp_path / "reset").is_file()
    assert (tmp_path / "empty-kubeconfig").read_bytes() == b""


@pytest.mark.parametrize("failure", ["tag", "resources", "version"])
def test_incorrect_pour_or_cli_cannot_reach_brew_test(tmp_path, failure):
    results, commands = run_producer(tmp_path, failure)
    assert results[-1].returncode != 0
    assert not any(command["args"] == ["test", "kuberich/tap/kuberich"] for command in commands)


@pytest.mark.parametrize(
    "formula",
    [
        "# Source version: 0.3.0\n",
        "# Missing source identity\n",
        "# Source version: 0.4.0\n  bottle do\n",
    ],
)
def test_wrong_formula_or_existing_bottles_stop_before_dependencies(tmp_path, formula):
    results, commands = run_producer(tmp_path, formula=formula)
    assert len(results) == 1 and results[0].returncode != 0
    assert [command["args"] for command in commands] == [["--repository", "kuberich/tap"]]
    assert not (tmp_path / "bottles").exists()


def test_producer_has_separate_setup_and_one_application_deadline_with_strict_shell():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    build = workflow["jobs"]["build"]
    assert build["timeout-minutes"] == "${{ matrix.os == 'macos-15-intel' && 225 || 90 }}"
    assert build["defaults"]["run"]["shell"] == "bash"
    assert build["strategy"] == {
        "fail-fast": True,
        "matrix": {
            "include": [
                {"os": "macos-15", "tag": "arm64_sequoia"},
                {"os": "macos-15-intel", "tag": "sequoia"},
                {"os": "ubuntu-24.04", "tag": "x86_64_linux"},
            ]
        },
    }
    steps = build["steps"]
    assert [step["id"] for step in steps] == ["bootstrap", "dependencies", "producer", "upload"]
    assert [step["timeout-minutes"] for step in steps] == [
        10,
        "${{ matrix.os == 'macos-15-intel' && 120 || 75 }}",
        90,
        5,
    ]
    assert all(not step.get("continue-on-error", False) and "if" not in step for step in steps)
    assert "--only-dependencies" in steps[1]["run"]
    assert "--only-dependencies" not in steps[2]["run"]
    assert steps[3]["with"] == {
        "name": "bottle-${{ matrix.tag }}",
        "path": "bottles/",
        "if-no-files-found": "error",
        "retention-days": 30,
    }
    assert workflow["jobs"]["publish"]["needs"] == "build"
    assert workflow["jobs"]["publish"]["environment"]["name"] == "release"
