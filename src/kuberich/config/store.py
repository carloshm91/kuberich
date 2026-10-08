"""Bounded safe YAML reads and atomic, private preference writes."""

import os
import tempfile
from collections.abc import Hashable
from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent
from yaml.nodes import MappingNode

from kuberich.config.paths import log_location
from kuberich.config.schema import ConfigDocument, parse_document
from kuberich.errors import AppError, ExitCode

MAX_CONFIG_BYTES = 65536


class _PreferenceLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[str] = set()
        for key, _ in node.value:
            if key.tag != "tag:yaml.org,2002:str" or key.value in seen:
                raise AppError("YAML preference keys must be unique strings.")
            seen.add(key.value)
        return super().construct_mapping(node, deep=deep)


def _parse_yaml(text: str) -> ConfigDocument:
    depth = 0
    for count, event in enumerate(yaml.parse(text, Loader=yaml.SafeLoader)):
        if isinstance(event, AliasEvent):
            raise AppError("YAML aliases are not supported in preferences.")
        if isinstance(event, CollectionStartEvent):
            depth += 1
        elif isinstance(event, CollectionEndEvent):
            depth -= 1
        if depth > 20 or count > 4096:
            raise AppError("Preference structure exceeds its size or nesting limit.")
    data = yaml.load(text, Loader=_PreferenceLoader)
    if data is None:
        return ConfigDocument()
    if not isinstance(data, dict):
        raise AppError("Preferences must be a YAML mapping.")
    return parse_document(data)


def read_config(path: Path, *, missing_ok: bool = True) -> ConfigDocument:
    try:
        if not path.exists() and missing_ok and not path.is_symlink():
            return ConfigDocument()
        if not path.is_file():
            raise AppError(
                "Preference file is missing or is not a regular file.", ExitCode.LOCAL_IO
            )
        with path.open("rb") as stream:
            content = stream.read(MAX_CONFIG_BYTES + 1)
        if len(content) > MAX_CONFIG_BYTES:
            raise AppError("Preference file exceeds 64 KiB.")
        return _parse_yaml(content.decode("utf-8"))
    except (yaml.YAMLError, UnicodeError, RecursionError, ValueError):
        raise AppError("Invalid YAML preferences; check syntax and UTF-8 encoding.") from None
    except OSError:
        raise AppError(
            "Cannot read preferences; check the file and its permissions.", ExitCode.LOCAL_IO
        ) from None


def write_config(path: Path, document: ConfigDocument, *, overwrite: bool = False) -> None:
    """Commit via same-directory link/replace; failure before commit preserves the old file."""
    committed = False
    try:
        if path.is_symlink():
            raise AppError(
                "Refusing to write preferences through a symbolic link.", ExitCode.LOCAL_IO
            )
        if path.exists():
            if not overwrite:
                raise AppError(
                    "Preferences already exist; this operation never overwrites them.",
                    ExitCode.LOCAL_IO,
                )
            read_config(path, missing_ok=False)
        text = yaml.safe_dump(document.to_mapping(), sort_keys=False, allow_unicode=True)
        if len(text.encode("utf-8")) > MAX_CONFIG_BYTES:
            raise AppError("Preference file exceeds 64 KiB.")
        _parse_yaml(text)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".kuberich-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            try:
                stream = os.fdopen(descriptor, "w", encoding="utf-8")
            except BaseException:
                os.close(descriptor)
                raise
            with stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            if overwrite:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
            committed = True
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
    except (yaml.YAMLError, RecursionError):
        raise AppError("Preferences cannot be represented as safe YAML.") from None
    except OSError:
        if committed:
            raise AppError(
                "Preferences were saved, but cleanup or durability could not be confirmed; check the filesystem.",
                ExitCode.LOCAL_IO,
            ) from None
        raise AppError(
            "Cannot save preferences; check permissions and free space.", ExitCode.LOCAL_IO
        ) from None


def migrate_config(source: Path, destination: Path) -> None:
    """Retain the source and log destination; create the new file without replacement."""
    document = read_config(source, missing_ok=False)
    if document.settings.log_file is not None:
        document = replace(
            document,
            settings=replace(
                document.settings,
                log_file=str(log_location(document.settings, source, from_file=True)),
            ),
        )
    write_config(destination, document)
