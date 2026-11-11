"""Explicit selected-context connection keeps an offline draft and owns cancellation."""

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from textual.widgets import Button, Checkbox, Input

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.domain.commands import Command
from kuberich.domain.connections import ConnectionState
from kuberich.domain.processes import ProcessResult, ProcessStatus
from kuberich.domain.views import ViewStatus
from kuberich.services.appearance import PreferenceSource
from kuberich.services.manifests import ManifestMutationService
from kuberich.services.mutations import MutationManager
from kuberich.services.resource_creation import ResourceCreationService
from kuberich.ui.app import KubeRichApp
from kuberich.ui.manifest_review import ManifestReviewScreen
from kuberich.ui.resource_creation import ResourceCreationScreen
from tests.contract.test_manifest_writes import live_service_fixture
from tests.support.connections import catalog_fixture
from tests.support.manifest_ui import ManifestTestApp, click_ready
from tests.support.resource_creation_cli import CreationServer
from tests.support.workspace import wait_for

BODY = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-connection}\ndata: {private: owned-connection-private}\n"


@asynccontextmanager
async def owned_server(*, hold=False):
    server = CreationServer(hold=False)
    if hold:
        server.namespace_gate.clear()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.namespace_gate.set()
        server.release.set()
        server.stopping.set()
        await asyncio.to_thread(server.shutdown)
        await asyncio.to_thread(thread.join, 3)
        server.server_close()
        await asyncio.to_thread(server.drain_handlers)
        assert not thread.is_alive()


def initial_app(tmp_path, server, *, preferences=None):
    (tmp_path / "draft.yaml").write_text(BODY)
    return KubeRichApp(
        Settings(),
        logging.Logger("owned-explicit-connect"),
        catalog=catalog_fixture(
            tmp_path, f"http://127.0.0.1:{server.server_port}", {"token": "synthetic-pty"}
        ),
        directory=tmp_path,
        environment={"KUBERICH_CONFIG": str(tmp_path / "preferences.yaml")},
        preferences=preferences,
        initial_command=Command.CREATE,
    )


async def capture(app, pilot):
    await wait_for(
        lambda: (
            isinstance(app.screen, ResourceCreationScreen)
            and app.focused is not None
            and app.focused.id == "creation-back"
        )
    )
    screen = app.screen
    screen.file.value = "draft.yaml"
    await click_ready(app, pilot, screen.query_one("#creation-import", Button))
    await wait_for(lambda: "File captured offline" in str(screen.status.render()))
    return screen, screen.service.current_source


@pytest.mark.asyncio
async def test_initial_offline_capture_explicit_connect_review_and_validation_keep_exact_draft(
    tmp_path,
):
    async with owned_server() as server:
        app = initial_app(tmp_path, server)
        async with app.run_test(size=(80, 24)) as pilot:
            creator, source = await capture(app, pilot)
            assert app.sessions.client is None and not server.namespace_requested.is_set()
            assert str(creator.query_one("#creation-review", Button).label) == "Connect & Review"
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(
                lambda: (
                    isinstance(app.screen, ManifestReviewScreen)
                    and app.focused is not None
                    and app.focused.id == "manifest-review-back"
                )
            )
            review = app.screen
            assert review.service.source is source and creator.service.current_source is source
            assert review.service.scope.session.context == "kuberich-test-one"
            await click_ready(app, pilot, review.query_one("#manifest-review-validate", Button))
            await wait_for(lambda: "All resources validated" in str(review.status.render()))
            assert review.plan.ready and not server.values
            assert len(server.requests) == 1 and server.requests[0]["dry_run"]
            await click_ready(app, pilot, review.query_one("#manifest-review-confirm", Button))
            await wait_for(lambda: "Verified persistent creation receipt" in review.viewer.text)
            assert server.values["owned-connection"]["metadata"]["uid"] == "owned-created-uid"
            assert "owned-connection-private" not in review.viewer.text
            await pilot.press("escape")
            await wait_for(lambda: app.screen is creator)
            assert creator.service.current_source is source
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_held_initial_connect_escape_drains_connection_without_self_await_or_post(tmp_path):
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            assert creator.service.current_source is source
            back = asyncio.create_task(pilot.press("escape"))
            try:
                await wait_for(lambda: len(app.screen_stack) == 1)
                assert app.sessions.client is None and not server.requests
                assert app.sessions.observation.state is ConnectionState.DISCONNECTED
            finally:
                server.namespace_gate.set()
                await back
            assert creator.service.current_source is None


