"""Actual ProcessRunner Helm execution, failure bounds and cancellation cleanup."""

import asyncio
import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.adapters import helm as helm_adapter
from kuberich.adapters.helm import HelmAdapter
from kuberich.domain.helm import HelmProblem
from kuberich.services.access import AccessPolicy
from kuberich.services.delegation import ConnectionFile
from kuberich.services.processes import ProcessRunner
from tests.support.helm import (
    adapter_source,
    calls,
    owned_process_state,
    wait_owned_process_stopped,
)


async def wait_pid(path):
    async with asyncio.timeout(3):
        while True:
            try:
                value = path.read_text()
            except FileNotFoundError:
                pass
            else:
                if value.isascii() and value.isdecimal() and int(value) > 0:
                    return int(value)
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_child_pid_wait_requires_a_positive_published_payload(tmp_path, monkeypatch):
    marker = tmp_path / "child.pid"
    marker.touch()
    empty_observed, zero_observed = asyncio.Event(), asyncio.Event()
    original = Path.read_text

    def observe_read(path, *args, **options):
        value = original(path, *args, **options)
        if path == marker:
            if value == "":
                empty_observed.set()
            elif value == "0":
                zero_observed.set()
        return value

    monkeypatch.setattr(Path, "read_text", observe_read)
    operation = asyncio.create_task(wait_pid(marker))
    try:
        async with asyncio.timeout(3):
            await empty_observed.wait()
            assert not operation.done()
            marker.write_text("0")
            await zero_observed.wait()
            assert not operation.done()
            marker.write_text(str(os.getpid()))
            assert await operation == os.getpid()
    finally:
        if not operation.done():
            operation.cancel()
        await asyncio.gather(operation, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v3.22.1", "v4.3.1"])
async def test_supported_probe_is_offline_then_explicit_scope_and_private_cleanup(
    tmp_path, version
):
    async with adapter_source(tmp_path, version=version) as (
        adapter,
        client,
        api,
        request,
        _,
        record,
    ):
        assert not record.exists()
        assert (await adapter.version(lambda: None)).text == version
        assert not api.requests and not list(Path(client.directory.name).glob("helm-*"))
        assert len((await adapter.list(request, lambda: None)).releases) == 1
        probe, read = calls(record)
        assert probe["argv"] == ["version", "--template={{.Version}}"]
        assert "KUBECONFIG" not in probe["environment"] and probe["config_mode"] is None
        assert read["config_mode"] == 0o600
        path = read["environment"]["KUBECONFIG"]
        assert f"--kubeconfig={path}" in read["argv"]
        assert (
            "--kube-context=kuberich-test-one" in read["argv"]
            and "--namespace=team" in read["argv"]
        )
        assert "--max=501" in read["argv"] and "--offset=0" in read["argv"]
        assert ("--all" in read["argv"]) == (version == "v3.22.1")
        assert "--debug=false" in read["argv"] and not Path(path).exists()
        assert not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_frozen_environment_ignores_helm_auth_overrides_and_ambient_kubeconfig(tmp_path):
    async with adapter_source(tmp_path) as (original, client, _, request, _, record):
        environment = {
            **original.environment,
            "KUBECONFIG": "caller-private-config",
            "HELM_DRIVER": "secrets",
            "HELM_KUBEAPISERVER": "hostile-server",
            "HELM_KUBETOKEN": "private-token",
            "HELM_KUBEUNKNOWN": "unknown",
            "HELM_NAMESPACE": "wrong",
            "HELM_DEBUG": "true",
            "HELM_MAX_HISTORY": "1",
            "HELM_DRIVER_SQL_CONNECTION_STRING": "private-sql",
            "CLOUD_HELPER_ENV": "captured",
        }
        before = dict(os.environ)
        adapter = HelmAdapter(client, AccessPolicy(False), original.settings, environment, tmp_path)
        environment["HELM_TEST_RECORD"] = str(tmp_path / "late-record")
        environment["PATH"] = "/invalid"
        try:
            await adapter.list(request, lambda: None)
        finally:
            await adapter.close()
        assert os.environ == before
        for invocation in calls(record):
            observed = invocation["environment"]
            assert observed["HELM_DRIVER"] == "secret" and observed["HELM_NO_PLUGINS"] == "1"
            assert not any(key.startswith("HELM_KUBE") for key in observed)
            assert not any(
                key in observed
                for key in (
                    "HELM_NAMESPACE",
                    "HELM_DEBUG",
                    "HELM_MAX_HISTORY",
                    "HELM_DRIVER_SQL_CONNECTION_STRING",
                )
            )
            assert observed.get("KUBECONFIG") != "caller-private-config"
        assert not (tmp_path / "late-record").exists()


@pytest.mark.asyncio
async def test_missing_tool_and_rejected_probe_never_stage_or_read_cluster(tmp_path):
    async with adapter_source(tmp_path, version="v4.3.2") as (
        adapter,
        client,
        api,
        request,
        _,
        record,
    ):
        with pytest.raises(HelmProblem) as problem:
            await adapter.list(request, lambda: None)
        assert problem.value.kind == "unsupported-version"
        assert len(calls(record)) == 1 and not api.requests
        assert not list(Path(client.directory.name).glob("helm-*"))
        missing = HelmAdapter(
            client,
            AccessPolicy(False),
            replace(adapter.settings, executable=str(tmp_path / "missing")),
            adapter.environment,
            tmp_path,
        )
        try:
            with pytest.raises(HelmProblem) as problem:
                await missing.list(request, lambda: None)
            assert problem.value.kind == "missing-tool" and "install supported" in str(
                problem.value
            )
            assert not list(Path(client.directory.name).glob("helm-*"))
        finally:
            await missing.close()


@pytest.mark.asyncio
async def test_executable_removed_after_successful_probe_is_feature_local_and_cleans_stage(
    tmp_path,
):
    async with adapter_source(tmp_path) as (adapter, client, _, request, *_):
        await adapter.version(lambda: None)
        Path(adapter.settings.executable).unlink()
        with pytest.raises(HelmProblem) as failure:
            await adapter.list(request, lambda: None)
        assert failure.value.kind == "missing-tool"
        assert not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,kind",
    [
        ("malformed", "invalid-output"),
        ("overflow", "output-limit"),
        ("stderr-overflow", "output-limit"),
    ],
)
async def test_malformed_and_excessive_output_refuse_partial_parsing_and_clean_files(
    tmp_path, mode, kind
):
    async with adapter_source(tmp_path, mode=mode) as (adapter, client, _, request, _, record):
        with pytest.raises(HelmProblem) as problem:
            await adapter.list(request, lambda: None)
        assert problem.value.kind == kind and "sensitive arbitrary" not in str(problem.value)
        assert not list(Path(client.directory.name).glob("helm-*"))
        for invocation in calls(record):
            with pytest.raises(ProcessLookupError):
                os.kill(invocation["pid"], 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stderr,kind",
    [
        ("Error: release: not found private", "missing-release"),
        ("secrets is forbidden private", "forbidden"),
        ("Unauthorized private", "authentication"),
        ("unrecognized sensitive private", "unavailable"),
    ],
)
async def test_nonzero_stderr_is_categorized_without_raw_echo(tmp_path, stderr, kind):
    async with adapter_source(tmp_path, mode="error", error=stderr) as (adapter, _, _, request, *_):
        with pytest.raises(HelmProblem) as problem:
            await adapter.list(request, lambda: None)
        assert problem.value.kind == kind and "private" not in str(problem.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("version_probe", [False, True])
async def test_cancellation_reaps_process_groups_before_private_file_removal(
    tmp_path, version_probe
):
    options = {"version_mode" if version_probe else "mode": "sleep"}
    async with adapter_source(tmp_path, **options) as (adapter, client, _, request, _, record):
        operation = asyncio.create_task(adapter.list(request, lambda: None))
        child_path = Path(str(record) + ".child")
        child = await wait_pid(child_path)
        assert os.getpgid(child) == calls(record)[-1]["pid"]
        before_cancel = owned_process_state(child)
        owned_paths = list(Path(client.directory.name).glob("helm-*"))
        assert bool(owned_paths) is not version_probe
        operation.cancel()
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert not list(Path(client.directory.name).glob("helm-*"))
        for invocation in calls(record):
            with pytest.raises(ProcessLookupError):
                os.kill(invocation["pid"], 0)
        states = await wait_owned_process_stopped(
            child, tmp_path / "descendant-stop.json", before_cancel=before_cancel
        )
        assert states[-1] in {"absent", "Z"}
        await adapter.close()
        await adapter.close()


@pytest.mark.asyncio
async def test_descendant_stop_observation_rejects_a_live_owned_child(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        "import time; time.sleep(60)",
        cwd=tmp_path,
        env={},
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    evidence = tmp_path / "live-descendant-stop.json"
    try:
        with pytest.raises(AssertionError, match="did not terminate"):
            await wait_owned_process_stopped(
                process.pid, evidence, before_cancel=owned_process_state(process.pid), timeout=0.05
            )
        assert process.returncode is None
    finally:
        process.kill()
        await process.wait()
    states = await wait_owned_process_stopped(
        process.pid, tmp_path / "reaped-descendant-stop.json", before_cancel="reaped"
    )
    assert states == ("absent",)


@pytest.mark.asyncio
@pytest.mark.parametrize("version_probe", [False, True])
async def test_real_process_timeout_is_not_partial_success(tmp_path, monkeypatch, version_probe):
    original = ProcessRunner.capture

    async def deadline(self, command, *, timeout=30, guard=None):
        return await original(self, command, timeout=0.1, guard=guard)

    monkeypatch.setattr(ProcessRunner, "capture", deadline)
    options = {"version_mode" if version_probe else "mode": "sleep"}
    async with adapter_source(tmp_path, **options) as (adapter, client, _, request, *_):
        with pytest.raises(HelmProblem) as problem:
            await adapter.list(request, lambda: None)
        assert problem.value.kind == "timeout"
        assert not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_staging_thread_is_drained_after_cancellation_before_file_cleanup(
    tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    original = ConnectionFile.write

    def writing(self, configuration):
        original(self, configuration)
        started.set()
        release.wait(3)

    monkeypatch.setattr(ConnectionFile, "write", writing)
    async with adapter_source(tmp_path) as (adapter, client, _, request, _, record):
        operation = asyncio.create_task(adapter.list(request, lambda: None))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            operation.cancel()
            await asyncio.sleep(0.02)
            assert not operation.done() and list(Path(client.directory.name).glob("helm-*"))
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert len(calls(record)) == 1 and not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_parser_is_drained_under_repeated_cancel_before_staged_connection_unlinks(
    tmp_path, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    original = helm_adapter.parse_helm_list

    def parsing(data, scope):
        started.set()
        release.wait(3)
        return original(data, scope)

    monkeypatch.setattr(helm_adapter, "parse_helm_list", parsing)
    async with adapter_source(tmp_path) as (adapter, client, _, request, *_):
        operation = asyncio.create_task(adapter.list(request, lambda: None))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            operation.cancel()
            await asyncio.sleep(0.02)
            operation.cancel()
            await asyncio.sleep(0.02)
            assert not operation.done() and list(Path(client.directory.name).glob("helm-*"))
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert not list(Path(client.directory.name).glob("helm-*"))


@pytest.mark.asyncio
async def test_guard_refusal_precedes_executable_resolution_and_staging(tmp_path, monkeypatch):
    def lookup(*args, **kwargs):
        raise AssertionError("Executable lookup must not run.")

    monkeypatch.setattr("shutil.which", lookup)
    async with adapter_source(tmp_path) as (adapter, client, _, request, _, record):

        def guard():
            raise HelmProblem("stale", "Captured request expired.")

        with pytest.raises(HelmProblem, match="expired"):
            await adapter.list(request, guard)
        assert not record.exists() and not list(Path(client.directory.name).glob("helm-*"))
