"""Read only explicitly configured, bounded regular plugin files in owned workers."""

import os
import stat
from pathlib import Path

import yaml

from kuberich.config.plugins import PluginLayer, PluginPreferences, parse_layer
from kuberich.config.store import MAX_CONFIG_BYTES, parse_config_text
from kuberich.domain.keyboard import KeyOverrides
from kuberich.domain.plugins import MAX_PLUGINS, Plugin, plugin_bindings
from kuberich.errors import AppError


def _file(path: Path) -> tuple[Plugin, ...]:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise AppError("Plugin locations must contain regular YAML files.")
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                content = stream.read(MAX_CONFIG_BYTES + 1)
        finally:
            os.close(descriptor)
        if len(content) > MAX_CONFIG_BYTES:
            raise AppError("Plugin files must not exceed 64 KiB.")
        document = parse_config_text(content.decode("utf-8"))
        extension = document.extensions.get("plugins")
        if (
            not isinstance(extension, dict)
            or type(extension.get("schema_version")) is not int
            or extension.get("schema_version") != 1
        ):
            raise AppError("Plugin files require a schema_version: 1 plugins extension.")
        if extension.keys() - {"schema_version", "commands"}:
            raise AppError("External plugin files accept only schema_version and commands.")
        return parse_layer(
            {"commands": extension.get("commands", {})}, path.parent, external=True
        ).commands
    except (OSError, UnicodeError, yaml.YAMLError, RecursionError, ValueError):
        raise AppError(
            "Cannot load configured plugin file; check regular UTF-8 YAML and permissions."
        ) from None


def _layer(layer: PluginLayer) -> tuple[Plugin, ...]:
    commands = {plugin.name: plugin for plugin in layer.commands}
    paths: list[Path] = []
    try:
        for location in layer.locations:
            if location.is_symlink():
                raise AppError("Plugin locations cannot be symbolic links.")
            if location.is_dir():
                with os.scandir(location) as entries:
                    for index, entry in enumerate(entries):
                        if index >= 128:
                            raise AppError(
                                "Configured plugin directories support at most 128 entries."
                            )
                        if entry.name.endswith((".yaml", ".yml")):
                            paths.append(location / entry.name)
            else:
                paths.append(location)
            if len(paths) > 16:
                raise AppError("Plugin layers load at most 16 explicit YAML files.")
    except OSError:
        raise AppError("Cannot enumerate configured plugin directory; check permissions.") from None
    for path in sorted(paths):
        for plugin in _file(path):
            if plugin.name in commands:
                raise AppError("Duplicate plugin name in one configuration layer.")
            commands[plugin.name] = plugin
            if len(commands) > MAX_PLUGINS:
                raise AppError("Plugin layers support at most 64 loaded commands.")
    return tuple(commands.values())


def load_plugins(
    preferences: PluginPreferences,
    context: str | None,
    keys: KeyOverrides = (),
) -> tuple[Plugin, ...]:
    commands = {plugin.name: plugin for plugin in _layer(preferences.global_layer)}
    scoped = dict(preferences.contexts).get(context) if context is not None else None
    if scoped is not None:
        commands.update((plugin.name, plugin) for plugin in _layer(scoped))
    if len(commands) > MAX_PLUGINS:
        raise AppError("An effective plugin catalogue supports at most 64 commands.")
    plugins = tuple(sorted(commands.values(), key=lambda plugin: plugin.name))
    resources = {scope for plugin in plugins for scope in plugin.scopes}
    for resource in {None, "v1/namespaces", *resources}:
        plugin_bindings(plugins, resource, keys)
    return plugins
