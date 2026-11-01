"""Read offline application declarations for the generated site reference.

The subprocess imports the selected checkout, constructs its argument parser and
reads its immutable registry. It never parses user options or launches the app.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import TypedDict, cast

from scripts.site_schema import fields as schema_fields


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


class Command(TypedDict):
    action: str
    aliases: list[str]


class Keymap(TypedDict):
    profiles: list[str]
    keys: dict[str, str]


class Setting(TypedDict):
    name: str
    default: object
    environment: list[str]


class Contracts(TypedDict):
    options: list[Option]
    resources: list[Resource]
    commands: list[Command]
    interactions: list[str]
    keymaps: list[Keymap]
    bindings: dict[str, list[dict[str, str]]]
    settings: list[Setting]
    schema_version: int
    extensions: list[str]


# Use JSON declarations rather than argparse's platform-dependent help layout.
# -I ignores PYTHONPATH/user site; the explicit source path selects this build.
SNAPSHOT = """
import argparse
import json
import sys
sys.path.insert(0, sys.argv[1])
from kuberich.cli import _parser
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.services.commands import ALIASES
from kuberich.domain.interactions import INTERACTION_VERBS
from kuberich.domain.keyboard import PROFILES, keys_for
from kuberich.config.schema import Settings, ENV_FIELDS, SCHEMA_VERSION, EXTENSIONS
from dataclasses import fields
from kuberich.ui.app import KubeRichApp
from kuberich.ui.logs import LogScreen
from kuberich.ui.containers import ContainerScreen
from kuberich.ui.inspection import InspectionScreen
from kuberich.ui.terminal import ShellScreen
parser = _parser()
options = []
def collect_options(current, prefix=""):
    for group in current._action_groups:
        for action in group._group_actions:
            if action.option_strings and action.help != argparse.SUPPRESS:
                options.append({"flags": action.option_strings, "help": action.help or "", "group": prefix})
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    collect_options(child, (prefix + " " + name).strip())
collect_options(parser)
resources = [{"name": item.name, "group": item.group, "namespaced": item.namespaced,
              "aliases": list(item.aliases), "columns": [column.key for column in item.columns]}
             for item in STANDARD_RESOURCES]
commands = {}
for alias, command in ALIASES.items():
    commands.setdefault(command.name.lower(), []).append(alias)
keymaps = {}
for profile in PROFILES:
    keys = keys_for((), profile)
    keymaps.setdefault(tuple(keys.items()), []).append(profile)
bindings = {}
for label, owner in (("Workspace", KubeRichApp), ("Logs", LogScreen), ("Containers", ContainerScreen),
                     ("Inspection", InspectionScreen), ("Embedded terminal", ShellScreen)):
    grouped = {}
    for item in owner.BINDINGS:
        if isinstance(item, tuple):
            key, action, description = item[:3]
        else:
            key, action, description = item.key, item.action, item.description
        if description:
            grouped.setdefault((action, description), []).append(key)
    bindings[label] = [{"keys": ", ".join(keys), "action": action, "description": description}
                       for (action, description), keys in grouped.items()]
settings = Settings()
print(json.dumps({"options": options, "resources": resources,
    "commands": [{"action": action, "aliases": sorted(aliases)} for action, aliases in sorted(commands.items())],
    "interactions": sorted(INTERACTION_VERBS),
    "keymaps": [{"profiles": profiles, "keys": dict(keys)} for keys, profiles in keymaps.items()],
    "bindings": bindings,
    "settings": [{"name": field.name, "default": getattr(settings, field.name),
                  "environment": sorted(key for key, name in ENV_FIELDS.items() if name == field.name)} for field in fields(Settings)],
    "schema_version": SCHEMA_VERSION, "extensions": sorted(EXTENSIONS)}, sort_keys=True))
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


def cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def generated_guides(root: Path, version: str) -> dict[str, str]:
    data = contracts(root)
    configuration_fields = schema_fields(root)
    covered_extensions = {item["path"].split(".", 1)[0] for item in configuration_fields}
    if covered_extensions != set(data["extensions"]):
        raise ValueError("Preference extension schema parsers do not match registered extensions")
    cli = [
        "# Commands, keys, and launch options",
        "",
        f"Generated from application declarations for source version `{version}`.",
        "",
        "Keys apply to the focused view. Inputs keep their normal editing keys;",
        "configured additional keys and plugins can change effective shortcuts.",
        "Press `?` in a view for its current actions. See [navigation](command-navigation.md).",
        "",
        "## Launch options",
        "",
        "| Option / aliases | Description |",
        "| --- | --- |",
    ]
    for option in data["options"]:
        scope = f"`{option['group']}`: " if option["group"] else ""
        cli.append(
            "| "
            + scope
            + ", ".join(f"`{flag}`" for flag in option["flags"])
            + " | "
            + cell(option["help"])
            + " |"
        )
    cli += [
        "",
        "## In-app commands",
        "",
        "Type `:` before an alias. Arguments and resource requirements depend on the task;",
        "registration alone does not make a command available in every view or at launch.",
        "Resource aliases are in the [resource reference](resource-reference.md).",
        "",
        "| Aliases | Action |",
        "| --- | --- |",
    ]
    for command in data["commands"]:
        cli.append(
            "| "
            + ", ".join(f"`{alias}`" for alias in command["aliases"])
            + " | "
            + command["action"].replace("_", " ")
            + " |"
        )
    cli += [
        "| `resource NAME[.GROUP][/VERSION] [NAMESPACE or *]` | Browse a discovered resource |",
        "| `plugin NAME` | Review a configured local plugin |",
        "",
        "### Local view controls",
        "",
        ", ".join(f"`:{verb}`" for verb in data["interactions"]) + ".",
        "",
        "`favorite` takes `add NAMESPACE` or `remove NAMESPACE`; other local view controls",
        "take no arguments. `!!` repeats through the normal checks, without confirming a write.",
        "",
        "## Additional navigation defaults",
        "",
        "Each row is generated from an effective default key profile. Fixed arrows and",
        "page keys stay available. Table Home/End move horizontally; Ctrl+Home/End select",
        "first/last rows. Uppercase letters are distinct keys, not Vim sequences.",
        "",
    ]
    profiles = data["keymaps"]
    for number, keymap in enumerate(profiles, 1):
        cli.append(
            f"Profile {number}: " + ", ".join(f"`{name}`" for name in keymap["profiles"]) + "."
        )
    cli += [
        "",
        "| Action | "
        + " | ".join(f"Profile {number}" for number in range(1, len(profiles) + 1))
        + " |",
        "| --- | " + " | ".join("---" for _ in profiles) + " |",
    ]
    for action in sorted({action for keymap in profiles for action in keymap["keys"]}):
        cli.append(
            "| "
            + action.replace("_", " ")
            + " | "
            + " | ".join(
                f"`{keymap['keys'][action]}`" if action in keymap["keys"] else "—"
                for keymap in profiles
            )
            + " |"
        )
    cli += ["", "## View action keys", "", "| View | Key | Action |", "| --- | --- | --- |"]
    for label, bindings in data["bindings"].items():
        cli += [
            f"| {label} | `{cell(item['keys'])}` | {cell(item['description'])} |"
            for item in bindings
        ]
    cli.append("")
    resources = [
        "# Resource reference",
        "",
        f"Generated from the standard-resource registry for source version `{version}`.",
        "",
        "Discovery chooses a served API version. Availability still depends on your cluster",
        "and permissions. Pods and namespaces also have dedicated workspace views.",
        "",
        "## Standard views",
        "",
        "| Resource / aliases | API group | Scope | Columns |",
        "| --- | --- | --- | --- |",
    ]
    for item in data["resources"]:
        names = ", ".join(f"`{name}`" for name in [item["name"], *item["aliases"]])
        scope = "Namespace" if item["namespaced"] else "Cluster"
        resources.append(
            f"| {names} | {item['group'] or 'core'} | {scope} | {', '.join(item['columns'])} |"
        )
    resources += [
        "",
        "See [the workspace explanation](resource-workspace.md) for standard and discovered views.",
    ]
    capabilities = [
        "# Feature availability",
        "",
        f"Generated from the maintained feature inventory for source version `{version}`.",
        "",
        "Available describes implemented behavior within its stated limits. Partial means",
        "only the described portion is usable. Planned features are unavailable.",
        "Real cloud accounts, terminals, and provider policies can need additional setup.",
        "",
        "## Current inventory",
        "",
    ]
    inventory = json.loads((root / "docs/capabilities.json").read_text())
    for row in inventory["rows"]:
        capabilities += [
            f"### {row.get('public_title', row['capability'])}",
            textwrap.fill(f"**{row['public_status']}** — {row['public_summary']}", width=100),
        ]
    config = [
        "# Configuration reference",
        "",
        f"Generated from preference defaults and parser declarations for source version `{version}`.",
        "",
        "Use [configuration](configuration.md) for examples, precedence, reload, and saving.",
        "`NAME` and `RESOURCE` denote your mapping keys; `[]` denotes a list item.",
        "",
        "## Root fields",
        "",
        f"The current root `schema_version` is `{data['schema_version']}`.",
        "",
        "| Field | Default | Environment |",
        "| --- | --- | --- |",
    ]
    for setting in data["settings"]:
        default = json.dumps(setting["default"])
        config.append(
            f"| `{setting['name']}` | `{default}` | "
            + ", ".join(f"`{name}`" for name in setting["environment"])
            + " |"
        )
    config += [
        "",
        "## Extension fields",
        "",
        "These names come from the current validators, including optional fields absent",
        "from empty defaults. A missing value without a fallback may be required or",
        "nullable; the parser still validates it. A null fallback is not permission to supply null.",
        "",
        "| Path | When omitted |",
        "| --- | --- |",
    ]
    config += [f"| `{item['path']}` | {cell(item['omitted'])} |" for item in configuration_fields]
    config += [
        "",
        "The root accepts these versioned extensions: "
        + ", ".join(f"`{name}`" for name in data["extensions"])
        + ".",
        "Key profiles/actions come from the [key reference](cli-reference.md#additional-navigation-defaults).",
        "Theme colors and plugin definitions are validated as described in their task guides.",
    ]
    return {
        "cli-reference.md": "\n".join(cli).rstrip() + "\n",
        "resource-reference.md": "\n".join(resources) + "\n",
        "capability-reference.md": "\n".join(capabilities) + "\n",
        "config-reference.md": "\n".join(config) + "\n",
    }


def reference_files(root: Path) -> dict[str, str]:
    """Version-neutral checked reference stays stable across release-number changes."""
    return generated_guides(root, "SOURCE_VERSION")


def check_reference_files(root: Path) -> None:
    for name, content in reference_files(root).items():
        path = root / "docs/generated" / name
        if not path.is_file() or path.is_symlink() or path.read_text() != content:
            raise ValueError(
                f"Generated reference is stale: {name}; run python -m scripts.site_reference --write"
            )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Update or check source-generated documentation.")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.write:
        folder = root / "docs/generated"
        folder.mkdir(exist_ok=True)
        for name, content in reference_files(root).items():
            (folder / name).write_text(content)
    else:
        check_reference_files(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
