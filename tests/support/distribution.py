"""Built artifacts and isolated installed environments shared by packaging tests."""

import os
import shutil
import signal
import subprocess
import sys
import tomllib
from contextlib import suppress
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]


def clean_environment(directory: Path) -> dict[str, str]:
    """Keep installer state/configuration away from the developer's tools."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("KUBERICH_", "KUBETROL_", "TEXTUAL", "UV_", "PIPX_", "PIP_"))
        and name not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
    }
    state = directory / "installer-state"
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "UV_NO_CONFIG": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "UV_TOOL_DIR": str(state / "uv/tools"),
            "UV_TOOL_BIN_DIR": str(state / "uv/bin"),
            "UV_CACHE_DIR": str(state / "uv/cache"),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_CACHE_DIR": str(state / "pip-cache"),
            "PIPX_HOME": str(state / "pipx/home"),
            "PIPX_BIN_DIR": str(state / "pipx/bin"),
            "PIPX_MAN_DIR": str(state / "pipx/man"),
            "PIPX_SHARED_LIBS": str(state / "pipx/shared"),
            "PIPX_CACHE_DIR": str(state / "pipx/cache"),
            "PIPX_LOG_DIR": str(state / "pipx/log"),
            "PIPX_DISABLE_SHARED_LIBS_AUTO_UPGRADE": "1",
            "PIPX_DEFAULT_BACKEND": "pip",
            "PIPX_DEFAULT_PYTHON": sys.executable,
            "KUBECONFIG": str(directory / "no-cluster-config"),
            "KUBERICH_CONFIG": str(directory / "preferences.yaml"),
            "KUBERICH_LOG_FILE": str(directory / "kuberich.log"),
        }
    )
    return environment


def run(
    command: list[str],
    directory: Path,
    timeout: int = 120,
    *,
    check: bool = True,
    environment: dict[str, str] | None = None,
    unset_environment: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Own the installer process group, including timeout/failure cleanup."""
    settings = clean_environment(directory)
    settings.update(environment or {})
    for name in unset_environment:
        settings.pop(name, None)
    process = subprocess.Popen(
        command,
        cwd=directory,
        env=settings,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except BaseException:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


@pytest.fixture(scope="session")
def artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    assert uv is not None, "Install uv to run the distribution checks."
    output = tmp_path_factory.mktemp("artifacts")
    run(
        [uv, "build", "--python", sys.executable, "--out-dir", str(output)],
        ROOT,
        environment=clean_environment(output),
    )
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
