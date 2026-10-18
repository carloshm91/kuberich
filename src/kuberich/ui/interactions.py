"""Session interaction controls; Kubernetes operations retain their normal review path."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from kuberich.domain.interactions import CommandHistory, InteractionCommand, RangeSelection
from kuberich.domain.resource_preferences import ColumnSpec, ViewSpec
from kuberich.errors import AppError
from kuberich.services.metadata_filtering import MetadataFilter
from kuberich.ui.chrome import Breadcrumbs, WorkspaceFrame, WorkspaceHeader

if TYPE_CHECKING:
    from kuberich.config.navigation import NavigationPreferences
    from kuberich.ui.app import KubeRichApp


class Interactions:
    def __init__(self, app: KubeRichApp) -> None:
        self.app = app
        self.history = CommandHistory()
        self.filter_history = CommandHistory()
        self.selection = RangeSelection()
        self.filter = MetadataFilter()
        self.errors = False
        self.favorites = False
        self.wide = False
        self.revision = 0
        self.scope_revision = -1
        self._painted: dict[str, frozenset[str]] = {}
        self._painted_columns: dict[str, int] = {}
        self.fullscreen = False
        self._favorite_task: asyncio.Task[None] | None = None

    def apply(self, command: InteractionCommand) -> None:
        app, verb = self.app, command.verb
        try:
            if verb == "!!":
                app._submit_command(self.history.repeat(), repeat=True)
                return
            if verb == "favorite":
                if self._favorite_task is not None and not self._favorite_task.done():
                    raise AppError("A favorite preference write is already in progress.")
                context = app.workspace.store.observation.context
                if context is None or app.preferences is None or app._navigation_invalid:
                    raise AppError(
                        "Favorites require a selected context and writable valid preferences."
                    )
                action, _, name = command.argument.partition(" ")
                updated = app.navigation.with_favorite(context, name, remove=action == "remove")
                self._favorite_task = asyncio.create_task(self._save_favorite(updated))
                return
            if verb in {"headless", "crumbsless", "fullscreen"}:
                self._presentation(verb)
                return
            if verb in {"copy", "copyns", "copytext"}:
                self._copy(verb)
                return
            if verb in {"mark", "range", "selectall", "selectnone"}:
                table = app._active_table
                visible = tuple(
                    row.key.value for row in table.ordered_rows if row.key.value is not None
                )
                uid = (
                    table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                    if table.row_count
                    else None
                )
                self.selection.apply(verb, uid, visible)
                self.paint_selection()
                app._set_status(
                    f"Marked {len(self.selection.marked)} resources · :deletebatch reviews marked rows"
                )
                return
            if verb == "wide":
                self.wide = not self.wide
            elif verb == "errors":
                self.errors = not self.errors
            elif verb == "favorites":
                app.action_namespaces()
                self.favorites = True
            self.changed()
        except AppError as error:
            app._set_status(str(error))

    def paint_selection(self) -> None:
        table = self.app._active_table
        previous = self._painted.get(table.id or "", frozenset())
        marked = self.selection.marked
        if (
            previous == marked
            and self._painted_columns.get(table.id or "") == table._column_revision
        ):
            return
        table.border_subtitle = f"{len(marked)} marked" if marked else ""
        changed = (
            previous ^ marked
            if self._painted_columns.get(table.id or "") == table._column_revision
            else previous | marked
        )
        for uid in changed:
            table.set_mark(uid, uid in marked)
        self._painted[table.id or ""] = marked
        self._painted_columns[table.id or ""] = table._column_revision
        table.refresh(layout=True)

    def changed(self) -> None:
        self.revision += 1
        self.app._render_ready.set()

    async def _save_favorite(self, updated: NavigationPreferences) -> None:
        app = self.app
        assert app.preferences is not None
        try:
            await app.preferences.save_navigation(updated)
        except AppError as error:
            app._set_status(str(error))
        else:
            app.navigation = updated
            app._set_status("Namespace favorites saved for the captured context.")
            self.changed()

    def _copy(self, verb: str) -> None:
        app, table = self.app, self.app._active_table
        if not table.row_count:
            raise AppError("Select a visible row before copying.")
        visible = tuple(row.key.value for row in table.ordered_rows if row.key.value is not None)
        self.selection.prune(visible)
        uid = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        uids = (
            self.selection.marked or frozenset((uid,)) if uid is not None else self.selection.marked
        )
        snapshot = app.workspace.store.observation.snapshot
        if app._resource_name == "contexts":
            names = [
                (app.context_table._rows[key].namespace if verb == "copyns" else key)
                for key in visible
                if key in uids
            ]
        else:
            records = {record.uid: record for record in snapshot.items} if snapshot else {}
            names = []
            for key in visible:
                if key in uids:
                    record = records.get(key)
                    if record is None:
                        raise AppError("The selected resource is stale.")
                    names.append((record.namespace or "") if verb == "copyns" else record.name)
        if verb == "copytext":
            # Cells are already bounded/redacted projections; never export raw manifests here.
            text = "\n".join(
                "\t".join(str(cell) for cell in table.get_row(key))
                for key in visible
                if key in uids
            )
        else:
            text = "\n".join(dict.fromkeys(names))
        app.copy_to_clipboard(text)
        app._set_status("Visible selection copied; clipboard write requested.")

    def overlay(self, view: ViewSpec, fields: tuple[str, ...]) -> ViewSpec:
        return (
            replace(view, columns=tuple(ColumnSpec(key) for key in fields)) if self.wide else view
        )

    def _presentation(self, verb: str) -> None:
        app = self.app
        if verb == "fullscreen":
            self.fullscreen = not self.fullscreen
        else:
            app._presentation = replace(
                app._presentation, **{verb: not getattr(app._presentation, verb)}
            )
            app.chrome = replace(app.chrome, presentation=app._presentation)
        for screen in app.screen_stack:
            if hasattr(screen, "chrome"):
                screen.chrome = app.chrome
            hidden = self.fullscreen or bool(getattr(screen, "_local_fullscreen", False))
            for header in screen.query(WorkspaceHeader):
                header.chrome = app.chrome
                header.update_identity()
                header.layout_header()
                header.display = not hidden
            for trail in screen.query(Breadcrumbs):
                trail.display = not hidden and not app._presentation.crumbsless
            for frame in screen.query(WorkspaceFrame):
                frame.set_class(hidden, "fullscreen")
        app._set_status(f"{verb} toggled · command and search remain available")
