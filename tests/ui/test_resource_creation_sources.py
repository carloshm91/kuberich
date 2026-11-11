"""Public template forms, explicit native capture and focused non-echo paste."""

import json
import logging

import pytest
from textual.events import Paste
from textual.widgets import Button, Input, Select

from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.services.clipboard import NativeClipboard
from kuberich.ui.app import KubeRichApp
from kuberich.ui.resource_creation import ResourceCreationScreen
from tests.support.manifest_ui import click_ready
from tests.support.workspace import wait_for

BODY = "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned-paste}\ndata: {private: source-ui-private}\n"


def owned_app(tmp_path, *, environment=None):
    return KubeRichApp(
        Settings(),
        logging.Logger("owned-creation-sources"),
        catalog=KubeCatalog(),
        directory=tmp_path,
        environment=environment or {},
    )


async def source_screen(app):
    await app.run_command(":create")
    await wait_for(
        lambda: (
            isinstance(app.screen, ResourceCreationScreen)
            and app.focused is not None
            and app.focused.id == "creation-back"
            and app.screen.source_choice.region.area > 0
        )
    )
    assert await app.screen.wait_for_refresh()
    return app.screen


async def select_template(screen, origin, template_id):
    screen.source_choice.value = origin
    await wait_for(lambda: "Choose a template" in str(screen.status.render()) and screen.entries)
    index = next(
        index for index, entry in enumerate(screen.entries) if entry.identity[1] == template_id
    )
    screen.template_choice.value = index
    await wait_for(
        lambda: "Typed parameters" in str(screen.status.render()) and screen.parameter_inputs
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 36)])
async def test_builtin_deployment_form_preserves_zero_and_invalidates_replaced_value(
    tmp_path, size
):
    app = owned_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        screen = await source_screen(app)
        await select_template(screen, "builtin", "deployment")
        assert len(screen.entries) == 6 and app.sessions.client is None
        screen.parameter_inputs["name"].value = "owned-workload"
        screen.parameter_inputs["image"].value = "example.invalid/owned:v1"
        screen.parameter_inputs["replicas"].value = "invalid-integer"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-render", Button))
        await wait_for(lambda: "Integer parameter" in str(screen.status.render()))
        assert screen.service.current_source is None
        screen.parameter_inputs["replicas"].value = "0"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-render", Button))
        await wait_for(lambda: "Template rendered offline" in str(screen.status.render()))
        source = screen.service.current_source
        value = json.loads(source.body)
        assert value["spec"]["replicas"] == 0 and type(value["spec"]["replicas"]) is int
        assert (
            value["spec"]["selector"]["matchLabels"]
            == value["spec"]["template"]["metadata"]["labels"]
        )
        assert app.sessions.client is None
        screen.parameter_inputs["replicas"].value = "1"
        await wait_for(lambda: screen.service.current_source is None)
        assert screen.query_one("#creation-review", Button).disabled
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


def user_template():
    return {
        "schema_version": 1,
        "kind": "ResourceTemplate",
        "id": "typed-owned",
        "revision": 1,
        "title": "Typed owned template",
        "parameters": {
            "flag": {
                "type": "boolean",
                "required": True,
                "default": True,
                "paths": ["/0/spec/flag"],
            },
            "count": {"type": "integer", "required": True, "paths": ["/0/spec/count"]},
            "text": {
                "type": "string",
                "required": True,
                "default": "nonempty-default-to-override",
                "paths": ["/0/spec/text"],
            },
            "choice": {
                "type": "string",
                "required": True,
                "enum": ["source-private-default", "source-private-other"],
                "default": "source-private-default",
                "paths": ["/0/spec/choice"],
            },
            "map": {
                "type": "string_map",
                "required": True,
                "sensitive": True,
                "default": {},
                "paths": ["/0/spec/map"],
            },
        },
        "objects": [
            {
                "apiVersion": "owned.example/v1",
                "kind": "Widget",
                "metadata": {"name": "typed-owned"},
                "spec": {"flag": True, "count": 1, "text": "", "choice": "", "map": {}},
            }
        ],
    }


