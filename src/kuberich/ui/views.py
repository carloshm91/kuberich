"""Captured resource-view editing and bounded session display preferences."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from kuberich.config.navigation import navigation_from
from kuberich.domain.custom import CustomLayout
from kuberich.domain.navigation import MAX_HISTORY
from kuberich.domain.pods import PodColumn
from kuberich.domain.resource_preferences import (
    ColumnSpec,
    ViewSpec,
    applicable_view,
    column_text,
    field_key,
    parse_column_text,
    printer_signature,
)
from kuberich.domain.views import ViewObservation
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.processes import _finish_owned
from kuberich.ui.commands import NavigationInput
from kuberich.ui.custom import CustomTable
from kuberich.ui.namespaces import NamespaceTable
from kuberich.ui.pods import PodTable
from kuberich.ui.standard import StandardTable

if TYPE_CHECKING:
    from kuberich.ui.app import KubeRichApp

type ViewTable = PodTable | NamespaceTable | StandardTable


@dataclass(frozen=True)
class ViewDescriptor:
    key: str
    context: str | None
    revision: int
    fields: tuple[str, ...]
    labels: tuple[tuple[str, str], ...]
    signature: str | None
    all_namespaces: bool


@dataclass
class _SessionView:
    source: tuple[ViewSpec, ...]
    signature: str | None
    effective: ViewSpec
    fields: tuple[str, ...]


class ViewDescending(Checkbox):
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "toggle_button", "Toggle descending", show=False, priority=True),
    ]


class ViewScreen(ModalScreen[None]):
    AUTO_FOCUS = "#view-columns"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ViewScreen { align: center middle; background: $background 80%; }
    #view-dialog { width: 95%; height: 92%; border: solid $primary;
        background: $surface; padding: 0 1; }
    #view-title { height: 1; text-overflow: ellipsis; }
    #view-fields { height: 1fr; }
    #view-fields Static { height: auto; }
    #view-columns, #view-sort, #view-reverse { height: 1; border: none; padding: 0; }
    #view-buttons { height: 1; }
    #view-buttons Button { height: 1; border: none; min-width: 7; width: 1fr; }
    #view-feedback { height: auto; min-height: 1; max-height: 3; }
    """

    def __init__(
        self,
        descriptor: ViewDescriptor,
        current: ViewSpec,
        apply: Callable[[ViewSpec, str], Awaitable[str]],
        *,
        writable: bool,
    ) -> None:
        super().__init__()
        self.descriptor, self.initial, self.apply, self.writable = (
            descriptor,
            current,
            apply,
            writable,
        )
        self._save_task: asyncio.Task[None] | None = None
        self._view_stopped = False
        self.columns_input = NavigationInput(
            lambda: self.set_focus(self.sort_input), placeholder="name:24 age:8", id="view-columns"
        )
        self.columns_input.max_length = 8192
        self.columns_input.value = column_text(current.columns or ())
        self.sort_input = NavigationInput(
            lambda: self.set_focus(self.reverse), placeholder="Typed sort field", id="view-sort"
        )
        self.sort_input.value = current.sort
        self.reverse = ViewDescending("Descending", value=current.descending, id="view-reverse")
        self.feedback = Static(
            "Apply is session-only · Global/Context saves · Esc cancels",
            markup=False,
            id="view-feedback",
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="view-dialog"):
            yield Static(
                safe_text(f"View · {self.descriptor.key} · {self.descriptor.context or 'global'}"),
                id="view-title",
            )
            with VerticalScroll(id="view-fields"):
                yield Static(
                    "Columns: key[:width][:alignment]; omit to hide. Name stays visible.",
                    markup=False,
                )
                yield self.columns_input
                yield Static("Typed sort field (may be hidden)", markup=False)
                yield self.sort_input
                yield self.reverse
                yield Static(
                    safe_text(
                        "Available: "
                        + ", ".join(f"{key}={label}" for key, label in self.descriptor.labels)
                    )
                )
                yield Static(
                    "Alignment: auto/left/center/right. All-namespace lists retain namespace.",
                    markup=False,
                )
            with Horizontal(id="view-buttons"):
                yield Button("Apply", id="view-session", compact=True)
                yield Button("Global", id="view-global", compact=True, disabled=not self.writable)
                yield Button(
                    "Context",
                    id="view-context",
                    compact=True,
                    disabled=not self.writable or self.descriptor.context is None,
                )
                yield Button("Back", id="view-back", compact=True)
            yield self.feedback

    def back(self) -> None:
        if self._save_task is not None and not self._save_task.done():
            self.feedback.update("Saving the requested preference; wait before closing.")
        else:
            self.dismiss()

    @on(Button.Pressed, "#view-back")
    def pressed_back(self) -> None:
        self.back()

    @on(Button.Pressed, "#view-session")
    @on(Button.Pressed, "#view-global")
    @on(Button.Pressed, "#view-context")
    def requested(self, event: Button.Pressed) -> None:
        event.stop()
        if self._view_stopped or (self._save_task is not None and not self._save_task.done()):
            return
        try:
            view = applicable_view(
                ViewSpec(
                    parse_column_text(self.columns_input.value),
                    field_key(self.sort_input.value),
                    self.reverse.value,
                    self.descriptor.signature,
                ),
                self.descriptor.fields,
                all_namespaces=self.descriptor.all_namespaces,
                signature=self.descriptor.signature,
            )
        except AppError as error:
            self.feedback.update(str(error))
            return
        mode = (event.button.id or "").removeprefix("view-")
        self.feedback.update("Saving…" if mode != "session" else "Applying…")
        self._save_task = asyncio.create_task(self._perform(view, mode))

    async def _perform(self, view: ViewSpec, mode: str) -> None:
        try:
            message = await self.apply(view, mode)
        except AppError as error:
            if self.feedback.is_attached:
                self.feedback.update(str(error))
            return
        if self.is_attached and not self._view_stopped:
            self.app.notify(message)
            self.dismiss()

    async def on_unmount(self) -> None:
        self._view_stopped = True
        if self._save_task is not None:
            await _finish_owned(self._save_task)


