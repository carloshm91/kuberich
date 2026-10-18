"""A deliberate local metadata-selector subset; no credentials or arbitrary JSON paths."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from kuberich.errors import AppError

_KEY = r"[A-Za-z0-9_.\-/]+"
_VALUE = r"[A-Za-z0-9_.\-/]*"
_FIELDS = frozenset(
    {
        "metadata.name",
        "metadata.namespace",
        "status.phase",
        "spec.nodeName",
        "spec.unschedulable",
        "spec.schedulerName",
        "spec.hostNetwork",
        "status.successful",
    }
)


@dataclass(frozen=True)
class Selector:
    key: str
    operator: str
    values: tuple[str, ...]

    def matches(self, fields: Mapping[str, str]) -> bool:
        present = self.key in fields
        value = fields.get(self.key, "")
        if self.operator == "exists":
            return present
        if self.operator == "absent":
            return not present
        if self.operator in {"!=", "notin"}:
            return not present or value not in self.values
        return present and value in self.values


def selectors(text: str, *, field: bool = False) -> tuple[Selector, ...]:
    if not text or len(text) > 256:
        raise AppError("Selectors require 1-256 characters.")
    terms = re.split(r",(?![^()]*\))", text)
    if len(terms) > 8:
        raise AppError("Selectors support at most eight AND terms.")
    result = []
    for term in terms:
        match = re.fullmatch(
            rf"\s*({_KEY})\s+(in|notin)\s*\(({_VALUE}(?:\s*,\s*{_VALUE})*)\)\s*", term
        )
        if match and not field:
            key, operator, values = match.groups()
            item = Selector(key, operator, tuple(value.strip() for value in values.split(",")))
        else:
            match = re.fullmatch(rf"\s*({_KEY})\s*(==|=|!=)\s*({_VALUE})\s*", term)
            if match:
                key, operator, value = match.groups()
                item = Selector(key, operator, (value,))
            elif not field and re.fullmatch(rf"!?{_KEY}", term.strip()):
                key = term.strip()
                item = Selector(
                    key.removeprefix("!"), "absent" if key.startswith("!") else "exists", ()
                )
            else:
                raise AppError(
                    "Invalid local selector; use equality, labels in/notin or label existence."
                )
        if field and item.key not in _FIELDS:
            raise AppError("Unsupported local field; consult the navigation field allowlist.")
        result.append(item)
    return tuple(result)


def object_fields(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def metadata_fields(manifest: dict[str, object], resource: str) -> dict[str, str]:
    metadata = object_fields(manifest.get("metadata"))
    spec, status = object_fields(manifest.get("spec")), object_fields(manifest.get("status"))
    result = {
        "metadata." + key: value
        for key, value in metadata.items()
        if key in {"name", "namespace"} and isinstance(value, str)
    }
    if resource == "pods":
        for key in ("nodeName", "schedulerName", "hostNetwork"):
            value = spec.get(key, False if key == "hostNetwork" else "")
            result["spec." + key] = str(value).lower() if isinstance(value, bool) else str(value)
        result["status.phase"] = str(status.get("phase", ""))
    if resource == "nodes":
        result["spec.unschedulable"] = str(spec.get("unschedulable", False)).lower()
    if resource == "jobs":
        result["status.successful"] = str(status.get("succeeded", 0))
    return result


def unhealthy(manifest: dict[str, object], resource: str) -> bool | None:
    """Unknown is distinct from healthy. Historic failures do not override completion."""
    status = object_fields(manifest.get("status"))
    if resource == "pods":
        phase = status.get("phase")
        if phase == "Succeeded":
            return False
        if phase in {"Failed", "Pending", "Unknown"}:
            return True
    conditions = status.get("conditions")
    observed: list[bool] = []
    if isinstance(conditions, list):
        for raw in conditions:
            condition = object_fields(raw)
            kind, value = condition.get("type"), condition.get("status")
            if kind in {"Failed", "ReplicaFailure"} and value == "True":
                observed.append(True)
            if kind in {"Ready", "Available", "Complete"} and value in {"True", "False"}:
                observed.append(value == "False")
    return any(observed) if observed else None