@pytest.mark.asyncio
async def test_selected_config_user_template_has_typed_false_zero_empty_and_private_map(tmp_path):
    selected = tmp_path / "selected-config"
    (selected / "templates").mkdir(parents=True)
    (selected / "templates" / "owned.yaml").write_text(json.dumps(user_template()))
    app = owned_app(tmp_path, environment={"KUBERICH_CONFIG": str(selected / "config.yaml")})
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await source_screen(app)
        await select_template(screen, "user", "typed-owned")
        assert isinstance(screen.parameter_inputs["flag"], Select)
        assert (
            isinstance(screen.parameter_inputs["map"], Input)
            and screen.parameter_inputs["map"].password
        )
        assert screen.parameter_inputs["choice"].value == "absent"
        screen.parameter_inputs["flag"].value = "false"
        screen.parameter_inputs["count"].value = "0"
        screen.parameter_inputs["choice"].value = "1"
        screen.parameter_presence["text"].value = True
        screen.parameter_inputs["map"].value = '{"source-private-key":"source-private-value"}'
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-render", Button))
        await wait_for(lambda: "Template rendered offline" in str(screen.status.render()))
        source = screen.service.current_source
        spec = json.loads(source.body)["spec"]
        assert spec == {
            "flag": False,
            "count": 0,
            "text": "",
            "choice": "source-private-other",
            "map": {"source-private-key": "source-private-value"},
        }
        assert source.private_preview and "Content withheld" in screen.viewer.text
        assert "source-private" not in screen.viewer.text + str(screen.status.render())
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_clipboard_read_occurs_only_after_explicit_button_and_paste_is_focused(
    tmp_path, monkeypatch
):
    calls = []

    async def read(owner, backend, *, guard):
        guard()
        calls.append(backend)
        return BODY.encode()

    monkeypatch.setattr(NativeClipboard, "read", read)
    app = owned_app(tmp_path)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await source_screen(app)
        assert not calls
        screen.source_choice.value = "clipboard"
        await pilot.pause()
        assert not calls
        screen.paste_capture.post_message(Paste(BODY))
        await pilot.pause()
        assert screen.service.current_source is None
        await click_ready(app, pilot, screen.query_one("#creation-clipboard", Button))
        await wait_for(lambda: "Clipboard captured once" in str(screen.status.render()))
        assert len(calls) == 1 and screen.service.current_source.kind == "clipboard"
        original = screen.service.current_source
        await click_ready(app, pilot, screen.query_one("#creation-review", Button))
        assert len(calls) == 1 and screen.service.current_source is original
        await click_ready(app, pilot, screen.query_one("#creation-paste", Button))
        assert app.focused is screen.paste_capture
        screen.paste_capture.post_message(Paste(BODY.replace("owned-paste", "owned-pasted-next")))
        await wait_for(lambda: "Paste captured without echo" in str(screen.status.render()))
        assert screen.service.current_source.kind == "paste" and len(calls) == 1
        assert "source-ui-private" not in screen.viewer.text + str(screen.status.render())
        assert screen.service.current_source.documents[0].name == "owned-pasted-next"
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload,message",
    [("private\x1bcontrol", "control characters"), ("x" * (1024 * 1024 + 1), "backend limit")],
)
async def test_focused_paste_rejects_invalid_or_oversized_without_echo(tmp_path, payload, message):
    app = owned_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await source_screen(app)
        screen.source_choice.value = "clipboard"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-paste", Button))
        screen.paste_capture.post_message(Paste(payload))
        await wait_for(lambda: message in str(screen.status.render()))
        assert screen.service.current_source is None and not screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "known-interrupted", "lost"])
async def test_create_review_publishes_persistent_receipt_and_actual_diff_even_when_interrupted(
    tmp_path, monkeypatch, mode
):
    from dataclasses import replace

    from kuberich.adapters.manifests import ManifestAdapter
    from kuberich.domain.mutations import MutationResult, MutationState
    from kuberich.services.mutations import MutationManager
    from kuberich.ui.manifest_review import ManifestReviewScreen
    from tests.contract.test_manifest_writes import live_service_fixture
    from tests.support.manifest_ui import ManifestTestApp

    async with live_service_fixture(tmp_path) as (service, api):
        manager = MutationManager()
        screen = ManifestReviewScreen(service=service, manager=manager, action="create")
        app = ManifestTestApp(screen)
        async with app.run_test(size=(80, 24)) as pilot:
            await wait_for(
                lambda: app.focused is not None and app.focused.id == "manifest-review-back"
            )
            assert screen.action_field.disabled and screen.action_field.value == "create"
            await click_ready(app, pilot, screen.query_one("#manifest-review-validate", Button))
            await wait_for(lambda: "All resources validated" in str(screen.status.render()))
            assert api.value is None and len(api.requests) == 1
            if mode == "lost":
                api.mode = "bad-json"
            elif mode == "known-interrupted":
                execute = ManifestAdapter.execute_creation

                async def interrupted(owner, intent, guard, *, private_preview=False):
                    response = await execute(owner, intent, guard, private_preview=private_preview)
                    return replace(
                        response,
                        result=MutationResult(
                            MutationState.UNCERTAIN,
                            "Completion interrupted after a verified receipt; do not replay.",
                        ),
                    )

                monkeypatch.setattr(ManifestAdapter, "execute_creation", interrupted)
            await click_ready(app, pilot, screen.query_one("#manifest-review-confirm", Button))
            expected = MutationState.SUCCEEDED if mode == "success" else MutationState.UNCERTAIN
            await wait_for(
                lambda: expected.value in str(screen.status.render()) and screen.result is not None
            )
            assert api.value is not None and len(api.requests) == 2
            assert screen.query_one("#manifest-review-confirm", Button).disabled
            if mode == "lost":
                assert (
                    not service.created_receipts
                    and "Verified persistent creation receipt" not in screen.viewer.text
                )
            else:
                assert "Verified persistent creation receipt" in screen.viewer.text
                assert (
                    "actual-server-uid" in screen.viewer.text
                    and "resourceVersion 1" in screen.viewer.text
                )
                assert "Actual server response compared" in screen.viewer.text
                assert service.created_receipts[0].target.uid == api.value["metadata"]["uid"]
            assert "private-value" not in screen.viewer.text + repr(manager.records)
            await pilot.press("escape")
            await wait_for(lambda: len(app.screen_stack) == 1)
        await manager.close()


