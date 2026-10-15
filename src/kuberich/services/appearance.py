"""Explicit local preference persistence, separate from effective runtime overrides."""

from dataclasses import dataclass, replace

from kuberich.adapters.editing import file_worker
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument
from kuberich.config.store import read_config, write_config
from kuberich.domain.appearance import Appearance, parse_appearance, theme_name
from kuberich.errors import AppError


@dataclass
class PreferenceSource:
    location: ConfigLocation
    document: ConfigDocument
    theme_override: str | None = None

    async def save(self, appearance: Appearance, theme: str, context: str | None) -> None:
        if self.location.migration_target is not None:
            raise AppError(
                "Run kuberich config migrate before saving preferences from the legacy path."
            )
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

        def persist() -> None:
            current = read_config(self.location.path)
            if current.to_mapping() != original.to_mapping():
                raise AppError("Preferences changed on disk; restart to reload before saving.")
            write_config(self.location.path, updated, overwrite=self.location.path.exists())

        await file_worker(persist)
        self.document = updated
