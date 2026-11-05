"""Evidence detail stays literal/read-only and owns explicit action cancellation."""

import asyncio
from dataclasses import replace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from kuberich.domain.cluster_diagnostics import (
    DiagnosticIdentity,
    DiagnosticLogMode,
    DiagnosticSourceKind,
)
from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.domain.interactions import CommandHistory
from kuberich.errors import AppError
from kuberich.ui.chrome import WorkspaceChrome
from kuberich.ui.diagnostic_evidence import (
    DiagnosticEvidenceScreen,
    available_log_modes,
    evidence_text,
)
from kuberich.ui.nested import NestedCommands
from tests.support.diagnostic_ui import POD, finding, snapshot
from tests.support.workspace import wait_for


class Host(App):
    def __init__(self, screen):
        super().__init__()
        self.detail = screen

    def compose(self) -> ComposeResult:
        yield Static("Underlying Diagnostics")

    def on_mount(self):
        self.push_screen(self.detail)


def detail(
    *, item=None, current=lambda: True, open_object=None, open_logs=None, refresh=lambda: None
):
    data = snapshot()
    objects, logs = [], []

    async def object_action(ref):
        objects.append(ref)

    async def log_action(mode):
        logs.append(mode)

    screen = DiagnosticEvidenceScreen(
        data.request,
        item or data.findings[0],
        sources=data.sources,
        current=current,
        open_object=open_object or object_action,
        open_logs=open_logs or log_action,
        refresh=refresh,
    )
    return screen, objects, logs


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (120, 30)])
async def test_detail_shows_exact_source_uid_field_paths_times_and_reads_no_logs_on_entry(size):
    screen, objects, logs = detail()
    app = Host(screen)
    async with app.run_test(size=size) as pilot:
        await wait_for(lambda: screen.is_mounted)
        assert objects == logs == []
        assert screen.viewer.region.width > 0 and screen.viewer.region.height > 0
        text = screen.viewer.text
        assert "Severity: error · source: condition" in text
        assert "pod-uid" in text and "event-uid" in text
        assert "status.containerStatuses[0].state.waiting.reason" in text
        assert "Locally observed: 2026-11-05T11:58:50+00:00" in text
        assert "Server reported: 2026-11-05T10:00:00+00:00" in text
        assert "Historical evidence" in text and "forbidden" in text and "partial" in text
        await pilot.press("p")
        await wait_for(lambda: logs == [DiagnosticLogMode.PREVIOUS])
        await pilot.press("l")
        await wait_for(lambda: logs == [DiagnosticLogMode.PREVIOUS, DiagnosticLogMode.CURRENT])
        assert app.screen is screen
        await pilot.press("escape")
        await wait_for(lambda: app.screen is not screen)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["o", "e", "r", "button"])
async def test_explicit_resource_event_refresh_and_back_use_captured_callbacks(action):
    refreshed = []
    item = finding()
    second = replace(
        item.evidence[1],
        key="event-again",
        ref=replace(item.evidence[1].ref, uid="event-2", name="second"),
    )
    screen, objects, logs = detail(
        item=replace(item, evidence=(*item.evidence, second)),
        refresh=lambda: refreshed.append(True),
    )
    app = Host(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: screen.is_mounted)
        if action == "e":
            await pilot.press("n")
            await wait_for(lambda: screen.event_index == 1)
            assert "event-2" in str(screen.status.content)
        if action == "button":
            button = screen.query_one("#diagnostic-back", Button)
            await wait_for(
                lambda: (
                    button.region.width > 0
                    and app.get_widget_at(button.region.x, button.region.y)[0] is button
                )
            )
            assert await pilot.click("#diagnostic-back")
        else:
            await pilot.press(action)
        await wait_for(lambda: app.screen is not screen)
        assert logs == []
        assert objects == ([POD] if action == "o" else [second.ref] if action == "e" else [])
        assert refreshed == ([True] if action == "r" else [])


@pytest.mark.asyncio
async def test_pending_action_yields_to_scope_invalidation_and_is_drained_on_screen_close():
    started, closed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    valid = True

    async def held(mode):
        assert mode is DiagnosticLogMode.CURRENT
        started.set()
        try:
            await release.wait()
        finally:
            closed.set()

    screen, _, _ = detail(current=lambda: valid, open_logs=held)
    app = Host(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: screen.is_mounted)
        await pilot.press("l")
        await wait_for(started.is_set)
        await pilot.press("p")
        assert "already pending" in str(screen.status.content)
        valid = False
        screen.validate_target()
        assert screen.query_one("#diagnostic-current", Button).disabled
        await screen.stop_owned()
        assert closed.is_set() and screen.invalidated
        await pilot.press("escape")
        await wait_for(lambda: app.screen is not screen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        AppError("[bold]Denied\x1b[31m"),
        ConnectionProblem(ConnectionState.TIMEOUT, "Denied synthetic request deadline."),
    ],
    ids=["application", "expected-timeout"],
)
async def test_action_error_and_hostile_provenance_are_literal_and_informational_rows_have_no_actions(
    error,
):
    async def denied(ref):
        raise error

    item = replace(finding(evidence=False), summary="[bold]literal\x1b[31m", log_modes=frozenset())
    screen, _, _ = detail(item=item, open_object=denied)
    app = Host(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: screen.is_mounted)
        assert "[bold]literal" in screen.viewer.text and "\x1b" not in screen.viewer.text
        assert screen.query_one("#diagnostic-event", Button).disabled
        assert screen.query_one("#diagnostic-previous", Button).disabled
        await pilot.press("o")
        await wait_for(lambda: "Denied" in str(screen.status.content))
        assert "\x1b" not in str(screen.status.content) and app.screen is screen


