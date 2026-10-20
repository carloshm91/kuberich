"""Open a configured jump from the selected row into its target view."""

from typing import TYPE_CHECKING

from kuberich.config.jumps import jumps_from
from kuberich.domain.jumps import JumpDefinition, Jumps, resolve_jump
from kuberich.domain.navigation import NamespaceChoice
from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.errors import AppError
from kuberich.services.commands import GenericResourceCommand

if TYPE_CHECKING:
    from kuberich.domain.resources import ResourceRecord
    from kuberich.ui.app import KubeRichApp

_BUILT_IN = frozenset({("", "pods"), *((item.group, item.name) for item in STANDARD_RESOURCES)})


class JumpController:
    def __init__(self, app: "KubeRichApp") -> None:
        self.app = app
        self.jumps = Jumps()
        self.error: str | None = None
        if app.preferences is not None:
            try:
                self.jumps = jumps_from(app.preferences.document)
            except AppError as error:
                self.error = str(error)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(jump.name for jump in self.jumps.definitions)

    def open(self, name: str | None = None) -> None:
        app = self.app
        if self.error is not None:
            app._set_status(f"Jumps are unavailable: {self.error} Run kuberich config check.")
            return
        captured = app._capture_target()
        if captured is None:
            return
        _, resource, record, _, _ = captured
        source = f"{resource.api_version}/{resource.name}"
        choices = self.jumps.available(source)
        if name is not None:
            choices = tuple(jump for jump in choices if jump.name == name)
        if len(choices) != 1:
            app._set_status(
                f"No jump named {name} for {source}."
                if name is not None
                else f"No jump is configured for {source}."
                if not choices
                else f"Jumps for {source}: {', '.join(j.name for j in choices)}. Use :jump NAME."
            )
            return
        try:
            self._open(choices[0], record)
        except AppError as error:
            app._set_status(str(error))

    def _open(self, jump: JumpDefinition, record: "ResourceRecord") -> None:
        """Render from the captured row, then open the target view with its filter."""
        app = self.app
        discovery = app.workspace.discovery
        if discovery is None:
            raise AppError("Wait for the current resource catalogue or use :refresh.")
        *group, version, plural = jump.target.split("/")
        target = discovery.resolve(plural, group="".join(group), version=version)
        result = resolve_jump(jump, record.manifest, record.namespace, target.namespaced)
        if (target.group, target.name) in _BUILT_IN and target == discovery.resolve(
            target.name, group=target.group
        ):
            # Built-in views follow the served preferred version.
            view = target.name
            app._select_resource(
                view,
                scope=None
                if result.namespace is None
                else NamespaceChoice(None if result.namespace == "*" else result.namespace),
            )
        else:
            view = f"{target.name}.{target.group or 'core'}"
            app._apply_generic(
                GenericResourceCommand(target.name, target.group, target.version, result.namespace)
            )
        if app._resource_name == view:
            app.filter_input.value = result.query
