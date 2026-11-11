"""Offline chart archive policy, with cumulative decompression and parse budgets."""

import gzip
import hashlib
import io
import json
import re
import tarfile
from collections.abc import Buffer
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from kuberich.domain.helm_catalog import (
    MAX_CHART_BYTES,
    MAX_CHART_DEPTH,
    MAX_CHART_FILES,
    MAX_EXPANDED_BYTES,
    MAX_VALUES_BYTES,
    catalog_name,
    chart_version,
    chart_version_key,
)
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

_METASCHEMAS = frozenset(
    f"{scheme}://json-schema.org/{version}/schema{suffix}"
    for scheme in ("http", "https")
    for version in ("draft-07", "draft/2019-09", "draft/2020-12")
    for suffix in ("", "#")
)
_DEPENDENCY_FIELDS = (
    "name",
    "version",
    "repository",
    "condition",
    "tags",
    "enabled",
    "import-values",
    "alias",
)


def _refused() -> AppError:
    return AppError(
        "Helm chart package is unsafe, inconsistent or exceeds the supported offline policy."
    )


@dataclass(slots=True)
class _Budget:
    expanded: int = 0
    files: int = 0
    crds: list[str] = field(default_factory=list)

    def charge(self, size: int) -> None:
        self.expanded += size
        if self.expanded > MAX_EXPANDED_BYTES:
            raise _refused()


class _ExpandedReader(io.RawIOBase):
    def __init__(self, compressed: bytes, budget: _Budget) -> None:
        super().__init__()
        self.stream = gzip.GzipFile(fileobj=io.BytesIO(compressed))
        self.budget = budget

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        view = memoryview(buffer)
        remaining = MAX_EXPANDED_BYTES - self.budget.expanded
        data = self.stream.read(min(len(view), remaining + 1))
        self.budget.charge(len(data))
        view[: len(data)] = data
        return len(data)

    def close(self) -> None:
        self.stream.close()
        super().close()


def values_mapping(data: bytes) -> dict[str, Any]:
    from kuberich.domain.editing import parse_manifest

    if not isinstance(data, bytes) or not 1 <= len(data) <= MAX_VALUES_BYTES:
        raise AppError("Helm values require a bounded UTF-8 YAML mapping.")
    try:
        return parse_manifest(data)
    except AppError:
        raise AppError(
            "Helm values require a bounded JSON-compatible YAML mapping without aliases or duplicate keys."
        ) from None


def _json_pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _refused()
        result[key] = value
    return result


