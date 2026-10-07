"""Require the same owned built artifacts across all packaging checks."""

import json
import shutil
import sys

import pytest

from scripts.check_supply_chain import INPUT_FILES, generate, write_json
from scripts.release import prepare, verify_bundle
from scripts.supply_chain import digest
from tests.support.distribution import PROJECT, ROOT, run
from tests.support.distribution import artifacts as artifacts
from tests.support.distribution import installed_wheel as installed_wheel


@pytest.fixture(scope="session")
def security_evidence(artifacts, tmp_path_factory):
    directory = tmp_path_factory.mktemp("supply-chain")
    distribution = directory / "dist"
    distribution.mkdir()
    for artifact in artifacts:
        shutil.copy2(artifact, distribution / artifact.name)
    output = directory / "reports"
    result = run(
        [
            sys.executable,
            "-m",
            "scripts.check_supply_chain",
            "--dist",
            str(distribution),
            "--output",
            str(output),
        ],
        ROOT,
        600,
        check=False,
        environment={"PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Supply-chain gate passed" in result.stdout, result.stderr
    retained = ROOT / "artifacts/security"
    retained.mkdir(parents=True, exist_ok=True)
    for path in output.iterdir():
        shutil.copy2(path, retained / path.name)
    return output, distribution


@pytest.fixture(scope="session")
def canonical_release(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("canonical-rc")
    source = tmp_path / "source"
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    files = {
        *INPUT_FILES,
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        ".gitignore",
        "scripts/__init__.py",
        "scripts/homebrew.py",
        "packaging/homebrew/README.md",
        "packaging/homebrew/.github/workflows/verify.yml",
    }
    for name in files:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    project = source / "pyproject.toml"
    project.write_text(
        project.read_text().replace(f'version = "{PROJECT["version"]}"', 'version = "0.0.1rc1"', 1)
    )
    lock = source / "uv.lock"
    entry = f'name = "kubetrol"\nversion = "{PROJECT["version"]}"'
    assert lock.read_text().count(entry) == 1
    lock.write_text(lock.read_text().replace(entry, 'name = "kubetrol"\nversion = "0.0.1rc1"', 1))
    checked = run(
        ["uv", "lock", "--locked", "--offline", "--python", sys.executable], source, 60, check=False
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    run(["git", "init", "--initial-branch=main"], source)
    run(["git", "add", "src", *sorted(files)], source)
    run(
        [
            "git",
            "-c",
            "user.name=Release Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-s",
            "-m",
            "test: owned unpublished release candidate",
        ],
        source,
    )
    sha = run(["git", "rev-parse", "HEAD"], source).stdout.strip()
    run(["uv", "build", "--python", sys.executable], source, 120)
    generate(source / "artifacts/security", source / "dist", root=source)
    bundle = tmp_path / "release-candidate"
    prepared = prepare(source, bundle, sha, "0.0.1rc1", root=source)
    assert prepared["tag"] == "v0.0.1-rc.1" and prepared["candidate_only"] is False
    verify_bundle(bundle, sha, "0.0.1rc1", root=source)
    outside = tmp_path / "outside"
    outside.mkdir()
    installed = tmp_path / "installed"
    run(["uv", "venv", "--python", sys.executable, str(installed)], outside, 60)
    wheel = next((bundle / "dist").glob("*.whl"))
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed / "bin/python"),
            "--only-binary",
            ":all:",
            str(wheel),
        ],
        outside,
        120,
    )
    assert (
        run([str(installed / "bin/kubetrol"), "--version"], outside).stdout == "kubetrol 0.0.1rc1\n"
    )
    result = run([str(installed / "bin/kubetrol"), "--help"], outside)
    assert "--context" in result.stdout and "--readonly" in result.stdout
    manifest = json.loads((bundle / "release.json").read_text())
    assert all(digest(bundle / name) == value for name, value in manifest["files"].items())
    retained = ROOT / "artifacts/releases"
    retained.mkdir(parents=True, exist_ok=True)
    write_json(
        retained / "local-rc.json",
        {
            "version": "0.0.1rc1",
            "commit": sha,
            "artifacts": {path.name: digest(path) for path in (bundle / "dist").iterdir()},
            "installed_outside_checkout": True,
            "publications": 0,
            "index": "local fixture",
        },
    )
    return source, bundle, sha
