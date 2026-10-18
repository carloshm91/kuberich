"""Explicit local preference persistence, separate from effective runtime overrides."""

import asyncio
from dataclasses import dataclass, field, replace

from kuberich.adapters.editing import file_worker
from kuberich.config.navigation import NavigationPreferences, parse_navigation
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument
from kuberich.config.store import read_config, write_config
from kuberich.domain.appearance import Appearance, parse_appearance, theme_name
from kuberich.errors import AppError
from kuberich.services.commands import RESERVED_COMMANDS


@dataclass
class PreferenceSource:
    location: ConfigLocation
    document: ConfigDocument
    theme_override: str | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def save(self, appearance: Appearance, theme: str, context: str | None) -> None:
        theme_name(theme)
        original = self.document
        contexts = dict(appearance.contexts)
        if context is not None:
            contexts[context] = theme
        changed = replace(appearance, contexts=tuple(sorted(contexts.items())))
        parse_appearance(changed.mapping())
        updated = replace(
            original,
            settings=replace(original.settings, theme=theme)
            if context is None
            else original.settings,
            extensions={**original.extensions, "appearance": changed.mapping()},
            migrated=False,
        )

        await self._persist(updated, original)

    async def save_navigation(self, navigation: NavigationPreferences) -> None:
        original = self.document
        validated = parse_navigation(navigation.mapping(), RESERVED_COMMANDS)
        updated = replace(
            original,
            extensions={**original.extensions, "navigation": validated.mapping()},
            migrated=False,
        )
        await self._persist(updated, original)

    async def _persist(self, updated: ConfigDocument, original: ConfigDocument) -> None:
        if self.location.migration_target is not None:
            raise AppError(
                "Run kuberich config migrate before saving preferences from the legacy path."
            )

        def persist() -> None:
            existed = self.location.path.exists()
            current = read_config(self.location.path)
            if current.to_mapping() != original.to_mapping():
                raise AppError("Preferences changed on disk; restart to reload before saving.")
            write_config(self.location.path, updated, overwrite=existed)

        async with self._lock:
            if self.document is not original:
                raise AppError(
                    "Preferences changed during another save; retry the explicit change."
                )
            await file_worker(persist)
            self.document = updated
