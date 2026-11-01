"""Own local plugin loading, scoped hotkeys and jobs without loading modal widgets."""

import asyncio
import re
from typing import TYPE_CHECKING

from textual.screen import ModalScreen

from kuberich.adapters.editing import file_worker
from kuberich.adapters.plugin_files import load_plugins
from kuberich.config.plugins import plugins_from
from kuberich.domain.plugins import Plugin, PluginSelection, plugin_bindings
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned
from kuberich.services.plugins import PluginManager, PluginSource

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp
    from kuberich.ui.plugin_screens import PluginCatalogue as PluginCatalogue
    from kuberich.ui.plugin_screens import PluginJobs as PluginJobs
    from kuberich.ui.plugin_screens import PluginScreen as PluginScreen


def __getattr__(name: str) -> object:
    if name in {"PluginCatalogue", "PluginJobs", "PluginScreen"}:
        from kuberich.ui.plugin_screens import PluginCatalogue, PluginJobs, PluginScreen

        return {
            "PluginCatalogue": PluginCatalogue,
            "PluginJobs": PluginJobs,
            "PluginScreen": PluginScreen,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class PluginController:
    def __init__(self, app: "KubeRichApp") -> None:
        self.app = app
        self.manager = PluginManager(app.commands.policy)
        self.plugins: tuple[Plugin, ...] = ()
        self._context: str | None = None
        self._loader: asyncio.Task[None] | None = None
        self._opening: asyncio.Task[None] | None = None
        self._closed = False
        self._loaded = False
        self._loaders: set[asyncio.Task[None]] = set()
        self.error: str | None = None

    def refresh(self) -> None:
        app = self.app
        context = app.appearance_controller.context()
        if self._closed or (self._loaded and context == self._context) or app.preferences is None:
            return
        self._context = context
        self._loaded = True
        self.plugins = ()
        if self._loader is not None:
            self._loader.cancel()
        if "plugins" not in app.preferences.document.extensions:
            return
        self._loader = asyncio.create_task(self._load(context))
        self._loaders.add(self._loader)
        self._loader.add_done_callback(self._loaders.discard)

    def reload(self) -> None:
        """Read plugin definitions again after the preference file changed."""
        self._loaded = False
        self.refresh()

    async def _load(self, context: str | None) -> None:
        preferences = self.app.preferences
        assert preferences is not None
        try:
            plugins = await file_worker(
                lambda: load_plugins(
                    plugins_from(preferences.document, preferences.location.path.parent),
                    context,
                    keys=self.app.navigation.keys,
                )
            )
        except (AppError, OSError) as error:
            if self._context == context:
                self.error = (
                    str(error)
                    if isinstance(error, AppError)
                    else "Cannot read configured plugin files."
                )
            return
        if self._context == context and not self._closed:
            self.plugins, self.error = plugins, None

    def resource(self) -> str | None:
        scope = self.app.workspace.store.observation.scope
        return (
            scope.resource.api_version + "/" + scope.resource.name
            if scope is not None and self.app._resource_name != "contexts"
            else None
        )

    def bindings(self) -> tuple[tuple[str, str], ...]:
        if self.app._resource_name == "contexts":
            return ()
        return plugin_bindings(self.plugins, self.resource(), self.app.navigation.keys)

    def open(self, name: str | None = None) -> None:
        if self._closed or (self._opening is not None and not self._opening.done()):
            return
        self.refresh()
        self._opening = asyncio.create_task(self._open(name))

    def capture_source(self) -> PluginSource:
        app = self.app
        view, client = app.workspace.store.observation, app.sessions.client
        if client is None or view.scope is None:
            raise AppError("Select a connected context before running a plugin.")
        local_contexts = app._resource_name == "contexts"
        resource = None if local_contexts else view.scope.resource
        generic = app._generic_selection
        expected_name = generic.name if generic is not None else app._resource_name
        if resource is not None and resource.name != expected_name:
            raise AppError("The resource view is loading; wait before reviewing a plugin.")
        if (
            resource is not None
            and generic is not None
            and (generic.group != resource.group or generic.version not in {None, resource.version})
        ):
            raise AppError("The resource version is loading; wait before reviewing a plugin.")
        uid = app._active_table.capture_viewport().selected
        selected = (
            app._capture_target() if uid is not None and app._resource_name != "contexts" else None
        )
        target = None
        columns: tuple[tuple[str, str], ...] = ()
        if selected is not None:
            client, resource, _, target, current = selected
            table = app._active_table
            columns = tuple(
                (re.sub(r"[^A-Z0-9_-]", "_", column.label.plain.upper()), str(value))
                for column, value in zip(
                    table.columns.values(), table.get_row(target.uid), strict=True
                )
                if re.match(r"[A-Za-z]", column.label.plain)
            )
        else:

            def current() -> bool:
                observation = app.workspace.store.observation
                return (
                    app.sessions.client is client
                    and observation.scope == view.scope
                    and observation.revision == view.revision
                )

        context_data = app.sessions.catalog.contexts[client.context.name].data
        selection = PluginSelection(
            client.context.name,
            resource.api_version + "/" + resource.name if resource is not None else None,
            target,
            variables=(
                ("CLUSTER", str(context_data.get("cluster", ""))),
                ("USER", str(context_data.get("user", ""))),
                ("FILTER", app.filter_input.value),
            ),
            columns=columns,
            namespace=None if local_contexts else view.scope.namespace,
        )
        return PluginSource(
            client, resource, selection, app.commands.policy, current, app._process_environment
        )

    async def _open(self, name: str | None) -> None:
        original_client = self.app.sessions.client
        original_scope = self.app.workspace.store.observation.scope
        try:
            source = self.capture_source() if name is not None else None
        except AppError as error:
            self.app._set_status(str(error))
            return
        if self._loader is not None:
            await asyncio.shield(self._loader)
        app = self.app
        if (
            self._closed
            or isinstance(app.screen, ModalScreen)
            or app.sessions.client is not original_client
            or app.workspace.store.observation.scope != original_scope
        ):
            return
        if self.error is not None:
            app._set_status(self.error)
            return
        if name is None:
            from kuberich.ui.plugin_screens import PluginCatalogue

            app.push_screen(
                PluginCatalogue(
                    tuple(plugin for plugin in self.plugins if plugin.applies(self.resource()))
                ),
                lambda result: self.open(result) if result is not None else None,
            )
            return
        plugin = next((plugin for plugin in self.plugins if plugin.name == name), None)
        try:
            if plugin is None:
                raise AppError("Plugin is not configured for this context. Use :plugins.")
            plugin.require_access(app.commands.policy.read_only)
            assert source is not None
            source.require(plugin)
            from kuberich.ui.plugin_screens import PluginScreen

            app.push_screen(PluginScreen(plugin, source, self.manager))
        except AppError as error:
            app._set_status(str(error))

    async def close(self) -> None:
        self._closed = True
        for task in (self._opening, *tuple(self._loaders)):
            if task is not None:
                if not task.done():
                    task.cancel()
                await finish_owned(asyncio.gather(task, return_exceptions=True))
        await self.manager.close()
