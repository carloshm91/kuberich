"""Real helper subprocesses exercise the native verifier's external-process boundary."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import verify_standalone

ROOT = Path(__file__).resolve().parents[2]


def test_controller_docker_remains_discoverable_when_the_application_has_no_path(
    monkeypatch, tmp_path
):
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nprintf 'owned controller command executed\\n'\n")
    docker.chmod(0o755)
    monkeypatch.setattr(verify_standalone.platform, "system", lambda: "Linux")
    monkeypatch.setattr(verify_standalone.shutil, "which", lambda name: str(docker))
    monkeypatch.setattr(
        verify_standalone,
        "capture_docker",
        lambda executable: {"DOCKER_HOST": "unix:///owned-controller.sock"},
    )
    host = verify_standalone.Host(tmp_path / "bundle", tmp_path, tmp_path)
    output = host.observe(
        "outside-path", ["/app/kuberich", "--version"], {"PATH": str(tmp_path / "empty")}
    )
    assert output == "owned controller command executed\n"


def test_missing_controller_docker_is_an_explicit_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_standalone.platform, "system", lambda: "Linux")
    monkeypatch.setattr(verify_standalone.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="controller's Docker"):
        verify_standalone.Host(tmp_path, tmp_path, tmp_path)


@pytest.fixture
def helper(tmp_path):
    compiler = shutil.which("cc")
    assert compiler is not None, "Native helper verification requires the platform C compiler"
    executable = tmp_path / "owned-auth"
    subprocess.run(
        [
            compiler,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/support/native_helper.c"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return executable


def helper_environment(bundle: Path) -> dict[str, str]:
    result = {name: value for name, value in os.environ.items() if not name.startswith("_PYI_")}
    for name in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
        result.pop(name, None)
    result.update(KUBERNETES_EXEC_INFO="{}", OWNED_NATIVE_BUNDLE=str(bundle))
    return result


def test_native_helper_accepts_clean_credentials_and_retains_only_owned_marker(helper, tmp_path):
    marker = tmp_path / "marker"
    result = subprocess.run(
        [str(helper), str(marker)],
        env=helper_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert '"apiVersion":"client.authentication.k8s.io/v1"' in result.stdout
    assert marker.read_text() == "native auth helper called with sanitized loader environment\n"


@pytest.mark.parametrize(
    "key",
    [
        "_PYI_APPLICATION_HOME_DIR",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
    ],
)
def test_native_helper_refuses_private_frozen_loader_state_before_auth(helper, tmp_path, key):
    marker = tmp_path / "marker"
    environment = helper_environment(tmp_path)
    environment[key] = str(tmp_path / "_internal")
    result = subprocess.run(
        [str(helper), str(marker)], env=environment, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == (71 if key.startswith("_PYI_") else 72)
    assert result.stdout == "" and not marker.exists()


def test_native_exec_fixture_refuses_a_public_snapshot_before_launching_shell(helper, tmp_path):
    kubectl = tmp_path / "kubectl"
    shutil.copyfile(helper, kubectl)
    kubectl.chmod(0o755)
    snapshot = tmp_path / "snapshot"
    snapshot.write_text("owned snapshot")
    snapshot.chmod(0o644)
    environment = helper_environment(tmp_path)
    environment["OWNED_NATIVE_EVIDENCE"] = str(tmp_path)
    result = subprocess.run(
        [
            str(kubectl),
            "--kubeconfig=" + str(snapshot),
            "--context=owned",
            "--namespace=default",
            "exec",
            "--stdin",
            "--tty",
            "--container=worker",
            "owned-pod",
            "--",
            "/bin/sh",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 77
    assert result.stdout == "" and not (tmp_path / "exec-called").exists()
