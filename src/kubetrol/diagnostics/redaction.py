"""Defense-in-depth for owned diagnostic text, not a license to log raw credentials."""

import re

_PATTERNS = (
    # Include unterminated blocks so truncation cannot reveal part of a private key.
    (
        r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\n]*PRIVATE KEY-----|$)",
        "[REDACTED KEY]",
    ),
    (r"\b(Bearer|Basic)\s+[^\s,;\"']+", r"\1 [REDACTED]"),
    (r"(https?://)[^\s/@]+:[^\s/@]*@", r"\1[REDACTED]@"),
    (r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED JWT]"),
    (r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED AWS KEY]"),
    (
        r"(?<![\w-])([\"']?[\w-]{0,64}(?:token|password|passwd|secret|authorization|credential|private[-_]?key|client[-_]?key|client[-_]?certificate[-_]?data|certificate[-_]?authority[-_]?data|access[-_]?key|api[-_]?key)[\w-]{0,64}[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"]*(?:\"|$)|'[^']*(?:'|$)|[^\s,;&}]+)",
        r"\1[REDACTED]",
    ),
)
_REDACTORS = tuple(
    (re.compile(pattern, re.IGNORECASE), replacement) for pattern, replacement in _PATTERNS
)
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


def sanitize_text(text: str) -> str:
    """Redact common credentials and render controls as inert escapes on one line."""
    # Defensive bound before regex work. Secret patterns also consume truncated values.
    text = text[:65536]
    for pattern, replacement in _REDACTORS:
        text = pattern.sub(replacement, text)
    return _CONTROLS.sub(lambda match: f"\\u{ord(match.group()):04x}", text)