class ViewPreferences:
    """Own local presentation state; no transport, writes or resource values in the cache."""

    def __init__(self, app: KubeRichApp) -> None:
        self.app = app
        self._states: OrderedDict[tuple[str | None, str], _SessionView] = OrderedDict()
        self._table_contexts: dict[str, str | None] = {}

    def _table(self) -> ViewTable:
        table = self.app._active_table
        if not isinstance(table, (PodTable, NamespaceTable, StandardTable)):
            raise AppError("Select a Kubernetes resource before opening :views.")
        return table

    def descriptor(
        self, view: ViewObservation, layout: CustomLayout | None = None
    ) -> ViewDescriptor:
        table = self._table()
        context = (
            view.context or self.app.sessions.request.context or self.app.sessions.catalog.current
        )
        signature = None
        if isinstance(table, CustomTable):
            layout = layout or table.resource_layout
            if layout is None:
                raise AppError("Wait for this discovered resource before opening :views.")
            snapshot = view.snapshot
            if (
                snapshot is not None
                and snapshot.resource == layout.resource
                and snapshot.columns != layout.headers
            ):
                layout = CustomLayout.build(snapshot.resource, snapshot.columns)
            resource = layout.resource
            eligible = tuple(
                f"c{index + 1}"
                for index, header in enumerate(layout.headers)
                if header.format != "name" and header.name.casefold() != "age"
            )
            full = layout.configure(eligible)
            fields = tuple(column.key for column in full.definition.columns)
            labels = tuple((key, full.label(key)) for key in fields)
            key = "server:" + "/".join(
                part for part in (resource.group, resource.version, resource.name) if part
            )
            signature = printer_signature(layout.headers)
        elif isinstance(table, PodTable):
            fields = tuple(column.value for column in PodColumn)
            labels = tuple((key, key.upper()) for key in fields)
            key = "v1/pods"
        elif isinstance(table, NamespaceTable):
            fields = ("name", "status", "age")
            labels = tuple((key, key.upper()) for key in fields)
            key = "v1/namespaces"
        else:
            scope = view.scope
            if scope is None or (scope.resource.name, scope.resource.group) != (
                table.definition.name,
                table.definition.group,
            ):
                raise AppError("Wait for this resource to load before opening :views.")
            fields = tuple(column.key for column in table.definition.columns)
            labels = tuple((key, key.upper()) for key in fields)
            key = "/".join(
                part
                for part in (scope.resource.group, scope.resource.version, scope.resource.name)
                if part
            )
        all_namespaces = (
            bool(
                view.scope is not None
                and view.scope.resource.namespaced
                and view.scope.namespace is None
            )
            if view.scope is not None
            else self.app.sessions.request.all_namespaces
        )
        return ViewDescriptor(
            key, context, view.revision, fields, labels, signature, all_namespaces
        )

    def _current(self, captured: ViewDescriptor) -> bool:
        if not self.app.is_running:
            return False
        try:
            return self.descriptor(self.app.workspace.store.observation) == captured
        except AppError:
            return False

    def _remember(self, descriptor: ViewDescriptor, state: _SessionView) -> None:
        key = descriptor.context, descriptor.key
        self._states[key] = state
        self._states.move_to_end(key)
        while len(self._states) > MAX_HISTORY:
            self._states.popitem(last=False)

    def prepare(
        self, view: ViewObservation, layout: CustomLayout | None = None
    ) -> CustomLayout | None:
        try:
            descriptor = self.descriptor(view, layout)
        except AppError:
            return layout
        choices = self.app.navigation.choices(descriptor.key, descriptor.context)
        state = self._states.get((descriptor.context, descriptor.key))
        if (
            state is None
            or state.source != choices
            or state.signature != descriptor.signature
            or state.fields != descriptor.fields
        ):
            table = self._table()
            default_fields = (
                tuple(
                    column.key
                    for column in CustomLayout.build(
                        layout.resource, layout.headers
                    ).definition.columns
                )
                if layout is not None
                else descriptor.fields
            )
            effective = ViewSpec(
                tuple(ColumnSpec(key) for key in default_fields),
                printer_signature=descriptor.signature,
            )
            problems = []
            for choice in choices:
                try:
                    effective = applicable_view(
                        choice,
                        descriptor.fields,
                        all_namespaces=descriptor.all_namespaces,
                        signature=descriptor.signature,
                    )
                    break
                except AppError as error:
                    problems.append(str(error))
            if problems:
                self.app._column_notice = (
                    problems[0] + " Working defaults or the valid global view are retained."
                )
            state = _SessionView(choices, descriptor.signature, effective, descriptor.fields)
        effective = applicable_view(
            state.effective,
            descriptor.fields,
            all_namespaces=descriptor.all_namespaces,
            signature=descriptor.signature,
        )
        self._remember(descriptor, state)
        table = self._table()
        context_changed = (
            table.id in self._table_contexts
            and self._table_contexts[table.id or ""] != descriptor.context
        )
        self._table_contexts[table.id or ""] = descriptor.context
        if layout is not None:
            custom_keys = [
                column.key
                for column in effective.columns or ()
                if column.key.startswith("c") and column.key[1:].isdigit()
            ]
            if (
                effective.sort.startswith("c")
                and effective.sort[1:].isdigit()
                and effective.sort not in custom_keys
            ):
                custom_keys.append(effective.sort)
            return layout.configure(tuple(custom_keys))
        table.configure_view(effective, force=context_changed)
        return None

    def configure_custom(self, view: ViewObservation) -> None:
        descriptor = self.descriptor(view)
        state = self._states[(descriptor.context, descriptor.key)]
        effective = applicable_view(
            state.effective,
            descriptor.fields,
            all_namespaces=descriptor.all_namespaces,
            signature=descriptor.signature,
        )
        self.app.custom_table.configure_view(effective)

    def remember_sort(self) -> None:
        try:
            descriptor = self.descriptor(self.app.workspace.store.observation)
            table = self._table()
        except AppError:
            return
        state = self._states.get((descriptor.context, descriptor.key))
        if state is not None:
            state.effective = replace(
                state.effective, sort=str(table.sort_column), descending=table.descending
            )
            if table.view_spec is not None:
                table.view_spec = replace(
                    table.view_spec, sort=str(table.sort_column), descending=table.descending
                )

    def columns_changed(self, layout: CustomLayout) -> None:
        descriptor = self.descriptor(self.app.workspace.store.observation, layout)
        table = self.app.custom_table
        effective = ViewSpec(
            tuple(ColumnSpec(column.key) for column in layout.definition.columns),
            table.sort_column,
            table.descending,
            descriptor.signature,
        )
        self._remember(
            descriptor,
            _SessionView(
                self.app.navigation.choices(descriptor.key, descriptor.context),
                descriptor.signature,
                effective,
                descriptor.fields,
            ),
        )
        table.configure_view(effective)

    def open(self) -> None:
        try:
            descriptor = self.descriptor(self.app.workspace.store.observation)
            table = self._table()
            current = ViewSpec(
                table.visible_columns,
                str(table.sort_column),
                table.descending,
                descriptor.signature,
            )
        except AppError as error:
            self.app._set_status(str(error))
            return

        async def apply(view: ViewSpec, mode: str) -> str:
            if not self._current(descriptor):
                raise AppError(
                    "The resource, context or columns changed; reopen :views before applying."
                )
            if mode == "session":
                self._remember(
                    descriptor,
                    _SessionView(
                        self.app.navigation.choices(descriptor.key, descriptor.context),
                        descriptor.signature,
                        view,
                        descriptor.fields,
                    ),
                )
                message = "View applied to this session."
            else:
                source = self.app.preferences
                if source is None or self.app._navigation_invalid:
                    raise AppError(
                        "Correct navigation preferences with config check before saving."
                    )
                context = descriptor.context if mode == "context" else None
                if mode == "context" and context is None:
                    raise AppError("Select a context before saving a context view.")
                updated = self.app.navigation.with_view(descriptor.key, view, context)
                await source.save_navigation(updated)
                self.app.navigation = navigation_from(source.document)
                self._states.pop((descriptor.context, descriptor.key), None)
                message = (
                    "View saved for the captured context."
                    if context is not None
                    else "View saved globally; context overrides still take precedence."
                )
            if self._current(descriptor):
                self.app._column_notice = message
                self.app._render_ready.set()
            return message

        self.app.push_screen(
            ViewScreen(
                descriptor,
                current,
                apply,
                writable=self.app.preferences is not None and not self.app._navigation_invalid,
            )
        )
