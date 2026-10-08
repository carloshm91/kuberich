"""Actual source/installed CLI forwarding through explicitly owned TCP fixtures."""

import json
import os
import re
import socket
import threading
from http.server import ThreadingHTTPServer

import yaml

from tests.support.port_forwards import executable
from tests.support.standard_terminal import Handler
from tests.support.terminal_api import config
from tests.terminal.pty_support import TerminalSession


def terminal_forward(command, directory, evidence):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.stopping = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    path = config(
        directory / "fixture-config",
        f"http://127.0.0.1:{server.server_port}",
        {"token": "synthetic-pty"},
    )
    data = yaml.safe_load(path.read_text())
    data["current-context"] = data["contexts"][0]["name"] = "kubetrol-test-one"
    path.write_text(yaml.safe_dump(data))
    before = path.read_bytes()
    environment = executable(directory)
    try:
        with TerminalSession(
            [
                *command,
                "--kubeconfig",
                str(path),
                "--context",
                "kubetrol-test-one",
                "--command",
                "svc team",
            ],
            directory,
            environment={"PATH": environment["PATH"]},
        ) as terminal:
            terminal.wait_for_screen("services(team)[1]")
            marker = terminal.send(b"F")
            terminal.wait_for_screen("TCP mappings", since=marker)
            terminal.send(b"\x01\x0b:80\r")
            terminal.wait_for_screen("Listening; context changes stop this session.")
            pid = int((directory / "forward-child.pid").read_text())
            argv = json.loads((directory / "forward-argv.json").read_text())
            terminal.send(b"\x1b")
            terminal.wait_for_screen("services(team)[1]", absent=("Port forwards",))
            marker = terminal.send(b":pf\r")
            terminal.wait_for_screen("Listening; context changes stop this session.", since=marker)
            terminal.wait_for_screen("REQUESTED")
            terminal.wait_for_screen("->81")
            # Service targetPort and ephemeral local port are observed from the table.
            ports = []
            for line in terminal.screen.display:
                ports.extend(re.findall(r"([0-9]+)->81", line))
            assert len(ports) == 1, terminal.screen.display
            port = int(ports[0])
            with socket.create_connection(("127.0.0.1", port), timeout=3) as peer:
                peer.sendall(b"owned-terminal-payload")
                assert peer.recv(128) == b"owned-response:owned-terminal-payload"
            terminal.resize(40, 12)
            terminal.wait_for_screen("Port forwards")
            terminal.resize(100, 30)
            terminal.send(b"s")
            terminal.wait_for_screen("Stopped by operator.")
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Stopped child still exists")
            assert not os.path.exists(argv[0].split("=", 1)[1])
            try:
                peer = socket.create_connection(("127.0.0.1", port), timeout=2)
            except OSError:
                pass
            else:
                peer.close()
                raise AssertionError("Stopped port still accepts connections")
            terminal.send(b"\x1b")
            terminal.wait_for_screen("services(team)[1]", absent=("Port forwards",))
            # Quit with another real forward active; app exit must own its cleanup.
            terminal.send(b"F")
            terminal.wait_for_screen("TCP mappings")
            terminal.send(b"\r")
            terminal.wait_for_screen("Listening; context changes stop this session.")
            exit_pid = int((directory / "forward-child.pid").read_text())
            exit_argv = json.loads((directory / "forward-argv.json").read_text())
            terminal.send(b"\x11")
            terminal.finish()
            terminal.save_evidence(evidence)
            try:
                os.kill(exit_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Application abandoned a forwarding child")
            assert not os.path.exists(exit_argv[0].split("=", 1)[1])
            assert b"synthetic-pty" not in terminal.transcript
        assert path.read_bytes() == before
    finally:
        server.stopping.set()
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()
        assert not thread.is_alive()
