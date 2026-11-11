"""A private editor cannot move hidden values into public resource identities."""

import json
from pathlib import Path

import pytest
from textual.widgets import Button, Checkbox

from kuberich.domain.manifests import canonical_manifest
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.ui import resource_creation
from tests.support.manifest_ui import click_ready
from tests.support.workspace import wait_for
from tests.ui.test_resource_creation_sources import owned_app, select_template, source_screen

PRIVATE = "owned-private-routing-sentinel"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["name", "namespace"])
async def test_private_editor_identity_refusal_is_visible_and_preserves_the_captured_draft(
    tmp_path, monkeypatch, field
):
    edits = []

    async def handoff(app, runner, command, *, guard):
        guard()
        path = Path(command.argv[-1])
        value = json.loads(path.read_bytes())
        if not edits:
            value["metadata"][field] = PRIVATE
        else:
            value["metadata"]["annotations"] = {PRIVATE: PRIVATE}
        path.write_bytes(canonical_manifest(value))
        edits.append(path)
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(resource_creation, "terminal_handoff", handoff)
    app = owned_app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await source_screen(app)
        await select_template(screen, "builtin", "configmap")
        screen.parameter_inputs["name"].value = "owned-public-name"
        screen.parameter_inputs["data"].value = json.dumps({PRIVATE: PRIVATE})
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-render", Button))
        await wait_for(lambda: "Template rendered offline" in str(screen.status.render()))
        source = screen.service.current_source
        assert source is not None and source.private_preview
        consent = screen.query_one("#creation-disclosure", Checkbox)
        consent.value = True
        await click_ready(app, pilot, screen.query_one("#creation-edit", Button))
        await wait_for(
            lambda: "preserve the captured resource identities" in str(screen.status.render())
        )
        assert await screen.wait_for_refresh()
        assert screen.service.current_source is source and not edits[0].exists()
        assert PRIVATE not in screen.viewer.text + str(screen.status.render())
        assert app.sessions.client is None and screen.operation_count == 0
        consent.value = True
        await click_ready(app, pilot, screen.query_one("#creation-edit", Button))
        await wait_for(lambda: "Draft updated" in str(screen.status.render()))
        changed = screen.service.current_source
        assert changed is not None and changed is not source and changed.private_preview
        assert changed.documents[0].name == "owned-public-name"
        assert PRIVATE not in screen.viewer.text + str(screen.status.render())
        assert all(not path.exists() for path in edits) and app.sessions.client is None
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)
