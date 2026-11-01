"""Own theme preferences and optional release observations through public UI ports."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import version

from platformdirs import user_cache_path
from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Static

from kuberich.config.schema import ConfigDocument, Settings
from kuberich.domain.appearance import Appearance, effective_theme
from kuberich.errors import AppError
from kuberich.services.appearance import PreferenceSource
from kuberich.services.ownership import finish_owned
from kuberich.services.updates import UpdateResult, UpdateService
from kuberich.ui.theme_catalog import appearance_from, invert_theme, themes_for


class AppearanceController:
    def __init__(
        self,
        host: App[None],
        settings: Settings,
        preferences: PreferenceSource | None,
        context: Callable[[], str | None],
        apply_live: Callable[[str | None], None],
        build: Callable[[], str],
        on_error: Callable[[Exception], None],
        *,
        invert: bool = False,
        updates: UpdateService | None = None,
    ) -> None:
        self.host, self.preferences, self.context = host, preferences, context
        self.apply_live, self.build, self.on_error = apply_live, build, on_error
        self.invert = invert
        self._global_theme = preferences.document.settings.theme if preferences else settings.theme
        self._theme_override = preferences.theme_override if preferences else None
        self.appearance = Appearance()
        self.warning: str | None = None
        self.invalid = False
        if preferences is not None:
            try:
                self.appearance = appearance_from(preferences.document)
            except AppError as error:
                self.warning, self.invalid = str(error), True
        for theme in themes_for(self.appearance):
            host.register_theme(theme)
        if invert:
            for theme in tuple(host.available_themes.values()):
                host.register_theme(invert_theme(theme))
        self.applied_context: str | None = None
        self._updates = updates or UpdateService(
            version("kuberich"),
            user_cache_path("kuberich", appauthor=False) / "latest-release.json",
        )
        self._update_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._build_info: Static | None = None
        self.update_result = UpdateResult("Version checks disabled; opt in under :themes.")

    def apply(self, context: str | None = None) -> None:
        context = context or self.context()
        self.host.theme, unavailable = effective_theme(
            self._global_theme,
            self.appearance,
            context,
            self._theme_override,
            self.host.available_themes,
        )
        self.applied_context = context
        self.apply_live(context)
        if unavailable:
            self.warning = "Selected theme is unavailable; using k9s."

    def adopt(self, document: ConfigDocument, global_theme: str) -> None:
        """Replace validated custom themes while retaining the runtime theme override."""
        previous = {theme.name for theme in self.appearance.themes}
        self.appearance, self.invalid = appearance_from(document), False
        custom = {theme.name for theme in self.appearance.themes}
        for name in previous - custom:
            self.host.unregister_theme(name)
        for theme in themes_for(self.appearance):
            if theme.name in custom:
                self.host.register_theme(invert_theme(theme) if self.invert else theme)
        if self.preferences is not None and self.preferences.theme_override is None:
            self._global_theme = global_theme

    def open_themes(self) -> None:
        from kuberich.ui.appearance import ThemeScreen

        if not isinstance(self.host.screen, ModalScreen):
            self.host.push_screen(
                ThemeScreen(
                    tuple(sorted(self.host.available_themes)),
                    self.host.theme,
                    self.context(),
                    self.appearance.check_updates,
                    self._preview,
                    self.apply,
                    self._save,
                    writable=self.preferences is not None and not self.invalid,
                )
            )

    def _preview(self, name: str) -> None:
        self.host.theme = name

    async def _save(self, name: str, context: str | None, check_updates: bool) -> str:
        if self.preferences is None:
            raise AppError("Launch through the CLI to save local preferences.")
        if self.invalid:
            raise AppError(
                "Correct appearance settings with kuberich config check before saving; the file is retained."
            )
        if name not in self.host.available_themes or (
            context is not None and context != self.context()
        ):
            raise AppError("Theme or context changed; close and select it again.")
        appearance = replace(
            self.appearance,
            check_updates=check_updates if context is None else self.appearance.check_updates,
        )
        await self.preferences.save(appearance, name, context)
        self.appearance = appearance_from(self.preferences.document)
        self._global_theme = self.preferences.document.settings.theme
        self.apply()
        self.start_updates()
        return f"Saved {'globally' if context is None else 'for this context'} · effective theme: {self.host.theme} · environment > context > global"

    def open_about(self) -> None:
        from kuberich.ui.appearance import AboutScreen

        if not isinstance(self.host.screen, ModalScreen):
            self.host.push_screen(
                AboutScreen(
                    version("kuberich") + (" · inverted" if self.invert else ""),
                    self._notice(),
                )
            )

    def _notice(self) -> str:
        result = self.update_result
        return (
            result.message
            + (" · cached within 24 hours" if result.cached else "")
            + ("\n" + result.release.url if result.release else "")
        )

    def attach_build_info(self, widget: Static) -> None:
        self._build_info = widget

    def start_updates(self) -> None:
        if self._stopped:
            return
        if not self.appearance.check_updates:
            if self._update_task is not None:
                self._update_task.cancel()
            self.update_result = UpdateResult("Version checks disabled; opt in under :themes.")
            if self._build_info is not None and self._build_info.is_attached:
                self._build_info.update(self.build())
            return
        if self._update_task is None or self._update_task.done():
            self.update_result = UpdateResult("Checking public stable releases…")
            self._update_task = asyncio.create_task(self._check_update())
            self._update_task.add_done_callback(self._finished)

    async def _check_update(self) -> None:
        from kuberich.ui.appearance import AboutScreen

        result = await self._updates.check()
        if self._stopped or not self.appearance.check_updates:
            return
        self.update_result = result
        for screen in tuple(self.host.screen_stack):
            if isinstance(screen, AboutScreen):
                screen.update_notice(self._notice())
        if (
            self.host.is_running
            and result.release is not None
            and self._build_info is not None
            and self._build_info.is_attached
        ):
            self._build_info.update(self.build() + " · ↑" + result.release.version)
            self.host.notify(result.message + " · :about for release notes")

    def _finished(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            if not self._stopped and self.appearance.check_updates:
                self.start_updates()
            return
        if isinstance(error := task.exception(), Exception):
            self.on_error(error)

    def stop(self) -> None:
        self._stopped = True

    async def close(self) -> None:
        self.stop()
        if self._update_task is not None:
            if not self._update_task.done() and not self._update_task.cancelling():
                self._update_task.cancel()
            await finish_owned(asyncio.gather(self._update_task, return_exceptions=True))
