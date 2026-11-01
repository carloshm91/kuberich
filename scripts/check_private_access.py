"""Reject test dependencies on private KubeRich attributes without importing the app."""

from __future__ import annotations

import argparse
import ast
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

Names = frozenset[str]
Environment = dict[str, Names]
Function = ast.FunctionDef | ast.AsyncFunctionDef
EMPTY: Names = frozenset()
REFLECTION = frozenset({"getattr", "setattr", "delattr", "hasattr"})


def private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def owned(name: str) -> bool:
    return name == "kuberich" or name.startswith("kuberich.")


@dataclass(frozen=True, order=True)
class Violation:
    path: Path
    line: int
    column: int
    member: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}:{self.column}: private KubeRich access: {self.member}"


@dataclass
class Module:
    name: str
    path: Path
    tree: ast.Module
    offset: int = 0
    bindings: Environment = field(default_factory=dict)


@dataclass
class Definition:
    name: str
    module: Module
    node: Function | ast.ClassDef
    parent: str | None = None
    returns: Names = EMPTY
    parameters: Environment = field(default_factory=dict)
    attributes: Environment = field(default_factory=dict)


def union(values: Iterable[Names]) -> Names:
    return frozenset().union(*values)


def local_nodes(node: ast.AST) -> Iterable[ast.AST]:
    """Walk a scope without folding nested functions into its return/assignment state."""
    yield node
    for child in ast.iter_child_nodes(node):
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            yield from local_nodes(child)


