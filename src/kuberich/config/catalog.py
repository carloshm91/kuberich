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

from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import (
    ConnectionProblem,
    ConnectionRequest,
    ConnectionState,
    namespace_name,
)
from kuberich.errors import AppError, ExitCode
from kuberich.security.arguments import validate_argument

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


def _extensions(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) > 2048:
        raise AppError(f"{field} must be a list of at most 2048 named extensions.")
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise AppError(f"{field} entries require a string name.")
        # Extension payloads are opaque JSON, including Teleport string values.
        # Only the explicitly named credential extension has runtime semantics.


def text(value: Any) -> str:
    if not isinstance(value, str):
        raise AppError("Invalid kubeconfig string; check the selected configuration.")
    return validate_argument(value)


def parse_kubeconfig(raw: bytes) -> dict[str, Any]:
    """Parse bounded, alias-free kubeconfig YAML with unique string keys."""
    try:
        contents = raw.decode("utf-8")
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


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = regular_bytes(path)
    except OSError:
        raise AppError(
            "Cannot read kubeconfig; check the file and permissions.", ExitCode.LOCAL_IO
        ) from None
    return parse_kubeconfig(raw)


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
        try:
            cluster = overrides.cluster or text(context.data.get("cluster"))
        except AppError:
            raise AppError("contexts.context.cluster must name a configured cluster.") from None
        if cluster not in self.clusters:
            raise AppError("Selected context references a missing cluster.")
        user = overrides.user or context.data.get("user")
        if user == "":
            user = None
        if user is not None and (not isinstance(user, str) or user not in self.users):
            raise ConnectionProblem(
                ConnectionState.AUTH_ERROR,
                "Selected contexts.context.user references unavailable credentials. Check its users entry.",
            )
        try:
            raw_namespace = context.data.get("namespace")
            namespace = namespace_name(
                text("default" if raw_namespace in (None, "") else raw_namespace)
            )
        except AppError:
            raise AppError("contexts.context.namespace must be a valid namespace name.") from None
        cluster_data, user_data = overrides.apply(
            self.clusters[cluster].data, self.users[user].data if user is not None else {}
        )
        return ContextConfig(
            name,
            namespace,
            Entry(cluster_data, self.clusters[cluster].directory),
            Entry(user_data, self.users[user].directory if user is not None else context.directory),
        )


def kubeconfig_paths(request: ConnectionRequest, environment: Mapping[str, str]) -> list[Path]:
    """Return the kubeconfig files in kubectl precedence order, without duplicates."""
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
    return list(dict.fromkeys(paths))


def load_catalog(request: ConnectionRequest, environment: Mapping[str, str]) -> KubeCatalog:
    current = None
    sections: dict[str, dict[str, Entry]] = {"contexts": {}, "clusters": {}, "users": {}}
    for path in kubeconfig_paths(request, environment):
        if not path.exists():
            if request.kubeconfig is not None:
                raise AppError(
                    "Explicit kubeconfig is missing; check --kubeconfig.", ExitCode.LOCAL_IO
                )
            continue
        data = _read_yaml(path)
        if data.get("apiVersion") not in (None, "", "v1"):
            raise AppError("kubeconfig apiVersion must be v1.")
        if data.get("kind") not in (None, "", "Config"):
            raise AppError("kubeconfig kind must be Config.")
        _extensions(data.get("extensions"), "kubeconfig.extensions")
        preferences = data.get("preferences")
        if preferences is not None:
            if not isinstance(preferences, dict):
                raise AppError("kubeconfig.preferences must be a mapping.")
            if preferences.get("colors") is not None and type(preferences["colors"]) is not bool:
                raise AppError("kubeconfig.preferences.colors must be true or false.")
            _extensions(preferences.get("extensions"), "kubeconfig.preferences.extensions")
        raw_current = data.get("current-context")
        if raw_current not in (None, ""):
            try:
                validated_current = text(raw_current)
            except AppError:
                raise AppError(
                    "kubeconfig.current-context must be a bounded string without controls."
                ) from None
            if current is None:
                current = validated_current
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
                try:
                    name = text(entry.get("name"))
                except AppError:
                    raise AppError(
                        f"{section}.name must be bounded text without controls."
                    ) from None
                if name in names:
                    raise AppError("Kubeconfig contains duplicate names within one file.")
                names.add(name)
                content = entry.get(payload)
                if content is None:
                    content = {}
                if not isinstance(content, dict):
                    raise AppError(f"{section}.{payload} must be a mapping.")
                _extensions(content.get("extensions"), f"{section}.{payload}.extensions")
                sections[section].setdefault(name, Entry(content, path.absolute().parent))
                if len(sections[section]) > 2048:
                    raise AppError("Merged kubeconfig sections support at most 2048 names.")
    return KubeCatalog(current, sections["contexts"], sections["clusters"], sections["users"])
