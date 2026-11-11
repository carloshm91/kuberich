"""Owned public lifecycle contracts for process/file ownership and captured identities."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from kuberich.domain.helm import HelmProblem
from kuberich.domain.helm_lifecycle import HelmLifecycleKind
from kuberich.errors import AppError
from tests.support.helm import owned_process_state
from tests.support.helm_lifecycle import ADDRESS, VALUES, lifecycle_source
from tests.support.workspace import wait_for


@pytest.mark.asyncio
async def test_close_waits_for_active_preview_before_unlinking_its_exact_inputs(tmp_path):
    async with lifecycle_source(tmp_path, mode="hold") as fixture:
        prepare = asyncio.create_task(
            fixture.service.prepare_lifecycle(
                fixture.request, ADDRESS, HelmLifecycleKind.INSTALL, fixture.chart
            )
        )
        await wait_for(fixture.entered.exists)
        preview = fixture.previews()[-1]
        paths = [Path(preview[name]) for name in ("chart", "values")]
        assert preview["inputs_present"] and all(path.is_file() for path in paths)
        assert preview["package_sha256"] == fixture.chart.sha256
        assert preview["values_sha256"] == hashlib.sha256(VALUES).hexdigest()
        closing = asyncio.create_task(fixture.service.close_values_editor())
        done, pending = await asyncio.wait({closing}, timeout=0.1)
        assert not done and closing in pending
        assert all(path.is_file() for path in paths) and not fixture.lost_inputs.exists()
        fixture.release.touch()
        with pytest.raises(HelmProblem, match="review expired"):
            await prepare
        await closing
        assert all(not path.parent.exists() for path in paths)
        assert not fixture.input_directories() and fixture.service.operation_count == 0
        assert owned_process_state(preview["pid"]) in {"absent", "Z"}
        assert fixture.api.mutations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["error", "malformed", "cancel"])
async def test_failed_or_cancelled_native_preview_cleans_inputs_before_return(tmp_path, mode):
    async with lifecycle_source(tmp_path, mode="hold" if mode == "cancel" else mode) as fixture:
        prepare = asyncio.create_task(
            fixture.service.prepare_lifecycle(
                fixture.request, ADDRESS, HelmLifecycleKind.INSTALL, fixture.chart
            )
        )
        if mode == "cancel":
            await wait_for(fixture.entered.exists)
            prepare.cancel()
            with pytest.raises(asyncio.CancelledError):
                await prepare
        else:
            with pytest.raises(AppError) as error:
                await prepare
            assert "owned-private-lifecycle-value" not in str(error.value)
        preview = fixture.previews()[-1]
        assert preview["inputs_present"]
        assert all(not Path(preview[name]).parent.exists() for name in ("chart", "values"))
        assert not fixture.input_directories() and fixture.service.operation_count == 0
        assert owned_process_state(preview["pid"]) in {"absent", "Z"}
        assert fixture.api.mutations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [HelmLifecycleKind.UPGRADE, HelmLifecycleKind.UNINSTALL])
async def test_all_namespace_existing_release_defaults_manifest_objects_to_release_namespace(
    tmp_path, operation
):
    async with lifecycle_source(tmp_path, existing=True, namespace=None) as fixture:
        intent = await fixture.service.prepare_lifecycle(
            fixture.request,
            ADDRESS,
            operation,
            fixture.chart if operation is HelmLifecycleKind.UPGRADE else None,
        )
        assert intent.address == ADDRESS
        assert any(
            "/" + ADDRESS.namespace + "/owned-release-settings" in effect
            for effect in intent.effects
        )
        paths = [path for method, path, query in fixture.api.requests]
        assert "/api/v1/namespaces/release-team/configmaps/owned-release-settings" in paths
        assert not any("/namespaces/default/" in path for path in paths)
        assert fixture.api.mutations == []
        assert all(
            "--namespace=release-team" in call["argv"]
            for call in fixture.calls()
            if call["command"] != "version"
        )
        assert all(
            any(argument.startswith("--namespace=") for argument in call["argv"])
            for call in fixture.calls()
        )


@pytest.mark.asyncio
async def test_stale_catalog_chart_generation_is_rejected_before_native_preview(tmp_path):
    async with lifecycle_source(tmp_path) as fixture:
        catalog = fixture.service.catalog
        await catalog.add("owned", fixture.origin + "/charts", allow_loopback_http=True)
        snapshot = await catalog.select(catalog.search()[0])
        assert snapshot.catalog_generation == catalog.snapshot.generation
        await catalog.update("owned")
        assert snapshot.catalog_generation < catalog.snapshot.generation
        with pytest.raises(AppError, match="catalog"):
            await fixture.service.prepare_lifecycle(
                fixture.request, ADDRESS, HelmLifecycleKind.INSTALL, snapshot
            )
        assert fixture.previews() == [] and not fixture.input_directories()
        assert fixture.api.mutations == []


@pytest.mark.asyncio
@pytest.mark.parametrize("executable", ["./tools/owned-helm", "owned-helm"])
async def test_helm_executable_resolution_uses_captured_helper_directory_and_environment(
    tmp_path, executable
):
    async with lifecycle_source(tmp_path, delegated_executable=executable) as fixture:
        listing = await fixture.service.list(fixture.request)
        assert listing.complete and listing.releases == ()
        assert fixture.auth_called.exists() and not fixture.trap.exists()
        assert json.loads(fixture.auth_called.read_text()) == {
            "cwd": str(tmp_path / "helper"),
            "sentinel": "captured-helper",
        }
        calls = fixture.calls()
        assert [call["command"] for call in calls] == ["version", "list"]
        assert all(call["cwd"] == str(tmp_path / "helper") for call in calls)
        assert all(
            call["sentinel"] == "captured-helper" and call["path"] == "tools" for call in calls
        )
        assert all(
            "--kube-context=kuberich-test-one" in call["argv"]
            and "--namespace=release-team" in call["argv"]
            for call in calls
        )
        assert not fixture.input_directories() and fixture.service.operation_count == 0
