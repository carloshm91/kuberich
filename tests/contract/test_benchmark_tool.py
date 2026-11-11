"""Real process faults exercise bounded private input, cancellation and child cleanup."""

import asyncio
import sys
import threading
from pathlib import Path

import pytest

from kuberich.domain.benchmarks import LoadOptions, RequestOptions
from kuberich.errors import AppError
from kuberich.services import benchmark_tool as tool_module
from kuberich.services.access import AccessPolicy
from kuberich.services.benchmark_tool import (
    BenchmarkCleanupError,
    BenchmarkTool,
    BenchmarkToolError,
)
from tests.support.benchmarks import executable, gone, receipt


def owner(tmp_path, mode="normal", *, policy=None, guard=lambda: None):
    return BenchmarkTool(executable(tmp_path, mode), policy or AccessPolicy(False), tmp_path, guard)


@pytest.mark.asyncio
async def test_explicit_private_target_minimal_env_literal_args_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://synthetic-private-proxy")
    monkeypatch.setenv("KUBECONFIG", "/synthetic-private-kubeconfig")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-private-credential")
    monkeypatch.setenv("__CF_USER_TEXT_ENCODING", "synthetic-private-encoding")
    supplied_environments = []
    loop = asyncio.get_running_loop()
    launch = loop.subprocess_exec

    async def observe_launch(protocol_factory, *arguments, **options):
        supplied_environments.append(dict(options["env"]))
        return await launch(protocol_factory, *arguments, **options)

    monkeypatch.setattr(loop, "subprocess_exec", observe_launch)
    tool = owner(tmp_path)
    version = await tool.probe()
    metrics = await tool.execute(
        RequestOptions(
            target="/private?secret=synthetic",
            headers=(("Authorization", "Bearer synthetic-private"),),
            body=b"synthetic-body",
        ),
        LoadOptions(duration_seconds=2),
        12345,
        version=version,
    )
    assert metrics.attempts == metrics.successful_requests == 2
    assert supplied_environments == [{"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}] * 3
    observed_keys = {"PATH", "LANG", "LC_ALL", "LC_CTYPE"}
    if sys.platform == "darwin":
        # Apple's CoreFoundation may add this inside the Python fault helper.
        # It remains absent from the exact environment passed to the OS above.
        observed_keys.add("__CF_USER_TEXT_ENCODING")
    for phase in ("version", "attack", "report"):
        observed = await receipt(tmp_path / (phase + ".json"))
        assert observed["environment"].keys() <= observed_keys
        assert "synthetic-private" not in repr(observed)
        await gone(observed["pid"])
    assert len(tool.process_ids) == 3
    assert not tuple(tmp_path.glob("benchmark-*"))
    assert b"Bearer synthetic-private" in (tmp_path / "target.json").read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["version-fail", "version-flood", "version-sleep"])
async def test_version_failure_never_stages_or_attacks(tmp_path, mode):
    tool = owner(tmp_path, mode)
    with pytest.raises(BenchmarkToolError) as error:
        await tool.probe()
    assert "synthetic-private" not in str(error.value)
    assert not (tmp_path / "attack.json").exists() and not tuple(tmp_path.glob("benchmark-*"))
    for pid in tool.process_ids:
        await gone(pid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["attack-fail", "attack-flood", "report-fail", "report-flood", "report-malformed"]
)
async def test_raw_failure_is_fixed_classified_and_private_files_are_removed(tmp_path, mode):
    tool = owner(tmp_path, mode)
    with pytest.raises(BenchmarkToolError) as error:
        await tool.execute(
            RequestOptions(),
            LoadOptions(duration_seconds=1, timeout_seconds=1),
            12345,
            version="12.13.0",
        )
    assert error.value.reason == (
        "malformed_output" if mode == "report-malformed" else "tool_failed"
    )
    assert "synthetic-private" not in str(error.value) and not tuple(tmp_path.glob("benchmark-*"))
    for pid in tool.process_ids:
        await gone(pid)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["attack", "report"])
async def test_repeated_cancellation_reaps_before_private_files_disappear(tmp_path, phase):
    tool = owner(tmp_path, phase + "-sleep")
    task = asyncio.create_task(
        tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    )
    observed = await receipt(tmp_path / (phase + ".json"))
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await gone(observed["pid"])
    assert not tuple(tmp_path.glob("benchmark-*"))


@pytest.mark.asyncio
async def test_leader_exit_with_descendant_pipe_is_reaped(tmp_path):
    tool = owner(tmp_path, "attack-descendant")
    metrics = await tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    # This fault helper supplies a valid report independently of its synthetic
    # attack bytes. Its purpose here is leader/descendant cleanup, not gob compatibility.
    assert metrics.attempts == 2
    await gone(int((tmp_path / "descendant.pid").read_text()))
    assert not tuple(tmp_path.glob("benchmark-*"))


@pytest.mark.asyncio
async def test_readonly_and_invalid_executable_refuse_before_effects(tmp_path):
    with pytest.raises(AppError, match="absolute"):
        BenchmarkTool(Path("vegeta"), AccessPolicy(False), tmp_path, lambda: None)
    tool = owner(tmp_path, policy=AccessPolicy(True))
    with pytest.raises(AppError, match="Read-only"):
        await tool.probe()
    assert not (tmp_path / "version.json").exists()


@pytest.mark.asyncio
async def test_cancel_during_directory_creation_still_owns_late_created_directory(
    tmp_path, monkeypatch
):
    entered, released = threading.Event(), threading.Event()
    original = tool_module.tempfile.mkdtemp

    def held(*args, **kwargs):
        entered.set()
        assert released.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(tool_module.tempfile, "mkdtemp", held)
    tool = owner(tmp_path)
    task = asyncio.create_task(
        tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not tuple(tmp_path.glob("benchmark-*"))


@pytest.mark.asyncio
async def test_cleanup_failure_is_not_a_success(tmp_path, monkeypatch):
    tool = owner(tmp_path)

    def refused(path):
        raise OSError("synthetic-private-path")

    monkeypatch.setattr(tool_module.shutil, "rmtree", refused)
    with pytest.raises(BenchmarkCleanupError) as error:
        await tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    assert "synthetic-private" not in str(error.value)


@pytest.mark.asyncio
async def test_unsupported_version_refused_and_nonphysical_private_parent_never_creates(tmp_path):
    path = executable(tmp_path)
    path.write_text(path.read_text().replace("v12.13.0", "v99.0.0"))
    tool = BenchmarkTool(path, AccessPolicy(False), tmp_path, lambda: None)
    with pytest.raises(BenchmarkToolError):
        await tool.probe()
    not_directory = tmp_path / "parent-file"
    not_directory.write_bytes(b"foreign")
    tool = BenchmarkTool(path, AccessPolicy(False), not_directory, lambda: None)
    with pytest.raises(AppError, match="private benchmark"):
        await tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    assert not_directory.read_bytes() == b"foreign"


@pytest.mark.asyncio
async def test_concurrent_execution_refuses_before_second_private_run(tmp_path):
    tool = owner(tmp_path, "attack-sleep")
    task = asyncio.create_task(
        tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    )
    await receipt(tmp_path / "attack.json")
    with pytest.raises(AppError, match="already owned"):
        await tool.execute(RequestOptions(), LoadOptions(), 12345, version="12.13.0")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not tuple(tmp_path.glob("benchmark-*"))