@pytest.mark.asyncio
async def test_initial_create_with_selected_nonempty_catalog_never_connects(tmp_path, monkeypatch):
    from kuberich.domain.commands import Command
    from kuberich.services.sessions import SessionService
    from tests.support.connections import catalog_fixture

    def forbidden(*args, **kwargs):
        raise AssertionError("Initial offline creation tried to connect its selected context")

    monkeypatch.setattr(SessionService, "connect", forbidden)
    catalog = catalog_fixture(tmp_path, "http://127.0.0.1:9")
    app = KubeRichApp(
        Settings(),
        logging.Logger("owned-offline-selected-create"),
        catalog=catalog,
        directory=tmp_path,
        initial_command=Command.CREATE,
    )
    async with app.run_test() as pilot:
        await wait_for(
            lambda: (
                isinstance(app.screen, ResourceCreationScreen)
                and app.focused is not None
                and app.focused.id == "creation-back"
            )
        )
        assert app.sessions.client is None and app.sessions.observation.identity is None
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (120, 36)])
async def test_visible_browser_create_and_back_buttons_share_complete_small_geometry(
    tmp_path, size
):
    from kuberich.ui.manifest_browser import ManifestBrowserScreen

    app = owned_app(tmp_path)
    async with app.run_test(size=size) as pilot:
        await app.run_command(":manifests")
        await wait_for(
            lambda: isinstance(app.screen, ManifestBrowserScreen) and app.screen.listing is not None
        )
        browser = app.screen
        assert await browser.wait_for_refresh()
        for name in ("create", "back"):
            button = browser.query_one("#manifests-" + name, Button)
            assert button.region.bottom <= size[1]
            assert app.get_widget_at(*button.region.center)[0] is button
        await click_ready(app, pilot, browser.query_one("#manifests-create", Button))
        await wait_for(
            lambda: (
                isinstance(app.screen, ResourceCreationScreen)
                and app.focused is not None
                and app.focused.id == "creation-back"
            )
        )
        await pilot.press("escape")
        await wait_for(lambda: app.screen is browser)
        await click_ready(app, pilot, browser.query_one("#manifests-back", Button))
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
async def test_public_create_route_preserves_connected_root_or_nested_origin_for_back(
    tmp_path, nested
):
    from aiohttp import web

    from kuberich.ui.containers import ContainerScreen
    from tests.support.connections import catalog_fixture, namespaces
    from tests.support.pods import pod
    from tests.support.resources import collection
    from tests.support.workspace import stable_watch, workspace_api

    value = pod("owned-origin")

    async def resources(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(value) if request.path.endswith("/pods") else value)

    async def ns(request):
        return namespaces("team", "default")

    async with workspace_api(ns, resources) as url:
        app = KubeRichApp(
            Settings(),
            logging.Logger("owned-create-origin"),
            catalog=catalog_fixture(tmp_path, url),
            directory=tmp_path,
        )
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            before = app.resources.capture_viewport()
            if nested:
                await pilot.press("enter")
                await wait_for(
                    lambda: (
                        isinstance(app.screen, ContainerScreen) and app.screen.table.row_count == 1
                    )
                )
            origin = app.screen
            client = app.sessions.client
            await app.run_command(":create")
            await wait_for(
                lambda: (
                    isinstance(app.screen, ResourceCreationScreen)
                    and app.focused is not None
                    and app.focused.id == "creation-back"
                )
            )
            assert app.sessions.client is client
            await pilot.press("escape")
            await wait_for(lambda: app.screen is origin)
            assert app.resources.capture_viewport() == before
            if nested:
                assert not origin.invalidated and origin.table.row_count == 1
                await pilot.press("escape")
                await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_invalid_and_duplicate_user_entries_are_visible_but_never_render(tmp_path):
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "bad.yaml").write_text("source-private-invalid: []\n")
    for name in ("first.json", "second.json"):
        (templates / name).write_text(json.dumps(user_template()))
    app = owned_app(tmp_path, environment={"KUBERICH_CONFIG": str(tmp_path / "config.yaml")})
    async with app.run_test() as pilot:
        screen = await source_screen(app)
        screen.source_choice.value = "user"
        await wait_for(
            lambda: "Choose a template" in str(screen.status.render()) and len(screen.entries) == 3
        )
        for index, entry in enumerate(screen.entries):
            assert not entry.enabled
            screen.template_choice.value = index
            await wait_for(
                lambda entry=entry: (
                    screen.entry is entry and entry.problem in str(screen.status.render())
                )
            )
            assert screen.query_one("#creation-render", Button).disabled
            assert screen.service.current_source is None
        screen.template_choice.value = Select.NULL
        await wait_for(lambda: "Choose an available template" in str(screen.status.render()))
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_late_native_read_cannot_publish_after_source_generation_changes(
    tmp_path, monkeypatch
):
    import asyncio

    entered, release = asyncio.Event(), asyncio.Event()

    async def read(owner, backend, *, guard):
        entered.set()
        await release.wait()
        return BODY.encode()

    monkeypatch.setattr(NativeClipboard, "read", read)
    app = owned_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await source_screen(app)
        screen.source_choice.value = "clipboard"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-clipboard", Button))
        await wait_for(entered.is_set)
        screen.source_choice.value = "file"
        await pilot.pause()
        release.set()
        await wait_for(lambda: "capture changed" in str(screen.status.render()))
        assert screen.service.current_source is None and not screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_no_native_helper_backend_publishes_safe_explicit_paste_fallback(tmp_path):
    app = owned_app(tmp_path)
    async with app.run_test() as pilot:
        screen = await source_screen(app)
        screen.source_choice.value = "clipboard"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-clipboard", Button))
        await wait_for(lambda: "Paste capture" in str(screen.status.render()))
        assert screen.service.current_source is None and not screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)


