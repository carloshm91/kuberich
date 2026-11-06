"""Pure ordered environment provenance and fresh selected-value resolution.

Raw declarations and resolved text exist only in short-lived repr-suppressed
work records. Public snapshots carry no literal expression or decoded value.
"""

import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Any, cast
from uuid import UUID

from kuberich.domain.configuration_data import DataKey, configuration_index, configuration_value
from kuberich.domain.container_inspection import (
    MAX_DEPENDENCY_EDGES,
    MAX_ENV_ROWS,
    MAX_INPUT_BYTES,
    MAX_METADATA_BYTES,
    MAX_METADATA_CELL,
    MAX_READS,
    MAX_REFERENCES,
    MAX_RESOLUTION_BYTES,
    ContainerIdentity,
    Dependency,
    EntryId,
    EnvEntry,
    EnvOrigin,
    ImageFacts,
    InspectionSnapshot,
    PrecedenceState,
    ReasonCode,
    ResolvedValue,
    ResourceSelector,
    SourceObservation,
    SourceRead,
    SourceRef,
    SourceState,
    SourceUse,
    container_declaration,
    metadata_table,
    object_binding,
)
from kuberich.domain.resources import ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError

_SOURCE_REASONS = {
    "not-found": ReasonCode.SOURCE_NOT_FOUND,
    "forbidden": ReasonCode.SOURCE_FORBIDDEN,
    "timed-out": ReasonCode.SOURCE_TIMED_OUT,
    "unreachable": ReasonCode.SOURCE_UNREACHABLE,
    "invalid": ReasonCode.SOURCE_INVALID,
    "unsupported": ReasonCode.SOURCE_UNSUPPORTED,
    "not-collected-limit": ReasonCode.REFERENCE_LIMIT,
}
_LIMIT_REASONS = frozenset(
    {
        ReasonCode.REFERENCE_LIMIT,
        ReasonCode.ROW_LIMIT,
        ReasonCode.INPUT_LIMIT,
        ReasonCode.METADATA_LIMIT,
        ReasonCode.DEPENDENCY_LIMIT,
        ReasonCode.READ_LIMIT,
    }
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _array(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _declarations(declaration: dict[str, Any], family: str) -> list[Any]:
    value = declaration.get(family)
    if value is None:
        return []
    return value if isinstance(value, list) else [None]


def _bounded(value: Any) -> str | None:
    return value if isinstance(value, str) and len(value) <= MAX_METADATA_CELL else None


def _name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_METADATA_CELL
        and all(32 <= ord(char) <= 126 and char != "=" for char in value)
    )


def _ref(raw: dict[str, Any], namespace: str) -> SourceRef | None:
    pairs = [
        (kind, raw[key])
        for key, kind in (
            ("configMapRef", "ConfigMap"),
            ("secretRef", "Secret"),
            ("configMapKeyRef", "ConfigMap"),
            ("secretKeyRef", "Secret"),
        )
        if key in raw
    ]
    if len(pairs) != 1:
        return None
    kind, selector = pairs[0]
    name = _mapping(selector).get("name")
    if not isinstance(name, str) or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", name
    ):
        return None
    return SourceRef(cast("Any", kind), namespace, name)


