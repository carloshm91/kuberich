"""Read offline application declarations for the generated site reference.

The subprocess imports the selected checkout, constructs its argument parser and
reads its immutable registry. It never parses user options or launches the app.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import TypedDict, cast


class Option(TypedDict):
    flags: list[str]
    help: str
    group: str


class Resource(TypedDict):
    name: str
    group: str
    namespaced: bool
    aliases: list[str]
    columns: list[str]


class Contracts(TypedDict):
    options: list[Option]
    resources: list[Resource]


# Use JSON declarations rather than argparse's platform-dependent help layout.
# -I ignores PYTHONPATH/user site; the explicit source path selects this build.
SNAPSHOT = """
import argparse
import json
import sys
sys.path.insert(0, sys.argv[1])
from kuberich.cli import _parser
from kuberich.domain.registry import STANDARD_RESOURCES
parser = _parser()
options = []
for group in parser._action_groups:
    for action in group._group_actions:
        if action.option_strings and action.help != argparse.SUPPRESS:
            options.append({"flags": action.option_strings, "help": action.help or "",
                            "group": group.title if group.title not in ("options", "optional arguments") else "Launch options"})
resources = [{"name": item.name, "group": item.group, "namespaced": item.namespaced,
              "aliases": list(item.aliases), "columns": [column.key for column in item.columns]}
             for item in STANDARD_RESOURCES]
print(json.dumps({"options": options, "resources": resources}, sort_keys=True))
"""


def contracts(root: Path) -> Contracts:
    result = subprocess.run(
        [sys.executable, "-I", "-c", SNAPSHOT, str((root / "src").resolve())],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return cast(Contracts, json.loads(result.stdout))


def generated_guides(root: Path, version: str) -> dict[str, str]:
    data = contracts(root)
    cli = [
        "# Command-line reference",
        f"Generated from the argument parser for source version `{version}`. "
        "These are registered launch flags, including explicitly unavailable options. "
        "See [installation](quickstart.md), [connection setup](context-sessions.md) and "
        "[in-app commands](command-navigation.md) for usage and limits.",
        "Local `kuberich help`, `kuberich version`, `kuberich info`, and "
        "`kuberich config init|check|migrate` are described in the "
        "[preferences guide](configuration.md). They do not need a cluster.",
    ]
    group = ""
    for option in data["options"]:
        if option["group"] != group:
            group = option["group"]
            cli += [f"## {group}", "| Option / aliases | Description |", "| --- | --- |"]
        flags = ", ".join(f"`{flag}`" for flag in option["flags"])
        description = option["help"].replace("|", "\\|").replace("\n", " ")
        cli.append(f"| {flags} | {description} |")
    resources = [
        "# Resource reference",
        f"Generated from the standard-resource registry for source version `{version}`. "
        "Pods and namespaces have dedicated views; the table below describes the "
        "additional standard views. Discovery selects each server's served API version. "
        "Registration does not imply permission or API availability in your cluster.",
        "See [resource views](standard-resources.md) for behavior and "
        "[navigation](command-navigation.md) for commands and filtering.",
        "## Standard views",
        "| Resource / aliases | API group | Scope | Columns |",
        "| --- | --- | --- | --- |",
    ]
    for item in data["resources"]:
        names = ", ".join(f"`{name}`" for name in [item["name"], *item["aliases"]])
        scope = "Namespace" if item["namespaced"] else "Cluster"
        columns = ", ".join(item["columns"])
        resources.append(f"| {names} | {item['group'] or 'core'} | {scope} | {columns} |")
    capabilities = [
        "# Capability progress",
        f"Generated from the maintained capability inventory for source version `{version}`. "
        "This is an audit of intended scope, **not a promise of complete parity**. "
        "A planned row can contain delivered portions; its current difference explains "
        "the qualified scope. Feature guides describe the usable behavior.",
        "The inventory compares a pinned upstream baseline; task IDs link to the "
        "[planning map](backlog.md). Real-provider certification and final release "
        "qualification remain separate from implemented local contracts.",
        "## Current inventory",
    ]
    inventory = json.loads((root / "docs/capabilities.json").read_text())
    for row in inventory["rows"]:
        capabilities += [
            f"### {row['id']} · {row['capability']}",
            f"**Status: {row['status']}** · Tasks: {', '.join(row['tasks'])}",
            row["difference"],
        ]
    return {
        "cli-reference.md": "\n\n".join(cli[:3]) + "\n\n" + "\n".join(cli[3:]) + "\n",
        "resource-reference.md": "\n\n".join(resources[:3])
        + "\n\n"
        + "\n".join(resources[3:])
        + "\n",
        "capability-reference.md": "\n\n".join(capabilities) + "\n",
    }
