"""Read accepted preference fields from parser syntax without executing user input."""

import ast
from pathlib import Path
from typing import TypedDict


class Field(TypedDict):
    path: str
    omitted: str


# These are parser entry points, not a duplicate catalogue of accepted fields.
# Each field and its fallback expression is read from its production declaration.
PARSERS = (
    (
        "config/navigation.py",
        "parse_navigation",
        {"value": "navigation", "fields": "navigation.contexts.NAME"},
    ),
    (
        "domain/appearance.py",
        "parse_appearance",
        {"value": "appearance", "fields": "appearance.themes.NAME"},
    ),
    (
        "config/context_settings.py",
        "parse_context_settings",
        {"value": "context_settings", "fields": "context_settings.contexts.NAME"},
    ),
    (
        "config/forwarding.py",
        "parse_forwarding",
        {"value": "forwarding", "spec": "forwarding.presets.NAME"},
    ),
    ("config/plugins.py", "parse_plugins", {"value": "plugins"}),
    ("config/plugins.py", "parse_layer", {"value": "plugins.contexts.NAME"}),
    ("domain/plugins.py", "parse_plugin", {"fields": "plugins.commands.NAME"}),
    ("domain/plugins.py", "parse_input", {"fields": "plugins.commands.NAME.inputs[]"}),
    (
        "domain/resource_preferences.py",
        "parse_view",
        {
            "value": "navigation.views.RESOURCE",
            "item": "navigation.views.RESOURCE.columns[]",
            "order": "navigation.views.RESOURCE.sort",
        },
    ),
    ("domain/jumps.py", "parse_jumps", {"value": "jumps", "fields": "jumps.definitions.NAME"}),
)


def string_set(
    node: ast.AST, names: dict[str, set[str]], *, context: bool = False, strict: bool = False
) -> set[str]:
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        return {
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    if isinstance(node, ast.Name):
        if strict and not names.get(node.id):
            raise ValueError(f"Unresolved schema field set: {node.id}")
        return names.get(node.id, set())
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"set", "frozenset"}
    ):
        return (
            string_set(node.args[0], names, context=context, strict=strict) if node.args else set()
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return string_set(node.left, names, context=context, strict=strict) | string_set(
            node.right, names, context=context, strict=strict
        )
    if isinstance(node, ast.IfExp):
        # These parser branches add legacy or nested-layer compatibility fields.
        # Use the current nonlegacy top-level format, then inventory nested fields separately.
        if isinstance(node.test, ast.Name) and node.test.id in {"legacy", "context"}:
            return string_set(
                node.body if node.test.id == "context" and context else node.orelse,
                names,
                context=context,
                strict=strict,
            )
        return string_set(node.body, names, context=context, strict=strict) | string_set(
            node.orelse, names, context=context, strict=strict
        )
    if strict:
        raise ValueError(f"Unsupported schema field declaration: {ast.dump(node)}")
    return set()


def keys_owner(node: ast.AST) -> str | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        return keys_owner(node.left)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "keys"
        and isinstance(node.func.value, ast.Name)
    ):
        return node.func.value.id
    return None


def fallback(node: ast.AST | None) -> str:
    if node is None:
        return "null (before validation)"
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError):
        expression = ast.unparse(node)
        return {"name": "Entry name", "str(directory)": "Definition directory"}.get(
            expression, expression
        )
    if value is None:
        return "null"
    if value is True or value is False:
        return str(value).lower()
    return repr(value).replace("'", '"')


def fields(root: Path) -> list[Field]:
    result: list[Field] = []
    parsers = (
        *PARSERS,
        ("config/forwarding.py", "parse_forwarding", {"value": "forwarding.contexts.NAME"}),
    )
    for index, (filename, function_name, paths) in enumerate(parsers):
        nested_context = index == len(PARSERS)
        tree = ast.parse((root / "src/kuberich" / filename).read_text())
        names: dict[str, set[str]] = {}
        node: ast.AST
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = string_set(node.value, names, context=nested_context)
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        )
        for node in ast.walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = string_set(node.value, names, context=nested_context)
        accepted: dict[str, set[str]] = {name: set() for name in paths}
        for node in ast.walk(function):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
                accepted_owner = keys_owner(node.left)
                if accepted_owner in accepted:
                    accepted[accepted_owner].update(
                        string_set(node.right, names, context=nested_context, strict=True)
                    )
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "_mapping"
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in accepted:
                        accepted[target.id].update(
                            string_set(
                                node.value.args[1], names, context=nested_context, strict=True
                            )
                        )
        defaults: dict[tuple[str, str], str] = {}
        for node in ast.walk(function):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "get"
                or not isinstance(node.func.value, ast.Name)
            ):
                continue
            owner = node.func.value.id
            if owner not in accepted or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            key = node.args[0].value
            if isinstance(key, str) and key in accepted[owner]:
                defaults.setdefault(
                    (owner, key), fallback(node.args[1] if len(node.args) > 1 else None)
                )
        for owner, keys in accepted.items():
            if not keys:
                raise ValueError(f"No schema fields found for {filename}:{function_name}:{owner}")
            for key in sorted(keys):
                result.append(
                    {
                        "path": paths[owner] + "." + key,
                        "omitted": defaults.get(
                            (owner, key), "No explicit fallback; see task guide"
                        ),
                    }
                )
    return sorted(result, key=lambda item: item["path"])
