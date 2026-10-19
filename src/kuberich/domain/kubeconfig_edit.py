"""Plan explicit kubeconfig context rename/delete edits without touching credentials."""

import copy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument

MAX_CONTEXT_NAME = 253


class ContextChange(Enum):
    RENAME = "Rename"
    DELETE = "Delete"


@dataclass(frozen=True, repr=False)
class KubeconfigDocument:
    """One parsed kubeconfig file, in KUBECONFIG order, with its reviewed digest."""

    path: Path
    data: dict[str, Any]
    digest: str
    commented: bool = False


@dataclass(frozen=True, repr=False)
class ContextEditPlan:
    change: ContextChange
    name: str
    new_name: str | None
    path: Path
    digest: str
    document: dict[str, Any]
    renames_current: bool = False
    clears_current: bool = False
    commented: bool = False

    @property
    def confirmation(self) -> str | None:
        """Text the user must type before a deletion; renames need only Confirm."""
        if self.change is ContextChange.RENAME:
            return None
        return "DELETE CURRENT" if self.clears_current else "DELETE"

    @property
    def summary(self) -> tuple[str, ...]:
        lines = [f"File: {self.path}"]
        if self.change is ContextChange.RENAME:
            lines.append(f"Rename context: {self.name} → {self.new_name}")
        else:
            lines.append(f"Delete context: {self.name}")
        lines.append("Clusters and users stay unchanged.")
        if self.renames_current:
            lines.append("This is the current-context in that file; it is renamed too.")
        if self.clears_current:
            lines.append("This is the current-context in that file; it will be cleared.")
        if self.commented:
            lines.append("Comments and custom formatting in this file are not kept.")
        lines.append("A backup copy is saved next to the file first.")
        return tuple(lines)


def context_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_CONTEXT_NAME
        or value != value.strip()
    ):
        raise AppError("Context names need 1-253 characters without leading or trailing spaces.")
    return validate_argument(value)


def _entries(data: dict[str, Any]) -> list[Any]:
    entries = data.get("contexts")
    if entries is None:
        return []
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict) or not isinstance(entry.get("name"), str) for entry in entries
    ):
        raise AppError("Kubeconfig contexts must be a list of named entries.")
    return entries


def _names(document: KubeconfigDocument) -> list[str]:
    return [entry["name"] for entry in _entries(document.data)]


def plan_context_edit(
    documents: tuple[KubeconfigDocument, ...],
    change: ContextChange,
    name: str,
    new_name: str | None = None,
    *,
    connected: str | None = None,
) -> ContextEditPlan:
    """Edit exactly one owning file; refuse anything ambiguous instead of guessing."""
    if not isinstance(change, ContextChange):
        raise AppError("Choose rename or delete.")
    name = context_name(name)
    owners = [document for document in documents if name in _names(document)]
    if not owners:
        raise AppError("This context is not defined in the loaded kubeconfig files.")
    if len(owners) > 1:
        raise AppError(
            "This context is defined in more than one kubeconfig file. Edit it manually."
        )
    owner = owners[0]
    effective = next((d for d in documents if d.data.get("current-context")), None)
    if (
        effective is not None
        and effective is not owner
        and effective.data.get("current-context") == name
    ):
        raise AppError(
            "Another kubeconfig file sets this context as current-context. Edit it manually."
        )
    data = copy.deepcopy(owner.data)
    entries = _entries(data)
    index = [entry["name"] for entry in entries].index(name)
    owns_current = owner.data.get("current-context") == name
    if change is ContextChange.RENAME:
        target = context_name(new_name)
        if target == name:
            raise AppError("Choose a different name.")
        if any(target in _names(document) for document in documents):
            raise AppError("Another context already uses this name.")
        entries[index]["name"] = target
        if owns_current:
            data["current-context"] = target
        return ContextEditPlan(
            change,
            name,
            target,
            owner.path,
            owner.digest,
            data,
            renames_current=owns_current,
            commented=owner.commented,
        )
    if new_name is not None:
        raise AppError("Deletion does not take a new name.")
    if connected == name:
        raise AppError("Switch to another context before deleting the connected one.")
    del entries[index]
    if owns_current:
        del data["current-context"]
    return ContextEditPlan(
        change,
        name,
        None,
        owner.path,
        owner.digest,
        data,
        clears_current=owns_current,
        commented=owner.commented,
    )