def _selector(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("configMapRef", "secretRef", "configMapKeyRef", "secretKeyRef"):
        if key in raw:
            return _mapping(raw[key])
    return {}


def collect_references(
    pod: ResourceRecord, container: ContainerIdentity
) -> tuple[dict[SourceRef, list[SourceUse]], dict[str, Any]]:
    object_binding(pod, kind="Pod")
    declaration = container_declaration(pod.manifest, container)
    refs: dict[SourceRef, list[SourceUse]] = {}
    for family in ("envFrom", "env"):
        for ordinal, value in enumerate(_declarations(declaration, family)):
            raw = _mapping(value)
            source = raw if family == "envFrom" else _mapping(raw.get("valueFrom"))
            ref = _ref(source, pod.namespace or "")
            if ref is not None:
                selector = _selector(source)
                prefix = _bounded(raw.get("prefix", "")) if family == "envFrom" else ""
                key = _bounded(selector.get("key")) if family == "env" else None
                refs.setdefault(ref, []).append(
                    SourceUse(
                        f"spec.{container.field}[{container.name}].{family}[{ordinal}]",
                        selector.get("optional") is True,
                        prefix or "",
                        key,
                    )
                )
    return refs, declaration


def _observe(
    refs: dict[SourceRef, list[SourceUse]], sources: tuple[SourceRead, ...], observed_at: datetime
) -> tuple[tuple[SourceObservation, ...], dict[SourceRef, ResourceRecord], list[ReasonCode]]:
    supplied = {source.ref: source for source in sources}
    records = {}
    observations = []
    notices = []
    for ordinal, (ref, uses) in enumerate(refs.items()):
        read = supplied.get(ref)
        state: SourceState = (
            "not-collected-limit"
            if ordinal >= MAX_REFERENCES
            else read.state
            if read is not None
            else "unreachable"
        )
        binding = None
        keys: tuple[DataKey, ...] = ()
        if state == "available":
            try:
                if read is None or read.record is None:
                    raise AppError("Missing container inspection source.")
                binding = object_binding(read.record, kind=ref.kind)
                if (binding.namespace, binding.name) != (ref.namespace, ref.name):
                    raise AppError("Container inspection source identity changed.")
                if ref.kind == "Secret" and "stringData" in read.record.manifest:
                    state = "unsupported"
                else:
                    keys = configuration_index(read.record).keys
                    records[ref] = read.record
            except AppError:
                state = "invalid"
                binding = None
        if state != "available":
            notices.append(_SOURCE_REASONS[state])
        observations.append(
            SourceObservation(
                ref,
                state,
                binding,
                keys,
                read.observed_at if read is not None else observed_at,
                tuple(uses),
            )
        )
    return tuple(observations), records, notices


def _tokens(value: str) -> list[tuple[bool, str]]:
    """Kubernetes one-pass $()/$$ grammar, independently implemented."""
    result = []
    position = 0
    literal = []
    while position < len(value):
        char = value[position]
        if char == "$" and position + 1 < len(value):
            following = value[position + 1]
            if following == "$":
                literal.append("$")
                position += 2
                continue
            if following == "(":
                end = value.find(")", position + 2)
                if end != -1:
                    result.append((False, "".join(literal)))
                    literal = []
                    result.append((True, value[position + 2 : end]))
                    position = end + 1
                    continue
        literal.append(char)
        position += 1
    result.append((False, "".join(literal)))
    return result


@dataclass(frozen=True, slots=True)
class _Draft:
    entry: EnvEntry
    raw: dict[str, Any] = field(repr=False)


def _base(
    entry_id: EntryId,
    name: str,
    path: str,
    origin: EnvOrigin,
    *,
    source: SourceRef | None = None,
    key: str | None = None,
    prefix: str = "",
    optional: bool = False,
    reason: ReasonCode | None = None,
) -> EnvEntry:
    return EnvEntry(
        entry_id,
        name,
        path,
        origin,
        source,
        key,
        prefix,
        optional,
        None,
        None,
        (),
        "unknown" if reason else "effective",
        "unresolved" if reason else "text-resolvable-hidden",
        reason,
    )


def _field_value(data: dict[str, Any], raw: dict[str, Any]) -> ResolvedValue:
    if set(raw) - {"apiVersion", "fieldPath"} or raw.get("apiVersion", "v1") != "v1":
        return ResolvedValue(None, False, (ReasonCode.UNSUPPORTED_FIELD,))
    path = raw.get("fieldPath")
    if path in ("status.podIP", "status.podIPs", "status.hostIP", "status.hostIPs"):
        return ResolvedValue(None, False, (ReasonCode.RUNTIME_FIELD,))
    fixed = {
        "metadata.name": ("metadata", "name"),
        "metadata.namespace": ("metadata", "namespace"),
        "metadata.uid": ("metadata", "uid"),
        "spec.nodeName": ("spec", "nodeName"),
        "spec.serviceAccountName": ("spec", "serviceAccountName"),
    }
    if isinstance(path, str) and path in fixed:
        section, key = fixed[path]
        value = _mapping(data.get(section)).get(key)
    else:
        match = (
            re.fullmatch(r"metadata\.(labels|annotations)\['([^'\r\n]+)'\]", path)
            if isinstance(path, str)
            else None
        )
        if match is None:
            return ResolvedValue(None, False, (ReasonCode.UNSUPPORTED_FIELD,))
        value = _mapping(_mapping(data.get("metadata")).get(match[1])).get(match[2])
    return (
        ResolvedValue(value, True, ())
        if isinstance(value, str)
        else ResolvedValue(None, False, (ReasonCode.MISSING_FIELD,))
    )


def _quantity(value: Any, scale: int) -> int | ReasonCode:
    if not isinstance(value, str) or len(value) > 128:
        return ReasonCode.INVALID_QUANTITY
    match = re.fullmatch(
        r"([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))([eE][+-]?[0-9]+|[numkMGTPE]|[KMGTPE]i)?", value
    )
    if match is None:
        return ReasonCode.INVALID_QUANTITY
    suffix = match[2] or ""
    powers = {"n": -9, "u": -6, "m": -3, "k": 3, "M": 6, "G": 9, "T": 12, "P": 15, "E": 18}
    with localcontext() as context:
        context.prec = 512
        exponent = int(suffix[1:]) if suffix.startswith(("e", "E")) and len(suffix) > 1 else 0
        if abs(exponent) > 100:
            return ReasonCode.QUANTITY_LIMIT
        multiplier = (
            Decimal(2) ** (10 * ("KMGTPE".index(suffix[0]) + 1))
            if suffix.endswith("i")
            else Decimal(10) ** powers.get(suffix, exponent)
        )
        number = Decimal(match[1]) * multiplier * scale
        if number < 0:
            return ReasonCode.INVALID_QUANTITY
        rounded = int(number.to_integral_value(rounding=ROUND_CEILING))
    return rounded if rounded <= 2**53 else ReasonCode.QUANTITY_LIMIT


def _resource_value(
    data: dict[str, Any], container: ContainerIdentity, raw: dict[str, Any]
) -> ResolvedValue:
    resource, divisor, name = raw.get("resource"), raw.get("divisor", "1"), raw.get("containerName")
    if (
        set(raw) - {"resource", "divisor", "containerName"}
        or not isinstance(resource, str)
        or resource
        not in {
            f"{family}.{kind}"
            for family in ("requests", "limits")
            for kind in ("cpu", "memory", "ephemeral-storage")
        }
    ):
        return ResolvedValue(None, False, (ReasonCode.UNSUPPORTED_RESOURCE,))
    target = container_declaration(data, container)
    if name is not None:
        matches = [
            item
            for family in ("containers", "initContainers")
            for item in _array(_mapping(data.get("spec")).get(family))
            if isinstance(item, dict) and item.get("name") == name
        ]
        if len(matches) != 1:
            return ResolvedValue(None, False, (ReasonCode.MISSING_CONTAINER,))
        target = matches[0]
    family, kind = resource.split(".")
    value = _mapping(_mapping(target.get("resources")).get(family)).get(kind)
    scale = 1000 if kind == "cpu" else 1
    denominator = _quantity(divisor, scale)
    if isinstance(denominator, ReasonCode) or denominator == 0:
        return ResolvedValue(
            None,
            False,
            (denominator if isinstance(denominator, ReasonCode) else ReasonCode.INVALID_QUANTITY,),
        )
    if value is None:
        return ResolvedValue(
            None,
            False,
            (ReasonCode.NODE_DEPENDENT if family == "limits" else ReasonCode.MISSING_RESOURCE,),
        )
    numerator = _quantity(value, scale)
    if isinstance(numerator, ReasonCode):
        return ResolvedValue(None, False, (numerator,))
    if family == "limits" and numerator == 0:
        return ResolvedValue(None, False, (ReasonCode.NODE_DEPENDENT,))
    return ResolvedValue(str(math.ceil(float(numerator) / float(denominator))), True, ())


def _drafts(
    data: dict[str, Any],
    container: ContainerIdentity,
    declaration: dict[str, Any],
    observations: tuple[SourceObservation, ...],
) -> tuple[list[_Draft], list[ReasonCode]]:
    observed = {source.ref: source for source in observations}
    drafts: list[_Draft] = []
    bindings: dict[str, int] = {}
    barriers: list[tuple[str, int]] = []
    notices: list[ReasonCode] = []
    edges = 0
    reason: ReasonCode | None

    def add(
        entry: EnvEntry, raw: dict[str, Any], *, skip: bool = False, barrier: bool = False
    ) -> None:
        if len(drafts) >= MAX_ENV_ROWS:
            notices.append(ReasonCode.ROW_LIMIT)
            return
        index = len(drafts)
        if barrier:
            barriers.append((entry.prefix, index))
        elif not skip:
            bindings[entry.name] = index
        drafts.append(_Draft(entry, raw))

    for ordinal, value in enumerate(_declarations(declaration, "envFrom")):
        raw = _mapping(value)
        ref = _ref(raw, str(_mapping(data.get("metadata")).get("namespace", "")))
        selector = _selector(raw)
        prefix = _bounded(raw.get("prefix", ""))
        optional = selector.get("optional") is True
        path = f"spec.{container.field}[{container.name}].envFrom[{ordinal}]"
        observation = observed.get(ref) if ref else None
        origin: EnvOrigin = (
            "env-from-secret" if ref and ref.kind == "Secret" else "env-from-configmap"
        )
        malformed = (
            prefix is None
            or set(raw) - {"prefix", "configMapRef", "secretRef"}
            or len(set(raw) & {"configMapRef", "secretRef"}) != 1
            or set(selector) - {"name", "optional"}
            or ("optional" in selector and type(selector["optional"]) is not bool)
        )
        keys = (
            tuple(key for key in observation.keys if key.section == "data") if observation else ()
        )
        if malformed or observation is None or observation.state != "available":
            skipped = bool(
                observation and observation.state == "not-found" and optional and not malformed
            )
            reason = (
                ReasonCode.INVALID_DECLARATION
                if malformed
                else ReasonCode.OPTIONAL_MISSING
                if skipped
                else _SOURCE_REASONS[observation.state]
                if observation
                else ReasonCode.INVALID_DECLARATION
            )
            entry = _base(
                ("envFrom", ordinal, None),
                "(source unavailable)",
                path,
                origin,
                source=ref,
                prefix=prefix or "",
                optional=optional,
                reason=reason,
            )
            add(
                replace(entry, precedence="skipped") if skipped else entry,
                raw,
                skip=skipped,
                barrier=not skipped,
            )
            continue
        for data_key in keys:
            variable_name = (prefix or "") + data_key.name
            reason = None if _name(variable_name) else ReasonCode.INVALID_NAME
            entry = _base(
                ("envFrom", ordinal, data_key.name),
                variable_name if _name(variable_name) else "(invalid name)",
                path,
                origin,
                source=ref,
                key=data_key.name,
                prefix=prefix or "",
                optional=optional,
                reason=reason,
            )
            if data_key.binary:
                entry = replace(entry, resolution="binary", reason=ReasonCode.BINARY_VALUE)
            elif data_key.size == 0:
                entry = replace(entry, resolution="empty-hidden")
            add(entry, {}, skip=reason is not None)
    for ordinal, value in enumerate(_declarations(declaration, "env")):
        raw = _mapping(value)
        name = raw.get("name")
        path = f"spec.{container.field}[{container.name}].env[{ordinal}]"
        entry = _base(
            ("env", ordinal, None), str(name) if _name(name) else "(invalid name)", path, "literal"
        )
        skip = False
        source = _mapping(raw.get("valueFrom"))
        if (
            not _name(name)
            or set(raw) - {"name", "value", "valueFrom"}
            or ("value" in raw and not isinstance(raw["value"], str))
            or (
                "valueFrom" in raw
                and (not source or raw.get("value", "") != "" or len(source) != 1)
            )
        ):
            entry = replace(
                entry,
                origin="unsupported",
                resolution="invalid",
                reason=ReasonCode.INVALID_DECLARATION,
            )
        elif "valueFrom" not in raw:
            text = raw.get("value", "")
            dependencies = []
            for variable, token in _tokens(text):
                if not variable:
                    continue
                prior = bindings.get(token)
                unknown = any(
                    token.startswith(prefix) and (prior is None or position > prior)
                    for prefix, position in barriers
                )
                dependency = Dependency(
                    token if len(token) <= MAX_METADATA_CELL else "(overlong dependency)",
                    drafts[prior].entry.id if prior is not None and not unknown else None,
                    ReasonCode.UNKNOWN_BINDING
                    if unknown
                    else ReasonCode.UNKNOWN_VARIABLE
                    if prior is None
                    else None,
                )
                dependencies.append(dependency)
                edges += 1
                if edges > MAX_DEPENDENCY_EDGES:
                    notices.append(ReasonCode.DEPENDENCY_LIMIT)
                    break
            reason = (
                ReasonCode.NUL_VALUE
                if "\x00" in text
                else next((item.reason for item in dependencies if item.reason), None)
            )
            entry = replace(
                entry,
                dependencies=tuple(dependencies),
                resolution="unresolved"
                if reason
                else "empty-hidden"
                if text == ""
                else "text-resolvable-hidden",
                reason=reason,
            )
        elif "fieldRef" in source:
            selector = _mapping(source["fieldRef"])
            result = _field_value(data, selector)
            entry = replace(
                entry,
                origin="field-ref",
                field_path=_bounded(selector.get("fieldPath")),
                resolution="empty-hidden"
                if result.text == ""
                else "text-resolvable-hidden"
                if result.complete
                else "unresolved",
                reason=result.reasons[0] if result.reasons else None,
            )
        elif "resourceFieldRef" in source:
            selector = _mapping(source["resourceFieldRef"])
            result = _resource_value(data, container, selector)
            entry = replace(
                entry,
                origin="resource-field-ref",
                resource_selector=ResourceSelector(
                    _bounded(selector.get("containerName")),
                    _bounded(selector.get("resource")) or "",
                    _bounded(selector.get("divisor", "1")) or "",
                ),
                resolution="text-resolvable-hidden" if result.complete else "unresolved",
                reason=result.reasons[0] if result.reasons else None,
            )
        elif "fileKeyRef" in source:
            entry = replace(
                entry,
                origin="file-key-ref",
                resolution="unresolved",
                reason=ReasonCode.UNSUPPORTED_RUNTIME_SOURCE,
            )
        else:
            ref = _ref(source, str(_mapping(data.get("metadata")).get("namespace", "")))
            selector = _selector(source)
            key = _bounded(selector.get("key"))
            optional = selector.get("optional") is True
            observation = observed.get(ref) if ref else None
            reason = None
            if (
                set(source) - {"configMapKeyRef", "secretKeyRef"}
                or ref is None
                or key is None
                or not re.fullmatch(r"[A-Za-z0-9._-]+", key)
                or set(selector) - {"name", "key", "optional"}
                or ("optional" in selector and type(selector["optional"]) is not bool)
            ):
                reason = ReasonCode.INVALID_DECLARATION
            elif observation is None or observation.state != "available":
                skip = bool(optional and observation and observation.state == "not-found")
                reason = (
                    ReasonCode.OPTIONAL_MISSING
                    if skip
                    else _SOURCE_REASONS[observation.state]
                    if observation
                    else ReasonCode.SOURCE_UNREACHABLE
                )
            else:
                metadata = next(
                    (
                        item
                        for item in observation.keys
                        if item.section == "data" and item.name == key
                    ),
                    None,
                )
                if metadata is None:
                    skip = optional
                    reason = ReasonCode.OPTIONAL_MISSING if skip else ReasonCode.MISSING_KEY
                elif metadata.binary:
                    reason = ReasonCode.BINARY_VALUE
                elif metadata.size == 0:
                    entry = replace(entry, resolution="empty-hidden")
            entry = replace(
                entry,
                origin="secret-key"
                if ref and ref.kind == "Secret"
                else "configmap-key"
                if ref
                else "unsupported",
                source=ref,
                key=key,
                optional=optional,
                reason=reason,
                resolution="binary"
                if reason == ReasonCode.BINARY_VALUE
                else "unresolved"
                if reason
                else entry.resolution,
                precedence="skipped" if skip else "unknown" if reason else "effective",
            )
        add(entry, raw, skip=skip or not _name(name))
    for index, draft in enumerate(drafts):
        entry = draft.entry
        if entry.precedence == "skipped" or (entry.id[0] == "envFrom" and entry.id[2] is None):
            continue
        later_barrier = any(
            entry.name.startswith(prefix) and position > index for prefix, position in barriers
        )
        precedence: PrecedenceState = (
            "overridden"
            if bindings.get(entry.name, index) > index
            else "unknown"
            if later_barrier
            else "effective"
        )
        drafts[index] = replace(draft, entry=replace(entry, precedence=precedence))
    return drafts, notices


def _image(
    data: dict[str, Any], declaration: dict[str, Any], container: ContainerIdentity
) -> tuple[ImageFacts, bool]:
    family = {
        "containers": "containerStatuses",
        "initContainers": "initContainerStatuses",
        "ephemeralContainers": "ephemeralContainerStatuses",
    }[container.field]
    status = next(
        (
            item
            for item in _array(_mapping(data.get("status")).get(family))
            if isinstance(item, dict) and item.get("name") == container.name
        ),
        {},
    )
    raw_secrets = tuple(
        _mapping(item).get("name")
        for item in _array(_mapping(data.get("spec")).get("imagePullSecrets"))
    )
    values = (
        declaration.get("image"),
        declaration.get("imagePullPolicy"),
        status.get("image"),
        status.get("imageID"),
        status.get("containerID"),
    )
    omitted = any(
        isinstance(value, str) and len(value) > MAX_METADATA_CELL
        for value in (*values, *raw_secrets)
    )
    declared, pull_policy, status_image, image_id, container_id = (
        _bounded(value) for value in values
    )
    return ImageFacts(
        declared,
        pull_policy,
        status_image,
        image_id,
        container_id,
        tuple(name for value in raw_secrets if (name := _bounded(value)) is not None),
    ), omitted


def build_snapshot(
    pod: ResourceRecord,
    container: ContainerIdentity,
    sources: tuple[SourceRead, ...],
    *,
    target: ResourceTarget,
    snapshot_id: UUID,
    started_at: datetime,
    observed_at: datetime,
    reads: int,
) -> InspectionSnapshot:
    binding = object_binding(pod, kind="Pod")
    if (target.group, target.resource, target.namespace, target.name, target.uid) != (
        "",
        "pods",
        binding.namespace,
        binding.name,
        binding.uid,
    ) or target.container not in (None, container.name):
        raise AppError("The container inspection target is stale; reload required.")
    refs, declaration = collect_references(pod, container)
    input_limited = (
        pod.size_bytes
        + sum(source.record.size_bytes for source in sources if source.record is not None)
        > MAX_INPUT_BYTES
    )
    accepted_sources = (
        tuple(replace(source, state="not-collected-limit", record=None) for source in sources)
        if input_limited
        else sources
    )
    observations, _, notices = _observe(refs, accepted_sources, observed_at)
    data = pod.manifest
    drafts, reasons = _drafts(data, container, declaration, observations)
    notices.extend(reasons)
    if len(refs) > MAX_REFERENCES:
        notices.append(ReasonCode.REFERENCE_LIMIT)
    if input_limited:
        notices.append(ReasonCode.INPUT_LIMIT)
    if type(reads) is not int or not 0 <= reads <= MAX_READS:
        notices.append(ReasonCode.READ_LIMIT)
    image, image_overlong = _image(data, declaration, container)
    metadata_size = len(
        repr((observations, tuple(draft.entry for draft in drafts), image)).encode()
    )
    if metadata_size > MAX_METADATA_BYTES:
        notices.append(ReasonCode.METADATA_LIMIT)
        # Omitting all affected rows avoids publishing silently truncated provenance.
        observations, drafts = (), []
        image = ImageFacts(None, None, None, None, None, ())
    snapshot = InspectionSnapshot(
        snapshot_id,
        target,
        container,
        binding,
        observations,
        tuple(draft.entry for draft in drafts),
        image,
        started_at,
        observed_at,
        not notices,
        reads,
        tuple(dict.fromkeys(notices)),
    )
    omitted = any(
        "(metadata omitted: limit)" in row.cells
        for section in ("environment", "image", "sources")
        for row in metadata_table(snapshot, section).rows
    )
    if omitted or image_overlong:
        snapshot = replace(
            snapshot,
            complete=False,
            notices=tuple(dict.fromkeys((*snapshot.notices, ReasonCode.METADATA_LIMIT))),
        )
    return snapshot


def _checked_text(
    text: str | None, complete: bool, reasons: tuple[ReasonCode, ...]
) -> ResolvedValue:
    if text is not None and len(text.encode()) > MAX_RESOLUTION_BYTES:
        return ResolvedValue(None, False, (ReasonCode.RESOLUTION_LIMIT,))
    if text is not None and "\x00" in text:
        return ResolvedValue(text, False, tuple(dict.fromkeys((*reasons, ReasonCode.NUL_VALUE))))
    return ResolvedValue(text, complete, reasons)


def _resolve(
    draft: _Draft,
    values: dict[EntryId, ResolvedValue],
    data: dict[str, Any],
    container: ContainerIdentity,
    records: dict[SourceRef, ResourceRecord],
) -> ResolvedValue:
    entry, raw = draft.entry, draft.raw
    if entry.precedence == "skipped" or (entry.reason and entry.origin != "literal"):
        return ResolvedValue(None, False, (entry.reason or ReasonCode.ENTRY_UNAVAILABLE,))
    if entry.origin == "literal":
        text = raw.get("value", "")
        parts = []
        reasons = []
        size = 0
        dependencies = iter(entry.dependencies)
        for variable, token in _tokens(text):
            if variable:
                dependency = next(dependencies)
                result = values.get(dependency.entry) if dependency.entry is not None else None
                if result is None or result.text is None:
                    token = "$(" + token + ")"
                    reasons.append(dependency.reason or ReasonCode.UNKNOWN_BINDING)
                else:
                    token = result.text
                    reasons.extend(result.reasons)
            size += len(token.encode())
            if size > MAX_RESOLUTION_BYTES:
                return ResolvedValue(None, False, (ReasonCode.RESOLUTION_LIMIT,))
            parts.append(token)
        return _checked_text("".join(parts), not reasons, tuple(dict.fromkeys(reasons)))
    if entry.origin == "field-ref":
        result = _field_value(data, _mapping(_mapping(raw.get("valueFrom")).get("fieldRef")))
        return _checked_text(result.text, result.complete, result.reasons)
    if entry.origin == "resource-field-ref":
        return _resource_value(
            data, container, _mapping(_mapping(raw.get("valueFrom")).get("resourceFieldRef"))
        )
    # All remaining origins are validated data-key declarations. Their immutable
    # records were indexed successfully above and exact bindings were rechecked.
    return _checked_text(
        configuration_value(
            records[cast("SourceRef", entry.source)],
            ("data", cast("str", entry.key)),
            encoded=False,
        ),
        True,
        (),
    )


def resolve_entry(
    snapshot: InspectionSnapshot,
    entry: EntryId,
    pod: ResourceRecord,
    sources: tuple[SourceRead, ...],
) -> ResolvedValue:
    if (
        pod.size_bytes
        + sum(source.record.size_bytes for source in sources if source.record is not None)
        > MAX_INPUT_BYTES
    ):
        return ResolvedValue(None, False, (ReasonCode.INPUT_LIMIT,))
    if any(reason in _LIMIT_REASONS for reason in snapshot.notices):
        return ResolvedValue(None, False, (ReasonCode.ENTRY_UNAVAILABLE,))
    try:
        if object_binding(pod, kind="Pod") != snapshot.pod:
            return ResolvedValue(None, False, (ReasonCode.STALE_BINDING,))
        refs, declaration = collect_references(pod, snapshot.container)
        observations, records, _ = _observe(refs, sources, snapshot.observed_at)
        # Read timestamps vary; state, exact identity, content and uses may not.
        if len(observations) != len(snapshot.sources) or any(
            (fresh.ref, fresh.state, fresh.binding, fresh.references, fresh.keys)
            != (old.ref, old.state, old.binding, old.references, old.keys)
            for fresh, old in zip(observations, snapshot.sources, strict=True)
        ):
            return ResolvedValue(None, False, (ReasonCode.STALE_BINDING,))
        drafts, notices = _drafts(pod.manifest, snapshot.container, declaration, observations)
    except AppError:
        return ResolvedValue(None, False, (ReasonCode.STALE_BINDING,))
    if notices or tuple(draft.entry for draft in drafts) != snapshot.entries:
        return ResolvedValue(None, False, (ReasonCode.STALE_BINDING,))
    indexed = {draft.entry.id: draft for draft in drafts}
    if entry not in indexed:
        return ResolvedValue(None, False, (ReasonCode.ENTRY_UNAVAILABLE,))
    needed = {entry}
    pending = [entry]
    while pending:
        current = indexed[pending.pop()]
        for dependency in current.entry.dependencies:
            if dependency.entry is not None and dependency.entry not in needed:
                needed.add(dependency.entry)
                pending.append(dependency.entry)
    values: dict[EntryId, ResolvedValue] = {}
    retained = 0
    data = pod.manifest
    for draft in drafts:
        if draft.entry.id in needed:
            result = _resolve(draft, values, data, snapshot.container, records)
            retained += len(result.text.encode()) if result.text is not None else 0
            if retained > MAX_RESOLUTION_BYTES:
                return ResolvedValue(None, False, (ReasonCode.RESOLUTION_LIMIT,))
            values[draft.entry.id] = result
    return values[entry]
