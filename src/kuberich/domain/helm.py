"""Immutable Helm observations and storage-bound, reviewed operation identities."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from kuberich.domain.targets import SessionIdentity
from kuberich.errors import AppError
from kuberich.security.arguments import validate_argument
from kuberich.security.controls import escape_controls

MAX_HELM_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_HELM_LIST_BYTES = 2 * 1024 * 1024
MAX_HELM_RENDER_BYTES = 256 * 1024
MAX_HELM_RELEASES = 500
MAX_HELM_REVISIONS = 200
MAX_HELM_NODES = 50_000
MAX_HELM_DEPTH = 64
MAX_HELM_DOCUMENTS = 256
SUPPORTED_HELM_VERSIONS = {"v3.22.1": 3, "v4.3.1": 4}
type HelmProblemKind = Literal[
    "missing-tool",
    "unsupported-version",
    "unsupported-driver",
    "forbidden",
    "authentication",
    "missing-release",
    "invalid-output",
    "output-limit",
    "timeout",
    "stale",
    "unavailable",
]
_PROBLEM_KINDS = frozenset(
    {
        "missing-tool",
        "unsupported-version",
        "unsupported-driver",
        "forbidden",
        "authentication",
        "missing-release",
        "invalid-output",
        "output-limit",
        "timeout",
        "stale",
        "unavailable",
    }
)


class HelmProblem(AppError):
    """An application-authored feature error; raw command output is never retained."""

    def __init__(self, kind: HelmProblemKind, message: str) -> None:
        if kind not in _PROBLEM_KINDS:
            raise AppError("Unknown Helm problem category.")
        helm_cell(message, limit=4096)
        self.kind = kind
        super().__init__(message)


class HelmDriver(StrEnum):
    SECRET = "secret"
    CONFIGMAP = "configmap"


class HelmDocumentKind(StrEnum):
    NOTES = "notes"
    VALUES = "values"
    ALL_VALUES = "all-values"
    MANIFEST = "manifest"


def helm_positive(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 2_147_483_647:
        raise HelmProblem("invalid-output", "Helm revisions must be positive bounded integers.")
    return value


def helm_cell(value: str, *, limit: int = 4096, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or (not empty and not value)
        or escape_controls(value) != value
    ):
        # Do not use HelmProblem here: its message is validated through this helper.
        raise AppError("Helm metadata must be bounded text without terminal controls.")
    return value


def helm_timestamp(value: str | None) -> str | None:
    if value is not None:
        helm_cell(value, limit=128)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
        except ValueError:
            raise HelmProblem(
                "invalid-output", "Helm timestamps require an explicit timezone."
            ) from None
    return value


def _boolean(value: bool) -> None:
    if type(value) is not bool:
        raise HelmProblem("invalid-output", "Helm flags must be true or false.")


def _record(value: object, kind: type[object]) -> None:
    if not isinstance(value, kind):
        raise HelmProblem("invalid-output", "Helm observation contains an invalid nested record.")


def _records(values: tuple[object, ...], kind: type[object], limit: int) -> None:
    if not isinstance(values, tuple) or len(values) > limit:
        raise HelmProblem("invalid-output", "Helm observation exceeds its record limit.")
    for value in values:
        _record(value, kind)


def _status(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise HelmProblem("invalid-output", "Helm status must be a bounded literal state.")


@dataclass(frozen=True, slots=True)
class HelmSettings:
    executable: str = "helm"
    driver: HelmDriver = HelmDriver.SECRET

    def __post_init__(self) -> None:
        validate_argument(self.executable)
        if self.executable.startswith("-") or (
            "/" not in self.executable and any(c.isspace() for c in self.executable)
        ):
            raise HelmProblem("missing-tool", "Helm requires a literal executable name or path.")
        _record(self.driver, HelmDriver)


@dataclass(frozen=True, slots=True)
class HelmVersion:
    text: str
    major: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.text, str)
            or type(self.major) is not int
            or SUPPORTED_HELM_VERSIONS.get(self.text) != self.major
        ):
            raise HelmProblem(
                "unsupported-version", "Supported Helm versions are v3.22.1 and v4.3.1."
            )


@dataclass(frozen=True, slots=True)
class HelmScope:
    session: SessionIdentity
    namespace: str | None
    driver: HelmDriver

    def __post_init__(self) -> None:
        _record(self.session, SessionIdentity)
        _record(self.driver, HelmDriver)
        if self.namespace is not None:
            HelmReleaseKey(self.namespace, "scope")


@dataclass(frozen=True, slots=True)
class HelmRequest:
    scope: HelmScope
    generation: int

    def __post_init__(self) -> None:
        _record(self.scope, HelmScope)
        if type(self.generation) is not int or self.generation < 0:
            raise HelmProblem("invalid-output", "Helm request generation must be nonnegative.")


@dataclass(frozen=True, slots=True)
class HelmReleaseKey:
    namespace: str
    name: str

    def __post_init__(self) -> None:
        label = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
        for value, limit, pattern in (
            (self.namespace, 63, label),
            (self.name, 53, label + r"(?:\." + label + ")*"),
        ):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= limit
                or not re.fullmatch(pattern, value)
            ):
                raise HelmProblem(
                    "invalid-output",
                    "Helm release name or namespace is not a valid bounded identifier.",
                )


@dataclass(frozen=True, slots=True)
class HelmRelease:
    key: HelmReleaseKey
    revision: int
    status: str
    chart: str
    app_version: str
    updated: str

    def __post_init__(self) -> None:
        _record(self.key, HelmReleaseKey)
        helm_positive(self.revision)
        _status(self.status)
        for value in (self.chart, self.app_version, self.updated):
            helm_cell(value, empty=True)


@dataclass(frozen=True, slots=True)
class HelmList:
    releases: tuple[HelmRelease, ...]
    complete: bool

    def __post_init__(self) -> None:
        _records(self.releases, HelmRelease, MAX_HELM_RELEASES)
        _boolean(self.complete)
        if len({item.key for item in self.releases}) != len(self.releases):
            raise HelmProblem("invalid-output", "Helm list contains duplicate release identities.")


@dataclass(frozen=True, slots=True)
class HelmStorageIdentity:
    key: HelmReleaseKey
    driver: HelmDriver
    revision: int
    storage_name: str
    uid: str
    resource_version: str
    status: str

    def __post_init__(self) -> None:
        _record(self.key, HelmReleaseKey)
        _record(self.driver, HelmDriver)
        helm_positive(self.revision)
        if self.storage_name != f"sh.helm.release.v1.{self.key.name}.v{self.revision}":
            raise HelmProblem(
                "invalid-output", "Helm storage name does not match the selected revision."
            )
        helm_cell(self.uid)
        helm_cell(self.resource_version)
        _status(self.status)


@dataclass(frozen=True, slots=True)
class HelmTarget:
    request: HelmRequest
    head: HelmStorageIdentity

    def __post_init__(self) -> None:
        _record(self.request, HelmRequest)
        _record(self.head, HelmStorageIdentity)
        scope = self.request.scope
        if scope.driver != self.head.driver or (
            scope.namespace is not None and scope.namespace != self.head.key.namespace
        ):
            raise HelmProblem("stale", "Helm storage identity does not match the captured scope.")


@dataclass(frozen=True, slots=True)
class HelmRevision:
    revision: int
    status: str
    chart: str
    app_version: str
    updated: str | None
    description_present: bool
    rollback_revision: int | None

    def __post_init__(self) -> None:
        helm_positive(self.revision)
        _status(self.status)
        for value in (self.chart, self.app_version):
            helm_cell(value, empty=True)
        if self.updated is not None:
            helm_cell(self.updated)
        _boolean(self.description_present)
        if self.rollback_revision is not None:
            helm_positive(self.rollback_revision)


@dataclass(frozen=True, slots=True)
class HelmHistory:
    revisions: tuple[HelmRevision, ...]
    complete: bool

    def __post_init__(self) -> None:
        _records(self.revisions, HelmRevision, MAX_HELM_REVISIONS)
        _boolean(self.complete)
        if len({item.revision for item in self.revisions}) != len(self.revisions):
            raise HelmProblem("invalid-output", "Helm history contains duplicate revisions.")


@dataclass(frozen=True, slots=True)
class HelmHook:
    name: str
    kind: str
    events: tuple[str, ...]

    def __post_init__(self) -> None:
        helm_cell(self.name, limit=253)
        helm_cell(self.kind, limit=128)
        if not isinstance(self.events, tuple) or len(self.events) > 32:
            raise HelmProblem("invalid-output", "Helm hook events exceed their metadata limit.")
        for event in self.events:
            helm_cell(event, limit=64)


@dataclass(frozen=True, slots=True)
class HelmStatus:
    key: HelmReleaseKey
    revision: int
    status: str
    first_deployed: str | None
    last_deployed: str | None
    notes_present: bool
    description_present: bool
    hooks: tuple[HelmHook, ...]

    def __post_init__(self) -> None:
        _record(self.key, HelmReleaseKey)
        helm_positive(self.revision)
        _status(self.status)
        helm_timestamp(self.first_deployed)
        helm_timestamp(self.last_deployed)
        _boolean(self.notes_present)
        _boolean(self.description_present)
        _records(self.hooks, HelmHook, 256)


@dataclass(frozen=True, slots=True)
class HelmInspection:
    target: HelmTarget
    release: HelmRelease
    status: HelmStatus
    history: HelmHistory

    def __post_init__(self) -> None:
        for value, kind in (
            (self.target, HelmTarget),
            (self.release, HelmRelease),
            (self.status, HelmStatus),
            (self.history, HelmHistory),
        ):
            _record(value, kind)
        if (
            self.release.key != self.target.head.key
            or self.status.key != self.release.key
            or self.status.revision != self.release.revision
            or self.release.revision != self.target.head.revision
            or self.status.status != self.target.head.status
            or self.release.status != self.status.status
        ):
            raise HelmProblem("stale", "Helm inspection no longer matches the captured release.")


@dataclass(frozen=True, slots=True, repr=False)
class HelmDocument:
    target: HelmTarget
    revision: int
    kind: HelmDocumentKind
    text: str
    disclosed: bool

    def __post_init__(self) -> None:
        _record(self.target, HelmTarget)
        helm_positive(self.revision)
        _record(self.kind, HelmDocumentKind)
        _boolean(self.disclosed)
        if (
            not isinstance(self.text, str)
            or len(self.text.encode("utf-8", errors="surrogatepass")) > MAX_HELM_RENDER_BYTES
            or escape_controls(self.text, allow_newlines=True) != self.text
        ):
            raise HelmProblem(
                "invalid-output", "Helm document exceeds its safe rendered-text limit."
            )


@dataclass(frozen=True, slots=True)
class HelmRollbackOptions:
    run_hooks: bool = False
    wait: bool = True
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        _boolean(self.run_hooks)
        _boolean(self.wait)
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 600:
            raise HelmProblem(
                "invalid-output", "Helm rollback timeout must be between 1 and 600 seconds."
            )


def _selected(target: HelmTarget, selected: HelmStorageIdentity) -> None:
    _record(target, HelmTarget)
    _record(selected, HelmStorageIdentity)
    if (
        selected.key != target.head.key
        or selected.driver != target.head.driver
        or selected.revision > target.head.revision
    ):
        raise HelmProblem("stale", "Helm selected revision does not match the captured release.")


@dataclass(frozen=True, slots=True)
class HelmDisclosureIntent:
    identity: UUID
    target: HelmTarget
    selected: HelmStorageIdentity
    kind: HelmDocumentKind

    def __post_init__(self) -> None:
        _record(self.identity, UUID)
        _selected(self.target, self.selected)
        _record(self.kind, HelmDocumentKind)


@dataclass(frozen=True, slots=True)
class HelmRollbackIntent:
    identity: UUID
    target: HelmTarget
    selected: HelmStorageIdentity
    options: HelmRollbackOptions
    hooks: tuple[HelmHook, ...]

    def __post_init__(self) -> None:
        _record(self.identity, UUID)
        _selected(self.target, self.selected)
        _record(self.options, HelmRollbackOptions)
        _records(self.hooks, HelmHook, 256)
        if (
            self.selected.revision >= self.target.head.revision
            or self.target.head.status not in {"deployed", "failed"}
            or self.selected.status not in {"deployed", "superseded"}
        ):
            raise HelmProblem(
                "stale",
                "Helm rollback requires an eligible current release and a positive prior revision.",
            )

    @property
    def effects(self) -> tuple[str, ...]:
        return (
            "Helm may update chart resources and create a new release revision.",
            "Rollback hooks will run."
            if self.options.run_hooks
            else "Rollback hooks are disabled.",
            "Wait for resources and Jobs."
            if self.options.wait
            else "Do not wait for ordinary resource readiness.",
            f"Per-operation timeout: {self.options.timeout_seconds} seconds; whole-command deadline is separate.",
            "Release history is retained without automatic pruning.",
            "Revalidation is not atomic compare-and-swap; concurrent changes and partial effects remain possible.",
        )


@dataclass(frozen=True, slots=True, repr=False)
class HelmApproval:
    intent: UUID
    token: UUID

    def __post_init__(self) -> None:
        _record(self.intent, UUID)
        _record(self.token, UUID)


class HelmOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"
    STALE = "stale"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class HelmRollbackResult:
    outcome: HelmOutcome
    message: str
    observed: HelmRelease | None
    may_have_started: bool

    def __post_init__(self) -> None:
        _record(self.outcome, HelmOutcome)
        helm_cell(self.message)
        if self.observed is not None:
            _record(self.observed, HelmRelease)
        _boolean(self.may_have_started)


@dataclass(frozen=True, slots=True)
class HelmSnapshot:
    request: HelmRequest
    listing: HelmList | None
    collecting: bool
    problem: HelmProblem | None

    def __post_init__(self) -> None:
        _record(self.request, HelmRequest)
        if self.listing is not None:
            _record(self.listing, HelmList)
        _boolean(self.collecting)
        if self.problem is not None:
            _record(self.problem, HelmProblem)
