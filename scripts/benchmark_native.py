"""Actual native HTTP benchmark PTYs with an authenticated tool and compiled bridge."""

import json
import os
import platform
import shutil
import socket
import stat
import subprocess
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from scripts.benchmark_tools import verify_benchmark_binary
from scripts.standalone import native_target
from scripts.supply_chain import digest

ROOT = Path(__file__).resolve().parents[1]


class NativeHost(Protocol):
    directory: Path
    bundle: Path
    linux: bool
    profile: Path | None

    @property
    def executable(self) -> str: ...

    def command(
        self, argv: list[str], environment: dict[str, str], *, tty: bool = False
    ) -> list[str]: ...


class BenchmarkDriver(Protocol):
    def terminal_benchmark(
        self,
        command: list[str],
        directory: Path,
        evidence: str,
        *,
        vegeta: Path,
        stop: str,
        kubectl: Path,
        prepare_command: Callable[[list[str], dict[str, str]], list[str]],
    ) -> dict[str, object]: ...

    def terminal_benchmark_missing_tool(
        self,
        command: list[str],
        directory: Path,
        evidence: str,
        *,
        kubectl: Path,
        prepare_command: Callable[[list[str], dict[str, str]], list[str]],
    ) -> dict[str, object]: ...


def original_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def benchmark_command(host: NativeHost, argv: list[str], environment: dict[str, str]) -> list[str]:
    # All private files stay on the mounted fixture path. The controller owns the
    # host PIDs in the receipt; only this benchmark cohort shares PID identity.
    environment.update(
        HOME=str(host.directory / "benchmark"), TMPDIR=str(host.directory / "benchmark")
    )
    environment.update(
        TERM="xterm-256color",
        KUBERICH_CONFIG=str(host.directory / "benchmark/preferences.yaml"),
        KUBERICH_LOG_FILE=str(host.directory / "benchmark/kuberich.log"),
        KUBERICH_LOG_LEVEL="DEBUG",
        KUBERICH_CLIPBOARD="osc52",
        KUBECONFIG=str(host.directory / "benchmark/never-use-a-real-cluster"),
    )
    command = host.command(argv, environment, tty=True)
    if host.linux:
        try:
            position = command.index("run") + 1
        except ValueError:
            raise ValueError(
                "The native benchmark host did not provide an owned Docker run."
            ) from None
        command[position:position] = ["--user", f"{os.getuid()}:{os.getgid()}", "--pid=host"]
    return command


def terminal_receipt(name: str, destination: Path) -> dict[str, object]:
    root = ROOT / "artifacts/terminal"
    source = root / (name + ".json")
    receipt = json.loads(source.read_text())
    if (
        receipt.get("exit") != 0
        or receipt.get("terminal_mode_restored") is not True
        or receipt.get("alternate_screen_closed") is not True
        or receipt.get("cursor_restored") is not True
        or not isinstance(receipt.get("reporting_modes_disabled"), dict)
        or set(receipt["reporting_modes_disabled"]) != {"1000", "1003", "1004", "1006", "2004"}
        or not all(value is True for value in receipt["reporting_modes_disabled"].values())
    ):
        raise ValueError("Native benchmark PTY cleanup/restoration evidence is incomplete.")
    retained: dict[str, object] = {}
    for suffix in (".json", ".ansi"):
        path = root / (name + suffix)
        target = destination / path.name
        if target.exists() or target.is_symlink():
            raise ValueError("Use a fresh native benchmark evidence directory.")
        shutil.copyfile(path, target)
        retained[suffix.removeprefix(".")] = {"file": target.name, "sha256": digest(target)}
    return retained


def forward_receipt(directory: Path, destination: Path, stop: str) -> dict[str, object]:
    path = directory / "benchmark-forward.json"
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
        or before.st_size > 8192
    ):
        raise ValueError("Native benchmark bridge receipt must be private and physical.")
    data = path.read_bytes()
    raw = json.loads(data)
    if (
        not isinstance(raw, dict)
        or raw.keys() != {"pid", "port", "config"}
        or type(raw["pid"]) is not int
        or raw["pid"] <= 1
        or type(raw["port"]) is not int
        or not 1 <= raw["port"] <= 65535
        or not isinstance(raw["config"], str)
        or not Path(raw["config"]).is_absolute()
        or not Path(raw["config"]).is_relative_to(directory)
    ):
        raise ValueError("Invalid native benchmark bridge receipt.")
    try:
        os.kill(raw["pid"], 0)
    except ProcessLookupError:
        pass
    else:
        raise ValueError("The native benchmark bridge process is still present.")
    with socket.socket() as peer:
        peer.settimeout(1)
        if peer.connect_ex(("127.0.0.1", raw["port"])) == 0:
            raise ValueError("The native benchmark bridge listener was not closed.")
    if Path(raw["config"]).exists():
        raise ValueError("Native benchmark private connection material was not removed.")
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (
        after.st_dev,
        after.st_ino,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_size,
    ):
        raise ValueError("Native bridge receipt changed while being checked.")
    retained = destination / (stop + "-forward.json")
    with retained.open("xb") as stream:
        stream.write(data)
    retained.chmod(0o600)
    # This exact fixture entry is now retained and verified. Never mistake an old
    # PID/listener journal for the next run's readiness receipt.
    path.unlink()
    return {
        "file": retained.name,
        "sha256": digest(retained),
        "pid": raw["pid"],
        "process_reaped": True,
        "listener_closed": True,
        "private_config_removed": True,
    }


