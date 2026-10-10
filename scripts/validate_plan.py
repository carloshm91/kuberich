"""Validate repository planning artifacts; no application coverage is claimed."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
policy = {
    node.targets[0].id: ast.literal_eval(node.value)
    for node in ast.parse((ROOT / "scripts/release_policy.py").read_text()).body
    if isinstance(node, ast.Assign)
    and isinstance(node.targets[0], ast.Name)
    and node.targets[0].id
    in {
        "FIRST_PUBLIC_VERSION",
        "QUALIFICATION_GATES",
        "RELEASE_GATES",
        "PHASE_GATES",
        "TASK_ISSUE_IDS",
    }
}
plan = json.loads((ROOT / "docs/backlog.json").read_text())
capabilities = json.loads((ROOT / "docs/capabilities.json").read_text())
inventory = json.loads((ROOT / "docs/k9s-source-inventory.json").read_text())
tasks = {task["id"]: task for task in plan["tasks"]}
epics = {epic["id"]: epic for epic in plan["epics"]}
milestones = {item["title"]: index for index, item in enumerate(plan["milestones"])}
assert len(tasks) == len(plan["tasks"]), "Duplicate task ID"
assert len(epics) == len(plan["epics"]), "Duplicate epic ID"
assert not tasks.keys() & epics.keys(), "Overlapping IDs"
assert len(milestones) == len(plan["milestones"]), "Duplicate milestone"
seen = set()
visiting = set()


def visit(ident):
    assert ident in tasks, f"Unknown dependency {ident}"
    if ident in seen:
        return
    assert ident not in visiting, f"Dependency cycle at {ident}"
    visiting.add(ident)
    task = tasks[ident]
    assert task["epic"] in epics and task["milestone"] in milestones
    assert task["scope"] and task["verification"] and len(task["acceptance"]) >= 3
    for dependency in task["requires"]:
        visit(dependency)
        assert milestones[tasks[dependency]["milestone"]] <= milestones[task["milestone"]], ident
    visiting.remove(ident)
    seen.add(ident)


for ident in tasks:
    visit(ident)
assert set(plan["dependency_order"]) == tasks.keys()
assert len(plan["dependency_order"]) == len(tasks)
positions = {ident: index for index, ident in enumerate(plan["dependency_order"])}
for ident, task in tasks.items():
    assert all(positions[dep] < positions[ident] for dep in task["requires"]), ident
delivery = plan["delivery"]
assert delivery["first_public_version"] == policy["FIRST_PUBLIC_VERSION"]
assert {delivery["publication_gate"]} == policy["RELEASE_GATES"]
assert set(delivery["qualification_gates"]) == policy["QUALIFICATION_GATES"]
assert delivery["feature_first"] is False
assert delivery["stable_public_version"] == "1.0.0"
assert delivery["source_opening_issue"] == 155 and delivery["project_visibility"] == "private"
execution = delivery["execution_order"]
assert len(execution) == len(tasks) and set(execution) == tasks.keys()
execution_positions = {ident: index for index, ident in enumerate(execution)}
for ident, task in tasks.items():
    assert all(execution_positions[dep] < execution_positions[ident] for dep in task["requires"]), (
        ident
    )
assert policy["QUALIFICATION_GATES"] <= set(execution)
assert set(tasks) == set(policy["TASK_ISSUE_IDS"])
assert tasks["D10"]["milestone"] == "v0.1.0" and tasks["D10"]["requires"] == ["D06"]
phases = delivery["release_phases"]
assert [(phase["version"], phase["qualification_gate"]) for phase in phases] == list(
    policy["PHASE_GATES"].items()
)
for phase in phases:
    assert tasks[phase["qualification_gate"]]["milestone"] == "v" + phase["version"]
    extra = phase["extra_issues"]
    assert len(extra) == len(set(extra)) and all(
        type(number) is int and number > 0 for number in extra
    )
assert {53, 54, 123} <= set(phases[0]["extra_issues"])
assert 124 in phases[1]["extra_issues"]
extras = delivery["publication_extra_issues"]
assert len(extras) == len(set(extras)) and all(
    type(number) is int and number > 0 for number in extras
)
assert {149, 150, 154, 155, 157, 162, 166} <= set(extras)
for epic in epics.values():
    children = [task for task in tasks.values() if task["epic"] == epic["id"]]
    assert children, epic["id"]
    assert all(milestones[t["milestone"]] <= milestones[epic["milestone"]] for t in children), epic[
        "id"
    ]
rows = capabilities["rows"]
assert len({row["id"] for row in rows}) == len(rows)
for row in rows + inventory["records"] + inventory["unreleased_delta"]["files"]:
    assert row["tasks"] and set(row["tasks"]) <= tasks.keys(), row
for row in rows:
    assert row["status"] in {"planned", "implemented", "verified", "difference", "evidence-gap"}
    if row["status"] in {"implemented", "verified"}:
        assert row.get("evidence"), f"Missing behavior evidence: {row['id']}"
assert capabilities["baseline"] == inventory["baseline"]
flags = next(r for r in inventory["records"] if r["source"] == "cmd/root.go")["symbols"][
    "launch_flags"
]
cli_doc = (ROOT / "docs/k9s-cli.md").read_text()
assert len(flags) == 26 and len(set(flags)) == len(flags)
assert all(f"`--{flag}`" in cli_doc for flag in flags)
for path in ROOT.rglob("*.md"):
    if {
        ".git",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "build",
        "dist",
        "artifacts",
        "node_modules",
    } & set(path.relative_to(ROOT).parts):
        continue
    for target in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", path.read_text()):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        local = target.split("#", 1)[0]
        assert (path.parent / local).exists(), f"Broken link in {path}: {target}"
index = ROOT / "docs/github-issues.json"
if index.exists():
    issues = json.loads(index.read_text())
    assert plan["repository"] == issues["repository"] == "carloshm91/kuberich"
    assert set(issues["issues"]) == tasks.keys() | epics.keys()
    assert len({item["number"] for item in issues["issues"].values()}) == len(issues["issues"])
    expected = dict(zip(policy["TASK_ISSUE_IDS"], range(13, 92), strict=True))
    expected.update({f"E{number:02}": number for number in range(1, 13)})
    for identifier, item in issues["issues"].items():
        assert type(item["number"]) is int and item["number"] == expected[identifier]
        assert item["url"] == f"https://github.com/carloshm91/kuberich/issues/{item['number']}"
print(
    f"Valid plan: {len(epics)} epics, {len(tasks)} tasks, {len(rows)} capability families, {len(flags)} CLI flags"
)
