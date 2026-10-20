"""Configured jumps open related views with a validated filter through Pilot."""

import logging

import pytest

from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import parse_document
from kuberich.config.store import read_config, write_config
from kuberich.domain.views import ViewStatus
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture
from tests.support.custom import GROUP, CustomAPI, custom_api
from tests.support.workspace import wait_for

JUMPS = {
    "schema_version": 1,
    "definitions": {
        "beta": {
            "source": "v1/pods",
            "target": f"{GROUP}/v1beta1/widgets",
            "fields": "metadata.name=two",
        },
        "gadgets": {
            "source": "v1/pods",
            "target": f"{GROUP}/v1/gadgets",
            "namespace": "{{ metadata.namespace }}",
        },
        "pods": {
            "source": f"{GROUP}/v1beta1/widgets",
            "target": "v1/pods",
            "labels": "app={{ metadata.name }}",
        },
    },
}


def app_for(directory, url, jumps):
    path = directory / "preferences.yaml"
    write_config(path, parse_document({"schema_version": 1, "jumps": jumps}))
    document = read_config(path)
    return KubeRichApp(
        document.settings,
        logging.Logger("jumps", level=100),
        preferences=PreferenceSource(ConfigLocation(path, True), document),
        catalog=catalog_fixture(directory, url),
        initial_command=Command.PODS,
    )


async def command(app, pilot, value):
    await pilot.press("colon")
    app.command_input.value = value
    await pilot.press("enter")
    await pilot.pause()


def status(app):
    return str(app.status.content)


async def showing(app, name, version, namespace, rows):
    table = app.resources if name == "pods" else app.custom_table
    await wait_for(
        lambda: (
            app.workspace.store.observation.status is ViewStatus.LIVE
            and app.workspace.store.observation.scope.resource.name == name
            and app.workspace.store.observation.scope.resource.version == version
            and app.workspace.store.observation.scope.namespace == namespace
            and table.row_count == rows
        )
    )


@pytest.mark.asyncio
async def test_jumps_open_generic_and_built_in_targets_with_filters_and_history(tmp_path):
    async with custom_api(CustomAPI(core_pods=True)) as (url, _owner):
        app = app_for(tmp_path, url, JUMPS)
        async with app.run_test(size=(120, 30)) as pilot:
            await showing(app, "pods", "v1", "team", 1)
            await command(app, pilot, "jump")
            assert "Jumps for v1/pods: beta, gadgets. Use :jump NAME." in status(app)
            await command(app, pilot, "jump missing")
            assert "No jump named missing for v1/pods." in status(app)
            await command(app, pilot, "jump gadgets")
            assert "cluster-scoped" in status(app)
            assert app.workspace.store.observation.scope.resource.name == "pods"

            # A non-preferred version opens the discovered view at that version.
            await command(app, pilot, "jump beta")
            await showing(app, "widgets", "v1beta1", "team", 1)
            assert app.filter_input.value == "field:metadata.name=two"

            # The rendered label filter comes from the selected widget.
            await command(app, pilot, "jump")
            await showing(app, "pods", "v1", "team", 0)
            assert app.filter_input.value == "label:app=two"

            await command(app, pilot, "back")
            await showing(app, "widgets", "v1beta1", "team", 1)
            assert app.filter_input.value == "field:metadata.name=two"

            # Contexts are local rows, so there is nothing to jump from.
            await command(app, pilot, "ctx")
            await wait_for(lambda: app.context_table.display)
            await command(app, pilot, "jump")
            assert "Contexts are local configuration" in status(app)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "jumps, message",
    [
        ({"schema_version": 1}, "No jump is configured for v1/pods."),
        (
            {"definitions": {"bad": {"source": "v1/pods", "target": "v1/pods", "run": "x"}}},
            "Jumps are unavailable: Jump bad accepts only",
        ),
    ],
)
async def test_missing_or_invalid_jumps_report_without_changing_the_view(tmp_path, jumps, message):
    async with custom_api(CustomAPI(core_pods=True)) as (url, _owner):
        app = app_for(tmp_path, url, jumps)
        async with app.run_test(size=(120, 30)) as pilot:
            await showing(app, "pods", "v1", "team", 1)
            await command(app, pilot, "jump")
            assert message in status(app)
            assert app.workspace.store.observation.scope.resource.name == "pods"
            assert app.filter_input.value == ""
