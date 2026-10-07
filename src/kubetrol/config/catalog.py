"""Bounded read-only kubeconfig catalogue with first-file-wins merge semantics."""

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent
from yaml.nodes import MappingNode

from kubetrol.domain.connection_overrides import ConnectionOverrides
from kubetrol.domain.connections import (
    ConnectionProblem,
    ConnectionRequest,
    ConnectionState,
    namespace_name,
)
from kubetrol.errors import AppError, ExitCode
from kubetrol.security.arguments import validate_argument

MAX_FILE_BYTES = 1024 * 1024


def regular_bytes(path: Path) -> bytes:
    """Check the opened descriptor before reading; FIFOs cannot block a worker."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise AppError("Kubeconfig/credential paths must refer to regular files.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise AppError("Kubeconfig/credential file exceeds 1 MiB.")
        return data
    finally:
        os.close(descriptor)


class _KubeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[str] = set()
        for key, _ in node.value:
            if key.tag != "tag:yaml.org,2002:str" or key.value in seen:
                raise AppError("Kubeconfig YAML keys must be unique strings.")
            seen.add(key.value)
        return super().construct_mapping(node, deep=deep)


def mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AppError("Invalid kubeconfig mapping; check the selected configuration.")
    return value


def text(value: Any) -> str:
    if not isinstance(value, str):
        raise AppError("Invalid kubeconfig string; check the selected configuration.")
    return validate_argument(value)


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        contents = regular_bytes(path).decode("utf-8")
        depth = 0
        for count, event in enumerate(yaml.parse(contents)):
            if isinstance(event, AliasEvent) or count > 65536:
                raise AppError("Kubeconfig aliases or excessive YAML structure are unsupported.")
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > 30:
                raise AppError("Kubeconfig YAML nesting exceeds 30 levels.")
        data = yaml.load(contents, Loader=_KubeLoader)
        return mapping(data) if data is not None else {}
    except (yaml.YAMLError, UnicodeError, RecursionError, ValueError):
        raise AppError("Invalid kubeconfig YAML; check syntax and UTF-8 encoding.") from None
    except OSError:
        raise AppError(
            "Cannot read kubeconfig; check the file and permissions.", ExitCode.LOCAL_IO
        ) from None


@dataclass(frozen=True, repr=False)
class Entry:
    data: dict[str, Any]
    directory: Path


@dataclass(frozen=True, repr=False)
class ContextConfig:
    name: str
    namespace: str
    cluster: Entry
    user: Entry


@dataclass(frozen=True, repr=False)
class KubeCatalog:
    current: str | None = None
    contexts: dict[str, Entry] = field(default_factory=dict)
    clusters: dict[str, Entry] = field(default_factory=dict)
    users: dict[str, Entry] = field(default_factory=dict)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.contexts))

    def select(self, name: str, overrides: ConnectionOverrides | None = None) -> ContextConfig:
        if name not in self.contexts:
            raise AppError("Selected context is not present in the loaded kubeconfig.")
        context = self.contexts[name]
        overrides = overrides or ConnectionOverrides()
        cluster = overrides.cluster or text(context.data.get("cluster"))
        if cluster not in self.clusters:
            raise AppError("Selected context references a missing cluster.")
        user = overrides.user or context.data.get("user")
        if user is not None and text(user) not in self.users:
            raise ConnectionProblem(
                ConnectionState.AUTH_ERROR,
                "Selected context references unavailable credentials. Check its user entry.",
            )
        namespace = namespace_name(text(context.data.get("namespace", "default")))
        cluster_data, user_data = overrides.apply(
            self.clusters[cluster].data, self.users[user].data if user is not None else {}
        )
        return ContextConfig(
            name,
            namespace,
            Entry(cluster_data, self.clusters[cluster].directory),
            Entry(user_data, self.users[user].directory if user is not None else context.directory),
        )


def load_catalog(request: ConnectionRequest, environment: Mapping[str, str]) -> KubeCatalog:
    if request.kubeconfig is not None:
        paths = [Path(request.kubeconfig).expanduser()]
    elif environment.get("KUBECONFIG"):
        paths = [
            Path(text(path)).expanduser()
            for path in environment["KUBECONFIG"].split(os.pathsep)
            if path
        ]
    else:
        paths = [Path.home() / ".kube/config"]
    if len(paths) > 32:
        raise AppError("KUBECONFIG supports at most 32 file entries.")
    current = None
    sections: dict[str, dict[str, Entry]] = {"contexts": {}, "clusters": {}, "users": {}}
    for path in dict.fromkeys(paths):
        if not path.exists():
            if request.kubeconfig is not None:
                raise AppError(
                    "Explicit kubeconfig is missing; check --kubeconfig.", ExitCode.LOCAL_IO
                )
            continue
        data = _read_yaml(path)
        if current is None and data.get("current-context"):
            current = text(data["current-context"])
        for section, payload in (
            ("contexts", "context"),
            ("clusters", "cluster"),
            ("users", "user"),
        ):
            entries = data.get(section)
            if entries is None:
                entries = []
            if not isinstance(entries, list) or len(entries) > 2048:
                raise AppError("Kubeconfig named sections must be lists of at most 2048 entries.")
            names: set[str] = set()
            for value in entries:
                entry = mapping(value)
                name = text(entry.get("name"))
                if name in names:
                    raise AppError("Kubeconfig contains duplicate names within one file.")
                names.add(name)
                content = mapping(entry.get(payload))
                sections[section].setdefault(name, Entry(content, path.absolute().parent))
                if len(sections[section]) > 2048:
                    raise AppError("Merged kubeconfig sections support at most 2048 names.")
    return KubeCatalog(current, sections["contexts"], sections["clusters"], sections["users"])