@pytest.mark.asyncio
async def test_invalidated_detail_rejects_public_actions_and_late_errors_cannot_replace_stale_notice():
    valid = True
    started, release, returned = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def delayed(mode):
        started.set()
        try:
            await release.wait()
            raise AppError("obsolete-action-error")
        finally:
            returned.set()

    screen, objects, _ = detail(current=lambda: valid, open_logs=delayed)
    app = Host(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: screen.is_mounted)
        await pilot.press("l")
        await wait_for(started.is_set)
        valid = False
        screen.validate_target()
        screen.action_open_object()
        screen.action_refresh()
        release.set()
        await wait_for(returned.is_set)
        assert "changed" in str(screen.status.content) and "obsolete" not in str(
            screen.status.content
        )
        assert not objects and app.screen is screen
        screen.back()
        await wait_for(lambda: app.screen is not screen)


@pytest.mark.asyncio
async def test_unresolved_detail_has_no_resource_event_or_log_effect_even_through_public_actions():
    screen, objects, logs = detail(
        item=replace(finding(evidence=False), subject=None, log_modes=frozenset())
    )
    app = Host(screen)
    async with app.run_test():
        await wait_for(lambda: screen.is_mounted)
        screen.action_open_object()
        screen.action_open_event()
        screen.action_next_event()
        screen.action_logs("previous")
        assert objects == logs == []
        assert screen.query_one("#diagnostic-open", Button).disabled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier",
    [
        "diagnostic-open",
        "diagnostic-event",
        "diagnostic-next-event",
        "diagnostic-current",
        "diagnostic-previous",
        "diagnostic-refresh",
    ],
)
async def test_real_evidence_buttons_use_the_same_captured_action_ports(identifier):
    item = finding()
    second = replace(
        item.evidence[-1],
        key="second-event",
        ref=replace(item.evidence[-1].ref, name="second", uid="event-2"),
    )
    refreshed = []
    screen, objects, logs = detail(
        item=replace(item, evidence=(*item.evidence, second)),
        refresh=lambda: refreshed.append(True),
    )
    app = Host(screen)
    async with app.run_test() as pilot:
        await wait_for(lambda: screen.is_mounted)
        button = screen.query_one("#" + identifier, Button)
        await wait_for(
            lambda: (
                button.region.width > 0
                and app.get_widget_at(button.region.x, button.region.y)[0] is button
            )
        )
        assert await pilot.click("#" + identifier)
        if identifier in {"diagnostic-open", "diagnostic-event", "diagnostic-refresh"}:
            await wait_for(lambda: app.screen is not screen)
        elif identifier == "diagnostic-next-event":
            assert screen.event_index == 1
        else:
            expected = (
                DiagnosticLogMode.PREVIOUS
                if identifier == "diagnostic-previous"
                else DiagnosticLogMode.CURRENT
            )
            await wait_for(lambda: logs == [expected])
        assert objects == (
            [POD]
            if identifier == "diagnostic-open"
            else [item.evidence[-1].ref]
            if identifier == "diagnostic-event"
            else []
        )
        assert refreshed == ([True] if identifier == "diagnostic-refresh" else [])


@pytest.mark.parametrize(
    "invalid", [None, "subject", "resource", "group", "plural", "kind", "namespace", "container"]
)
def test_name_only_log_candidate_never_invents_previous_instance_or_a_fake_pod_resource(invalid):
    item = replace(
        finding(),
        identity=DiagnosticIdentity.NAME_ONLY,
        source=DiagnosticSourceKind.POPEYE,
        log_modes=frozenset(),
    )
    if invalid == "subject":
        item = replace(item, subject=None)
    elif invalid == "resource":
        item = replace(item, subject=replace(POD, resource=None))
    elif invalid in {"group", "plural", "kind"}:
        change = {
            "group": {"group": "example.test"},
            "plural": {"name": "containers"},
            "kind": {"kind": "Other"},
        }[invalid]
        item = replace(item, subject=replace(POD, resource=replace(POD.resource, **change)))
    elif invalid == "namespace":
        item = replace(item, subject=replace(POD, namespace=None))
    elif invalid == "container":
        item = replace(item, container=None)
    assert available_log_modes(item) == (
        frozenset({DiagnosticLogMode.CURRENT}) if invalid is None else frozenset()
    )
    assert DiagnosticLogMode.PREVIOUS not in available_log_modes(item)


def test_name_only_unresolved_and_tool_metadata_remain_explicit_in_literal_detail():
    data = snapshot()
    item = replace(
        finding(evidence=False),
        subject=None,
        identity=DiagnosticIdentity.NAME_ONLY,
        tool_version="0.22.1",
        source_code="POP-123",
    )
    text = evidence_text(data.request, item, data.sources)
    assert "Subject: unresolved" in text and "report has no UID" in text
    assert "Producer version: 0.22.1" in text and "Source code: POP-123" in text
    assert "No individual evidence items" in text and "unavailable" in text


@pytest.mark.asyncio
async def test_full_native_chrome_and_inline_command_input_keep_keys_out_of_action_callbacks():
    screen, objects, logs = detail()
    app = Host(screen)
    app.chrome = WorkspaceChrome(
        lambda: ("synthetic", "owned", "fixture", "team", "Connected"), "test"
    )
    app.nested_commands = NestedCommands(lambda _: (), CommandHistory(), lambda *_: None)
    async with app.run_test(size=(40, 12)) as pilot:
        await wait_for(lambda: screen.is_mounted and screen.command_input is not None)
        assert screen.viewer.region.height > 0
        screen.focus_command()
        screen.command_input.value = "p"
        await pilot.press("l")
        assert "l" in screen.command_input.value
        assert not logs and not objects
        screen.back()
        assert screen.command_input.value == "" and app.screen is screen
        screen.back()
        await wait_for(lambda: app.screen is not screen)
