"""Own two actual fresh children; instrumented allocation is not a latency result."""

import json
import sys
from pathlib import Path

import pytest

from tests.support.distribution import ROOT, run


@pytest.mark.parametrize("mode", ["memory", "latency"])
def test_real_terminal_history_retention_and_rendering_stress(tmp_path, mode):
    result = tmp_path / "result.json"
    child = run(
        [sys.executable, "-m", "tests.support.terminal_stress", mode, str(result)],
        ROOT,
        180,
        check=False,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    receipt = json.loads(result.read_text())
    assert receipt["measure"]
    output = Path("artifacts/terminal")
    output.mkdir(parents=True, exist_ok=True)
    (output / f"history-{mode}.json").write_bytes(result.read_bytes())
