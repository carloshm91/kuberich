"""Observable offline import, editor consent and separate creation review controls."""

import asyncio
import logging

import pytest
from textual.widgets import Button

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.commands import Command
from kuberich.services.commands import CommandService
from kuberich.services.processes import ProcessRunner
from kuberich.services.sessions import SessionService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.resource_creation import ResourceCreationScreen
from tests.support.manifest_ui import click_ready
from tests.support.workspace import wait_for


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 36)])
async def test_create_source_capture_is_offline_and_preview_is_redacted(
    tmp_path, monkeypatch, size
):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline creation import attempted helper or cluster connection")

    monkeypatch.setattr(SessionService, "connect", forbidden)
    monkeypatch.setattr(ProcessRunner, "capture", forbidden)
    source = tmp_path / "owned.yaml"
    original = b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\ndata: {private: creation-pilot-private}\n"
    source.write_bytes(original)
    app = KubeRichApp(
        Settings(),
        logging.Logger("owned-creation"),
        catalog=KubeCatalog(),
        directory=tmp_path,
        initial_command=Command.CREATE,
    )
    async with app.run_test(size=size) as pilot:
        await wait_for(lambda: isinstance(app.screen, ResourceCreationScreen))
        screen = app.screen
        assert app.focused.id == "creation-back"
        screen.file.value = "owned.yaml"
        await click_ready(app, pilot, screen.query_one("#creation-import", Button))
        await wait_for(
            lambda: (
                "File captured offline" in str(screen.status.render())
                and screen.service.current_source is not None
                and not screen.query_one("#creation-review", Button).disabled
            )
        )
        assert app.sessions.client is None and "creation-pilot-private" not in screen.viewer.text
        assert "[REDACTED]" in screen.viewer.text and source.read_bytes() == original
        await click_ready(app, pilot, screen.query_one("#creation-edit", Button))
        await wait_for(lambda: "Allow fresh editor disclosure" in str(screen.status.render()))
        await click_ready(app, pilot, screen.query_one("#creation-review", Button))
        assert app.screen is screen and app.sessions.client is None
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)
    assert app.manifests.operation_count == 0


@pytest.mark.asyncio
async def test_read_only_source_remains_inspectable_and_editor_review_are_disabled(tmp_path):
    source = tmp_path / "owned.yaml"
    source.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\n")
    app = KubeRichApp(
        Settings(read_only=True),
        logging.Logger("owned-read-only-creation"),
        catalog=KubeCatalog(),
        directory=tmp_path,
        initial_command=Command.CREATE,
    )
    async with app.run_test() as pilot:
        await wait_for(lambda: isinstance(app.screen, ResourceCreationScreen))
        screen = app.screen
        screen.file.value = "owned.yaml"
        await click_ready(app, pilot, screen.query_one("#creation-import", Button))
        await wait_for(lambda: "File captured offline" in str(screen.status.render()))
        assert screen.service.current_source is not None
        assert screen.query_one("#creation-review", Button).disabled
        assert screen.query_one("#creation-edit", Button).disabled
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


def test_create_command_is_local_and_rejects_unreviewed_arguments():
    from kuberich.services.access import AccessPolicy

    commands = CommandService(AccessPolicy(True))
    assert commands.resolve(":create") is Command.CREATE
    with pytest.raises(Exception, match="without arguments"):
        commands.resolve(":create owned.yaml")


@pytest.mark.asyncio
async def test_root_escape_keeps_creation_foreground_until_public_owner_close(
    tmp_path, monkeypatch
):
    from kuberich.services.resource_creation import ResourceCreationService

    app = KubeRichApp(
        Settings(),
        logging.Logger("owned-creation-escape"),
        catalog=KubeCatalog(),
        directory=tmp_path,
        initial_command=Command.CREATE,
    )
    async with app.run_test() as pilot:
        await wait_for(lambda: isinstance(app.screen, ResourceCreationScreen))
        screen = app.screen
        entered, release = asyncio.Event(), asyncio.Event()
        close = ResourceCreationService.close

        async def held(owner):
            if owner is screen.service:
                entered.set()
                await release.wait()
            await close(owner)

        monkeypatch.setattr(ResourceCreationService, "close", held)
        escape = asyncio.create_task(pilot.press("escape"))
        try:
            await wait_for(entered.is_set)
            assert app.screen is screen and len(app.screen_stack) == 2
        finally:
            release.set()
            await escape
        await wait_for(lambda: len(app.screen_stack) == 1)
