"""Session-only controls for the existing terminal workspace."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Presentation:
    headless: bool = False
    logoless: bool = False
    crumbsless: bool = False


DEFAULT_PRESENTATION = Presentation()
