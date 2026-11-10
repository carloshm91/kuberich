"""Strict Helm CLI shape readers and literal, version-specific command plans."""

import json
import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.helm import (
    MAX_HELM_DEPTH,
    MAX_HELM_LIST_BYTES,
    MAX_HELM_NODES,
    MAX_HELM_OUTPUT_BYTES,
    MAX_HELM_RELEASES,
    MAX_HELM_REVISIONS,
    HelmDocumentKind,
    HelmDriver,
    HelmHistory,
    HelmHook,
    HelmList,
    HelmProblem,
    HelmRelease,
    HelmReleaseKey,
    HelmRevision,
    HelmRollbackIntent,
    HelmScope,
    HelmSettings,
    HelmStatus,
    HelmStorageIdentity,
    HelmVersion,
    helm_cell,
    helm_positive,
    helm_timestamp,
)
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument


def _invalid() -> HelmProblem:
    return HelmProblem("invalid-output", "Helm returned invalid or inconsistent structured output.")


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def helm_structure(value: object) -> None:
    """Bound every parser tree, including records that will be discarded."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > MAX_HELM_DEPTH or nodes > MAX_HELM_NODES:
            raise _invalid()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 4096:
                    raise _invalid()
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise _invalid()
        elif item is not None and not isinstance(item, (str, int, bool)):
            raise _invalid()


def helm_json(data: bytes, *, limit: int = MAX_HELM_OUTPUT_BYTES) -> object:
    """Read bounded JSON without duplicate keys, non-finite values or source errors."""
    if not isinstance(data, bytes) or len(data) > limit:
        raise HelmProblem(
            "output-limit", "Helm output exceeds the bounded structured-output limit."
        )
    try:
        value: object = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs)
        helm_structure(value)
        return value
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise _invalid() from None


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise _invalid()
    return cast(dict[str, object], value)


def _array(value: object, limit: int) -> list[object]:
    if not isinstance(value, list) or len(value) > limit:
        raise _invalid()
    return value


def _text(value: object, *, empty: bool = False, limit: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value):
        raise _invalid()
    # Metadata is safe to retain, but remote controls and credential-like text are not.
    return sanitize_text(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise _invalid()
    return helm_positive(value)


def _decimal(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", value):
        raise _invalid()
    return helm_positive(int(value))


def _date(value: object) -> str | None:
    if value is None or value == "" or value == "0001-01-01T00:00:00Z":
        return None
    return helm_timestamp(_text(value, limit=128))


def _present(value: object) -> bool:
    if value is not None and not isinstance(value, str):
        raise _invalid()
    return bool(value)


def helm_settings(environment: Mapping[str, str], executable: str = "helm") -> HelmSettings:
    value = environment.get("HELM_DRIVER", "")
    aliases = {
        "": HelmDriver.SECRET,
        "secret": HelmDriver.SECRET,
        "secrets": HelmDriver.SECRET,
        "configmap": HelmDriver.CONFIGMAP,
        "configmaps": HelmDriver.CONFIGMAP,
    }
    if value not in aliases:
        raise HelmProblem(
            "unsupported-driver", "Helm supports only the secret and configmap storage drivers."
        )
    return HelmSettings(executable, aliases[value])


def parse_helm_version(data: bytes) -> HelmVersion:
    if not isinstance(data, bytes) or len(data) > 16384:
        raise HelmProblem("output-limit", "Helm version output exceeds 16 KiB.")
    try:
        text = data.decode("utf-8").strip()
    except UnicodeError:
        raise _invalid() from None
    if text not in {"v3.22.1", "v4.3.1"}:
        raise HelmProblem("unsupported-version", "Supported Helm versions are v3.22.1 and v4.3.1.")
    return HelmVersion(text, int(text[1]))


def parse_helm_list(data: bytes, scope: HelmScope) -> HelmList:
    rows = _array(helm_json(data, limit=MAX_HELM_LIST_BYTES), MAX_HELM_RELEASES + 1)
    releases: list[HelmRelease] = []
    for raw in rows:
        row = _object(raw)
        key = HelmReleaseKey(_text(row.get("namespace")), _text(row.get("name")))
        if scope.namespace is not None and scope.namespace != key.namespace:
            raise _invalid()
        releases.append(
            HelmRelease(
                key,
                _decimal(row.get("revision")),
                _text(row.get("status")),
                _text(row.get("chart"), empty=True),
                _text(row.get("app_version"), empty=True),
                _text(row.get("updated"), empty=True),
            )
        )
    if len({release.key for release in releases}) != len(releases):
        raise _invalid()
    return HelmList(tuple(releases[:MAX_HELM_RELEASES]), len(rows) <= MAX_HELM_RELEASES)


def parse_helm_status(data: bytes, key: HelmReleaseKey, revision: int) -> HelmStatus:
    helm_positive(revision)
    value = _object(helm_json(data))
    actual = HelmReleaseKey(_text(value.get("namespace")), _text(value.get("name")))
    if actual != key or _integer(value.get("version")) != revision:
        raise _invalid()
    info = _object(value.get("info"))
    hooks: list[HelmHook] = []
    raw_hooks = value.get("hooks", [])
    if raw_hooks is None:
        raw_hooks = []
    for raw in _array(raw_hooks, 256):
        hook = _object(raw)
        events = tuple(_text(event, limit=64) for event in _array(hook.get("events", []), 32))
        hooks.append(
            HelmHook(_text(hook.get("name"), limit=253), _text(hook.get("kind"), limit=128), events)
        )
    return HelmStatus(
        key,
        revision,
        _text(info.get("status")),
        _date(info.get("first_deployed")),
        _date(info.get("last_deployed")),
        _present(info.get("notes")),
        _present(info.get("description")),
        tuple(hooks),
    )


def parse_helm_history(data: bytes) -> HelmHistory:
    rows = _array(helm_json(data, limit=MAX_HELM_LIST_BYTES), MAX_HELM_REVISIONS + 1)
    revisions: list[HelmRevision] = []
    for raw in rows:
        row = _object(raw)
        updated = row.get("updated")
        rollback = row.get("rollback_revision")
        revisions.append(
            HelmRevision(
                _integer(row.get("revision")),
                _text(row.get("status")),
                _text(row.get("chart"), empty=True),
                _text(row.get("app_version"), empty=True),
                _date(updated),
                _present(row.get("description")),
                None
                if rollback is None or (type(rollback) is int and rollback == 0)
                else _integer(rollback),
            )
        )
    if len({row.revision for row in revisions}) != len(revisions):
        raise _invalid()
    revisions.sort(key=lambda row: row.revision, reverse=True)
    return HelmHistory(tuple(revisions[:MAX_HELM_REVISIONS]), len(rows) <= MAX_HELM_REVISIONS)


def parse_storage_identity(
    data: Mapping[str, object], key: HelmReleaseKey, driver: HelmDriver, revision: int
) -> HelmStorageIdentity:
    helm_positive(revision)
    if (
        data.get("apiVersion") != "meta.k8s.io/v1"
        or data.get("kind") != "PartialObjectMetadata"
        or set(data) - {"apiVersion", "kind", "metadata"}
    ):
        raise _invalid()
    meta = _object(data.get("metadata"))
    labels = _object(meta.get("labels"))
    if (
        meta.get("namespace") != key.namespace
        or labels.get("owner") != "helm"
        or labels.get("name") != key.name
        or _decimal(labels.get("version")) != revision
    ):
        raise _invalid()
    try:
        return HelmStorageIdentity(
            key,
            driver,
            revision,
            helm_cell(cast(str, meta.get("name"))),
            helm_cell(cast(str, meta.get("uid"))),
            helm_cell(cast(str, meta.get("resourceVersion"))),
            helm_cell(cast(str, labels.get("status"))),
        )
    except AppError:
        raise _invalid() from None


def helm_environment(
    environment: Mapping[str, str], driver: HelmDriver, kubeconfig: Path | None = None
) -> tuple[tuple[str, str], ...]:
    if not isinstance(driver, HelmDriver):
        raise HelmProblem(
            "unsupported-driver", "Helm supports only the secret and configmap storage drivers."
        )
    removed = {
        "KUBECONFIG",
        "HELM_NAMESPACE",
        "HELM_DEBUG",
        "HELM_MAX_HISTORY",
        "HELM_DRIVER_SQL_CONNECTION_STRING",
    }
    result = {
        key: value
        for key, value in environment.items()
        if key not in removed and not key.startswith("HELM_KUBE")
    }
    result.update(HELM_DRIVER=driver.value, HELM_NO_PLUGINS="1", NO_COLOR="1")
    if kubeconfig is not None:
        result["KUBECONFIG"] = _kubeconfig(kubeconfig)
    return tuple(result.items())


def _kubeconfig(path: Path) -> str:
    if not isinstance(path, Path) or not path.is_absolute():
        raise HelmProblem(
            "unavailable", "Helm requires an explicit private absolute kubeconfig path."
        )
    return validate_argument(str(path))


def _scope(
    settings: HelmSettings,
    version: HelmVersion,
    scope: HelmScope,
    kubeconfig: Path,
    key: HelmReleaseKey | None = None,
) -> tuple[str, ...]:
    if not isinstance(version, HelmVersion) or settings.driver != scope.driver:
        raise HelmProblem("stale", "Helm command settings do not match the captured scope.")
    namespace = scope.namespace if key is None else key.namespace
    if key is not None and scope.namespace is not None and key.namespace != scope.namespace:
        raise HelmProblem("stale", "Helm release namespace does not match the captured scope.")
    return (
        settings.executable,
        f"--kubeconfig={_kubeconfig(kubeconfig)}",
        f"--kube-context={validate_argument(scope.session.context)}",
        f"--namespace={namespace or 'default'}",
        "--debug=false",
    )


def helm_version_argv(settings: HelmSettings) -> tuple[str, ...]:
    return (settings.executable, "version", "--template={{.Version}}")


def helm_list_argv(
    settings: HelmSettings, version: HelmVersion, scope: HelmScope, kubeconfig: Path
) -> tuple[str, ...]:
    prefix = _scope(settings, version, scope, kubeconfig)
    flags = ("--all",) if version.major == 3 else ()
    return (
        prefix
        + ("list",)
        + flags
        + ("--max=501", "--offset=0", "--output=json")
        + (("--all-namespaces",) if scope.namespace is None else ())
    )


def helm_status_argv(
    settings: HelmSettings,
    version: HelmVersion,
    scope: HelmScope,
    kubeconfig: Path,
    key: HelmReleaseKey,
    revision: int,
) -> tuple[str, ...]:
    helm_positive(revision)
    return (
        *_scope(settings, version, scope, kubeconfig, key),
        "status",
        key.name,
        f"--revision={revision}",
        "--output=json",
    )


def helm_history_argv(
    settings: HelmSettings,
    version: HelmVersion,
    scope: HelmScope,
    kubeconfig: Path,
    key: HelmReleaseKey,
) -> tuple[str, ...]:
    return (
        *_scope(settings, version, scope, kubeconfig, key),
        "history",
        key.name,
        "--max=201",
        "--output=json",
    )


def helm_document_argv(
    settings: HelmSettings,
    version: HelmVersion,
    scope: HelmScope,
    kubeconfig: Path,
    key: HelmReleaseKey,
    revision: int,
    kind: HelmDocumentKind,
) -> tuple[str, ...]:
    helm_positive(revision)
    if not isinstance(kind, HelmDocumentKind):
        raise _invalid()
    command = (
        "values" if kind in {HelmDocumentKind.VALUES, HelmDocumentKind.ALL_VALUES} else kind.value
    )
    flags: tuple[str, ...] = ("--output=json",) if command == "values" else ()
    if kind is HelmDocumentKind.ALL_VALUES:
        flags += ("--all",)
    return (
        *_scope(settings, version, scope, kubeconfig, key),
        "get",
        command,
        key.name,
        f"--revision={revision}",
        *flags,
    )


def helm_rollback_argv(
    settings: HelmSettings, version: HelmVersion, kubeconfig: Path, intent: HelmRollbackIntent
) -> tuple[str, ...]:
    scope = intent.target.request.scope
    prefix = _scope(settings, version, scope, kubeconfig, intent.selected.key)
    options = intent.options
    waiting = (
        str(options.wait).lower()
        if version.major == 3
        else "legacy"
        if options.wait
        else "hookOnly"
    )
    flags: tuple[str, ...] = (
        f"--no-hooks={str(not options.run_hooks).lower()}",
        f"--timeout={options.timeout_seconds}s",
        "--history-max=0",
        f"--wait-for-jobs={str(options.wait).lower()}",
        f"--wait={waiting}",
    )
    if version.major == 4:
        flags += ("--server-side=auto",)
    return (
        *prefix,
        "rollback",
        intent.selected.key.name,
        str(intent.selected.revision),
        *flags,
    )
