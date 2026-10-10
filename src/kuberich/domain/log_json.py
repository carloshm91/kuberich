"""Decode credential keys before redaction; retain useful JSON shape within strict bounds."""

import json
import re
from typing import Any

from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.inspection import redacted
from kuberich.errors import AppError

TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})) ")
_JSON_ARRAY_VALUE = re.compile(
    r"^\s*(?:true\b|false\b|null\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?=\s*(?:,|$)))"
)
_JSON_SCALAR = re.compile(
    r'^\s*(?:"|(?:-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)\s*$)'
)
UNAVAILABLE = "[structured payload unavailable: invalid, truncated or excessive JSON]"


def _candidate(payload: str) -> bool:
    value = payload.lstrip()
    if value.startswith("{"):
        # A malformed first key must not bypass decoded credential-key redaction.
        return True
    if value.startswith("["):
        head, closing, tail = value[1:].partition("]")
        nested = any(character in head for character in '[{"')
        if closing and tail.strip() and not nested:
            # A completed simple PID/level/date prefix followed by prose is plain.
            return False
        return nested or not head.strip() or _JSON_ARRAY_VALUE.match(head) is not None
    return _JSON_SCALAR.match(value) is not None


def _bounded(value: Any, depth: int = 0, budget: list[int] | None = None) -> Any:
    budget = [512] if budget is None else budget
    budget[0] -= 1
    if depth > 16 or budget[0] < 0:
        raise AppError("Structured log exceeds the depth or expansion limit.")
    if isinstance(value, dict):
        return {key: _bounded(item, depth + 1, budget) for key, item in value.items()}
    if isinstance(value, list):
        return [_bounded(item, depth + 1, budget) for item in value]
    if isinstance(value, float) and not (-1e308 <= value <= 1e308):
        raise AppError("Structured log contains a non-finite number.")
    return value


def structured_payload(payload: str) -> tuple[str, str | None]:
    if not _candidate(payload):
        return sanitize_text(payload), None
    try:
        value = redacted(_bounded(json.loads(payload)))
        text = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(text) > 8192:
            return UNAVAILABLE, None
        return text, text
    except (ValueError, RecursionError, AppError):
        # Encoded credentials in malformed JSON cannot safely be decoded in isolation.
        return UNAVAILABLE, None


def sanitize_log_line(text: str) -> str:
    match = TIMESTAMP.match(text)
    prefix, payload = (text[: match.end()], text[match.end() :]) if match else ("", text)
    safe, _ = structured_payload(payload)
    return prefix + safe
