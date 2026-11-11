"""Finite data-only resource templates and typed, whole-value JSON pointers."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from kuberich.domain.editing import parse_manifest
from kuberich.domain.manifests import (
    MAX_MANIFEST_RESOURCES,
    canonical_manifest,
    manifest_documents,
)
from kuberich.domain.resources import resource_object, split_api_version
from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

type ParameterType = Literal["string", "integer", "boolean", "string_map"]
type TemplateOrigin = Literal["builtin", "user"]
type TemplateIdentity = tuple[TemplateOrigin, str, int, str]

_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,63}")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_SERVER_METADATA = frozenset(
    {
        "uid",
        "resourceVersion",
        "managedFields",
        "creationTimestamp",
        "generation",
        "deletionTimestamp",
        "deletionGracePeriodSeconds",
        "selfLink",
        "generateName",
    }
)


@dataclass(frozen=True, kw_only=True, slots=True)
class TemplateParameter:
    name: str
    type: ParameterType
    required: bool
    sensitive: bool
    paths: tuple[str, ...]
    has_default: bool
    default: bytes | None = field(repr=False)
    enum: tuple[bytes, ...] = field(repr=False)

    @property
    def default_value(self) -> object:
        """Return a detached value so UI edits cannot mutate a frozen template."""
        return json.loads(self.default) if self.default is not None else None


@dataclass(frozen=True, kw_only=True, slots=True)
class ResourceTemplate:
    id: str
    revision: int
    title: str
    description: str
    parameters: tuple[TemplateParameter, ...]
    objects: bytes = field(repr=False)
    source_sha256: str = field(repr=False)
    builtin: bool = False


@dataclass(frozen=True, kw_only=True, slots=True)
class TemplateCatalogEntry:
    origin: TemplateOrigin
    relative_path: str
    identity: TemplateIdentity
    template: ResourceTemplate | None = field(repr=False)
    problem: str | None = None

    @property
    def enabled(self) -> bool:
        return self.template is not None and self.problem is None


def _invalid(reason: str) -> AppError:
    return AppError("Resource template refused: " + reason + ".")


def _text(value: object, maximum: int, *, empty: bool = False, characters: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not empty and not value)
        or (len(value) if characters else len(value.encode("utf-8"))) > maximum
        or escape_controls(value, allow_newlines=True) != value
    ):
        raise _invalid("text is missing, unsafe or exceeds its bound")
    return value


def _typed(value: object, kind: ParameterType) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return type(value) is int
    if kind == "boolean":
        return type(value) is bool
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _pointer(path: object) -> tuple[str, ...]:
    if (
        not isinstance(path, str)
        or not 1 <= len(path) <= 1024
        or not path.startswith("/")
        or re.search(r"~(?![01])", path)
    ):
        raise _invalid("paths must be bounded literal RFC 6901 pointers")
    parts = tuple(part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/"))
    if (
        len(parts) < 2
        or re.fullmatch(r"0|[1-9][0-9]*", parts[0]) is None
        or parts[1] in {"apiVersion", "kind", "status"}
        or (parts[1] == "metadata" and (len(parts) < 3 or parts[2] in _SERVER_METADATA))
    ):
        raise _invalid("paths cannot replace resource type or server-owned metadata")
    return parts


def _location(objects: list[Any], parts: tuple[str, ...]) -> tuple[Any, str | int]:
    current: Any = objects
    for part in parts[:-1]:
        if isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            index = int(part)
            if index < len(current):
                current = current[index]
                continue
        elif isinstance(current, dict) and part in current:
            current = current[part]
            continue
        raise _invalid("a pointer must address an existing value")
    last = parts[-1]
    if isinstance(current, list) and re.fullmatch(r"0|[1-9][0-9]*", last):
        index = int(last)
        if index < len(current):
            return current, index
    elif isinstance(current, dict) and last in current:
        return current, last
    raise _invalid("a pointer must address an existing value")


def _objects(value: object) -> list[Any]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MANIFEST_RESOURCES:
        raise _invalid("objects must contain one to 100 resource mappings")
    for item in value:
        resource = resource_object(item)
        split_api_version(resource.get("apiVersion"))
        kind = resource.get("kind")
        metadata = resource_object(resource.get("metadata"))
        if (
            not isinstance(kind, str)
            or re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,127}", kind) is None
            or kind.endswith("List")
            or _SERVER_METADATA.intersection(metadata)
            or "status" in resource
        ):
            raise _invalid("objects require literal resource types and no server-owned fields")
    return value


def parse_resource_template(data: bytes) -> ResourceTemplate:
    """Use the ordinary bounded manifest parser; templates add no executable syntax."""
    value = parse_manifest(data)
    required = {"schema_version", "kind", "id", "revision", "title", "parameters", "objects"}
    if (
        not required <= value.keys()
        or value.keys() - required - {"description"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or value["kind"] != "ResourceTemplate"
        or not isinstance(value["id"], str)
        or _IDENTIFIER.fullmatch(value["id"]) is None
        or type(value["revision"]) is not int
        or value["revision"] < 1
    ):
        raise _invalid("unsupported or incomplete versioned envelope")
    title = _text(value["title"], 120, characters=True)
    description = _text(value.get("description", ""), 1024, empty=True)
    objects = _objects(value["objects"])
    declarations = value["parameters"]
    if not isinstance(declarations, dict) or len(declarations) > 32:
        raise _invalid("parameters must be a mapping of at most 32 declarations")
    parameters: list[TemplateParameter] = []
    destinations: list[tuple[str, ...]] = []
    for name, raw in declarations.items():
        declaration = resource_object(raw)
        if (
            _IDENTIFIER.fullmatch(name) is None
            or not {"type", "required", "paths"} <= declaration.keys()
            or declaration.keys() - {"type", "required", "paths", "default", "enum", "sensitive"}
            or not isinstance(declaration["type"], str)
            or declaration["type"] not in {"string", "integer", "boolean", "string_map"}
            or type(declaration["required"]) is not bool
            or type(declaration.get("sensitive", False)) is not bool
        ):
            raise _invalid("invalid parameter declaration")
        kind = cast(ParameterType, declaration["type"])
        paths = declaration["paths"]
        if not isinstance(paths, list) or not 1 <= len(paths) <= 32:
            raise _invalid("each parameter needs one to 32 destination paths")
        sensitive = declaration.get("sensitive", False)
        parameter_destinations: list[tuple[str, ...]] = []
        for path in paths:
            parts = _pointer(path)
            container, key = _location(objects, parts)
            if not _typed(container[key], kind):
                raise _invalid("parameter type differs from an existing destination value")
            if any(
                parts[: len(previous)] == previous or previous[: len(parts)] == parts
                for previous in destinations
            ):
                raise _invalid("parameter destinations overlap or repeat")
            destinations.append(parts)
            parameter_destinations.append(parts)
            sensitive = sensitive or parts[1] in {"data", "stringData"}
        if sensitive and any(
            parts[1:3] in {("metadata", "name"), ("metadata", "namespace")}
            for parts in parameter_destinations
        ):
            raise _invalid("sensitive parameters cannot supply public destination identity")
        enum = declaration.get("enum", [])
        if (
            not isinstance(enum, list)
            or len(enum) > 64
            or any(not _typed(item, kind) for item in enum)
        ):
            raise _invalid("enum must contain at most 64 values of the declared type")
        encoded_enum = tuple(canonical_manifest(item) for item in enum)
        if len(set(encoded_enum)) != len(encoded_enum):
            raise _invalid("enum values must be distinct")
        has_default = "default" in declaration
        default = canonical_manifest(declaration["default"]) if has_default else None
        if has_default and (
            not _typed(declaration["default"], kind)
            or (encoded_enum and default not in encoded_enum)
        ):
            raise _invalid("default must match the declared type and enum")
        parameters.append(
            TemplateParameter(
                name=name,
                type=kind,
                required=declaration["required"],
                sensitive=sensitive,
                paths=tuple(paths),
                has_default=has_default,
                default=default,
                enum=encoded_enum,
            )
        )
    return ResourceTemplate(
        id=value["id"],
        revision=value["revision"],
        title=title,
        description=description,
        parameters=tuple(parameters),
        objects=canonical_manifest(objects),
        source_sha256=hashlib.sha256(data).hexdigest(),
    )


def _builtin_values(template: ResourceTemplate, objects: list[Any]) -> None:
    if not template.builtin:
        return
    value = objects[0]
    if _DNS_LABEL.fullmatch(value["metadata"]["name"]) is None:
        raise _invalid("built-in names must be lowercase DNS labels of at most 63 characters")
    if template.id in {"deployment", "job"}:
        pod = value["spec"]["template"]["spec"]
        if not pod["containers"][0]["image"].strip():
            raise _invalid("a built-in workload requires an explicit nonempty image")
    if template.id == "deployment" and not 0 <= value["spec"]["replicas"] <= 2147483647:
        raise _invalid("replicas must be between zero and 2147483647")
    if template.id == "service" and any(
        not 1 <= value["spec"]["ports"][0][name] <= 65535 for name in ("port", "targetPort")
    ):
        raise _invalid("Service ports must be between one and 65535")


def render_resource_template(template: ResourceTemplate, values: Mapping[str, object]) -> bytes:
    """Substitute typed complete values, then enforce the ordinary manifest contract."""
    if values.keys() - {parameter.name for parameter in template.parameters}:
        raise _invalid("unknown parameter input")
    objects = json.loads(template.objects)
    for parameter in template.parameters:
        if parameter.name in values:
            value = values[parameter.name]
        elif parameter.has_default:
            value = parameter.default_value
        elif parameter.required:
            raise _invalid("a required parameter is absent")
        else:
            continue
        if not _typed(value, parameter.type):
            raise _invalid("parameter input has a different type")
        encoded = canonical_manifest(value)
        if parameter.enum and encoded not in parameter.enum:
            raise _invalid("parameter input is outside its finite enum")
        for path in parameter.paths:
            container, key = _location(objects, _pointer(path))
            container[key] = json.loads(encoded)
    _builtin_values(template, objects)
    output = b"\n---\n".join(canonical_manifest(item) for item in objects)
    manifest_documents(output, source_path="resource-template")
    return output


def builtin_templates() -> tuple[ResourceTemplate, ...]:
    """Construct the six small packaged templates only on explicit catalog access."""
    name = {"type": "string", "required": True, "paths": ["/0/metadata/name"]}
    image = {
        "type": "string",
        "required": True,
        "paths": ["/0/spec/template/spec/containers/0/image"],
    }
    objects: dict[str, dict[str, Any]] = {
        "deployment": {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": ""},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app": ""}},
                "template": {
                    "metadata": {"labels": {"app": ""}},
                    "spec": {"containers": [{"name": "app", "image": ""}]},
                },
            },
        },
        "service": {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": ""},
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": ""},
                "ports": [{"protocol": "TCP", "port": 80, "targetPort": 80}],
            },
        },
        "configmap": {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": ""},
            "data": {},
        },
        "secret": {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": ""},
            "type": "Opaque",
            "stringData": {},
        },
        "job": {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": ""},
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "spec": {"restartPolicy": "Never", "containers": [{"name": "app", "image": ""}]}
                },
            },
        },
        "namespace": {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ""}},
    }
    result: list[ResourceTemplate] = []
    for identifier, resource in objects.items():
        parameters: dict[str, Any] = {"name": name}
        if identifier == "deployment":
            parameters["name"] = {
                **name,
                "paths": [
                    "/0/metadata/name",
                    "/0/spec/selector/matchLabels/app",
                    "/0/spec/template/metadata/labels/app",
                ],
            }
            parameters["replicas"] = {
                "type": "integer",
                "required": False,
                "default": 1,
                "paths": ["/0/spec/replicas"],
            }
        if identifier in {"deployment", "job"}:
            parameters["image"] = image
        if identifier == "service":
            parameters["selector"] = {
                "type": "string",
                "required": True,
                "paths": ["/0/spec/selector/app"],
            }
            for parameter, destination in (("port", "port"), ("target-port", "targetPort")):
                parameters[parameter] = {
                    "type": "integer",
                    "required": False,
                    "default": 80,
                    "paths": [f"/0/spec/ports/0/{destination}"],
                }
        if identifier in {"configmap", "secret"}:
            parameters["data"] = {
                "type": "string_map",
                "required": False,
                "default": {},
                "sensitive": True,
                "paths": ["/0/" + ("data" if identifier == "configmap" else "stringData")],
            }
        value = {
            "schema_version": 1,
            "kind": "ResourceTemplate",
            "id": identifier,
            "revision": 1,
            "title": resource["kind"],
            "parameters": parameters,
            "objects": [resource],
        }
        result.append(replace(parse_resource_template(canonical_manifest(value)), builtin=True))
    return tuple(result)
