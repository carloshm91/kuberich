"""Wheel and sdist installations execute owned benchmarks and browse local results."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from scripts.benchmark_tools import verify_benchmark_binary
from tests.support.benchmark_terminal import terminal_benchmark
from tests.support.distribution import ROOT, run


@pytest.fixture(scope="module", params=["wheel", "sdist"])
def benchmark_install(request, artifacts, installed_wheel, tmp_path_factory):
    kind = request.param
    artifact = artifacts[0 if kind == "wheel" else 1]
    if kind == "wheel":
        binary, directory = installed_wheel
    else:
        directory = tmp_path_factory.mktemp("benchmark-installed-sdist")
        uv = shutil.which("uv")
        assert uv is not None
        environment = directory / "venv"
        run([uv, "venv", "--python", sys.executable, str(environment)], directory)
        binary = environment / "bin"
        run(
            [uv, "pip", "install", "--python", str(binary / "python"), str(artifact)],
            directory,
            180,
        )
    observed = run(
        [
            str(binary / "python"),
            "-I",
            "-c",
            "from pathlib import Path; import kuberich; print(Path(kuberich.__file__).resolve())",
        ],
        directory,
    )
    imported = Path(observed.stdout.strip())
    assert imported.is_relative_to(binary.parent) and not imported.is_relative_to(ROOT)
    return kind, binary, hashlib.sha256(artifact.read_bytes()).hexdigest()


@pytest.mark.parametrize("stop", ["escape", "complete"])
def test_installed_actual_benchmark_cancel_metrics_and_offline_restart(
    benchmark_install, tmp_path, stop
):
    selected = os.environ.get("KUBERICH_TEST_VEGETA")
    if selected is None:
        pytest.skip("Supply the explicit optional KUBERICH_TEST_VEGETA fixture; CI provisions it.")
    vegeta = Path(selected)
    tool_digest = verify_benchmark_binary(vegeta)
    kind, binary, artifact_digest = benchmark_install
    name = f"installed-benchmarks-{kind}-{stop}"
    outcome = terminal_benchmark(
        [str(binary / "kuberich")], tmp_path, name, vegeta=vegeta, stop=stop
    )
    output = ROOT / "artifacts/packaging" / f"{name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "artifact_kind": kind,
                "artifact_sha256": artifact_digest,
                "vegeta_sha256": tool_digest,
                "installed_outside_checkout": True,
                "outcome": outcome,
            },
            indent=2,
        )
        + "\n"
    )
