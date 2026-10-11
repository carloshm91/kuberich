"""Real manager upgrades between immutable local wheels, without public publication."""

import hashlib
import json
import shlex
import shutil
import sys
import zipfile
from pathlib import Path

import pytest
from packaging.version import Version

from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell


@pytest.fixture(scope="session")
def upgrade_artifacts(artifacts, tmp_path_factory):
    directory = tmp_path_factory.mktemp("upgrade-artifacts")
    source = directory / "source"
    source.mkdir()
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE", ".gitignore"):
        shutil.copyfile(ROOT / name, source / name)
    # This is an unpublished owned test build, not a repository version bump or edited wheel.
    current = Version(PROJECT["version"])
    fixture_version = (
        f"{current.base_version}.dev{current.dev + 1}"
        if current.dev is not None
        else current.public + ".post1"
        if current.is_prerelease
        else f"{current.base_version}rc1"
    )
    # A stable candidate receives the real normal upgrade, rather than only
    # serving as the baseline for a hypothetical subsequent test version.
    old_version, version = (
        (str(current), fixture_version)
        if current.is_prerelease
        else (fixture_version, str(current))
    )
    assert Version(version) > Version(old_version)
    project = source / "pyproject.toml"
    original = project.read_text()
    assert original.count(f'version = "{PROJECT["version"]}"') == 1
    project.write_text(
        original.replace(f'version = "{PROJECT["version"]}"', f'version = "{fixture_version}"', 1)
    )
    output = directory / "new"
    run(["uv", "build", "--wheel", "--python", sys.executable, "--out-dir", str(output)], source)
    fixture_wheel = next(output.glob("*.whl"))
    old, newer = (
        (artifacts[0], fixture_wheel) if current.is_prerelease else (fixture_wheel, artifacts[0])
    )
    with zipfile.ZipFile(old) as before, zipfile.ZipFile(newer) as after:
        old_payload = {
            name: before.read(name) for name in before.namelist() if name.startswith("kuberich/")
        }
        new_payload = {
            name: after.read(name) for name in after.namelist() if name.startswith("kuberich/")
        }
        assert old_payload and old_payload == new_payload
    requirements = directory / "runtime.txt"
    run(
        [
            "uv",
            "export",
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        ],
        ROOT,
    )
    dependencies = directory / "dependencies"
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--dest",
            str(dependencies),
            "--requirement",
            str(requirements),
        ],
        directory,
        180,
    )
    assert list(dependencies.glob("*.whl"))
    return old, newer, old_version, version, dependencies


@pytest.mark.parametrize("installer", ["uv", "pipx"])
def test_real_version_upgrade_retains_preferences_and_runs_installed_ui(
    upgrade_artifacts, tmp_path, installer
):
    old, newer, old_version, version, dependencies = upgrade_artifacts
    outside = tmp_path / "outside"
    outside.mkdir()
    wheelhouse = tmp_path / "owned wheelhouse"
    shutil.copytree(dependencies, wheelhouse)
    shutil.copyfile(old, wheelhouse / old.name)
    environment = clean_environment(outside)
    preferences = Path(environment["KUBERICH_CONFIG"])
    preferences.write_text("schema_version: 1\nread_only: true\nrefresh_seconds: 1.5\n")
    caller_config = Path(environment["KUBECONFIG"])
    caller_config.write_bytes(b"owned caller sentinel; no cluster credentials\n")
    preference_bytes, caller_bytes = preferences.read_bytes(), caller_config.read_bytes()
    originals = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (old, newer)}
    if installer == "uv":
        manager = ["uv", "tool"]
        options = ["--no-index", "--find-links", str(wheelhouse), "--prerelease", "allow"]
        install = [*manager, "install", "--python", sys.executable, *options, "kuberich"]
        upgrade = [*manager, "upgrade", *options, "kuberich"]
        binary = Path(environment["UV_TOOL_BIN_DIR"]) / "kuberich"
    else:
        manager = [sys.executable, "-m", "pipx"]
        options = [
            "--pip-args",
            shlex.join(["--no-index", "--find-links", str(wheelhouse), "--pre"]),
        ]
        install = [
            *manager,
            "install",
            "--backend",
            "pip",
            "--python",
            sys.executable,
            *options,
            "kuberich",
        ]
        upgrade = [*manager, "upgrade", "--skip-maintenance", *options, "kuberich"]
        binary = Path(environment["PIPX_BIN_DIR"]) / "kuberich"
    commands = []
    installed = False
    try:
        for argv in (install, upgrade):
            result = run(argv, outside, 180, environment=environment)
            installed = True
            commands.append({"command": argv, "exit": result.returncode})
            assert (
                run([str(binary), "--version"], outside, environment=environment).stdout
                == f"kuberich {old_version}\n"
            )
        # Make the second immutable version available; use the manager's normal upgrade command.
        shutil.copyfile(newer, wheelhouse / newer.name)
        result = run(upgrade, outside, 180, environment=environment)
        commands.append({"command": upgrade, "exit": result.returncode})
        assert (
            run([str(binary), "--version"], outside, environment=environment).stdout
            == f"kuberich {version}\n"
        )
        info = json.loads(run([str(binary), "info"], outside, environment=environment).stdout)
        assert info["version"] == version and info["preferences"]["read_only"] is True
        assert info["preferences"]["refresh_seconds"] == 1.5 and not info["cluster_connected"]
        assert (
            preferences.read_bytes() == preference_bytes
            and caller_config.read_bytes() == caller_bytes
        )
        for name, trial in (("navigation", terminal_navigation), ("shell", terminal_shell)):
            directory = outside / name
            directory.mkdir()
            if name == "navigation":
                trial([str(binary)], directory, evidence=f"upgraded-{installer}-navigation")
            else:
                trial([str(binary)], directory, "success", evidence=f"upgraded-{installer}-shell")
    finally:
        result = run(
            [*manager, "uninstall", "kuberich"], outside, 60, check=False, environment=environment
        )
        if installed:
            assert result.returncode == 0 and not binary.exists()
    assert (
        preferences.read_bytes() == preference_bytes and caller_config.read_bytes() == caller_bytes
    )
    assert originals == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (old, newer)
    }
    output = ROOT / "artifacts/packaging"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{installer}-version-upgrade.json").write_text(
        json.dumps(
            {
                "result": "passed",
                "installer": installer,
                "old_version": old_version,
                "new_version": version,
                "original_artifacts": originals,
                "commands": commands,
                "normal_manager_upgrade": True,
                "actual_upgraded_navigation_and_shell": True,
                "preferences_and_caller_config_unchanged": True,
                "uninstalled": True,
                "publication_performed": False,
            },
            indent=2,
        )
        + "\n"
    )
