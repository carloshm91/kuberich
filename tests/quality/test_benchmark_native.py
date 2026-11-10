"""Native adapter receipts bind exact tools, terminal cleanup and actual host PID scope."""

import json
import os
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts import benchmark_native as native
from scripts.supply_chain import digest


@dataclass
class Host:
    directory: Path
    bundle: Path
    linux: bool = True
    executable: str = "/app/kuberich"
    profile: Path | None = None
    calls: list[tuple[list[str], dict[str, str], bool]] = field(default_factory=list)

    def command(self, argv, environment, *, tty=False):
        self.calls.append((list(argv), dict(environment), tty))
        return (
            ["docker", "--host", "unix:///fixture", "run", "--rm", "image", *argv]
            if self.linux
            else ["sandbox-exec", "-f", "owned.sb", *argv]
        )


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    source = tmp_path / "source"
    (source / "tests/support").mkdir(parents=True)
    (source / "tests/support/benchmark_forward.c").write_text("synthetic C source")
    (source / "tests/support/benchmark_terminal.py").write_text("synthetic driver source")
    (source / "artifacts/terminal").mkdir(parents=True)
    parent = tmp_path / "native"
    (parent / "tools").mkdir(mode=0o700, parents=True)
    bundle = parent / "bundle"
    bundle.mkdir()
    (bundle / "kuberich").write_bytes(b"exact native bytes")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    vegeta = tmp_path / "vegeta"
    vegeta.write_bytes(b"authenticated fixture tool")
    state = {
        "source": source,
        "evidence": evidence,
        "vegeta": vegeta,
        "host": Host(parent, bundle),
        "compiler": [],
        "driver": [],
        "fault": "",
    }
    monkeypatch.setattr(native, "ROOT", source)
    monkeypatch.setattr(native, "verify_benchmark_binary", lambda path: digest(path))
    monkeypatch.setattr(native, "native_target", lambda: "linux-x86_64")

    def compile(command, **kwargs):
        state["compiler"].append((command, kwargs))
        if state["fault"] == "compiler":
            return subprocess.CompletedProcess(command, 1, "", "synthetic compiler failure")
        Path(command[-1]).write_bytes(b"compiled C bridge")
        return subprocess.CompletedProcess(command, 0, "", "")

    class Driver:
        def terminal_benchmark_missing_tool(self, command, directory, name, **kwargs):
            receipt = {
                "exit": 0,
                "terminal_mode_restored": True,
                "alternate_screen_closed": True,
                "cursor_restored": True,
                "reporting_modes_disabled": dict.fromkeys(
                    ["1000", "1003", "1004", "1006", "2004"], True
                ),
            }
            for suffix in ("", "-restart"):
                path = source / "artifacts/terminal" / (name + suffix)
                path.with_suffix(".json").write_text(json.dumps(receipt))
                path.with_suffix(".ansi").write_bytes(b"synthetic missing-tool terminal receipt")
            return {
                "http_requests": 1 if state["fault"] == "missing-traffic" else 0,
                "completion": "tool_failed",
                "forward_started": False,
            }

        def terminal_benchmark(self, command, directory, name, **kwargs):
            stop = kwargs["stop"]
            state["driver"].append((command, directory, name, kwargs))
            wrapped = kwargs["prepare_command"](
                [*command, "--command", "svc team"], {"OWNED_BENCHMARK_PORT": "1234"}
            )
            assert "--user" in wrapped and "--pid=host" in wrapped
            receipt = {
                "exit": 0,
                "terminal_mode_restored": True,
                "alternate_screen_closed": True,
                "cursor_restored": True,
                "reporting_modes_disabled": dict.fromkeys(
                    ["1000", "1003", "1004", "1006", "2004"], True
                ),
            }
            if state["fault"] == "terminal":
                receipt["cursor_restored"] = False
            for suffix in ("", "-restart"):
                path = source / "artifacts/terminal" / (name + suffix)
                path.with_suffix(".json").write_text(json.dumps(receipt))
                path.with_suffix(".ansi").write_bytes(b"synthetic terminal receipt")
            process = subprocess.Popen(["/bin/true"])
            process.wait(timeout=3)
            path = directory / "benchmark-forward.json"
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                closed_port = listener.getsockname()[1]
            raw = {
                "pid": os.getpid() if state["fault"] == "live-process" else process.pid,
                "port": closed_port,
                "config": str(directory / "removed-private-config"),
            }
            if state["fault"] == "private-config":
                Path(raw["config"]).write_text("synthetic private config")
            if state["fault"] == "journal-schema":
                raw["credential"] = "never accepted"
            path.write_text(json.dumps(raw))
            path.chmod(0o644 if state["fault"] == "public-journal" else 0o600)
            if state["fault"] == "source-changed":
                (source / "tests/support/benchmark_forward.c").write_text("changed C source")
            if state["fault"] == "profile-changed":
                state["host"].profile.write_text("changed sandbox profile")
            return {
                "stop": stop,
                "completion": "complete" if stop == "complete" else "cancelled",
                "http_requests": 0 if state["fault"] == "no-traffic" else 4,
            }

    monkeypatch.setattr(native.subprocess, "run", compile)
    monkeypatch.setattr(native, "import_module", lambda name: Driver())
    return state


def verify(state):
    host = state["host"]
    return native.verify_native_benchmarks(
        host, host.directory / "benchmark", state["evidence"], state["vegeta"]
    )


