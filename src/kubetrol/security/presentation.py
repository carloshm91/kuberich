"""Bounded literal Rich text for resource fields, logs and external error summaries."""

from rich.text import Text

from kubetrol.diagnostics.redaction import sanitize_text

MAX_DISPLAY_CHARACTERS = 16384


def safe_text(value: str, *, multiline: bool = False) -> Text:
    """Return literal text; callers must not reparse its plain value as markup.

    Known credential patterns are defense in depth. Opaque Secrets/credential
    responses require an allowlist or concealment before reaching this function.
    """
    content = sanitize_text(value[:MAX_DISPLAY_CHARACTERS], allow_newlines=multiline)
    if len(value) > MAX_DISPLAY_CHARACTERS:
        content += " … [truncated]"
    return Text(content)
