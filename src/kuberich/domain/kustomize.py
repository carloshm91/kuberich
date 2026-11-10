"""Explicit local-only Kustomize dependency declarations and fixed renderer argv."""

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from kuberich.domain.editing import parse_manifest_documents
from kuberich.domain.manifests import MAX_MANIFEST_BYTES, MAX_MANIFEST_DEPTH
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

KUSTOMIZATION_NAMES = frozenset({"kustomization.yaml", "kustomization.yml", "Kustomization"})
_ALLOWED = frozenset(
    {
        "apiVersion",
        "kind",
        "metadata",
        "resources",
        "bases",
        "components",
        "patches",
        "patchesJson6902",
        "patchesStrategicMerge",
        "configMapGenerator",
        "secretGenerator",
        "configurations",
        "crds",
        "replacements",
        "openapi",
        "namespace",
        "namePrefix",
        "nameSuffix",
        "labels",
        "commonLabels",
        "commonAnnotations",
        "images",
        "replicas",
        "vars",
        "generatorOptions",
        "sortOptions",
        "buildMetadata",
        "nameReference",
        "varReference",
    }
)
_FORBIDDEN = frozenset(
    {
        "generators",
        "transformers",
        "validators",
        "helmCharts",
        "helmGlobals",
        "helmChartInflationGenerator",
    }
)


@dataclass(frozen=True, kw_only=True, slots=True)
class KustomizeReference:
    path: str
    role: Literal["resource", "component", "file"]


def _local_syntax(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 4096
        or value.startswith(("/", "~", "-"))
        or any(
            character in value for character in ("\\", ":", "@", "?", "#", "*", "[", "]", "{", "}")
        )
        or "//" in value
        or re.match(r"^[^/]+\.[A-Za-z]{2,}/", value)
    ):
        raise AppError(
            "Kustomize references must be ordinary local relative paths; remote sources are unsupported."
        )
    validate_argument(value)


def local_reference(parent: str, value: str) -> str:
    """Return a root-relative path; reject remote syntax before filesystem access."""
    _local_syntax(value)
    validate_argument(parent or ".")
    if parent.startswith("/") or ".." in parent.split("/") or "\\" in parent:
        raise AppError("Kustomize parent must remain within the selected root.")
    result = posixpath.normpath(posixpath.join(parent, value))
    if result == ".." or result.startswith("../") or len(result.split("/")) > MAX_MANIFEST_DEPTH:
        raise AppError("Kustomize dependency escapes the selected root or exceeds 32 levels.")
    return "" if result == "." else result


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AppError("Kustomization fields have an unsupported shape.")
    return value


def _sequence(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise AppError("Kustomization list fields must contain ordinary lists.")
    return value


def kustomize_references(data: bytes) -> tuple[KustomizeReference, ...]:
    values = parse_manifest_documents(data, max_bytes=MAX_MANIFEST_BYTES, max_documents=1)
    if len(values) != 1:
        raise AppError("Kustomization must contain exactly one mapping.")
    value = values[0]
    if value.get("apiVersion", "kustomize.config.k8s.io/v1beta1") not in {
        "kustomize.config.k8s.io/v1beta1",
        "kustomize.config.k8s.io/v1alpha1",
    } or value.get("kind", "Kustomization") not in {"Kustomization", "Component"}:
        raise AppError("Unsupported Kustomization or Component identity.")
    if _FORBIDDEN.intersection(value) or set(value) - _ALLOWED:
        raise AppError("Kustomize plugins, Helm and unsupported fields are disabled.")
    references: list[KustomizeReference] = []

    def add(path: Any, role: Literal["resource", "component", "file"]) -> None:
        # Syntax validation here; the containing directory supplies the real
        # root boundary during closure traversal (including ../../base).
        _local_syntax(path)
        references.append(KustomizeReference(path=path, role=role))

    for key, role in (
        ("resources", "resource"),
        ("bases", "resource"),
        ("components", "component"),
        ("configurations", "file"),
        ("crds", "file"),
    ):
        if key in value:
            for path in _sequence(value[key]):
                add(path, role)  # type: ignore[arg-type]
    if "patchesStrategicMerge" in value:
        for path in _sequence(value["patchesStrategicMerge"]):
            add(path, "file")
    for key in ("patches", "patchesJson6902", "replacements"):
        if key in value:
            for entry in _sequence(value[key]):
                mapping = _mapping(entry)
                if "path" in mapping:
                    add(mapping["path"], "file")
    for key in ("configMapGenerator", "secretGenerator"):
        if key in value:
            for entry in _sequence(value[key]):
                mapping = _mapping(entry)
                if set(mapping) - {
                    "name",
                    "namespace",
                    "behavior",
                    "files",
                    "envs",
                    "literals",
                    "options",
                    "type",
                }:
                    raise AppError("Unsupported Kustomize generator fields.")
                for field in ("files", "envs"):
                    if field in mapping:
                        for path in _sequence(mapping[field]):
                            if not isinstance(path, str):
                                raise AppError("Kustomize generator paths must be text.")
                            add(path.split("=", 1)[-1] if field == "files" else path, "file")
    if "openapi" in value:
        mapping = _mapping(value["openapi"])
        if set(mapping) - {"path", "version"}:
            raise AppError("Unsupported Kustomize OpenAPI fields.")
        if "path" in mapping:
            add(mapping["path"], "file")
    for key in ("namespace", "namePrefix", "nameSuffix"):
        if key in value and not isinstance(value[key], str):
            raise AppError("Kustomization naming fields must be text.")
    return tuple(references)


def kustomize_argv(executable: str, target: Path, kubeconfig: Path, cache: Path) -> tuple[str, ...]:
    if any(not path.is_absolute() for path in (Path(executable), target, kubeconfig, cache)):
        raise AppError("Kustomize requires captured absolute executable and staging paths.")
    for value in (executable, str(target), str(kubeconfig), str(cache)):
        validate_argument(value)
    return (
        executable,
        f"--kubeconfig={kubeconfig}",
        f"--cache-dir={cache}",
        "kustomize",
        str(target),
        "--load-restrictor=LoadRestrictionsRootOnly",
        "--enable-alpha-plugins=false",
        "--enable-helm=false",
        "--network=false",
    )
