"""Defense-in-depth for owned diagnostic text, not a license to log raw credentials."""

import re

from kubetrol.security.controls import escape_controls

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


def sanitize_text(text: str, *, allow_newlines: bool = False) -> str:
    """Redact credentials and escape controls; diagnostics stay on one line by default."""
    # Defensive bound before regex work. Secret patterns also consume truncated values.
    text = text[:65536]
    for pattern, replacement in _REDACTORS:
        text = pattern.sub(replacement, text)
    return escape_controls(text, allow_newlines=allow_newlines)
