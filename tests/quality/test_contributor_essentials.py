"""Current contributor instructions are short and issue forms link one contract."""

import re
from pathlib import Path

import yaml

from scripts.startup_policy import (
    CLI_BUDGET_NS,
    IMPORT_BUDGET_US,
    PAINT_BUDGET_NS,
    RSS_BUDGET_BYTES,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = "https://github.com/carloshm91/kuberich/blob/main/CONTRIBUTING.md#delivery-contract"


def test_contribution_guide_keeps_delivery_architecture_identity_and_real_commands():
    guide = (ROOT / "CONTRIBUTING.md").read_text()
    assert "## Delivery contract\n" in guide
    assert "### Definition of ready\n" in guide and "### Definition of done\n" in guide
    assert "](docs/architecture.md)" in guide and "](docs/adr/README.md)" in guide
    for command in (
        "git commit -s",
        "uv sync --locked --group dev",
        "uv run pytest tests/unit tests/contract tests/ui -m fast -n 12",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run python scripts/check_coverage.py coverage.json",
        "uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float",
    ):
        assert command in guide
    assert "90% line, 90% branch and 90% changed-line coverage" in guide
    assert "100%" in guide and "contributor identity" in guide
    assert "squash" in guide and "publication" in guide
    assert "active context" in guide and "disposable clusters" in guide
    assert "ONE implementation issue globally" in guide
    assert (
        "git fetch --no-tags https://github.com/carloshm91/kuberich.git refs/pull/277/head refs/pull/290/head"
        in guide
    )
    assert "scripts/qualify.py 0.3.0" in guide and "private-access" in guide
    assert "docs/internal/first-preview-current.md" in guide


def test_bug_feature_and_task_forms_link_instead_of_copying_delivery_contract():
    expected = {
        "bug.yml": {"version", "environment", "reproduce", "evidence"},
        "feature.yml": {"problem", "outcome", "context"},
        "task.yml": {"outcome", "scope", "acceptance", "verification", "dependencies"},
    }
    for name, fields in expected.items():
        form = yaml.safe_load((ROOT / ".github/ISSUE_TEMPLATE" / name).read_text())
        assert form["name"] and form["description"] and form["title"]
        body = form["body"]
        assert {item["id"] for item in body if "id" in item} == fields
        instructions = [item["attributes"]["value"] for item in body if item["type"] == "markdown"]
        assert len(instructions) == 1 and instructions[0].count(CONTRACT) == 1
        assert "https://github.com/carloshm91/kuberich/blob/main/docs/quality.md" in instructions[0]
        assert "Definition of done" not in instructions[0] and "coverage" not in instructions[0]
    bug = (ROOT / ".github/ISSUE_TEMPLATE/bug.yml").read_text()
    assert "Do not include credentials or kubeconfig contents" in bug
    assert "Report vulnerabilities privately" in bug


def test_current_agent_instructions_keep_identity_and_verification_policy():
    agent = (ROOT / "AGENTS.md").read_text()
    assert not re.search(r"\b20\d\d-\d\d-\d\d\b|\b(?:Astra|GPT|Argon|Sol)\b", agent, re.I)
    assert "carloshm91@gmail.com" in agent
    assert "90%" in agent and "100%" in agent
    assert "docs/releases.md" in agent
    assert "ONE implementation issue globally" in agent
    assert "domain purchases" in agent and "DNS" in agent
    assert "existing authorization" in agent
    assert "docs/internal/first-preview-current.md" in agent
    assert not (ROOT / "docs/internal/contributor-history").exists()


def test_maintained_startup_policy_matches_original_limits_and_hard_boundaries():
    quality = (ROOT / "docs/quality.md").read_text()
    agent = (ROOT / "AGENTS.md").read_text()
    assert CLI_BUDGET_NS == 150_000_000 and IMPORT_BUDGET_US == 150_000
    assert PAINT_BUDGET_NS == 600_000_000 and RSS_BUDGET_BYTES == 40_000_000
    for phrase in ("150 ms", "150,000 µs", "600 ms", "40,000,000 bytes"):
        assert phrase in quality
    assert "All startup latency is advisory for 0.x" in quality
    assert "including prereleases" in quality and "always enforces all timing limits" in quality
    assert "`--strict-startup` enforces every original limit" in quality
    assert "`--strict-paint` stays UI-only" in quality
    assert "negative controls" in quality and "restoration stay hard" in quality
    assert "84.971693%" in quality and "misses that advisory target" in quality
    assert "runtime/collection heartbeat and input latency is advisory" in quality
    assert "KUBERICH_STRICT_RUNTIME_BUDGETS=1" in quality
    assert "200 ms controls stay strict" in quality
    assert "cannot opt out" in quality and "private-access/startup stages" in quality
    assert "check_private_access.py" in quality and "app.run_command(text)" in quality
    assert "--strict-startup" in agent and "RSS/import absence" in agent
    architecture = (ROOT / "docs/architecture.md").read_text()
    assert "Startup and runtime/collection latency targets are advisory" in architecture.replace(
        "\n", " "
    )
    assert "strict opt-ins and actual source major 1" in architecture
    assert "ownership/cleanup remain mandatory" in architecture
