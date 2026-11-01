"""Explicit bounded API selectors, separate from the local text filter."""

from dataclasses import dataclass, replace

from kuberich.domain.selectors import selectors
from kuberich.errors import AppError


@dataclass(frozen=True)
class ResourceQuery:
    label_selector: str | None = None
    field_selector: str | None = None
    compact: bool = False

    def __post_init__(self) -> None:
        for value, field in ((self.label_selector, False), (self.field_selector, True)):
            if value is not None:
                if not isinstance(value, str):
                    raise AppError("Server selectors must be bounded strings.")
                try:
                    selectors(value, field=field)
                except AppError:
                    raise AppError(
                        "Invalid server field selector; use an allowlisted field equality."
                        if field
                        else "Invalid server label selector; use bounded equality, set or existence terms."
                    ) from None
        if type(self.compact) is not bool:
            raise AppError("Compact server columns must be explicitly true or false.")

    @property
    def parameters(self) -> dict[str, str]:
        values = {}
        if self.label_selector is not None:
            values["labelSelector"] = self.label_selector
        if self.field_selector is not None:
            values["fieldSelector"] = self.field_selector
        return values

    @property
    def empty(self) -> bool:
        return self.label_selector is None and self.field_selector is None and not self.compact


def query_command(query: ResourceQuery, text: str) -> ResourceQuery:
    """Apply one explicit server command without changing the local filter."""
    verb, _, argument = text.strip().partition(" ")
    argument = argument.strip()
    if verb == "label" and argument:
        return replace(query, label_selector=argument)
    if verb == "field" and argument:
        return replace(query, field_selector=argument)
    if not argument:
        if verb == "clear":
            return replace(query, label_selector=None, field_selector=None)
        if verb in {"compact", "full"}:
            return replace(query, compact=verb == "compact")
    raise AppError(
        "Use :server label EXPR, :server field EXPR, :server clear, :server compact or :server full."
    )
