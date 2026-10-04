"""Validate repository planning artifacts; no application coverage is claimed."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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
    if {".git", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist"} & set(
        path.relative_to(ROOT).parts
    ):
        continue
    for target in re.findall(r"\[[^\]\n]*\]\(([^\s)]+)\)", path.read_text()):
        if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        local = target.split("#", 1)[0]
        assert (path.parent / local).exists(), f"Broken link in {path}: {target}"
index = ROOT / "docs/github-issues.json"
if index.exists():
    issues = json.loads(index.read_text())
    assert set(issues["issues"]) == tasks.keys() | epics.keys()
    assert len({item["number"] for item in issues["issues"].values()}) == len(issues["issues"])
print(
    f"Valid plan: {len(epics)} epics, {len(tasks)} tasks, {len(rows)} capability families, {len(flags)} CLI flags"
)