class Index:
    """Small provenance index for imports, factories, annotations and constructor fields."""

    def __init__(self, root: Path) -> None:
        self.modules: dict[str, Module] = {}
        self.definitions: dict[str, Definition] = {}
        self.by_node: dict[ast.AST, Definition] = {}
        for directory in (root / "src" / "kuberich", root / "tests"):
            if not directory.is_dir():
                raise FileNotFoundError(f"Private-access check requires directory: {directory}")
            for path in sorted(directory.rglob("*.py")):
                base = root / "src" if path.is_relative_to(root / "src") else root
                parts = list(path.relative_to(base).with_suffix("").parts)
                if parts[-1] == "__init__":
                    parts.pop()
                name = ".".join(parts)
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                module = Module(name, path, tree)
                self.modules[name] = module
                self._definitions(module, tree.body)
                if path.is_relative_to(root / "tests"):
                    self._embedded(module)
        # A fixed point handles factories imported from a test helper and public
        # fields whose constructor types are declared in another module.
        for _ in range(12):
            before = self._signature()
            for module in self.modules.values():
                module.bindings = self.environment(module, module.tree)
            for definition in self.definitions.values():
                self._infer_definition(definition)
            if self._signature() == before:
                break

    def _embedded(self, module: Module) -> None:
        # Terminal fixture programs are executable source stored as module
        # constants. Local strings in checker tests remain ordinary data.
        for node in module.tree.body:
            if (
                not isinstance(node, (ast.Assign, ast.AnnAssign))
                or not isinstance(node.value, ast.Constant)
                or not isinstance(node.value.value, str)
            ):
                continue
            try:
                tree = ast.parse(node.value.value)
            except (SyntaxError, UnicodeError, ValueError, RecursionError):
                continue
            if not any(
                (isinstance(child, ast.ImportFrom) and owned(child.module or ""))
                or (
                    isinstance(child, ast.Import)
                    and any(owned(alias.name) for alias in child.names)
                )
                for child in ast.walk(tree)
            ):
                continue
            name = f"{module.name}.__fixture_{node.lineno}"
            embedded = Module(name, module.path, tree, offset=node.value.lineno - 1)
            self.modules[name] = embedded
            self._definitions(embedded, tree.body)

    def _signature(self) -> tuple[object, ...]:
        return tuple(
            (name, definition.returns, dict(definition.attributes), dict(definition.parameters))
            for name, definition in self.definitions.items()
        )

    def _definitions(self, module: Module, body: list[ast.stmt], parent: str | None = None) -> None:
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{parent or module.name}.{node.name}"
                definition = Definition(name, module, node, parent)
                self.definitions[name] = definition
                self.by_node[node] = definition
                self._definitions(module, node.body, name)

    def imports(self, module: Module, node: ast.Import | ast.ImportFrom) -> Environment:
        if isinstance(node, ast.Import):
            return {
                alias.asname or alias.name.split(".")[0]: frozenset(
                    {alias.name if alias.asname else alias.name.split(".")[0]}
                )
                for alias in node.names
            }
        prefix = node.module or ""
        if node.level:
            package = (
                module.name if module.path.name == "__init__.py" else module.name.rpartition(".")[0]
            )
            parts = package.split(".")
            prefix = ".".join(parts[: len(parts) - node.level + 1] + ([prefix] if prefix else []))
        return {
            alias.asname or alias.name: frozenset({f"{prefix}.{alias.name}"})
            for alias in node.names
            if alias.name != "*"
        }

    def attribute(self, base: str, name: str) -> Names:
        module = self.modules.get(base)
        if module is not None:
            return module.bindings.get(name, frozenset({f"{base}.{name}"}))
        definition = self.definitions.get(base)
        if definition is not None and isinstance(definition.node, ast.ClassDef):
            if name in definition.attributes:
                return definition.attributes[name]
            method = self.definitions.get(f"{base}.{name}")
            if method is not None:
                if any(
                    isinstance(decorator, ast.Name) and decorator.id == "property"
                    for decorator in method.node.decorator_list
                ):
                    return method.returns
                return frozenset({method.name})
            for parent in definition.node.bases:
                for target in self.resolve(parent, definition.module.bindings):
                    inherited = self.definitions.get(target)
                    if inherited is not None and name in inherited.attributes:
                        return inherited.attributes[name]
        return frozenset({f"{base}.{name}"})

    def owns_member(self, base: str, name: str, seen: frozenset[str] = EMPTY) -> bool:
        if owned(base):
            return True
        definition = self.definitions.get(base)
        if base in seen or definition is None or not isinstance(definition.node, ast.ClassDef):
            return False
        parents = union(
            self.resolve(parent, definition.module.bindings) for parent in definition.node.bases
        )
        local = name in definition.attributes or f"{base}.{name}" in self.definitions
        for parent in parents:
            declaration = self.definitions.get(parent)
            if (
                local
                and declaration is not None
                and name not in declaration.attributes
                and f"{parent}.{name}" not in self.definitions
            ):
                continue
            if self.owns_member(parent, name, seen | {base}):
                return True
        return False

    def resolve(self, node: ast.AST | None, env: Environment) -> Names:
        if node is None:
            return EMPTY
        if isinstance(node, ast.Name):
            return env.get(node.id, frozenset({f"builtins.{node.id}"}))
        if isinstance(node, ast.Attribute):
            return union(self.attribute(base, node.attr) for base in self.resolve(node.value, env))
        if isinstance(node, ast.Await):
            return self.resolve(node.value, env)
        if isinstance(node, ast.Subscript):
            return self.resolve(node.value, env) | self.resolve(node.slice, env)
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return union(self.resolve(element, env) for element in node.elts)
        if isinstance(node, ast.Dict):
            return union(self.resolve(value, env) for value in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self.resolve(node.left, env) | self.resolve(node.right, env)
        if isinstance(node, ast.IfExp):
            return self.resolve(node.body, env) | self.resolve(node.orelse, env)
        if isinstance(node, ast.Lambda):
            return self.resolve(node.body, env)
        if isinstance(node, ast.Call):
            targets = self.resolve(node.func, env)
            if "typing.cast" in targets and node.args:
                return self.annotation(node.args[0], env)
            if "importlib.import_module" in targets and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    return frozenset({first.value})
            if "builtins.getattr" in targets and len(node.args) >= 2:
                member = node.args[1]
                if isinstance(member, ast.Constant) and isinstance(member.value, str):
                    return union(
                        self.attribute(base, member.value)
                        for base in self.resolve(node.args[0], env)
                    )
            results: set[str] = set()
            for target in targets:
                definition = self.definitions.get(target)
                if definition is not None and isinstance(
                    definition.node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    results.update(definition.returns)
                    for argument, parameter in zip(
                        node.args, definition.node.args.args, strict=False
                    ):
                        values = self.resolve(argument, env)
                        definition.parameters[parameter.arg] = (
                            definition.parameters.get(parameter.arg, EMPTY) | values
                        )
                    for keyword in node.keywords:
                        if keyword.arg is not None:
                            definition.parameters[keyword.arg] = definition.parameters.get(
                                keyword.arg, EMPTY
                            ) | self.resolve(keyword.value, env)
                else:
                    results.add(target)
            return frozenset(results)
        return EMPTY

    def annotation(self, node: ast.AST | None, env: Environment) -> Names:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except (SyntaxError, UnicodeError, ValueError, RecursionError):
                return EMPTY
        return self.resolve(node, env)

    def arguments(self, definition: Definition, env: Environment) -> Environment:
        node = definition.node
        if isinstance(node, ast.ClassDef):
            return env
        for parameter in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if parameter.annotation is not None:
                env[parameter.arg] = self.annotation(parameter.annotation, env)
                continue
            parents = definition.module.name.split(".")[:-1]
            candidates = [*env.get(parameter.arg, EMPTY)]
            for length in range(len(parents), 0, -1):
                module = self.modules.get(".".join([*parents[:length], "conftest"]))
                if module is not None:
                    candidates.extend(module.bindings.get(parameter.arg, EMPTY))
            for candidate in candidates:
                fixture = self.definitions.get(candidate)
                if (
                    fixture is not None
                    and isinstance(fixture.node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and any(
                        "pytest.fixture" in self.resolve(decorator, fixture.module.bindings)
                        for decorator in fixture.node.decorator_list
                    )
                ):
                    env[parameter.arg] = fixture.returns
                    break
        for decorator in node.decorator_list:
            if (
                not isinstance(decorator, ast.Call)
                or len(decorator.args) < 2
                or "pytest.mark.parametrize" not in self.resolve(decorator.func, env)
            ):
                continue
            names, values = decorator.args[:2]
            if (
                not isinstance(names, ast.Constant)
                or not isinstance(names.value, str)
                or not isinstance(values, (ast.Tuple, ast.List))
            ):
                continue
            parameters = [name.strip() for name in names.value.split(",")]
            for value in values.elts:
                if isinstance(value, ast.Call) and "pytest.param" in self.resolve(value.func, env):
                    entries = value.args
                else:
                    entries = (
                        [value]
                        if len(parameters) == 1
                        else value.elts
                        if isinstance(value, (ast.Tuple, ast.List))
                        else []
                    )
                for name, entry in zip(parameters, entries, strict=False):
                    env[name] = env.get(name, EMPTY) | self.resolve(entry, env)
        return env

    def environment(
        self, module: Module, scope: ast.AST, inherited: Environment | None = None
    ) -> Environment:
        env = dict(module.bindings if inherited is None else inherited)
        nodes = list(local_nodes(scope))
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                env.update(self.imports(module, node))
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definition = self.by_node.get(child)
                if definition is not None:
                    env[child.name] = frozenset({definition.name})
        for _ in range(3):
            for node in nodes:
                if isinstance(node, ast.Assign):
                    value = self.resolve(node.value, env)
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            env[target.id] = value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    env[node.target.id] = self.resolve(node.value, env) or self.annotation(
                        node.annotation, env
                    )
                elif isinstance(node, (ast.With, ast.AsyncWith)):
                    for item in node.items:
                        if isinstance(item.optional_vars, ast.Name):
                            env[item.optional_vars.id] = self.resolve(item.context_expr, env)
                elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(
                    node.target, ast.Name
                ):
                    env[node.target.id] = self.resolve(node.iter, env)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "isinstance"
                    and len(node.args) >= 2
                    and isinstance(node.args[0], ast.Name)
                ):
                    env[node.args[0].id] = self.resolve(node.args[1], env)
                elif isinstance(node, ast.Call):
                    self.resolve(node, env)
        return env

    def _infer_definition(self, definition: Definition) -> None:
        node = definition.node
        if isinstance(node, ast.ClassDef):
            return
        env = dict(definition.module.bindings)
        env.update(definition.parameters)
        env = self.arguments(definition, env)
        parent = self.definitions.get(definition.parent or "")
        if parent is not None and isinstance(parent.node, ast.ClassDef):
            env["self"] = frozenset({parent.name})
            env["cls"] = frozenset({parent.name})
        env = self.environment(definition.module, node, env)
        definition.returns = self.annotation(node.returns, env) or union(
            self.resolve(child.value, env)
            for child in local_nodes(node)
            if isinstance(child, (ast.Return, ast.Yield))
        )
        if parent is not None and isinstance(parent.node, ast.ClassDef):
            for child in local_nodes(node):
                if isinstance(child, (ast.Assign, ast.AnnAssign)):
                    targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                    value = self.resolve(child.value, env)
                    if not value and isinstance(child, ast.AnnAssign):
                        value = self.annotation(child.annotation, env)
                    for target in targets:
                        if (
                            isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id in {"self", "cls"}
                        ):
                            parent.attributes[target.attr] = (
                                parent.attributes.get(target.attr, EMPTY) | value
                            )


class Check(ast.NodeVisitor):
    def __init__(self, index: Index, module: Module) -> None:
        self.index = index
        self.module = module
        self.env = {
            child.name: frozenset({definition.name})
            for child in module.tree.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and (definition := index.by_node.get(child)) is not None
        }
        self.offset = module.offset
        self.findings: set[Violation] = set()
        self.strings: dict[str, frozenset[str]] = {}

    def literals(self, node: ast.AST) -> frozenset[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return frozenset({node.value})
        if isinstance(node, ast.Name):
            return self.strings.get(node.id, EMPTY)
        if isinstance(node, ast.IfExp):
            return self.literals(node.body) | self.literals(node.orelse)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return frozenset(
                left + right
                for left in self.literals(node.left)
                for right in self.literals(node.right)
            )
        return EMPTY

    def flag(self, node: ast.expr | ast.stmt, member: str, owners: Names) -> None:
        if private(member) and any(self.index.owns_member(owner, member) for owner in owners):
            self.findings.add(
                Violation(self.module.path, node.lineno + self.offset, node.col_offset + 1, member)
            )

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.flag(node, node.attr, self.index.resolve(node.value, self.env))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        bindings = self.index.imports(self.module, node)
        for alias in node.names:
            targets = bindings.get(alias.asname or alias.name, EMPTY)
            for part in [*(node.module or "").split("."), alias.name]:
                self.flag(node, part, targets)
        self.env.update(bindings)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            for part in alias.name.split("."):
                self.flag(node, part, frozenset({alias.name}))
        self.env.update(self.index.imports(self.module, node))

    def bind(self, target: ast.AST, value: ast.AST | None) -> None:
        if isinstance(target, ast.Name):
            self.env[target.id] = self.index.resolve(value, self.env)
            self.strings[target.id] = self.literals(value) if value is not None else EMPTY
        elif isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)) and len(target.elts) == len(value.elts):
                for element, item in zip(target.elts, value.elts, strict=True):
                    self.bind(element, item)
            else:
                for element in target.elts:
                    self.bind(element, value)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.generic_visit(node)
        for target in node.targets:
            self.bind(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.generic_visit(node)
        self.bind(node.target, node.value or node.annotation)
        if isinstance(node.target, ast.Name) and node.value is None:
            self.env[node.target.id] = self.index.annotation(node.annotation, self.env)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.bind(item.optional_vars, item.context_expr)
        for statement in node.body:
            self.visit(statement)

    visit_AsyncWith = visit_With

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        self.bind(node.target, node.iter)
        for statement in [*node.body, *node.orelse]:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def narrow(self, expression: ast.AST) -> None:
        if (
            isinstance(expression, ast.Call)
            and isinstance(expression.func, ast.Name)
            and expression.func.id == "isinstance"
            and len(expression.args) >= 2
            and isinstance(expression.args[0], ast.Name)
        ):
            self.env[expression.args[0].id] = self.index.resolve(expression.args[1], self.env)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.generic_visit(node)
        self.narrow(node.test)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        before = dict(self.env)
        previous_strings = dict(self.strings)
        self.narrow(node.test)
        for statement in node.body:
            self.visit(statement)
        first = dict(self.env)
        first_strings = dict(self.strings)
        self.env = before
        self.strings = previous_strings
        for statement in node.orelse:
            self.visit(statement)
        second = self.env
        self.env = {
            key: first.get(key, EMPTY) | second.get(key, EMPTY)
            for key in first.keys() | second.keys()
        }
        self.strings = {
            key: first_strings.get(key, EMPTY) | self.strings.get(key, EMPTY)
            for key in first_strings.keys() | self.strings.keys()
        }

    def visit_Call(self, node: ast.Call) -> None:
        targets = self.index.resolve(node.func, self.env)
        if len(node.args) >= 2 and any(
            target.rsplit(".", 1)[-1] in REFLECTION or target.endswith(".patch.object")
            for target in targets
        ):
            for member in self.literals(node.args[1]):
                self.flag(node, member, self.index.resolve(node.args[0], self.env))
        for argument in node.args[:1]:
            for literal in self.literals(argument):
                if literal.startswith("kuberich.") and any(
                    target.endswith((".setattr", ".delattr", ".patch")) for target in targets
                ):
                    self.flag(node, literal.rsplit(".", 1)[-1], frozenset({literal}))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: Function) -> None:
        previous = self.env
        previous_strings = self.strings
        self.strings = dict(previous_strings)
        env = dict(previous)
        definition = self.index.by_node.get(node)
        if definition is not None:
            env.update(definition.parameters)
            env = self.index.arguments(definition, env)
            if definition.parent in self.index.definitions:
                parent = self.index.definitions[definition.parent]
                if isinstance(parent.node, ast.ClassDef):
                    env["self"] = frozenset({parent.name})
                    env["super"] = union(
                        self.index.resolve(base, self.module.bindings) for base in parent.node.bases
                    )
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nested = self.index.by_node.get(child)
                if nested is not None:
                    env[child.name] = frozenset({nested.name})
        self.env = env
        self.generic_visit(node)
        self.env = previous
        self.strings = previous_strings

    visit_AsyncFunctionDef = visit_FunctionDef


def violations(root: Path) -> list[Violation]:
    index = Index(root)
    findings: set[Violation] = set()
    for module in index.modules.values():
        if not module.path.is_relative_to(root / "tests"):
            continue
        check = Check(index, module)
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
        print(f"Private-access check failed: {len(results)} violation(s).")
        return 1
    print("Private-access check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
