"""Operator-visible presets and exact-context annotation opt-in with real children."""

import logging

import pytest
from aiohttp import web
from textual.widgets import Checkbox, Input, Select, Static

from kuberich.cli import main
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import Settings, parse_document
from kuberich.config.store import write_config
from kuberich.domain.forward_presets import ANNOTATIONS, ForwardTransport
from kuberich.domain.port_forwards import ForwardState
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import ResourceCommand
from kuberich.ui.app import KubeRichApp
from kuberich.ui.port_forwards import ForwardPrompt, ForwardScreen
from tests.support.connections import catalog_fixture
from tests.support.port_forwards import executable
from tests.support.standard import manifest, standard_api
from tests.support.workspace import stable_watch, wait_for


def handler_for(annotation):
    async def handler(request, definition):
        if definition.name != "services":
            return None
        if "watch" in request.query:
            return await stable_watch(request)
        value = manifest(definition)
        value["spec"]["ports"] = [{"name": "http", "port": 8080, "targetPort": 8081}]
        if annotation is not None:
            value["metadata"]["annotations"] = {ANNOTATIONS[0]: annotation}
        return web.json_response(
            value
            if request.path.endswith("/owned-one")
            else {
                "apiVersion": "v1",
                "kind": "ServiceList",
                "metadata": {"resourceVersion": "owned/list"},
                "items": [value],
            }
        )

    return handler


def application(directory, url, forwarding):
    path = directory / "preferences.yaml"
    document = parse_document({"schema_version": 1, "forwarding": forwarding})
    write_config(path, document)
    app = KubeRichApp(
        Settings(),
        logging.Logger("owned-forward-presets", level=100),
        catalog=catalog_fixture(directory, url),
        preferences=PreferenceSource(ConfigLocation(path, True), document),
        initial_command=ResourceCommand(RESOURCE_ALIASES["svc"], "team"),
        environment=executable(directory),
        directory=directory,
    )
    return app, path


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(40, 12), (100, 30)])
async def test_presets_resolve_named_ports_and_cannot_grant_remote_bind_permission(tmp_path, size):
    async with standard_api(tmp_path, handler_for(None)) as (url, _reads):
        app, path = application(
            tmp_path,
            url,
            {
                "presets": {
                    "web": {"ports": ":http", "transport": "spdy", "retries": 2},
                    "public": {"ports": ":http", "address": "0.0.0.0"},
                }
            },
        )
        before = path.read_bytes()
        async with app.run_test(size=size) as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardPrompt))
            form = app.screen
            form.query_one("#forward-preset", Select).value = "public"
            await pilot.pause()
            assert not form.query_one("#forward-remote", Checkbox).value
            form.start()
            assert isinstance(app.screen, ForwardPrompt) and not app.forwards.infos
            assert "explicit" in str(form.query_one("#forward-feedback", Static).content)
            form.query_one("#forward-preset", Select).value = "web"
            await pilot.pause()
            assert form.query_one("#forward-retries", Input).value == "2"
            form.start()
            await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await wait_for(lambda: app.forwards.infos[-1].state is ForwardState.READY)
            info = app.forwards.infos[-1]
            assert info.mappings[0].remote == 8080 and info.transport is ForwardTransport.SPDY
            await app.forwards.stop(info.identity)
            await pilot.press("escape")
        assert path.read_bytes() == before and not app.processes.active_count


@pytest.mark.asyncio
@pytest.mark.parametrize("automatic", [False, True])
async def test_untrusted_auto_annotation_requires_explicit_local_optin(tmp_path, automatic):
    async with standard_api(tmp_path, handler_for("0:http")) as (url, _reads):
        app, path = application(tmp_path, url, {"auto_annotations": automatic})
        before = path.read_bytes()
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            assert not app.forwards.infos
            await pilot.press("F")
            await wait_for(
                lambda: isinstance(app.screen, ForwardScreen if automatic else ForwardPrompt)
            )
            if not automatic:
                assert not app.forwards.infos
                assert app.screen.query_one("#forward-mappings", Input).value == "0:8080"
                app.screen.query_one("#forward-trust-annotations", Checkbox).value = True
                app.screen.start()
                await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await wait_for(lambda: app.forwards.infos[-1].state is ForwardState.READY)
            await app.forwards.stop(app.forwards.infos[-1].identity)
            await pilot.press("escape")
            await pilot.press("F")
            await wait_for(lambda: isinstance(app.screen, ForwardScreen))
            await wait_for(lambda: app.forwards.infos[-1].state is ForwardState.READY)
        assert path.read_bytes() == before and not app.processes.active_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "forwarding,annotation",
    [
        ({"auto_annotations": "yes"}, "0:http"),
        ({"auto_annotations": True}, "0:missing"),
        ({"auto_annotations": True}, "$(untrusted)"),
    ],
)
async def test_invalid_preferences_or_annotations_fail_before_start(
    tmp_path, forwarding, annotation
):
    async with standard_api(tmp_path, handler_for(annotation)) as (url, _reads):
        app, _path = application(tmp_path, url, forwarding)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            await pilot.press("F")
            assert len(app.screen_stack) == 1 and not app.forwards.infos
            assert not (tmp_path / "forward-child.pid").exists()


@pytest.mark.asyncio
async def test_invalid_retries_and_changed_target_keep_review_open(tmp_path):
    async with standard_api(tmp_path, handler_for(None)) as (url, _reads):
        app, _path = application(tmp_path, url, {})
        async with app.run_test() as pilot:
            await wait_for(lambda: app.standard_table.row_count == 1)
            await pilot.pause()
            await pilot.press("F")
            form = app.screen
            form.query_one("#forward-retries", Input).value = "9"
            form.start()
            assert "retries" in str(form.query_one("#forward-feedback", Static).content)
            form.current = lambda: False
            form.start()
            assert "changed" in str(form.query_one("#forward-feedback", Static).content)
            assert not app.forwards.infos
            form.cancel()
            await pilot.pause()
            assert len(app.screen_stack) == 1


def test_config_check_validates_forwarding_without_a_cluster(tmp_path, capsys):
    path = tmp_path / "preferences.yaml"
    write_config(
        path,
        parse_document(
            {"schema_version": 1, "forwarding": {"presets": {"web": {"ports": ":http"}}}}
        ),
    )
    assert main(["--config", str(path), "config", "check"]) == 0
    assert "valid" in capsys.readouterr().out
    write_config(
        path,
        parse_document({"schema_version": 1, "forwarding": {"auto_annotations": "yes"}}),
        overwrite=True,
    )
    assert main(["--config", str(path), "config", "check"]) == 2
    assert "auto_annotations" in capsys.readouterr().err