@pytest.mark.asyncio
async def test_owned_paste_parser_keeps_ui_responsive_and_escape_awaits_worker(
    tmp_path, monkeypatch
):
    import asyncio
    import threading

    from kuberich.ui import resource_creation

    entered, release = threading.Event(), threading.Event()
    controller = threading.get_ident()
    parse = resource_creation.pasted_source_bytes

    def held(text):
        assert threading.get_ident() != controller
        entered.set()
        assert release.wait(5)
        return parse(text)

    monkeypatch.setattr(resource_creation, "pasted_source_bytes", held)
    app = owned_app(tmp_path)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await source_screen(app)
        screen.source_choice.value = "clipboard"
        await pilot.pause()
        await click_ready(app, pilot, screen.query_one("#creation-paste", Button))
        screen.paste_capture.post_message(Paste(BODY))
        await wait_for(entered.is_set)
        await pilot.resize_terminal(80, 24)
        assert screen.has_class("compact") and await screen.wait_for_refresh()
        back = asyncio.create_task(pilot.press("escape"))
        try:
            await wait_for(lambda: screen.stopped)
            assert app.screen is screen
        finally:
            release.set()
            await back
        await wait_for(lambda: len(app.screen_stack) == 1)
        assert screen.service.current_source is None


@pytest.mark.asyncio
async def test_owned_string_map_parser_rejects_changed_parameter_generation_after_worker(
    tmp_path, monkeypatch
):
    import threading

    from kuberich.ui import resource_creation

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "owned.json").write_text(json.dumps(user_template()))
    entered, release = threading.Event(), threading.Event()
    controller = threading.get_ident()
    parse = resource_creation.parse_manifest

    def held(data):
        assert threading.get_ident() != controller
        entered.set()
        assert release.wait(5)
        return parse(data)

    app = owned_app(tmp_path, environment={"KUBERICH_CONFIG": str(tmp_path / "config.yaml")})
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await source_screen(app)
        await select_template(screen, "user", "typed-owned")
        screen.parameter_inputs["count"].value = "0"
        screen.parameter_inputs["map"].value = '{"owned":"private"}'
        await pilot.pause()
        monkeypatch.setattr(resource_creation, "parse_manifest", held)
        await click_ready(app, pilot, screen.query_one("#creation-render", Button))
        try:
            await wait_for(entered.is_set)
            await pilot.resize_terminal(80, 24)
            assert screen.has_class("compact") and await screen.wait_for_refresh()
            screen.parameter_inputs["count"].value = "1"
            await pilot.pause()
        finally:
            release.set()
        await wait_for(lambda: "capture changed" in str(screen.status.render()))
        assert screen.service.current_source is None and not screen.viewer.text
        await pilot.press("escape")
        await wait_for(lambda: len(app.screen_stack) == 1)
