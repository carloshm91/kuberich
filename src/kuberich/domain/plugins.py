"""Bounded, immutable local-plugin contracts and literal invocation decisions."""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from kuberich.domain.connections import namespace_name
from kuberich.domain.keyboard import FIXED_KEYS, KeyOverrides, keys_for, navigation_key
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose, capture_command
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.security.controls import escape_controls

MAX_PLUGINS = 64
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z", re.ASCII)
_VARIABLE = re.compile(r"\$(?:\{([A-Z][A-Z0-9_-]*)\}|([A-Z][A-Z0-9_-]*))", re.ASCII)
_ENVIRONMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)
_SCOPES = re.compile(r"(?:[a-z0-9][a-z0-9.-]*/)?[a-z0-9]+/[a-z0-9]+\Z", re.ASCII)
_RESERVED_KEYS = frozenset({"q", "ctrl+q", "ctrl+c", "ctrl+z", "ctrl+p", "ctrl+y"})


def _text(value: object, label: str, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not value and not empty)
        or len(value) > 8192
        or escape_controls(value) != value
    ):
        raise AppError(f"Plugin {label} must be bounded text without terminal controls.")
    return value


def _mapping(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise AppError(f"Plugin {label} must be a mapping with string keys.")
    if value.keys() - fields:
        raise AppError(f"Plugin {label} contains unsupported fields; see the plugin guide.")
    return value


def _flag(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise AppError(f"Plugin {label} must be true or false.")
    return value


def _texts(value: object, label: str, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise AppError(f"Plugin {label} must be a list with at most {maximum} entries.")
    return tuple(_text(item, label) for item in value)


@dataclass(frozen=True, slots=True, repr=False)
class PluginInput:
    name: str
    label: str
    kind: str
    required: bool
    default: str | float | bool | None
    options: tuple[str, ...]

    def accept(self, value: object) -> str:
        if value is None or value == "":
            if self.required:
                raise AppError(f"Plugin input {self.name} is required.")
            return ""
        if self.kind == "bool":
            if type(value) is not bool and value not in ("true", "false"):
                raise AppError(f"Plugin input {self.name} requires true or false.")
            return "true" if value is True or value == "true" else "false"
        if self.kind == "number":
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise AppError(f"Plugin input {self.name} requires a finite number.")
            try:
                number = float(value)
            except (ValueError, OverflowError):
                raise AppError(f"Plugin input {self.name} requires a finite number.") from None
            if not math.isfinite(number):
                raise AppError(f"Plugin input {self.name} requires a finite number.")
            return _text(str(value), "numeric input")
        text = _text(value, "input")
        if self.kind == "dropdown" and text not in self.options:
            raise AppError(f"Plugin input {self.name} must be one of its configured choices.")
        return text


def parse_input(value: object) -> PluginInput:
    fields = _mapping(value, {"name", "label", "type", "required", "default", "options"}, "input")
    name = _text(fields.get("name"), "input name")
    if not _IDENTIFIER.fullmatch(name):
        raise AppError("Plugin input names use lowercase ASCII letters, digits, _ and -.")
    kind = fields.get("type", "string")
    if kind not in ("string", "number", "bool", "dropdown"):
        raise AppError("Plugin input type must be string, number, bool or dropdown.")
    options = _texts(fields.get("options", []), "input options", 64)
    if (kind == "dropdown" and not options) or (kind != "dropdown" and options):
        raise AppError("Only dropdown inputs declare a nonempty options list.")
    if len(set(options)) != len(options):
        raise AppError("Plugin dropdown choices must be unique.")
    default = fields.get("default")
    if default is not None and not isinstance(default, (str, float, int, bool)):
        raise AppError("Plugin input defaults must be scalar values.")
    parsed = PluginInput(
        name,
        _text(fields.get("label", name), "input label"),
        str(kind),
        _flag(fields.get("required", True), "input required"),
        default,
        options,
    )
    if default is not None:
        parsed.accept(default)
    return parsed


@dataclass(frozen=True, slots=True, repr=False)
class Plugin:
    name: str
    description: str
    command: str
    args: tuple[str, ...]
    environment: tuple[tuple[str, str], ...]
    scopes: tuple[str, ...]
    shortcut: str | None
    override: bool
    mode: ProcessMode
    confirm: bool
    dangerous: bool
    trusted_read_only: bool
    directory: Path
    inputs: tuple[PluginInput, ...]
    output_limit: int
    timeout: float

    def applies(self, resource: str | None) -> bool:
        return "*" in self.scopes or resource in self.scopes

    def require_access(self, read_only: bool) -> None:
        if read_only and (not self.trusted_read_only or self.dangerous):
            raise AppError("Read-only mode requires a trusted read-only, non-dangerous plugin.")


def parse_plugin(name: object, value: object, directory: Path) -> Plugin:
    name = _text(name, "name")
    if not _IDENTIFIER.fullmatch(name):
        raise AppError("Plugin names use lowercase ASCII letters, digits, _ and -.")
    fields = _mapping(
        value,
        {
            "description",
            "command",
            "args",
            "environment",
            "scopes",
            "shortcut",
            "override",
            "mode",
            "confirm",
            "dangerous",
            "trusted_read_only",
            "directory",
            "inputs",
            "output_limit",
            "timeout",
        },
        "definition",
    )
    command = _text(fields.get("command"), "command")
    if command.startswith("-") or "$" in command:
        raise AppError("Plugin executables must be literal names or paths, without variables.")
    scopes = _texts(fields.get("scopes", ["*"]), "scopes", 32)
    if not scopes or any(scope != "*" and not _SCOPES.fullmatch(scope) for scope in scopes):
        raise AppError("Plugin scopes use * or exact [group/]version/resource identifiers.")
    raw_environment = fields.get("environment", {})
    if not isinstance(raw_environment, dict) or len(raw_environment) > 64:
        raise AppError("Plugin environment supports at most 64 named variables.")
    environment = []
    for key, item in raw_environment.items():
        if not isinstance(key, str) or not _ENVIRONMENT.fullmatch(key) or len(key) > 128:
            raise AppError("Plugin environment names must be portable identifiers.")
        if key == "KUBECONFIG" or key.startswith("KUBERICH_"):
            raise AppError("KUBECONFIG and KUBERICH_ variables belong to the captured session.")
        environment.append((key, _text(item, "environment value", empty=True)))
    modes = {
        "capture": ProcessMode.CAPTURE,
        "background": ProcessMode.BACKGROUND,
        "foreground": ProcessMode.FOREGROUND,
    }
    mode = fields.get("mode", "capture")
    if not isinstance(mode, str) or mode not in modes:
        raise AppError("Plugin mode must be capture, foreground or background.")
    shortcut = fields.get("shortcut")
    if shortcut is not None:
        shortcut = navigation_key(shortcut)
        if shortcut in _RESERVED_KEYS:
            raise AppError("Plugin shortcut conflicts with a reserved application safety key.")
    raw_inputs = fields.get("inputs", [])
    if not isinstance(raw_inputs, list) or len(raw_inputs) > 16:
        raise AppError("Plugins support at most 16 inputs.")
    inputs = tuple(parse_input(item) for item in raw_inputs)
    if len({item.name.upper().replace("-", "_") for item in inputs}) != len(inputs):
        raise AppError("Plugin input names must be unique.")
    output_limit = fields.get("output_limit", 65536)
    timeout = fields.get("timeout", 300)
    if type(output_limit) is not int or not 1024 <= output_limit <= 1048576:
        raise AppError("Plugin output_limit must be 1024-1048576 bytes.")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not 0 < timeout <= 86400
    ):
        raise AppError("Plugin timeout must be finite, positive and at most one day.")
    try:
        cwd = Path(_text(fields.get("directory", str(directory)), "directory")).expanduser()
    except RuntimeError:
        raise AppError("Cannot resolve the configured plugin working directory.") from None
    if not directory.is_absolute():
        raise AppError("Plugin definitions require an absolute configuration directory.")
    return Plugin(
        name,
        _text(fields.get("description", name), "description"),
        command,
        _texts(fields.get("args", []), "args", 255),
        tuple(environment),
        scopes,
        shortcut,
        _flag(fields.get("override", False), "override"),
        modes[mode],
        _flag(fields.get("confirm", True), "confirm"),
        _flag(fields.get("dangerous", True), "dangerous"),
        _flag(fields.get("trusted_read_only", False), "trusted_read_only"),
        cwd if cwd.is_absolute() else directory / cwd,
        inputs,
        output_limit,
        float(timeout),
    )


def plugin_bindings(
    plugins: tuple[Plugin, ...], resource: str | None, keys: KeyOverrides = ()
) -> tuple[tuple[str, str], ...]:
    bindings: dict[str, str] = {}
    profile = "namespaces" if resource == "v1/namespaces" else "resources"
    occupied = FIXED_KEYS[profile] | set(keys_for(keys, profile).values())
    for plugin in plugins:
        if plugin.shortcut is None or not plugin.applies(resource):
            continue
        if plugin.shortcut in bindings:
            raise AppError("Applicable plugins have conflicting shortcuts; choose unique keys.")
        if plugin.shortcut in occupied and not plugin.override:
            raise AppError("Plugin shortcut requires override: true to replace a resource action.")
        bindings[plugin.shortcut] = plugin.name
    return tuple(sorted(bindings.items()))


@dataclass(frozen=True, slots=True, repr=False)
class PluginSelection:
    """Immutable values from one owned view; no subsequent ambient lookup."""

    context: str
    resource: str | None = None
    target: ResourceTarget | None = None
    variables: tuple[tuple[str, str], ...] = ()
    columns: tuple[tuple[str, str], ...] = ()
    namespace: str | None = None

    def values(self) -> dict[str, str]:
        if self.resource is not None and not _SCOPES.fullmatch(self.resource):
            raise AppError(
                "Captured plugin resource requires an exact group/version/resource scope."
            )
        values = {"CONTEXT": validate_argument(self.context)}
        if self.resource is not None:
            parts = self.resource.split("/")
            values.update(
                RESOURCE=parts[-1],
                VERSION=parts[-2],
                GROUP=parts[0] if len(parts) == 3 else "",
                NAMESPACE=namespace_name(self.namespace) if self.namespace is not None else "",
            )
        for key, value in self.variables:
            if key not in {"CLUSTER", "USER", "FILTER", "KUBECONFIG"}:
                raise AppError("Unknown captured plugin variable.")
            values[key] = _text(value, "captured variable", empty=True)
        if self.target is not None:
            if self.target.session.context != self.context:
                raise AppError("Plugin context does not match its captured resource.")
            parts = (self.resource or "").split("/")
            expected = (
                [self.target.group, "", self.target.resource]
                if self.target.group
                else ["", self.target.resource]
            )
            if (
                len(parts) != len(expected)
                or parts[-1] != self.target.resource
                or (len(parts) == 3 and parts[0] != self.target.group)
            ):
                raise AppError("Plugin resource scope does not match its captured target.")
            values.update(
                NAME=self.target.name,
                NAMESPACE=self.target.namespace or "",
                RESOURCE=self.target.resource,
                GROUP=self.target.group,
                CONTAINER=self.target.container or "",
                VERSION=parts[-2],
            )
        for name, value in self.columns:
            if re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", name) is None:
                raise AppError("Plugin column names must be uppercase identifiers.")
            values["COL-" + name] = _text(value, "column", empty=True)
        return values


def expand_plugin(text: str, values: Mapping[str, str]) -> str:
    """Expand once into one literal argument; substituted text is never reparsed."""
    _text(text, "template", empty=True)
    if "$!" in text:
        raise AppError("Plugin shell-escaped variables are unsupported; use literal argv.")
    marker = "\x00"
    text = text.replace("$$", marker)

    def substitute(match: re.Match[str]) -> str:
        name = match[1] or match[2]
        if name not in values:
            raise AppError("Plugin variable is unavailable in this captured selection.")
        return _text(values[name], "variable", empty=True)

    # Protect inserted dollars so no other interpolation pass can reinterpret them.
    parts: list[str] = []
    end = 0
    for match in _VARIABLE.finditer(text):
        literal = text[end : match.start()]
        if "$" in literal:
            raise AppError("Malformed plugin variable; use $NAME, ${NAME} or $$.")
        parts.extend((literal, substitute(match)))
        end = match.end()
    if "$" in text[end:]:
        raise AppError("Malformed plugin variable; use $NAME, ${NAME} or $$.")
    return _text("".join((*parts, text[end:])).replace(marker, "$"), "expanded value", empty=True)


def plugin_command(
    plugin: Plugin,
    selection: PluginSelection,
    inputs: Mapping[str, object] | None,
    environment: Mapping[str, str],
) -> ProcessCommand | None:
    """None is deliberate input cancellation and cannot yield an executable request."""
    if inputs is None:
        return None
    if not plugin.applies(selection.resource):
        raise AppError("Plugin does not apply to this resource view.")
    if inputs.keys() - {item.name for item in plugin.inputs}:
        raise AppError("Unknown plugin input; invocation refused.")
    values = selection.values()
    for item in plugin.inputs:
        values["INPUT_" + item.name.upper().replace("-", "_")] = item.accept(
            inputs.get(item.name, item.default)
        )
    variables = dict(environment)
    variables.update((key, expand_plugin(value, values)) for key, value in plugin.environment)
    return capture_command(
        (plugin.command, *(expand_plugin(argument, values) for argument in plugin.args)),
        environment=variables,
        directory=plugin.directory,
        mode=plugin.mode,
        purpose=ProcessPurpose.PLUGIN,
        target=selection.target,
        trusted_read_only=plugin.trusted_read_only and not plugin.dangerous,
    )