@pytest.mark.asyncio
async def test_context_policy_is_applied_before_explicit_connection_even_with_stale_enabled_button(
    tmp_path,
):
    document = parse_document(
        {
            "schema_version": 1,
            "context_settings": {"contexts": {"kuberich-test-one": {"read_only": True}}},
        }
    )
    preferences = PreferenceSource(ConfigLocation(tmp_path / "preferences.yaml", True), document)
    async with owned_server() as server:
        app = initial_app(tmp_path, server, preferences=preferences)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            assert creator.query_one("#creation-review", Button).disabled
            app.commands.policy.restrict(False)
            creator.query_one("#creation-review", Button).disabled = False
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(lambda: "Read-only" in str(creator.status.render()))
            assert app.sessions.client is None and not server.namespace_requested.is_set()
            assert creator.service.current_source is source and not server.requests
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_held_connect_source_replacement_refuses_review_publication(tmp_path):
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            assert source is not None
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            creator.file.value = "replacement.yaml"
            await pilot.pause()
            server.namespace_gate.set()
            await wait_for(lambda: "changed" in str(creator.status.render()))
            assert app.screen is creator and creator.service.current_source is None
            assert not server.requests
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", ["kuberich-test-one", "kuberich-test-Two"])
async def test_superseding_connection_epoch_refuses_review_even_for_same_context_name(
    tmp_path, replacement
):
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            transition = app.workspace.connect(replacement)
            server.namespace_gate.set()
            await transition
            await wait_for(
                lambda: "did not establish current discovery" in str(creator.status.render())
            )
            assert app.screen is creator and creator.service.current_source is source
            assert app.sessions.observation.identity.context == replacement
            assert not server.requests
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_action", ["stop", "back"])
async def test_post_connect_discovery_cancellation_keeps_owned_client_and_retryable_draft(
    tmp_path, monkeypatch, exit_action
):
    from kuberich.services.resources import ResourceReader

    entered, release = asyncio.Event(), asyncio.Event()
    discover = ResourceReader.discover
    calls = []

    async def held(reader):
        calls.append(reader.session)
        if len(calls) == 1:
            entered.set()
            await release.wait()
        return await discover(reader)

    monkeypatch.setattr(ResourceReader, "discover", held)
    async with owned_server() as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(entered.is_set)
            client = app.sessions.client
            identity = app.sessions.observation.identity
            assert (
                client is not None and app.sessions.observation.state is ConnectionState.CONNECTED
            )
            if exit_action == "stop":
                await click_ready(app, pilot, creator.query_one("#creation-stop", Button))
                await wait_for(lambda: "Operation stopped" in str(creator.status.render()))
                assert app.screen is creator and creator.service.current_source is source
            else:
                await pilot.press("escape")
                await wait_for(lambda: len(app.screen_stack) == 1)
            assert app.sessions.client is client and app.sessions.observation.identity == identity
            assert app.workspace.store.observation.status is ViewStatus.FAILED
            assert "cancelled during discovery" in str(app.workspace.store.observation.problem)
            assert not server.requests
            if exit_action == "back":
                await wait_for(lambda: "cancelled during discovery" in str(app.status.render()))
                assert "Retry" in str(app.status.render()) and await app.screen.wait_for_refresh()
            release.set()
            if exit_action == "stop":
                await click_ready(app, pilot, creator.query_one("#creation-review", Button))
                await wait_for(
                    lambda: (
                        isinstance(app.screen, ManifestReviewScreen)
                        and app.focused is not None
                        and app.focused.id == "manifest-review-back"
                    )
                )
                review = app.screen
                assert (
                    app.sessions.client is client and app.sessions.observation.identity == identity
                )
                assert review.service.source is source and calls == [client, client]
                await click_ready(app, pilot, review.query_one("#manifest-review-validate", Button))
                await wait_for(lambda: "All resources validated" in str(review.status.render()))
                assert review.plan.ready and not server.values and len(server.requests) == 1
                await pilot.press("escape")
                await wait_for(lambda: app.screen is creator)
                await pilot.press("escape")
                await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_unchanged_or_stale_initial_namespace_event_cannot_retire_fresh_validation(
    tmp_path, monkeypatch
):
    entered, release = asyncio.Event(), asyncio.Event()
    prepare = ManifestMutationService.prepare

    async def held(owner, action):
        entered.set()
        await release.wait()
        return await prepare(owner, action)

    monkeypatch.setattr(ManifestMutationService, "prepare", held)
    async with live_service_fixture(tmp_path) as (service, api):
        manager = MutationManager()
        screen = ManifestReviewScreen(service=service, manager=manager, action="create")
        app = ManifestTestApp(screen)
        async with app.run_test() as pilot:
            await wait_for(
                lambda: app.focused is not None and app.focused.id == "manifest-review-back"
            )
            await click_ready(app, pilot, screen.query_one("#manifest-review-validate", Button))
            await wait_for(entered.is_set)
            screen.post_message(Input.Changed(screen.namespace, "team"))
            await pilot.pause()
            assert "Review fields changed" not in str(screen.status.render())
            release.set()
            await wait_for(lambda: "All resources validated" in str(screen.status.render()))
            assert screen.plan.ready and api.value is None
            screen.namespace.value = "other"
            await wait_for(lambda: "Review fields changed" in str(screen.status.render()))
            screen.post_message(Input.Changed(screen.namespace, "team"))
            await pilot.pause()
            assert screen.namespace.value == "other" and screen.plan is None
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
        await manager.close()


