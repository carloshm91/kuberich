"""Original manifests and translated argv never execute upstream programs."""

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web

from kuberich.adapters.plugin_files import load_plugins
from kuberich.config.plugins import PluginLayer, PluginPreferences
from kuberich.domain.plugins import PluginSelection, expand_plugin, parse_plugin, plugin_command
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.plugins import PluginManager, PluginSource
from tests.support.plugin_examples import EXAMPLES, ROOT, executable
from tests.support.pods import pod
from tests.support.resources import pod_resource, reader_fixture

TRANSLATIONS = json.loads((ROOT / "tests/fixtures/plugins/translations.json").read_text())
CENSUS = json.loads((ROOT / "docs/plugin-compatibility.json").read_text())


def examples():
    return load_plugins(PluginPreferences(PluginLayer(locations=(EXAMPLES,))), None)


@pytest.mark.parametrize("present", [False, True])
def test_original_examples_validate_with_the_real_offline_cli_without_running_tools(
    tmp_path, present
):
    preferences = tmp_path / "preferences.yaml"
    preferences.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "plugins": {"schema_version": 1, "locations": [str(EXAMPLES)]},
            }
        )
    )
    before = preferences.read_bytes()
    missing = tmp_path / "missing-kubeconfig"
    tools = tmp_path / "bin"
    tools.mkdir()
    marker = tmp_path / "must-not-start"
    if present:
        tool = tools / "kubectl"
        tool.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
        )
        tool.chmod(0o700)
    result = subprocess.run(
        [sys.executable, "-m", "kuberich", "--config", str(preferences), "config", "check"],
        env={
            **os.environ,
            "KUBECONFIG": str(missing),
            "PATH": str(tools),
            "KUBERICH_LOG_FILE": str(tmp_path / "owned.log"),
        },
        cwd=tmp_path,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    assert b"valid" in result.stdout
    assert preferences.read_bytes() == before and not missing.exists() and not marker.exists()


def test_census_covers_every_pinned_source_and_all_workflows_without_bundling_scripts():
    inventory = json.loads((ROOT / "docs/k9s-source-inventory.json").read_text())
    expected = {r["source"]: r for r in inventory["records"] if r["source"].startswith("plugins/")}
    records = CENSUS["records"]
    assert CENSUS["baseline"] == {k: inventory["baseline"][k] for k in ("tag", "commit")}
    assert len(records) == len(expected) == 50
    assert {r["source"] for r in records} == expected.keys()
    assert sum(len(r["commands"]) for r in records) == 108
    assert sum(r["kind"] == "executable-helper" for r in records) == 2
    assert TRANSLATIONS["baseline"] == CENSUS["baseline"]["commit"]
    cases = {(c["source"], c["upstream_command"]): c["id"] for c in TRANSLATIONS["cases"]}
    classified = {}
    guide = (ROOT / "docs/plugin-compatibility.md").read_text()
    for record in records:
        assert record["url"] == expected[record["source"]]["url"]
        assert record["revision"] == inventory["baseline"]["commit"]
        assert re.fullmatch("[a-f0-9]{40}", record["git_blob"])
        assert re.fullmatch("[a-f0-9]{64}", record["sha256"])
        assert record["bytes"] > 0
        assert record["dependencies"] and all(record["dependencies"])
        assert record["free_alternative"] and record["review_note"]
        assert record["url"] in guide
        row = next(line for line in guide.splitlines() if record["url"] in line)
        assert all(dependency in row for dependency in record["dependencies"])
        assert record["free_alternative"] in guide and record["review_note"] in guide
        assert len({c["name"] for c in record["commands"]}) == len(record["commands"])
        for command in record["commands"]:
            assert command["classification"] in {
                "tested-argv",
                "reviewed-rewrite",
                "unsupported-view",
                "retired-helper",
            }
            key = (record["source"], command["name"])
            if command["classification"] == "tested-argv":
                classified[key] = command["fixture"]
            else:
                assert command["fixture"] is None
    assert classified == cases and len(cases) == 18


@pytest.mark.parametrize("case", TRANSLATIONS["cases"], ids=lambda c: c["id"])
def test_documented_translation_has_exact_literal_argv_and_explicit_trust(case, tmp_path):
    data = case["selection"]
    parts = data["scope"].split("/")
    group = parts[0] if len(parts) == 3 else ""
    target = ResourceTarget(
        SessionIdentity(data["context"], 1),
        group,
        parts[-1],
        None if parts[-1] in {"nodes", "namespaces"} else data["namespace"],
        data["name"],
        "synthetic-uid",
    )
    selected = PluginSelection(
        data["context"],
        data["scope"],
        target,
        (("FILTER", data["filter"]), ("KUBECONFIG", "/owned/private.yaml")),
        tuple(data["columns"].items()),
    )
    plugin = parse_plugin(case["id"], case["definition"], tmp_path)
    command = plugin_command(
        plugin, selected, case["inputs"], {"KUBECONFIG": "/owned/private.yaml"}
    )
    assert command is not None and list(command.argv) == case["expected_argv"]
    assert plugin.confirm and plugin.dangerous and not plugin.trusted_read_only
    with pytest.raises(AppError, match="Read-only"):
        plugin.require_access(True)
    assert plugin_command(plugin, selected, None, {}) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("shortCut", "Shift-H"),
        ("background", True),
        ("overwriteOutput", True),
        ("pipes", ["jq"]),
    ],
)
def test_upstream_fields_are_rejected_instead_of_silently_imported(field, value, tmp_path):
    with pytest.raises(AppError, match="unsupported fields"):
        parse_plugin("original", {"command": "kubectl", field: value}, tmp_path)