def _schema(data: bytes) -> None:
    if len(data) > MAX_VALUES_BYTES:
        raise _refused()
    try:
        value = json.loads(data, object_pairs_hook=_json_pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise _refused() from None
    if not isinstance(value, (dict, bool)):
        raise _refused()
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 50_000 or depth > 64:
            raise _refused()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 4096:
                    raise _refused()
                if key in {"$ref", "$dynamicRef", "$recursiveRef"} and (
                    not isinstance(child, str) or not child.startswith("#") or len(child) > 4096
                ):
                    raise _refused()
                if key == "$schema" and (not isinstance(child, str) or child not in _METASCHEMAS):
                    raise _refused()
                if key == "$id" and child != "":
                    raise _refused()
                if key == "$vocabulary":
                    raise _refused()
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and (item != item or abs(item) == float("inf")):
            raise _refused()


def _yaml(data: bytes) -> dict[str, Any]:
    from kuberich.domain.editing import parse_manifest_documents

    try:
        values = parse_manifest_documents(data, max_bytes=MAX_VALUES_BYTES, max_documents=1)
        if len(values) != 1:
            raise _refused()
        return values[0]
    except AppError:
        raise _refused() from None


def _dependency_record(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - set(_DEPENDENCY_FIELDS):
        raise _refused()
    if (
        not isinstance(value.get("name"), str)
        or not isinstance(value.get("version"), str)
        or not value.get("version")
    ):
        raise _refused()
    catalog_name(value["name"])
    if not isinstance(value.get("repository", ""), str):
        raise _refused()
    # Match Helm's typed Dependency JSON field order and omitempty rules.
    return {
        key: value[key]
        for key in _DEPENDENCY_FIELDS
        if key in value and value[key] not in (None, "", False, [])
    }


def _matches(version: str, constraint: str) -> bool:
    actual = chart_version_key(version)[:5]
    alternatives = constraint.split("||")
    if len(alternatives) > 8:
        raise _refused()
    for alternative in alternatives:
        tokens = alternative.replace(",", " ").split()
        if not tokens or len(tokens) > 16:
            raise _refused()
        matched = True
        for token in tokens:
            operator = next(
                (
                    item
                    for item in (">=", "<=", "!=", "==", ">", "<", "=", "^", "~")
                    if token.startswith(item)
                ),
                None,
            )
            wanted = token[len(operator) :] if operator else token
            if wanted in {"*", "x", "X"}:
                if operator is not None:
                    raise _refused()
                continue
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?(?:\.[xX*])?|[0-9]+\.[xX*]", wanted):
                if operator not in {None, "=", "=="}:
                    raise _refused()
                parts = wanted.split(".")
                significant = [int(part) for part in parts if part not in {"x", "X", "*"}]
                matched = matched and tuple(actual[: len(significant)]) == tuple(significant)
                continue
            chart_version(wanted)
            key = chart_version_key(wanted)[:5]
            if operator in {"^", "~"}:
                major, minor, patch = (
                    int(number) for number in wanted.split("-")[0].split("+")[0].split(".")
                )
                upper = (
                    (major + 1, 0, 0)
                    if operator == "^" and major
                    else (major, minor + 1, 0)
                    if operator == "~" or minor
                    else (major, minor, patch + 1)
                )
                matched = matched and actual >= key and actual[:3] < upper
            else:
                matches = {
                    None: actual == key,
                    "=": actual == key,
                    "==": actual == key,
                    "!=": actual != key,
                    ">": actual > key,
                    ">=": actual >= key,
                    "<": actual < key,
                    "<=": actual <= key,
                }
                matched = matched and matches[operator]
        if matched:
            return True
    return False


def _chart(
    files: dict[str, bytes], budget: _Budget, depth: int, parent: str
) -> tuple[str, str, bytes]:
    if (
        depth > MAX_CHART_DEPTH
        or "Chart.yaml" not in files
        or "requirements.yaml" in files
        or "requirements.lock" in files
    ):
        raise _refused()
    metadata = _yaml(files["Chart.yaml"])
    name, version = metadata.get("name"), metadata.get("version")
    chart_type = metadata.get("type", "application")
    if (
        metadata.get("apiVersion") != "v2"
        or not isinstance(chart_type, str)
        or chart_type not in {"application", "library"}
        or (depth == 0 and chart_type != "application")
    ):
        raise _refused()
    if not isinstance(name, str) or not isinstance(version, str):
        raise _refused()
    catalog_name(name)
    chart_version(version)
    chart_path = f"{parent}/charts/{name}" if parent else name
    defaults = files.get("values.yaml", b"{}\n")
    values_mapping(defaults)
    if "values.schema.json" in files:
        _schema(files["values.schema.json"])
    children: dict[str, tuple[str, str, bytes]] = {}
    directories: dict[str, dict[str, bytes]] = {}
    for path, data in files.items():
        if path.startswith("crds/") and path.rpartition(".")[2].lower() in {
            "yaml",
            "yml",
            "json",
        }:
            budget.crds.append(f"{chart_path}/{path}")
        if not path.startswith("charts/"):
            continue
        relative = path[7:]
        if "/" in relative:
            folder, childpath = relative.split("/", 1)
            directories.setdefault(folder, {})[childpath] = data
        elif relative.endswith(".tgz"):
            child = _archive(data, budget, depth + 1, chart_path)
            if child[0] in children:
                raise _refused()
            children[child[0]] = child
        else:
            raise _refused()
    for folder, entries in directories.items():
        child = _chart(entries, budget, depth + 1, chart_path)
        if folder != child[0] or child[0] in children:
            raise _refused()
        children[child[0]] = child
    dependencies = metadata.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) > 128:
        raise _refused()
    declarations = [_dependency_record(item) for item in dependencies]
    if len({item["name"] for item in declarations}) != len(declarations):
        raise _refused()
    for dependency in declarations:
        selected = children.get(dependency["name"])
        if selected is None or not _matches(selected[1], dependency["version"]):
            raise _refused()
    if declarations:
        if "Chart.lock" not in files:
            raise _refused()
        lock = _yaml(files["Chart.lock"])
        raw_locked = lock.get("dependencies")
        if not isinstance(raw_locked, list) or len(raw_locked) != len(declarations):
            raise _refused()
        locked = [_dependency_record(item) for item in raw_locked]
        for wanted, pinned in zip(declarations, locked, strict=True):
            if (
                pinned["name"] != wanted["name"]
                or pinned.get("repository", "") != wanted.get("repository", "")
                or pinned["version"] != children[wanted["name"]][1]
            ):
                raise _refused()
        content = (
            json.dumps([declarations, locked], ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .encode()
        )
        if lock.get("digest") != "sha256:" + hashlib.sha256(content).hexdigest():
            raise _refused()
    elif "Chart.lock" in files:
        raise _refused()
    return name, version, defaults


def _archive(data: bytes, budget: _Budget, depth: int, parent: str) -> tuple[str, str, bytes]:
    if depth > MAX_CHART_DEPTH or not 1 <= len(data) <= MAX_CHART_BYTES:
        raise _refused()
    stream = io.BufferedReader(_ExpandedReader(data, budget))
    files: dict[str, bytes] = {}
    names: set[str] = set()
    root: str | None = None
    try:
        with tarfile.open(fileobj=stream, mode="r|") as archive:
            for entry in archive:
                budget.files += 1
                if (
                    budget.files > MAX_CHART_FILES
                    or not (entry.isfile() or entry.isdir())
                    or entry.sparse is not None
                    or any(key.startswith("GNU.sparse") for key in entry.pax_headers)
                ):
                    raise _refused()
                path = entry.name.rstrip("/") if entry.isdir() else entry.name
                parts = PurePosixPath(path).parts
                if (
                    not path
                    or len(path) > 4096
                    or escape_controls(path) != path
                    or "\\" in path
                    or path.startswith("/")
                    or any(part in {"", ".", ".."} for part in path.split("/"))
                    or len(parts) < (1 if entry.isdir() else 2)
                    or path in names
                    or entry.size < 0
                    or entry.size > MAX_EXPANDED_BYTES
                ):
                    raise _refused()
                names.add(path)
                if root is None:
                    root = parts[0]
                if parts[0] != root:
                    raise _refused()
                if entry.isdir():
                    continue
                extracted = archive.extractfile(entry)
                # TarFile returns a stream for a validated regular member;
                # truncated members raise ReadError during the bounded read.
                assert extracted is not None
                content = extracted.read(entry.size)
                files["/".join(parts[1:])] = content
        # Consume trailing compressed bytes too, detecting truncated gzip streams/bombs.
        while stream.read(16_384):
            pass
    except (OSError, EOFError, tarfile.TarError, ValueError, UnicodeError):
        raise _refused() from None
    finally:
        stream.close()
    result = _chart(files, budget, depth, parent)
    if root != result[0]:
        raise _refused()
    return result


def _inspect(data: bytes, expected_name: str, expected_version: str, budget: _Budget) -> bytes:
    catalog_name(expected_name)
    chart_version(expected_version)
    if not isinstance(data, bytes):
        raise _refused()
    actual_name, actual_version, defaults = _archive(data, budget, 0, "")
    if actual_name != expected_name or actual_version != expected_version:
        raise _refused()
    return defaults


def inspect_chart_package(data: bytes, *, expected_name: str, expected_version: str) -> bytes:
    """Validate without extraction or filesystem/network schema resolution."""
    return _inspect(data, expected_name, expected_version, _Budget())


def chart_crd_files(data: bytes, *, expected_name: str, expected_version: str) -> tuple[str, ...]:
    """Return bounded loaded-chart CRD paths, before dependency aliases/conditions.

    The same full offline policy and cumulative archive budget apply. These
    paths disclose files skipped by the application, without parsing CRD bodies
    or claiming that the release JSON retains a subchart inventory.
    """
    budget = _Budget()
    _inspect(data, expected_name, expected_version, budget)
    return tuple(sorted(budget.crds))
