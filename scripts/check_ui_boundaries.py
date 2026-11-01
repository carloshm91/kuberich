"""Reject UI dependencies on another KubeRich implementation's private members."""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

from scripts.check_private_access import Check, Function, Index, Module, Names, Violation


class BoundaryCheck(Check):
    def __init__(self, index: Index, module: Module) -> None:
        super().__init__(index, module)
        self.owner: str | None = None

    def flag(self, node: ast.expr | ast.stmt, member: str, owners: Names) -> None:
        # Methods and their closures may use the implementation of their own
        # class. Other KubeRich classes and module-private imports remain opaque.
        external = frozenset(owner for owner in owners if owner != self.owner)
        super().flag(node, member, external)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "super"
            and not node.value.args
            and not node.value.keywords
        ):
            # Zero-argument super() dispatches on this same instance. Pinned
            # framework override removal is tracked by its separate boundary.
            self.generic_visit(node)
            return
        super().visit_Attribute(node)

    def visit_FunctionDef(self, node: Function) -> None:
        previous = self.owner
        definition = self.index.by_node.get(node)
        if definition is not None:
            parent = self.index.definitions.get(definition.parent or "")
            if parent is not None and isinstance(parent.node, ast.ClassDef):
                self.owner = parent.name
        super().visit_FunctionDef(node)
        self.owner = previous

    visit_AsyncFunctionDef = visit_FunctionDef


def violations(root: Path) -> list[Violation]:
    index = Index(root)
    findings: set[Violation] = set()
    for module in index.modules.values():
        if not module.path.is_relative_to(root / "src" / "kuberich" / "ui"):
            continue
        check = BoundaryCheck(index, module)
        check.visit(module.tree)
        findings.update(check.findings)
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    results = violations(arguments.root.resolve())
    for finding in results:
        print(finding)
    if results:
        print(f"UI ownership check failed: {len(results)} violation(s).")
        return 1
    print("UI ownership check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
