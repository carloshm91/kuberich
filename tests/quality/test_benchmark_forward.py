"""Actual compiled TCP forwarding fixture, strict scope and task-owned cleanup."""

import json
import os
import platform
import select
import signal
import socket
import socketserver
import stat
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compiled_bridge(tmp_path_factory):
    output = tmp_path_factory.mktemp("native-benchmark") / "kubectl"
    command = [
        "cc",
        "-std=c99",
        "-Wall",
        "-Wextra",
        "-Werror",
        *(["-static"] if platform.system() == "Linux" else []),
        str(ROOT / "tests/support/benchmark_forward.c"),
        "-o",
        str(output),
    ]
    subprocess.run(command, capture_output=True, check=True, timeout=30)
    return output


def argv(binary, config):
    return [
        str(binary),
        f"--kubeconfig={config}",
        "--context=kuberich-test-one",
        "--namespace=team",
        "port-forward",
        "--address=127.0.0.1",
        "--pod-running-timeout=10s",
        "pod/backend",
        "0:8080",
    ]


def private_config(directory):
    path = directory / "private-config.json"
    path.write_text('{"token":"synthetic-private-value"}')
    path.chmod(0o600)
    return path


class Echo(socketserver.BaseRequestHandler):
    def handle(self):
        with self.server.condition:
            self.server.accepted += 1
            self.server.condition.notify_all()
        while data := self.request.recv(65536):
            self.request.sendall(data)


@contextmanager
def upstream():
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo)
    server.daemon_threads = True
    server.condition, server.accepted = threading.Condition(), 0
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


@contextmanager
def running(binary, directory, port):
    path = private_config(directory)
    process = subprocess.Popen(
        argv(binary, path),
        cwd=directory,
        env={"OWNED_BENCHMARK_PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        assert select.select([process.stdout], [], [], 3)[0]
        line = process.stdout.readline()
        assert line.startswith(b"Forwarding from 127.0.0.1:") and line.endswith(b" -> 8080\n")
        record_path = directory / "benchmark-forward.json"
        record = json.loads(record_path.read_bytes())
        assert record["pid"] == process.pid and record["config"] == str(path)
        assert stat.S_IMODE(record_path.stat().st_mode) == 0o600
        assert b"synthetic-private-value" not in record_path.read_bytes() + line
        assert not list(directory.glob(".benchmark-forward.*"))
        yield process, record
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=3)
            raise
        assert process.returncode == 0 and not stdout and not stderr


def test_actual_tcp_bridge_roundtrip_and_half_close(compiled_bridge, tmp_path):
    with upstream() as server:
        with (
            running(compiled_bridge, tmp_path, server.server_address[1]) as (_, record),
            socket.create_connection(("127.0.0.1", record["port"]), timeout=3) as peer,
        ):
            message = b"synthetic HTTP-like bytes\x00" * 4096
            peer.sendall(message)
            peer.shutdown(socket.SHUT_WR)
            received = bytearray()
            while data := peer.recv(65536):
                received.extend(data)
            assert bytes(received) == message
        with socket.socket() as peer:
            assert peer.connect_ex(("127.0.0.1", record["port"])) != 0


def test_eight_children_ceiling_and_process_group_drain(compiled_bridge, tmp_path):
    peers = []
    children = []
    try:
        with upstream() as server:
            with running(compiled_bridge, tmp_path, server.server_address[1]) as (process, record):
                for _ in range(9):
                    peers.append(socket.create_connection(("127.0.0.1", record["port"]), timeout=3))
                with server.condition:
                    assert server.condition.wait_for(lambda: server.accepted >= 8, timeout=3)
                    assert server.accepted == 8
                if platform.system() == "Linux":
                    path = Path(f"/proc/{process.pid}/task/{process.pid}/children")
                    children = [int(pid) for pid in path.read_text().split()]
                    assert len(children) == 8
                peers[0].close()
                with server.condition:
                    assert server.condition.wait_for(lambda: server.accepted == 9, timeout=3)
            for child in children:
                with pytest.raises(ProcessLookupError):
                    os.kill(child, 0)
    finally:
        for peer in peers:
            peer.close()


@pytest.mark.parametrize(
    "index,value",
    [
        (1, "--kubeconfig=relative"),
        (2, "--context=other"),
        (3, "--namespace=other"),
        (4, "exec"),
        (5, "--address=0.0.0.0"),
        (6, "--pod-running-timeout=0s"),
        (7, "service/backend"),
        (8, "80:8080"),
        (9, "extra"),
    ],
)
def test_literal_forward_scope_refuses_other_arguments(compiled_bridge, tmp_path, index, value):
    command = argv(compiled_bridge, private_config(tmp_path))
    if index == 9:
        command.append(value)
    else:
        command[index] = value
    result = subprocess.run(
        command, cwd=tmp_path, env={"OWNED_BENCHMARK_PORT": "1234"}, capture_output=True, timeout=3
    )
    assert result.returncode and not result.stdout
    assert not (tmp_path / "benchmark-forward.json").exists()


@pytest.mark.parametrize("value", [None, "", "0", "65536", "-1", "+1", " 1", "1x", "9" * 40])
def test_upstream_is_only_an_explicit_numeric_loopback_port(compiled_bridge, tmp_path, value):
    environment = {} if value is None else {"OWNED_BENCHMARK_PORT": value}
    result = subprocess.run(
        argv(compiled_bridge, private_config(tmp_path)),
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 73 and not result.stdout


@pytest.mark.parametrize(
    "fault", ["public", "symlink", "ancestor", "hardlink", "fifo", "directory", "missing"]
)
def test_private_kubeconfig_must_be_physical_owned_0600_regular_file(
    compiled_bridge, tmp_path, fault
):
    path = private_config(tmp_path)
    if fault == "public":
        path.chmod(0o644)
    elif fault == "symlink":
        other = tmp_path / "other"
        path.rename(other)
        path.symlink_to(other)
    elif fault == "ancestor":
        directory = tmp_path / "physical"
        directory.mkdir()
        path.rename(directory / path.name)
        alias = tmp_path / "alias"
        alias.symlink_to(directory, target_is_directory=True)
        path = alias / path.name
    elif fault == "hardlink":
        os.link(path, tmp_path / "link")
    elif fault == "missing":
        path.unlink()
    else:
        path.unlink()
        os.mkfifo(path) if fault == "fifo" else path.mkdir()
    result = subprocess.run(
        argv(compiled_bridge, path),
        cwd=tmp_path,
        env={"OWNED_BENCHMARK_PORT": "1234"},
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 72 and not result.stdout


def test_receipt_symlink_refused_without_overwriting_target(compiled_bridge, tmp_path):
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    (tmp_path / "benchmark-forward.json").symlink_to(sentinel)
    result = subprocess.run(
        argv(compiled_bridge, private_config(tmp_path)),
        cwd=tmp_path,
        env={"OWNED_BENCHMARK_PORT": "1234"},
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == 76 and not result.stdout and sentinel.read_bytes() == b"unchanged"
