"""Apply per-context settings and reload the preference file while the app runs."""

import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from textual.timer import Timer

from kuberich.adapters.editing import file_worker
from kuberich.config.context_settings import ContextSettings, context_settings_from
from kuberich.config.navigation import navigation_from
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.config.store import read_config
from kuberich.errors import AppError
from kuberich.ui.config_check import unsupported_fields, validate_preferences
from kuberich.ui.theme_catalog import appearance_from, invert_theme, themes_for

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp

POLL_SECONDS = 2.0
Identity = tuple[int, int, int, int]
RETAINED = " Run kuberich config check; working defaults retained."


def file_identity(path: Path) -> Identity | None:
    try:
        status = os.stat(path)
    except OSError:
        return None
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns


class LivePreferences:
    def __init__(self, app: "KubeRichApp", settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.context_settings = ContextSettings()
        self.error: str | None = None
        self.refresh_seconds = settings.refresh_seconds
        self._refresh_timer: Timer | None = None
        self._poll_timer: Timer | None = None
        self._identity: Identity | None = None
        self._baseline = True
        if app.preferences is not None:
            try:
                self.context_settings = context_settings_from(app.preferences.document)
            except AppError as error:
                self.error = str(error)

    def apply(self, context: str | None) -> None:
        """Use the settings of the context being shown."""
        pinned = self.app.preferences.pinned if self.app.preferences is not None else ()
        read_only, refresh = self.context_settings.effective(self.settings, pinned, context)
        self.app.commands.policy.restrict(read_only)
        if refresh != self.refresh_seconds:
            self.refresh_seconds = refresh
            if self._refresh_timer is not None:
                self._refresh_timer.stop()
                self._refresh_timer = self.app.set_interval(refresh, self.app._refresh_tables)

    def start(self, warnings: tuple[str | None, ...]) -> None:
        app = self.app
        self._refresh_timer = app.set_interval(self.refresh_seconds, app._refresh_tables)
        notices = (*warnings, self.error)
        for warning in notices:
            if warning:
                app.notify(warning + RETAINED, severity="warning", markup=False)
        if app.preferences is not None:
            if (unsupported := unsupported_fields(app.preferences.document)) is not None:
                app.notify(unsupported, markup=False)
            # The timer awaits each check and skips ticks while one is running.
            self._poll_timer = app.set_interval(POLL_SECONDS, self.check)

    async def check(self) -> None:
        """Reload the file if it changed; an invalid file keeps the current preferences."""
        app, preferences = self.app, self.app.preferences
        if preferences is None:
            return
        location, original, known = preferences.location, preferences.document, self._identity

        def load() -> tuple[Identity | None, ConfigDocument | str | None]:
            identity = file_identity(location.path)
            if identity is None or identity == known:
                return known, None
            try:
                document = read_config(location.path)
                validate_preferences(document, location, preferences.settings(document))
            except AppError as error:
                return identity, str(error)
            return identity, document

        identity, result = await file_worker(load)
        baseline, self._identity, self._baseline = self._baseline, identity, False
        if isinstance(result, str):
            if not baseline:
                app.notify(
                    f"Preferences were not reloaded: {result}"
                    " The last valid preferences remain active.",
                    severity="warning",
                    markup=False,
                )
        elif (
            result is not None
            and result.to_mapping() != original.to_mapping()
            and await preferences.replace(result, original)
        ):
            restart = self.adopt(result)
            app.notify(
                "Preferences reloaded."
                + (" Key binding and mouse changes apply after restart." if restart else "")
                + (f" {unsupported}" if (unsupported := unsupported_fields(result)) else ""),
                markup=False,
            )

    def adopt(self, document: ConfigDocument) -> bool:
        """Apply a validated document; returns whether some changes wait for a restart."""
        app = self.app
        assert app.preferences is not None
        settings = app.preferences.settings(document)
        navigation = navigation_from(document)
        restart = (navigation.keys, navigation.mouse) != (app.navigation.keys, app.navigation.mouse)
        app.navigation, app._navigation_invalid = navigation, False
        app.commands = replace(app.commands, aliases=navigation.aliases)
        previous = {theme.name for theme in app.appearance.themes}
        app.appearance, app._appearance_invalid = appearance_from(document), False
        custom = {theme.name for theme in app.appearance.themes}
        themes = [theme for theme in themes_for(app.appearance) if theme.name in custom]
        for name in previous - custom:
            app.unregister_theme(name)
        for theme in themes:
            app.register_theme(invert_theme(theme) if app.chrome.presentation.invert else theme)
        if app.preferences.theme_override is None:
            app._global_theme = settings.theme
        if settings.read_only:
            app.commands.policy.tighten()
        app._shell = settings.shell
        self.settings, self.context_settings, self.error = (
            settings,
            context_settings_from(document),
            None,
        )
        app.jumps.configure(document)
        app.plugins.reload()
        app._apply_theme()
        app._render_ready.set()  # Saved column views apply to the current table.
        return restart

    async def close(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
