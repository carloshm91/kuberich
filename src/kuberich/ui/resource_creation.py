"""Explicit offline source capture and private editor before separate cluster review."""

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import ClassVar

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Paste
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Select, Static

from kuberich.adapters.editing import file_worker
from kuberich.domain.clipboard import MAX_NATIVE_BYTES, clipboard_backend, pasted_source_bytes
from kuberich.domain.editing import parse_manifest
from kuberich.domain.manifests import FrozenDraftSource, manifest_preview
from kuberich.domain.processes import ProcessStatus
from kuberich.domain.resource_templates import TemplateCatalogEntry, TemplateParameter
from kuberich.errors import AppError
from kuberich.security.presentation import safe_text
from kuberich.services.clipboard import NativeClipboard
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.services.resource_creation import DraftDisclosureIntent, ResourceCreationService
from kuberich.services.resource_templates import TemplateCatalogService
from kuberich.ui.editing import DisclosureCheckbox
from kuberich.ui.handoff import terminal_handoff
from kuberich.ui.port_forwards import ForwardInput
from kuberich.ui.read_only_text import ReadOnlyText


class PasteCapture(Static, can_focus=True):
    """Receive one explicit public Paste event without rendering its contents."""

    def __init__(self, captured: Callable[[str], None]) -> None:
        super().__init__(
            "Paste one manifest here · contents are never echoed",
            markup=False,
            id="creation-paste-capture",
        )
        self.captured = captured

    def on_paste(self, event: Paste) -> None:
        event.stop()
        event.prevent_default()
        if self.has_focus and not self.disabled:
            self.captured(event.text)


