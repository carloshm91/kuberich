"""Qualification retains inspector evidence and uses the real typed verifier."""

from pathlib import Path

from scripts.qualification import type_command
from scripts.qualification_runner import archive

ROOT = Path(__file__).resolve().parents[2]


def test_inspector_verifier_is_in_the_workflow_derived_strict_targets():
    assert "scripts/verify_container_inspection_kind.py" in type_command(ROOT)


def test_canonical_inspector_sibling_receipts_are_preserved_before_next_run(tmp_path):
    root = tmp_path / "source"
    evidence = root / "artifacts/container-inspection"
    evidence.mkdir(parents=True)
    (evidence / "evidence.json").write_text('{"passed":true}\n')
    (evidence / "container-inspection-api.json").write_text('{"reads":66}\n')
    destination = tmp_path / "retained"
    archive(root, destination)
    (evidence / "container-inspection-api.json").write_text('{"reads":0}\n')
    assert (destination / "container-inspection/evidence.json").read_text() == '{"passed":true}\n'
    assert (
        destination / "container-inspection/container-inspection-api.json"
    ).read_text() == '{"reads":66}\n'