@pytest.mark.asyncio
async def test_stop_prepares_fresh_consent_for_same_edited_draft_without_recapture(
    tmp_path, monkeypatch
):
    from kuberich.ui import resource_creation

    captures, edits = [], []
    capture_file = ResourceCreationService.capture_file

    async def capture_once(owner, path):
        captures.append(path)
        return await capture_file(owner, path)

    async def handoff(app, runner, command, *, guard):
        guard()
        path = Path(command.argv[-1])
        value = (
            json.loads(path.read_text())
            if edits
            else {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "owned-connection"},
                "data": {"private": "owned-connection-private"},
            }
        )
        if edits:
            assert value["metadata"]["labels"]["example.io/phase"] == "before-stop"
        phase = "after-stop" if edits else "before-stop"
        value["metadata"]["labels"] = {"example.io/phase": phase}
        path.write_text(json.dumps(value))
        edits.append(phase)
        return ProcessResult(ProcessStatus.SUCCEEDED, 0)

    monkeypatch.setattr(ResourceCreationService, "capture_file", capture_once)
    monkeypatch.setattr(resource_creation, "terminal_handoff", handoff)
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, original = await capture(app, pilot)
            creator.query_one("#creation-disclosure", Checkbox).value = True
            await click_ready(app, pilot, creator.query_one("#creation-edit", Button))
            await wait_for(lambda: "Draft updated" in str(creator.status.render()))
            edited = creator.service.current_source
            assert edited is not original and edited is not None
            disclosure = creator.disclosure
            creator.query_one("#creation-disclosure", Checkbox).value = True
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            await click_ready(app, pilot, creator.query_one("#creation-stop", Button))
            await wait_for(
                lambda: (
                    "Operation stopped" in str(creator.status.render())
                    and not creator.query_one("#creation-edit", Button).disabled
                )
            )
            assert creator.service.current_source is edited
            assert creator.service.current_source.generation == edited.generation
            assert creator.disclosure is not None and creator.disclosure is not disclosure
            assert creator.disclosure.source is edited
            assert not creator.query_one("#creation-disclosure", Checkbox).value
            creator.query_one("#creation-disclosure", Checkbox).value = True
            await click_ready(app, pilot, creator.query_one("#creation-edit", Button))
            await wait_for(
                lambda: (
                    edits == ["before-stop", "after-stop"]
                    and "Draft updated" in str(creator.status.render())
                )
            )
            assert len(captures) == 1
            assert (
                json.loads(creator.service.current_source.body)["metadata"]["labels"][
                    "example.io/phase"
                ]
                == "after-stop"
            )
            assert (tmp_path / "draft.yaml").read_text() == BODY and not server.requests
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_back_joins_held_stop_disclosure_before_retiring_foreground(tmp_path, monkeypatch):
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            entered, release = asyncio.Event(), asyncio.Event()
            prepare = ResourceCreationService.prepare_editor

            async def held(owner):
                intent = await prepare(owner)
                entered.set()
                await release.wait()
                return intent

            monkeypatch.setattr(ResourceCreationService, "prepare_editor", held)
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            await click_ready(app, pilot, creator.query_one("#creation-stop", Button))
            await wait_for(entered.is_set)
            assert creator.service.current_source is source and creator.operation_count > 0
            assert creator.query_one("#creation-edit", Button).disabled
            back = asyncio.create_task(pilot.press("escape"))
            try:
                await wait_for(lambda: creator.stopped)
                assert app.screen is creator and creator.operation_count > 0
                assert await creator.wait_for_refresh()
            finally:
                release.set()
                await back
            await wait_for(lambda: len(app.screen_stack) == 1)
            assert creator.disclosure is None and creator.service.current_source is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["readonly", "source"])
async def test_stop_disclosure_rejects_policy_or_source_changed_after_preparation(
    tmp_path, monkeypatch, change
):
    async with owned_server(hold=True) as server:
        app = initial_app(tmp_path, server)
        async with app.run_test() as pilot:
            creator, source = await capture(app, pilot)
            entered, release = asyncio.Event(), asyncio.Event()
            prepare = ResourceCreationService.prepare_editor

            async def held(owner):
                intent = await prepare(owner)
                entered.set()
                await release.wait()
                return intent

            monkeypatch.setattr(ResourceCreationService, "prepare_editor", held)
            await click_ready(app, pilot, creator.query_one("#creation-review", Button))
            await wait_for(server.namespace_requested.is_set)
            await click_ready(app, pilot, creator.query_one("#creation-stop", Button))
            await wait_for(entered.is_set)
            assert creator.service.current_source is source
            if change == "readonly":
                creator.service.policy.tighten()
            else:
                creator.file.value = "different.yaml"
                await pilot.pause()
            release.set()
            await wait_for(lambda: "Source or policy changed" in str(creator.status.render()))
            assert (
                creator.disclosure is None and creator.query_one("#creation-edit", Button).disabled
            )
            assert not server.requests
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
