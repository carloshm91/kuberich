"""Declarative resource jumps: literal templates over a row's manifest, never code."""

import re
from dataclasses import dataclass

from kuberich.domain.connections import namespace_name
from kuberich.domain.resource_preferences import resource_key
from kuberich.domain.selectors import selectors
from kuberich.errors import AppError

MAX_JUMPS = 64
MAX_PLACEHOLDERS = 8
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z", re.ASCII)
_PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
_SEGMENT = re.compile(r"""[A-Za-z_][A-Za-z0-9_-]*|\[(["'])([A-Za-z0-9_./-]{1,253})\1\]""", re.ASCII)
_VALUE = re.compile(r"[A-Za-z0-9_./-]{0,253}\Z", re.ASCII)
_FIELDS = frozenset({"source", "target", "namespace", "labels", "fields", "description"})


def _path(text: str) -> tuple[str, ...]:
    """Dotted names and quoted ["keys"] only: no calls, indexes, filters or functions."""
    segments: list[str] = []
    position = 0
    while position < len(text):
        if segments and text[position] == ".":
            position += 1
        match = _SEGMENT.match(text, position)
        if match is None:
            raise AppError(
                'Jump placeholders accept field paths such as metadata.labels["app"] only.'
            )
        segments.append(match[2] or match[0])
        position = match.end()
    if not segments or len(segments) > 16:
        raise AppError("Jump placeholders need a field path with 1-16 parts.")
    return tuple(segments)


@dataclass(frozen=True)
class Template:
    text: str
    paths: tuple[tuple[str, ...], ...]

    @property
    def whole(self) -> bool:
        """A template that is exactly one placeholder may expand a label map."""
        return len(self.paths) == 1 and _PLACEHOLDER.fullmatch(self.text.strip()) is not None


def template(value: object, label: str) -> Template:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise AppError(f"Jump {label} must be text of 1-256 characters.")
    paths = tuple(_path(match[1]) for match in _PLACEHOLDER.finditer(value))
    if len(paths) > MAX_PLACEHOLDERS:
        raise AppError(f"Jump {label} accepts at most {MAX_PLACEHOLDERS} placeholders.")
    if "{{" in _PLACEHOLDER.sub("", value) or "}}" in _PLACEHOLDER.sub("", value):
        raise AppError(f"Jump {label} has an unclosed placeholder.")
    return Template(value, paths)


@dataclass(frozen=True)
class JumpDefinition:
    name: str
    source: str
    target: str
    namespace: Template | None = None
    labels: Template | None = None
    fields: Template | None = None
    description: str = ""


@dataclass(frozen=True)
class Jumps:
    definitions: tuple[JumpDefinition, ...] = ()

    def available(self, source: str) -> tuple[JumpDefinition, ...]:
        return tuple(jump for jump in self.definitions if jump.source == source)


def parse_jumps(value: object) -> Jumps:
    if not isinstance(value, dict) or value.keys() - {"schema_version", "definitions"}:
        raise AppError("jumps accepts only schema_version and definitions.")
    if value.get("schema_version", 1) != 1 or type(value.get("schema_version", 1)) is not int:
        raise AppError("Unsupported jumps.schema_version; use version 1.")
    definitions = value.get("definitions", {})
    if not isinstance(definitions, dict) or len(definitions) > MAX_JUMPS:
        raise AppError(f"jumps.definitions accepts at most {MAX_JUMPS} named jumps.")
    parsed = []
    for name, fields in definitions.items():
        if not isinstance(name, str) or _NAME.match(name) is None:
            raise AppError("Jump names use lowercase letters, digits, - or _ (1-64).")
        if not isinstance(fields, dict) or fields.keys() - _FIELDS:
            raise AppError(f"Jump {name} accepts only {', '.join(sorted(_FIELDS))}.")
        if not {"source", "target"} <= fields.keys():
            raise AppError(f"Jump {name} needs source and target resources.")
        if "labels" in fields and "fields" in fields:
            raise AppError(f"Jump {name} filters by labels or fields, not both.")
        description = fields.get("description", "")
        if not isinstance(description, str) or len(description) > 200:
            raise AppError(f"Jump {name} description must be text up to 200 characters.")
        namespace, labels, selected = (
            template(fields[key], f"{name} {key}") if key in fields else None
            for key in ("namespace", "labels", "fields")
        )
        parsed.append(
            JumpDefinition(
                name,
                _resource(fields["source"], name),
                _resource(fields["target"], name),
                namespace,
                labels,
                selected,
                description,
            )
        )
    return Jumps(tuple(sorted(parsed, key=lambda jump: jump.name)))


def _resource(value: object, name: str) -> str:
    try:
        key = resource_key(value)
    except AppError:
        raise AppError(
            f"Jump {name} resources use VERSION/RESOURCE or GROUP/VERSION/RESOURCE."
        ) from None
    if key.startswith("server:"):
        raise AppError(f"Jump {name} resources use VERSION/RESOURCE or GROUP/VERSION/RESOURCE.")
    return key


def _lookup(manifest: object, path: tuple[str, ...]) -> object:
    value = manifest
    for segment in path:
        if not isinstance(value, dict) or segment not in value:
            raise AppError(f"The selected row has no {'.'.join(path)}; the jump was not opened.")
        value = value[segment]
    return value


def _scalar(value: object, path: tuple[str, ...]) -> str:
    if isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (str, int)):
        text = str(value)
    else:
        raise AppError(f"{'.'.join(path)} is not a single value; the jump was not opened.")
    if _VALUE.match(text) is None:
        raise AppError(
            f"{'.'.join(path)} contains characters a selector cannot carry; the jump was not opened."
        )
    return text


def render(value: Template, manifest: object, *, labels: bool = False) -> str:
    if labels and value.whole:
        found = _lookup(manifest, value.paths[0])
        if isinstance(found, dict):
            if not found:
                raise AppError("The selected row has an empty label map; the jump was not opened.")
            return ",".join(
                f"{_scalar(key, value.paths[0])}={_scalar(item, value.paths[0])}"
                for key, item in sorted(found.items())
            )
    paths = iter(value.paths)
    return _PLACEHOLDER.sub(
        lambda _: _scalar(_lookup(manifest, path := next(paths)), path), value.text
    )


@dataclass(frozen=True)
class JumpTarget:
    resource: str
    namespace: str | None
    query: str


def resolve_jump(
    jump: JumpDefinition, manifest: object, row_namespace: str | None, namespaced: bool
) -> JumpTarget:
    """Render once from the captured manifest; every result is validated before use."""
    namespace: str | None = None
    if namespaced:
        text = row_namespace if jump.namespace is None else render(jump.namespace, manifest)
        namespace = "*" if text is None or text == "*" else namespace_name(text)
    elif jump.namespace is not None:
        raise AppError(f"Jump {jump.name} targets a cluster-scoped resource; remove namespace.")
    query = ""
    if jump.labels is not None:
        query = "label:" + render(jump.labels, manifest, labels=True)
        selectors(query.removeprefix("label:"))
    elif jump.fields is not None:
        query = "field:" + render(jump.fields, manifest)
        selectors(query.removeprefix("field:"), field=True)
    return JumpTarget(jump.target, namespace, query)
