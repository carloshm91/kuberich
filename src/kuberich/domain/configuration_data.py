"""Bounded configuration payloads; ordinary indexes retain metadata only."""

import base64
import binascii
import re
from dataclasses import dataclass

from kuberich.domain.resources import ResourceRecord
from kuberich.errors import AppError

MAX_DATA_BYTES = 1024 * 1024
MAX_DATA_KEYS = 4096
MAX_CLIPBOARD_BYTES = 65536


@dataclass(frozen=True)
class DataKey:
    section: str
    name: str
    size: int
    binary: bool

    @property
    def identity(self) -> tuple[str, str]:
        return self.section, self.name


@dataclass(frozen=True)
class ConfigurationIndex:
    resource_version: str
    keys: tuple[DataKey, ...]


def _entries(record: ResourceRecord) -> dict[tuple[str, str], bytes]:
    if record.size_bytes > 2 * MAX_DATA_BYTES:
        raise AppError("Configuration resource exceeds the 2 MiB inspection limit.")
    manifest = record.manifest
    kind = manifest.get("kind")
    if kind not in {"Secret", "ConfigMap"}:
        raise AppError("Data inspection requires a core ConfigMap or Secret.")
    result: dict[tuple[str, str], bytes] = {}
    total = 0
    for section in ("data", "stringData") if kind == "Secret" else ("data", "binaryData"):
        values = manifest.get(section)
        if values is None:
            continue
        if not isinstance(values, dict):
            raise AppError("Configuration data must map keys to strings.")
        for key, value in values.items():
            if (
                not isinstance(key, str)
                or len(key) > 253
                or re.fullmatch(r"[A-Za-z0-9._-]+", key) is None
                or not isinstance(value, str)
            ):
                raise AppError("Configuration data contains an invalid key or value type.")
            try:
                data = (
                    base64.b64decode(value, validate=True)
                    if section == "binaryData" or (kind == "Secret" and section == "data")
                    else value.encode("utf-8")
                )
            except (binascii.Error, ValueError, UnicodeError):
                raise AppError("Invalid base64 or UTF-8 configuration data.") from None
            total += len(data)
            if total > MAX_DATA_BYTES or len(result) >= MAX_DATA_KEYS:
                raise AppError("Configuration data exceeds the 1 MiB or 4096-key limit.")
            result[section, key] = data
    return result


def _text(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeError:
        return None


def configuration_index(record: ResourceRecord) -> ConfigurationIndex:
    if not record.resource_version:
        raise AppError("Configuration inspection requires a resource version.")
    return ConfigurationIndex(
        record.resource_version,
        tuple(
            DataKey(section, name, len(data), _text(data) is None)
            for (section, name), data in sorted(
                _entries(record).items(), key=lambda item: (item[0][1], item[0][0])
            )
        ),
    )


def configuration_value(record: ResourceRecord, key: tuple[str, str], *, encoded: bool) -> str:
    data = _entries(record).get(key)
    if data is None:
        raise AppError("The selected configuration key is unavailable; reload the key list.")
    if encoded:
        return base64.b64encode(data).decode("ascii")
    text = _text(data)
    if text is None:
        raise AppError("This value is binary; choose Base64 before revealing or copying it.")
    return text


def clipboard_value(value: str) -> str:
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise AppError("Clipboard value is not valid UTF-8.") from None
    if size > MAX_CLIPBOARD_BYTES:
        raise AppError("Value exceeds the 64 KiB clipboard limit; use the trusted editor.")
    return value