def verify_native_benchmarks(
    host: NativeHost, directory: Path, evidence: Path, vegeta: Path
) -> dict[str, Any]:
    if directory != host.directory / "benchmark" or not directory.is_absolute():
        raise ValueError("Use the owned native host's fixed benchmark fixture directory.")
    tool_digest = verify_benchmark_binary(vegeta)
    tools = host.directory / "tools"
    target = tools / "vegeta"
    if target.exists() or target.is_symlink():
        raise ValueError("Native benchmark tool destination already exists.")
    with target.open("xb") as output:
        output.write(vegeta.read_bytes())
    target.chmod(0o500)
    if digest(target) != tool_digest:
        raise ValueError("Native benchmark tool changed during its authenticated copy.")
    retained = evidence / "benchmarks"
    retained.mkdir(mode=0o700, exist_ok=False)
    helper = tools / "benchmark-kubectl"
    if helper.exists() or helper.is_symlink():
        raise ValueError("Native benchmark bridge destination already exists.")
    helper_source = ROOT / "tests/support/benchmark_forward.c"
    helper_source_digest = digest(helper_source)
    compilation = subprocess.run(
        [
            "cc",
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(["-static"] if platform.system() == "Linux" else []),
            str(helper_source),
            "-o",
            str(helper),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    original_json(
        retained / "compiler.json",
        {
            "exit": compilation.returncode,
            "stdout": compilation.stdout,
            "stderr": compilation.stderr,
        },
    )
    compilation.check_returncode()
    directory.mkdir(mode=0o700, exist_ok=False)
    inputs = {
        "native_executable": digest(host.bundle / "kuberich"),
        "vegeta": digest(target),
        "bridge_source": helper_source_digest,
        "bridge_binary": digest(helper),
        "terminal_driver": digest(ROOT / "tests/support/benchmark_terminal.py"),
    }
    if host.profile is not None:
        inputs["sandbox_profile"] = digest(host.profile)
    driver = cast(BenchmarkDriver, import_module("tests.support.benchmark_terminal"))
    observations: dict[str, dict[str, object]] = {}
    for stop in ("complete", "cancel"):
        name = "native-benchmark-" + native_target() + "-" + stop + "-" + uuid4().hex
        observed = driver.terminal_benchmark(
            [host.executable],
            directory,
            name,
            vegeta=target,
            stop=stop,
            kubectl=helper,
            prepare_command=lambda argv, env: benchmark_command(host, argv, env),
        )
        if (
            observed.get("stop") != stop
            or observed.get("completion") != ("complete" if stop == "complete" else "cancelled")
            or type(observed.get("http_requests")) is not int
            or cast(int, observed["http_requests"]) < 1
        ):
            raise ValueError(
                "Native benchmark did not observe actual load and expected completion."
            )
        observations[stop] = {
            **observed,
            "active_pty": terminal_receipt(name, retained),
            "restart_pty": terminal_receipt(name + "-restart", retained),
            "forward": forward_receipt(directory, retained, stop),
        }
    missing_name = "native-benchmark-" + native_target() + "-missing-" + uuid4().hex
    missing = driver.terminal_benchmark_missing_tool(
        [host.executable],
        directory,
        missing_name,
        kubectl=helper,
        prepare_command=lambda argv, env: benchmark_command(host, argv, env),
    )
    if (
        missing != {"http_requests": 0, "completion": "tool_failed", "forward_started": False}
        or (directory / "benchmark-forward.json").exists()
    ):
        raise ValueError("Native missing-tool control started traffic or a forward.")
    observations["missing_tool"] = {
        **missing,
        "active_pty": terminal_receipt(missing_name, retained),
        "restart_pty": terminal_receipt(missing_name + "-restart", retained),
    }
    after = {
        "native_executable": digest(host.bundle / "kuberich"),
        "vegeta": digest(target),
        "bridge_source": digest(helper_source),
        "bridge_binary": digest(helper),
        "terminal_driver": digest(ROOT / "tests/support/benchmark_terminal.py"),
    }
    if host.profile is not None:
        after["sandbox_profile"] = digest(host.profile)
    if after != inputs:
        raise ValueError("Native benchmark measured inputs changed during execution.")
    receipt = {
        "schema_version": 1,
        "inputs_sha256": inputs,
        "observations": observations,
        "actual_vegeta_traffic": True,
        "compiled_forward_fixture": True,
        "outside_python_executed": False,
        "linux_shared_host_network_and_pid_identity": host.linux,
        "linux_shared_pid_proc_exposure": host.linux,
        "filesystem_isolation_qualified": False,
        "benchmark_executable_paths": [str(target), str(directory / "kubectl")],
        "scope": "Actual frozen executable, authenticated Go Vegeta and synthetic compiled C TCP bridge; no outside Python used by that application/tool cohort. Shared Linux PID/network identity exposes host /proc and is not a filesystem or interpreter-inaccessibility certification. Generic native isolation controls remain separate; this bridge is not real Kubernetes/provider certification.",
    }
    original_json(retained / "evidence.json", receipt)
    return receipt