@pytest.mark.parametrize(
    "value",
    [
        "$RESOURCE_GROUP",
        "$RESOURCE_VERSION",
        "$RESOURCE_NAME",
        "$POD",
        "$GROUPS",
        "$!COL-SUSPEND",
        "${!COL-SUSPEND}",
        "$context",
        "${NAME:-default}",
    ],
)
def test_untranslated_upstream_variables_fail_closed(value):
    with pytest.raises(AppError):
        expand_plugin(value, {"CONTEXT": "demo", "NAME": "api", "COL-SUSPEND": "false"})


def test_boolean_adaptation_sets_requested_value_and_pvc_quantity_cannot_inject_json(tmp_path):
    for case in TRANSLATIONS["cases"]:
        if case["id"] in {"set-cronjob-suspend", "set-spark-suspend"}:
            definition = parse_plugin(case["id"], case["definition"], tmp_path)
            assert definition.inputs[0].accept(False) == "false"
            assert json.loads(
                expand_plugin('{"spec":{"suspend":${INPUT_SUSPEND}}}', {"INPUT_SUSPEND": "false"})
            ) == {"spec": {"suspend": False}}
        if case["id"] == "resize-pvc":
            definition = parse_plugin(case["id"], case["definition"], tmp_path)
            with pytest.raises(AppError, match="choices"):
                definition.inputs[0].accept('10Gi"},"other":"injected')


@pytest.mark.asyncio
async def test_original_capture_background_cancel_readonly_and_private_cleanup(tmp_path):
    executable(tmp_path)
    plugins = {p.name: p for p in examples()}
    assert set(plugins) == {"inspect-pod", "pod-shell", "collect-pod-events"}

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        target = ResourceTarget(
            SessionIdentity(reader.session.context.name, 1), "", "pods", "team", "api", "api-uid"
        )
        owner = PluginSource(
            reader.session,
            pod_resource(),
            PluginSelection(target.session.context, "v1/pods", target),
            AccessPolicy(True),
            lambda: True,
            {**os.environ, "PATH": str(tmp_path), "EXAMPLE_RECEIPT": str(tmp_path / "receipt")},
        )
        manager = PluginManager(owner.policy)
        try:
            request = await owner.prepare(plugins["inspect-pod"], {})
            assert request is not None
            job = manager.start(owner, request, confirmed=True)
            await job.wait()
            assert job.status == "Succeeded" and "EXAMPLE_INSPECTION" in job.output
            assert all(not path.exists() for path, _ in request.files)
            with pytest.raises(AppError, match="Read-only"):
                await owner.prepare(plugins["pod-shell"], {"container": "app"})
            assert await owner.prepare(plugins["inspect-pod"], None) is None
            request = await owner.prepare(plugins["collect-pod-events"], {})
            assert request is not None
            job = manager.start(owner, request, confirmed=True)
            await job.wait()
            assert job.status == "Succeeded" and "EXAMPLE_EVENTS" in job.output
            assert all(not path.exists() for path, _ in request.files)
            (tmp_path / "receipt-events").unlink()
            held = PluginSource(
                owner.client,
                owner.resource,
                owner.selection,
                owner.policy,
                owner.current,
                {**owner.environment, "EXAMPLE_HOLD": "1"},
            )
            request = await held.prepare(plugins["collect-pod-events"], {})
            assert request is not None
            job = manager.start(held, request, confirmed=True)
            async with asyncio.timeout(5):
                # The stand-in publishes the closed JSON receipt atomically.
                while not (tmp_path / "receipt-events").exists():
                    await asyncio.sleep(0.01)
            await manager.stop(job)
            assert job.status == "Cancelled" and all(not path.exists() for path, _ in request.files)
            receipt = json.loads((tmp_path / "receipt-events").read_text())
            assert receipt["argv"][-2:] == [
                "--field-selector=involvedObject.kind=Pod,involvedObject.name=api",
                "--output=json",
            ]
            assert not Path(receipt["private"]).exists()
            missing = PluginSource(
                owner.client,
                owner.resource,
                owner.selection,
                owner.policy,
                owner.current,
                {**owner.environment, "PATH": str(tmp_path / "missing-bin")},
            )
            request = await missing.prepare(plugins["inspect-pod"], {})
            assert request is not None
            job = manager.start(missing, request, confirmed=True)
            await job.wait()
            assert job.status.startswith("Error:") and "no automatic retry" in job.output
            assert all(not path.exists() for path, _ in request.files)
        finally:
            await manager.close()