class ResourceCreationScreen(ModalScreen[None]):
    AUTO_FOCUS = "#creation-back"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "back", "Back", priority=True),
        Binding("tab", "app.focus_next", "Next field", show=False, priority=True),
        Binding("shift+tab", "app.focus_previous", "Previous field", show=False, priority=True),
    ]
    DEFAULT_CSS = """
    ResourceCreationScreen { align: center middle; background: $background 80%; }
    #creation-form { width: 98%; height: 96%; border: solid $primary;
        padding: 0 1; background: $surface; }
    #creation-title, #creation-source, #creation-status, #creation-page,
    #creation-destination { height: 1; }
    #creation-file { height: 3; }
    #creation-source-choice, #creation-template { height: 3; }
    #creation-parameters { height: auto; max-height: 9; min-height: 1; }
    #creation-parameters Static { height: 1; }
    #creation-parameters Input, #creation-parameters Select { height: 3; }
    #creation-paste-capture { height: 2; border: solid $primary; }
    #creation-paste-capture:focus { background: $primary; }
    #creation-disclosure { height: auto; }
    #creation-preview { height: 1fr; min-height: 2; }
    #creation-buttons { height: 3; layout: grid; grid-size: 4; grid-rows: 1 1 1; }
    #creation-buttons Button { height: 1; border: none; min-width: 0; width: 1fr; }
    ResourceCreationScreen.compact #creation-file { height: 1; border: none; padding: 0 1; }
    ResourceCreationScreen.compact #creation-source-choice,
    ResourceCreationScreen.compact #creation-template,
    ResourceCreationScreen.compact #creation-parameters Input,
    ResourceCreationScreen.compact #creation-parameters Select { height: 1; border: none; padding: 0 1; }
    ResourceCreationScreen.compact #creation-parameters { max-height: 6; }
    """

    def __init__(
        self,
        *,
        service: ResourceCreationService,
        runner: ProcessRunner,
        open_review: Callable[[FrozenDraftSource], None],
        catalog: TemplateCatalogService | None = None,
        selected_context: str | None = None,
        connection_ready: Callable[[], bool] | None = None,
        connect_review: Callable[[FrozenDraftSource], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__()
        self.service, self.runner, self.open_review = service, runner, open_review
        self.selected_context = selected_context
        self.connection_ready = connection_ready or (lambda: False)
        self.connect_review = connect_review
        self.catalog = catalog or TemplateCatalogService(
            service.directory / "config.yaml", service.directory
        )
        self.native = NativeClipboard(runner, service.environment, service.directory)
        self.source_choice: Select[str] = Select(
            (
                ("Built-in template", "builtin"),
                ("User template", "user"),
                ("File", "file"),
                ("Clipboard / paste", "clipboard"),
            ),
            value="file",
            allow_blank=False,
            id="creation-source-choice",
        )
        self.template_choice: Select[int] = Select(
            (), id="creation-template", prompt="Choose an available template"
        )
        self.parameters = VerticalScroll(id="creation-parameters")
        self.paste_capture = PasteCapture(self._paste)
        self.entries: tuple[TemplateCatalogEntry, ...] = ()
        self.entry: TemplateCatalogEntry | None = None
        self.parameter_inputs: dict[str, Input | Select[str]] = {}
        self.parameter_presence: dict[str, Checkbox] = {}
        self._capture_generation = 0
        self._paste_armed = False
        self.file = ForwardInput(
            placeholder="Explicit local manifest file path", id="creation-file", max_length=4096
        )
        self.viewer = ReadOnlyText("", read_only=True, id="creation-preview")
        self.status = Static(
            "Import is offline. No cluster validation or clipboard read occurs automatically.",
            markup=False,
            id="creation-status",
        )
        self.pages: tuple[str, ...] = ()
        self.page = 0
        self.disclosure: DraftDisclosureIntent | None = None
        self._operation_task: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[None] | None = None
        self._stopped = False
        self._cleanup_failed = False

    @property
    def stopped(self) -> bool:
        return self._stopped and not self._cleanup_failed

    @property
    def operation_count(self) -> int:
        return (
            int(self._operation_task is not None and not self._operation_task.done())
            + int(self._stopping is not None and not self._stopping.done())
            + self.service.operation_count
            + self.catalog.operation_count
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="creation-form"):
            yield Static("Create resources · offline source", markup=False, id="creation-title")
            yield Static("No source captured", markup=False, id="creation-source")
            yield Static(
                safe_text(
                    f"Selected context: {self.selected_context} · Connect & Review is explicit"
                    if self.selected_context
                    else "No selected context · source capture remains offline"
                ),
                id="creation-destination",
            )
            yield self.source_choice
            yield self.template_choice
            yield self.parameters
            yield self.file
            yield self.paste_capture
            yield DisclosureCheckbox(
                "I allow my trusted editor to receive the full draft, including sensitive values.",
                id="creation-disclosure",
            )
            yield self.viewer
            yield Static("Redacted draft preview", markup=False, id="creation-page")
            yield self.status
            with Horizontal(id="creation-buttons"):
                for label, name in (
                    ("Import file", "import"),
                    ("Render template", "render"),
                    ("Read clipboard", "clipboard"),
                    ("Capture paste", "paste"),
                    ("Edit draft", "edit"),
                    ("Review Create", "review"),
                    ("Stop", "stop"),
                    ("Previous page", "previous"),
                    ("Next page", "next"),
                    ("Back", "back"),
                ):
                    yield Button(label, compact=True, id="creation-" + name)

    def on_mount(self) -> None:
        self.on_resize()
        self._controls()

    def on_resize(self) -> None:
        self.set_class(self.size.height < 28, "compact")

    def _current(self) -> bool:
        return not self._stopped and self.is_attached and self.app.screen is self

    def _controls(self) -> None:
        if not self.viewer.is_attached:
            return
        busy = (self._operation_task is not None and not self._operation_task.done()) or (
            self._stopping is not None and not self._stopping.done()
        )
        source = self.service.current_source
        choice = self.source_choice.value
        template = choice in {"builtin", "user"}
        self.source_choice.disabled = busy or self._stopped
        self.template_choice.display = template
        self.template_choice.disabled = busy or self._stopped
        self.parameters.display = template
        self.file.display = choice == "file"
        self.paste_capture.display = choice == "clipboard" and self._paste_armed
        self.paste_capture.disabled = busy or self._stopped
        for control in self.parameter_inputs.values():
            control.disabled = busy or self._stopped
        for presence in self.parameter_presence.values():
            presence.disabled = busy or self._stopped
        self.file.disabled = busy or self._stopped
        self.query_one("#creation-import", Button).display = choice == "file"
        self.query_one("#creation-import", Button).disabled = busy or self._stopped
        self.query_one("#creation-render", Button).display = template
        self.query_one("#creation-render", Button).disabled = (
            busy or self._stopped or self.entry is None or not self.entry.enabled
        )
        for name in ("clipboard", "paste"):
            self.query_one("#creation-" + name, Button).display = choice == "clipboard"
            self.query_one("#creation-" + name, Button).disabled = busy or self._stopped
        self.query_one("#creation-edit", Button).disabled = (
            busy or self._stopped or self.service.policy.read_only or self.disclosure is None
        )
        self.query_one("#creation-review", Button).disabled = (
            busy or self._stopped or source is None or self.service.policy.read_only
        )
        self.query_one("#creation-review", Button).label = (
            "Connect & Review"
            if not self.connection_ready()
            and self.connect_review is not None
            and self.selected_context is not None
            else "Review Create"
        )
        self.query_one("#creation-disclosure", Checkbox).disabled = (
            busy or self._stopped or self.service.policy.read_only or source is None
        )
        self.query_one("#creation-stop", Button).disabled = not busy
        self.query_one("#creation-previous", Button).disabled = self.page <= 0
        self.query_one("#creation-next", Button).disabled = self.page + 1 >= len(self.pages)

    def _start(self, operation: Callable[[], Awaitable[str]]) -> None:
        if (
            self._stopped
            or (self._operation_task is not None and not self._operation_task.done())
            or (self._stopping is not None and not self._stopping.done())
        ):
            return
        self._operation_task = asyncio.create_task(self._run(operation))
        self._operation_task.add_done_callback(self._retired)
        self._controls()

    async def _run(self, operation: Callable[[], Awaitable[str]]) -> None:
        feedback = ""
        try:
            feedback = await operation()
        except AppError as error:
            feedback = str(error)
        except Exception:
            feedback = "Creation source operation failed; private details withheld."
        finally:
            if self._current():
                self._operation_task = None
                self._controls()
                self.set_focus(self.query_one("#creation-back", Button))
                if feedback:
                    self.status.update(safe_text(feedback))

    def _retired(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        if self._operation_task is task:
            self._operation_task = None
        self._controls()

    async def _show_source(self) -> None:
        source = self.service.current_source
        self.pages = (
            await file_worker(
                lambda: manifest_preview(None, source.body, private=source.private_preview)
            )
            if source
            else ()
        )
        self.page = 0
        if self._current():
            self.query_one("#creation-source", Static).update(
                safe_text(
                    f"{source.kind.title()} · {len(source.documents)} resources · local syntax passed; server validation not requested"
                    if source
                    else "No source captured"
                )
            )
            self._page()
        self.disclosure = (
            await self.service.prepare_editor()
            if source is not None and not self.service.policy.read_only
            else None
        )

    def _page(self) -> None:
        if self._current():
            self.viewer.load_text(self.pages[self.page] if self.pages else "")
            self.query_one("#creation-page", Static).update(
                f"Redacted draft preview · page {self.page + 1 if self.pages else 0}/{len(self.pages)}"
            )
            self._controls()

    async def _import_file(self) -> str:
        self.disclosure = None
        await self.service.capture_file(Path(self.file.value))
        await self._show_source()
        return "File captured offline · allow fresh editor disclosure or explicitly Review Create."

    def _clear_capture(self) -> None:
        self._capture_generation += 1
        self._paste_armed = False
        self.service.invalidate()
        self.disclosure = None
        self.pages = ()
        self.page = 0
        self._page()
        if self._current():
            self.query_one("#creation-source", Static).update(
                "No source captured · fresh local capture required"
            )

    @on(Select.Changed, "#creation-source-choice")
    def source_changed(self) -> None:
        if self.is_mounted and self._current():
            self._clear_capture()
            self.entry = None
            if self.source_choice.value in {"builtin", "user"}:
                self._start(self._load_templates)
            self._controls()

    async def _load_templates(self) -> str:
        generation = self._capture_generation
        entries = await self.catalog.load()
        if generation != self._capture_generation or not self._current():
            raise AppError("Source choice changed; load a fresh template catalog.")
        self.entries = tuple(entry for entry in entries if entry.origin == self.source_choice.value)
        self.template_choice.set_options(
            (
                safe_text(
                    f"{entry.origin}/{entry.identity[1]} r{entry.identity[2]}"
                    + (" · unavailable" if not entry.enabled else "")
                ),
                index,
            )
            for index, entry in enumerate(self.entries)
        )
        self.template_choice.value = Select.NULL
        await self.parameters.remove_children()
        self.parameter_inputs.clear()
        self.parameter_presence.clear()
        return (
            "Choose a template · invalid and duplicate entries cannot render. "
            + str(len(self.entries))
            + " entries."
        )

    @on(Select.Changed, "#creation-template")
    def template_changed(self, event: Select.Changed) -> None:
        if not self.is_mounted or not self._current():
            return
        self._clear_capture()
        self.entry = (
            self.entries[event.value]
            if type(event.value) is int and 0 <= event.value < len(self.entries)
            else None
        )
        self._start(self._parameter_form)

    async def _parameter_form(self) -> str:
        await self.parameters.remove_children()
        self.parameter_inputs.clear()
        self.parameter_presence.clear()
        entry = self.entry
        if entry is None:
            return "Choose an available template."
        if not entry.enabled or entry.template is None:
            return entry.problem or "This template is unavailable."
        for index, parameter in enumerate(entry.template.parameters):
            label = Static(
                safe_text(
                    f"{parameter.name} · {parameter.type} · "
                    + (
                        "default available"
                        if parameter.has_default
                        else "required"
                        if parameter.required
                        else "optional"
                    )
                    + (" · sensitive (masked)" if parameter.sensitive else "")
                ),
                markup=False,
            )
            control: Input | Select[str]
            absent = "Use declared default" if parameter.has_default else "Not supplied"
            if parameter.enum:
                control = Select(
                    (
                        (absent, "absent"),
                        *(
                            (f"Option {choice + 1} ({parameter.type})", str(choice))
                            for choice in range(len(parameter.enum))
                        ),
                    ),
                    value="absent",
                    allow_blank=False,
                    id=f"creation-parameter-{index}",
                )
            elif parameter.type == "boolean":
                control = Select(
                    ((absent, "absent"), ("False", "false"), ("True", "true")),
                    value="absent",
                    allow_blank=False,
                    id=f"creation-parameter-{index}",
                )
            else:
                control = Input(
                    placeholder=absent
                    + (" · literal mapping" if parameter.type == "string_map" else ""),
                    password=parameter.sensitive,
                    max_length=1024 * 1024,
                    id=f"creation-parameter-{index}",
                )
            self.parameter_inputs[parameter.name] = control
            if parameter.type == "string" and not parameter.enum:
                present = Checkbox(
                    "Supply an explicit string (empty is permitted)",
                    value=parameter.required and not parameter.has_default,
                    id=f"creation-parameter-presence-{index}",
                )
                self.parameter_presence[parameter.name] = present
                await self.parameters.mount(label, present, control)
            else:
                await self.parameters.mount(label, control)
        return "Typed parameters replace whole values. Defaults and enum contents stay hidden; trusted-editor disclosure can inspect the rendered draft."

    @on(Input.Changed)
    def parameter_changed(self, event: Input.Changed) -> None:
        if event.input.id and event.input.id.startswith("creation-parameter-") and self.is_mounted:
            if event.value:
                for name, control in self.parameter_inputs.items():
                    if control is event.input and name in self.parameter_presence:
                        self.parameter_presence[name].value = True
            self._clear_capture()

    @on(Checkbox.Changed)
    def parameter_presence_changed(self, event: Checkbox.Changed) -> None:
        if (
            event.checkbox.id
            and event.checkbox.id.startswith("creation-parameter-presence-")
            and self.is_mounted
        ):
            self._clear_capture()

    @on(Select.Changed)
    def parameter_selected(self, event: Select.Changed) -> None:
        if (
            event.select.id
            and event.select.id.startswith("creation-parameter-")
            and self.is_mounted
        ):
            self._clear_capture()

    @staticmethod
    def _parameter_value(
        parameter: TemplateParameter, raw: str | None, present: bool | None
    ) -> tuple[bool, object]:
        if parameter.enum or parameter.type == "boolean":
            if raw == "absent" or raw is None:
                return False, None
            if parameter.enum:
                return True, json.loads(parameter.enum[int(raw)])
            if raw not in {"false", "true"}:
                raise AppError("Boolean parameter requires an explicit true or false choice.")
            return True, raw == "true"
        text = raw or ""
        if parameter.type == "string":
            return (True, text) if present else (False, None)
        if not text:
            return False, None
        if parameter.type == "integer":
            try:
                return True, int(text)
            except ValueError:
                raise AppError("Integer parameter requires a complete decimal value.") from None
        if parameter.type == "string_map":
            return True, parse_manifest(text.encode("utf-8"))
        return True, text

    async def _render_template(self) -> str:
        entry = self.entry
        if entry is None or entry.template is None or not entry.enabled:
            raise AppError("Choose an available unambiguous template.")
        captured = tuple(
            (
                parameter,
                raw
                if isinstance(raw := self.parameter_inputs[parameter.name].value, str)
                else None,
                self.parameter_presence[parameter.name].value
                if parameter.name in self.parameter_presence
                else None,
            )
            for parameter in entry.template.parameters
        )
        self._clear_capture()
        generation = self._capture_generation

        def parse() -> dict[str, object]:
            values: dict[str, object] = {}
            for parameter, raw, supplied in captured:
                present, value = self._parameter_value(parameter, raw, supplied)
                if present:
                    values[parameter.name] = value
            return values

        values = await file_worker(parse)
        self._capture_guard(generation)
        await self.service.capture_template(entry, values, self.catalog)
        self._capture_guard(generation)
        await self._show_source()
        return "Template rendered offline · typed local checks passed; strict server validation remains separate."

    def _capture_guard(self, generation: int) -> None:
        if not self._current() or generation != self._capture_generation:
            raise AppError("Creation capture changed; import an explicit fresh source.")

    async def _read_clipboard(self) -> str:
        self._clear_capture()
        generation = self._capture_generation
        backend = clipboard_backend(
            self.service.environment, sys.platform, headless=self.app.is_headless
        )
        data = await self.native.read(backend, guard=lambda: self._capture_guard(generation))
        self._capture_guard(generation)
        await self.service.capture_bytes(data, "clipboard", "Explicit clipboard capture")
        await self._show_source()
        return "Clipboard captured once · confirmation uses this frozen draft and never rereads the clipboard."

    def _paste(self, text: str) -> None:
        if not self._paste_armed or not self.paste_capture.has_focus or not self._current():
            return
        self._paste_armed = False
        if len(text) > MAX_NATIVE_BYTES:
            self.status.update("Paste exceeds the 1024 KiB backend limit; select less text.")
            self._controls()
            return
        generation = self._capture_generation

        async def capture() -> str:
            data = await file_worker(lambda: pasted_source_bytes(text))
            self._capture_guard(generation)
            await self.service.capture_bytes(data, "paste", "Explicit paste capture")
            self._capture_guard(generation)
            await self._show_source()
            return "Paste captured without echo · review the redacted draft before separate server validation."

        self._start(capture)

    async def _edit(self) -> str:
        disclosure, self.disclosure = self.disclosure, None
        if disclosure is None:
            raise AppError("Capture a valid draft before editing.")
        self.query_one("#creation-disclosure", Checkbox).value = False
        command = await self.service.open_editor(self.service.confirm_disclosure(disclosure))
        try:
            result = await terminal_handoff(
                self.app, self.runner, command, guard=self.service.require_editor_current
            )
            changed = await self.service.finish_editor(
                succeeded=result.status is ProcessStatus.SUCCEEDED
            )
            await self._show_source()
            return (
                "Editor cancelled or failed; prior draft retained."
                if result.status is not ProcessStatus.SUCCEEDED
                else "Draft updated · review the redacted preview; validation must be fresh."
                if changed is not None
                else "No changes; prior draft retained."
            )
        finally:
            await self.service.close_draft()
            if self._current() and self.service.current_source is not None:
                self.disclosure = await self.service.prepare_editor()

    async def _connect_review(self, source: FrozenDraftSource) -> str:
        callback = self.connect_review
        if callback is None:
            raise AppError("Select a configured context before connecting for creation review.")
        self.status.update("Connecting the explicit selected context; frozen draft retained…")
        await callback(source)
        return ""

    @on(Input.Changed, "#creation-file")
    def file_changed(self) -> None:
        if self.is_mounted and self._current():
            self._clear_capture()

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        event.stop()
        name = (event.button.id or "").removeprefix("creation-")
        if name == "import":
            self._start(self._import_file)
        elif name == "render":
            self._start(self._render_template)
        elif name == "clipboard":
            self._start(self._read_clipboard)
        elif name == "paste":
            self._clear_capture()
            self._paste_armed = True
            self._controls()
            self.set_focus(self.paste_capture)
            self.status.update(
                "Paste one manifest into the focused capture; raw content is never echoed."
            )
        elif name == "edit":
            if not self.query_one("#creation-disclosure", Checkbox).value:
                self.status.update("Allow fresh editor disclosure before opening the draft.")
            else:
                self._start(self._edit)
        elif name == "review" and self.service.current_source is not None:
            source = self.service.current_source
            if (
                not self.connection_ready()
                and self.connect_review is not None
                and self.selected_context is not None
            ):
                self._start(lambda: self._connect_review(source))
            else:
                self.open_review(source)
        elif name in {"previous", "next"} and self.pages:
            self.page = max(0, min(len(self.pages) - 1, self.page + (1 if name == "next" else -1)))
            self._page()
        elif name == "stop":
            self.run_worker(self.action_stop())
        elif name == "back":
            self.run_worker(self.action_back())

    async def action_stop(self) -> None:
        if self._stopping is None or self._stopping.done():
            self._stopping = asyncio.create_task(self._stop_action())
        stopping = self._stopping
        self._controls()
        try:
            await finish_owned(stopping)
        finally:
            if self._stopping is stopping and stopping.done():
                self._stopping = None
            self._controls()

    async def _stop_action(self) -> None:
        task = self._operation_task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))
        self._operation_task = None
        await self.service.close_draft()
        self.disclosure = None
        source, generation = self.service.current_source, self._capture_generation
        if self._current():
            self.query_one("#creation-disclosure", Checkbox).value = False
            if source is not None and not self.service.policy.read_only:
                try:
                    disclosure = await self.service.prepare_editor()
                except AppError as error:
                    if self._current():
                        self.status.update(safe_text(str(error)))
                    return
                if (
                    not self._current()
                    or self.service.current_source is not source
                    or disclosure.source is not source
                    or self._capture_generation != generation
                    or self.service.policy.read_only
                ):
                    if self._current():
                        self.status.update(
                            "Source or policy changed · fresh editor disclosure required."
                        )
                    return
                self.disclosure = disclosure
        if self._current():
            self.status.update(
                "Operation stopped · read-only mode blocks fresh editor disclosure and creation."
                if self.service.policy.read_only
                else "Operation stopped · frozen draft retained; explicitly Review or capture a new source."
                if self.service.current_source is not None
                else "Operation stopped · capture a fresh source."
            )

    async def action_back(self) -> None:
        await self.stop_owned()
        self.dismiss()

    async def stop_owned(self) -> None:
        self._stopped = True
        failures: list[BaseException] = []
        for close in (self.action_stop, self.service.close, self.catalog.close, self.native.close):
            try:
                await close()
            except BaseException as error:
                failures.append(error)
        self._cleanup_failed = bool(failures)
        for control in self.parameter_inputs.values():
            if isinstance(control, Input):
                control.value = ""
        self.parameter_inputs.clear()
        self.parameter_presence.clear()
        self.entry, self.entries = None, ()
        self.pages = ()
        if self.viewer.is_attached and self.app.screen_stack:
            self.viewer.load_text("")
        if len(failures) == 1:
            raise failures[0]
        if failures:
            raise BaseExceptionGroup("Creation owners could not completely close.", failures)

    async def on_unmount(self) -> None:
        await self.stop_owned()
