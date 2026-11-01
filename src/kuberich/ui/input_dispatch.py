"""Serialize terminal input dispatch without transferring App internals."""

import asyncio
from collections.abc import Awaitable, Callable

from textual.app import App
from textual.events import Event, Key, Paste
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input

from kuberich.ui.nested import CommandWorkspace


class InputDispatcher:
    def __init__(
        self,
        host: App[None],
        bindings: Callable[[], tuple[tuple[str, str], ...]],
        open_plugin: Callable[[str], None],
    ) -> None:
        self.host, self.bindings, self.open_plugin = host, bindings, open_plugin
        self._completion: asyncio.Future[None] | None = None

    def release_pending(self) -> None:
        """Release forwarded input when the host begins exception cleanup."""
        if self._completion is not None and not self._completion.done():
            self._completion.set_result(None)

    async def dispatch(self, event: Event, forward: Callable[[Event], Awaitable[None]]) -> None:
        if (
            self.host.screen_stack
            and isinstance(self.host.screen, ModalScreen)
            and isinstance(event, (Key, Paste))
            and not event.is_forwarded
        ):
            from kuberich.ui.terminal import ShellScreen

            if isinstance(self.host.screen, ShellScreen):
                if isinstance(event, Key):
                    if event.key == "ctrl+q" and not (
                        self.host.screen.attach_mode and self.host.screen.detach_pending
                    ):
                        self.host.exit()
                    else:
                        self.host.screen.key(event)
                else:
                    self.host.screen.paste(event)
                event.stop()
                event.prevent_default()
                return
        if (
            isinstance(event, Key)
            and not event.is_forwarded
            and self.host.screen_stack
            and isinstance(self.host.screen, CommandWorkspace)
            and event.key == "colon"
            and not isinstance(self.host.focused, Input)
        ):
            self.host.screen.focus_command()
            event.stop()
            event.prevent_default()
            return
        if (
            isinstance(event, Key)
            and not event.is_forwarded
            and self.host.screen_stack
            and not isinstance(self.host.screen, ModalScreen)
            and isinstance(self.host.focused, DataTable)
        ):
            plugin = dict(self.bindings()).get(event.key)
            if plugin is not None:
                self.open_plugin(plugin)
                event.stop()
                event.prevent_default()
                return
        focused = (
            self.host.focused
            if isinstance(event, Key) and not event.is_forwarded and self.host.screen_stack
            else None
        )
        input_key = (
            isinstance(event, Key)
            and not event.is_forwarded
            and isinstance(focused, Input)
            and event.key not in {"ctrl+q", "ctrl+c"}
        )
        await forward(event)
        if input_key and isinstance(focused, Input):
            # Forwarded printable keys use the widget's queue. Drain that key before
            # a subsequent editing binding or Enter reads the input's value.
            completion: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            self._completion = completion

            def settle() -> None:
                if not completion.done():
                    completion.set_result(None)

            try:
                if focused.call_later(settle):
                    await completion
            finally:
                self._completion = None
