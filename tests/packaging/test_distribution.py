"""Check real built artifacts and entry points outside the source checkout."""

import configparser
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def run(
    command: list[str], directory: Path, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    """Run tools with an explicit directory and without ambient source import paths."""
    environment = os.environ.copy()
    for name in os.environ:
        if name.startswith("KUBETROL_"):
            environment.pop(name)
    environment.pop("PYTHONPATH", None)
    environment.pop("VIRTUAL_ENV", None)
    environment["KUBECONFIG"] = str(directory / "no-cluster-config")
    environment["KUBETROL_CONFIG"] = str(directory / "preferences.yaml")
    environment["KUBETROL_LOG_FILE"] = str(directory / "kubetrol.log")
    return subprocess.run(
        command,
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=timeout,
    )


@pytest.fixture(scope="session")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None, "Install uv to run the distribution checks."
    output = tmp_path_factory.mktemp("artifacts")
    run([uv, "build", "--out-dir", str(output)], ROOT)
    return next(output.glob("*.whl")), next(output.glob("*.tar.gz"))


@pytest.fixture(scope="session")
def installed_wheel(
    artifacts: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None
    directory = tmp_path_factory.mktemp("installed-wheel")
    (directory / "preferences.yaml").write_text("schema_version: 1\n", encoding="utf-8")
    venv = directory / "venv"
    run([uv, "venv", "--python", sys.executable, str(venv)], directory)
    binary_dir = venv / ("Scripts" if sys.platform == "win32" else "bin")
    python = binary_dir / ("python.exe" if sys.platform == "win32" else "python")
    run([uv, "pip", "install", "--python", str(python), str(artifacts[0])], directory, 180)
    return binary_dir, directory


def test_wheel_metadata_entry_point_and_assets(artifacts: tuple[Path, Path]) -> None:
    with zipfile.ZipFile(artifacts[0]) as archive:
        names = archive.namelist()
        assert "kubetrol/py.typed" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = BytesParser().parsebytes(archive.read(metadata_name))
        assert metadata["Name"] == "kubetrol"
        assert metadata["Version"] == PROJECT["version"]
        assert metadata["License-Expression"] == "MIT"
        assert any(name.endswith(".dist-info/licenses/LICENSE") for name in names)
        entry_name = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        entry_points = configparser.ConfigParser()
        entry_points.read_string(archive.read(entry_name).decode())
        assert entry_points["console_scripts"]["kubetrol"] == "kubetrol.cli:main"
        assert not any(name.startswith(("tests/", ".venv/", ".github/")) for name in names)


def test_source_distribution_can_build_a_wheel(
    artifacts: tuple[Path, Path], tmp_path: Path
) -> None:
    uv = shutil.which("uv")
    assert uv is not None
    with tarfile.open(artifacts[1]) as archive:
        archive.extractall(tmp_path, filter="data")
    source = next(tmp_path.glob("kubetrol-*"))
    assert (source / "src/kubetrol/py.typed").is_file()
    assert (source / "LICENSE").is_file()
    rebuilt = tmp_path / "rebuilt"
    run([uv, "build", "--wheel", "--out-dir", str(rebuilt)], source)
    assert next(rebuilt.glob("*.whl")).name == artifacts[0].name


@pytest.mark.parametrize("entry_point", ["console", "module"])
@pytest.mark.parametrize("argument", ["--help", "--version", "info", None])
def test_installed_entry_points_work_without_source_or_cluster(
    installed_wheel: tuple[Path, Path], entry_point: str, argument: str | None
) -> None:
    binary_dir, directory = installed_wheel
    if entry_point == "console":
        command = [str(binary_dir / ("kubetrol.exe" if sys.platform == "win32" else "kubetrol"))]
    else:
        command = [
            str(binary_dir / ("python.exe" if sys.platform == "win32" else "python")),
            "-m",
            "kubetrol",
        ]
    if argument is not None:
        command.append(argument)
    output = run(command, directory, 10)

    assert output.stderr == ""
    if argument == "--version":
        assert output.stdout == f"kubetrol {PROJECT['version']}\n"
    elif argument == "--help":
        assert "usage: kubetrol" in output.stdout
    elif argument == "info":
        information = json.loads(output.stdout)
        assert information["config_file"] == str(directory / "preferences.yaml")
        assert not information["cluster_connected"]
    else:
        assert "terminal interface is not available yet" in output.stdout


def test_installed_package_has_assets_and_runtime_dependencies(
    installed_wheel: tuple[Path, Path],
) -> None:
    binary_dir, directory = installed_wheel
    python = binary_dir / ("python.exe" if sys.platform == "win32" else "python")
    code = (
        "import importlib.metadata as m, importlib.resources as r, json; "
        "import textual, kubernetes_asyncio, platformdirs, yaml; "
        "print(json.dumps({'version': m.version('kubetrol'), "
        "'typed': r.files('kubetrol').joinpath('py.typed').is_file(), "
        "'textual': m.version('textual'), 'kubernetes_asyncio': m.version('kubernetes-asyncio')}))"
    )
    result = json.loads(run([str(python), "-c", code], directory, 10).stdout)
    assert result["version"] == PROJECT["version"]
    assert result["typed"] is True
    assert result["textual"] and result["kubernetes_asyncio"]


def test_installed_config_init_check_and_refusal_to_overwrite(
    installed_wheel: tuple[Path, Path], tmp_path: Path
) -> None:
    binary_dir, directory = installed_wheel
    command = [str(binary_dir / "kubetrol"), "--config", str(tmp_path / "preferences.yaml")]
    assert "Created default" in run([*command, "config", "init"], directory, 10).stdout
    assert "valid" in run([*command, "config", "check"], directory, 10).stdout
    with pytest.raises(subprocess.CalledProcessError) as error:
        run([*command, "config", "init"], directory, 10)
    assert error.value.returncode == 3
    assert "already exist" in error.value.stderr