def test_native_adapter_uses_fixed_paths_retains_every_receipt_and_binds_inputs(fixture):
    result = verify(fixture)
    host = fixture["host"]
    assert result["actual_vegeta_traffic"] and result["compiled_forward_fixture"]
    assert result["outside_python_executed"] is False
    assert result["linux_shared_host_network_and_pid_identity"] is True
    assert result["linux_shared_pid_proc_exposure"] is True
    assert result["filesystem_isolation_qualified"] is False
    assert result["inputs_sha256"]["native_executable"] == digest(host.bundle / "kuberich")
    assert result["inputs_sha256"]["vegeta"] == digest(fixture["vegeta"])
    assert set(result["observations"]) == {"complete", "cancel", "missing_tool"}
    retained = fixture["evidence"] / "benchmarks"
    assert json.loads((retained / "evidence.json").read_text()) == result
    assert len(list(retained.glob("*.ansi"))) == 6
    assert (retained / "complete-forward.json").exists() and (
        retained / "cancel-forward.json"
    ).exists()
    assert not (host.directory / "benchmark/benchmark-forward.json").exists()
    for command, directory, _, kwargs in fixture["driver"]:
        assert command == [host.executable] and directory == host.directory / "benchmark"
        assert kwargs["vegeta"] == host.directory / "tools/vegeta"
        assert kwargs["kubectl"] == host.directory / "tools/benchmark-kubectl"
    compiler, options = fixture["compiler"][0]
    assert compiler[:5] == ["cc", "-std=c99", "-Wall", "-Wextra", "-Werror"]
    assert options["timeout"] == 60 and options["capture_output"]
    assert stat_mode(host.directory / "tools/vegeta") == 0o500


def stat_mode(path):
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize(
    "fault",
    [
        "compiler",
        "terminal",
        "live-process",
        "private-config",
        "journal-schema",
        "public-journal",
        "source-changed",
        "no-traffic",
        "missing-traffic",
    ],
)
def test_native_adapter_refuses_unproved_execution_or_cleanup(fixture, fault):
    fixture["fault"] = fault
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        verify(fixture)
    assert not (fixture["evidence"] / "benchmarks/evidence.json").exists()


def test_wrong_paths_existing_destinations_and_unknown_binaries_refused_before_driver(
    fixture, monkeypatch
):
    host = fixture["host"]
    with pytest.raises(ValueError):
        native.verify_native_benchmarks(
            host, host.directory / "other", fixture["evidence"], fixture["vegeta"]
        )
    monkeypatch.setattr(
        native,
        "verify_benchmark_binary",
        lambda path: (_ for _ in ()).throw(ValueError("unreviewed bytes")),
    )
    with pytest.raises(ValueError, match="unreviewed"):
        verify(fixture)
    assert not fixture["driver"] and not fixture["compiler"]
    monkeypatch.setattr(native, "verify_benchmark_binary", lambda path: digest(path))
    target = host.directory / "tools/vegeta"
    target.write_bytes(b"existing")
    with pytest.raises(ValueError, match="already exists"):
        verify(fixture)
    assert target.read_bytes() == b"existing" and not fixture["driver"]


@pytest.mark.parametrize("changed", [False, True])
def test_actual_sandbox_profile_bytes_are_bound_and_drift_refused(fixture, changed):
    profile = fixture["host"].directory / "native.sb"
    profile.write_text("synthetic native sandbox policy")
    fixture["host"].profile = profile
    fixture["fault"] = "profile-changed" if changed else ""
    if changed:
        with pytest.raises(ValueError, match="inputs changed"):
            verify(fixture)
    else:
        assert verify(fixture)["inputs_sha256"]["sandbox_profile"] == digest(profile)


def test_wrapper_changes_only_benchmark_docker_process_identity_and_explicit_fixture_environment(
    tmp_path,
):
    host = Host(tmp_path, tmp_path / "bundle")
    environment = {"OWNED_BENCHMARK_PORT": "4321"}
    command = native.benchmark_command(host, [host.executable], environment)
    assert command[:10] == [
        "docker",
        "--host",
        "unix:///fixture",
        "run",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--pid=host",
        "--workdir",
        str(tmp_path / "benchmark"),
        "--rm",
    ]
    assert environment["TMPDIR"] == str(tmp_path / "benchmark")
    assert environment["KUBERICH_CONFIG"] == str(tmp_path / "benchmark/preferences.yaml")
    assert environment["KUBECONFIG"] == str(tmp_path / "benchmark/never-use-a-real-cluster")
    assert host.calls[0][2] is True
    host.linux = False
    command = native.benchmark_command(host, ["/native/kuberich"], {})
    assert command == ["sandbox-exec", "-f", "owned.sb", "/native/kuberich"]


@pytest.mark.parametrize("unsafe", ["writable", "symlink"])
def test_native_tools_directory_refuses_shared_write_or_link_before_copy_and_compile(
    fixture, unsafe
):
    tools = fixture["host"].directory / "tools"
    if unsafe == "writable":
        tools.chmod(0o770)
    else:
        actual = fixture["host"].directory / "real-tools"
        tools.rename(actual)
        tools.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="private physical"):
        verify(fixture)
    assert not fixture["driver"] and not fixture["compiler"] and not (tools / "vegeta").exists()
