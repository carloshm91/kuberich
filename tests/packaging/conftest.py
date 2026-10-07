"""Require the same owned built artifacts across all packaging checks."""

import shutil
import sys

import pytest

from tests.support.distribution import ROOT, run
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
