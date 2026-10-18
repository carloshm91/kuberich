"""Explicit plugin configuration layers; no directory discovery or execution."""

from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from kuberich.config.schema import ConfigDocument
from kuberich.domain.plugins import MAX_PLUGINS, Plugin, parse_plugin
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument


@dataclass(frozen=True, slots=True, repr=False)
class PluginLayer:
    commands: tuple[Plugin, ...] = ()
    locations: tuple[Path, ...] = ()


@dataclass(frozen=True, slots=True, repr=False)
class PluginPreferences:
    global_layer: PluginLayer = PluginLayer()
    contexts: tuple[tuple[str, PluginLayer], ...] = ()


def parse_layer(value: object, directory: Path, *, external: bool = False) -> PluginLayer:
    if not isinstance(value, dict) or value.keys() - {"commands", "locations"}:
        raise AppError("Plugin layers accept only commands and locations.")
    raw = value.get("commands", {})
    locations = value.get("locations", [])
    if not isinstance(raw, dict) or len(raw) > MAX_PLUGINS:
        raise AppError("Plugin layers support at most 64 named commands.")
    if not isinstance(locations, list) or len(locations) > 8 or (external and locations):
        raise AppError("Plugin locations support at most eight paths and cannot nest in files.")
    paths = []
    for location in locations:
        try:
            path = Path(validate_argument(location)).expanduser()
        except RuntimeError:
            raise AppError("Cannot resolve a configured plugin location.") from None
        paths.append(path if path.is_absolute() else directory / path)
    if len(set(paths)) != len(paths):
        raise AppError("Plugin locations must be unique.")
    return PluginLayer(
        tuple(parse_plugin(name, definition, directory) for name, definition in raw.items()),
        tuple(paths),
    )


def parse_plugins(value: object, directory: Path) -> PluginPreferences:
    if not isinstance(value, dict) or value.keys() - {
        "schema_version",
        "commands",
        "locations",
        "contexts",
    }:
        raise AppError("plugins accepts schema_version, commands, locations and contexts.")
    if type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise AppError("plugins.schema_version must be 1.")
    contexts = value.get("contexts", {})
    if not isinstance(contexts, dict) or len(contexts) > 128:
        raise AppError("Plugin contexts supports at most 128 named layers.")
    scoped = []
    for context, fields in contexts.items():
        if len(validate_argument(context)) > 253:
            raise AppError("Plugin context names must be at most 253 characters.")
        scoped.append((context, parse_layer(fields, directory)))
    return PluginPreferences(
        parse_layer(
            {key: value[key] for key in ("commands", "locations") if key in value}, directory
        ),
        tuple(sorted(scoped)),
    )


def plugins_from(document: ConfigDocument, directory: Path) -> PluginPreferences:
    return (
        parse_plugins(document.extensions["plugins"], directory)
        if "plugins" in document.extensions
        else PluginPreferences()
    )


def relocate_plugins(document: ConfigDocument, directory: Path) -> ConfigDocument:
    """An explicit preference migration must retain its executable trust roots."""
    if "plugins" not in document.extensions:
        return document
    preferences = plugins_from(document, directory)
    extension = cast(dict[str, object], deepcopy(document.extensions["plugins"]))

    def relocate(layer: dict[str, object], parsed: PluginLayer) -> None:
        if "locations" in layer:
            layer["locations"] = [str(path) for path in parsed.locations]
        commands = cast(dict[str, dict[str, object]], layer.get("commands", {}))
        for plugin in parsed.commands:
            commands[plugin.name]["directory"] = str(plugin.directory)

    relocate(extension, preferences.global_layer)
    contexts = cast(dict[str, dict[str, object]], extension.get("contexts", {}))
    for context, layer in preferences.contexts:
        relocate(contexts[context], layer)
    updated = replace(document, extensions={**document.extensions, "plugins": extension})
    # Absolute output paths must still meet the same bounded schema.
    plugins_from(updated, directory)
    return updated
