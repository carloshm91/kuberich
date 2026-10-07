"""Owned loopback SSH and isolated tmux transports for actual terminal trials."""

import errno
import json
import os
import pwd
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType

# A remote/pane session owner records attributes while its TTY still exists.
# A caught HUP keeps the observer alive; exec resets that caught handler in the
# application, so it does not silently immunize the application against HUP.
OWNER = """
import errno,json,os,signal,subprocess,sys,termios
from pathlib import Path
def encode(mode):
    return [*mode[:6], [v.hex() if isinstance(v,bytes) else v for v in mode[6]]]
observed_signals=[]
process=None
def terminal_signal(value,_):
    observed_signals.append(value)
    if process is not None and process.returncode is None:
        try:
            os.kill(process.pid,value)
        except ProcessLookupError:
            pass
for signum in (signal.SIGHUP,signal.SIGTERM):
    signal.signal(signum, terminal_signal)
spec=json.loads(Path(sys.argv[1]).read_text())
before=encode(termios.tcgetattr(0))
process=subprocess.Popen(spec['command'],cwd=spec['directory'],env=spec['environment'])
ready={'owner':os.getpid(),'connection':os.getppid(),'application':process.pid,
       'before':before,'foreground':os.tcgetpgrp(0)==os.getpgrp(),
       'observer_signals':observed_signals}
temporary=Path(spec['ready']+'.tmp')
temporary.write_text(json.dumps(ready));temporary.replace(spec['ready'])
result=process.wait()
try:
    after=encode(termios.tcgetattr(0));unavailable=None
except termios.error as error:
    after=None;unavailable=error.args[0]
temporary=Path(spec['result']+'.tmp')
temporary.write_text(json.dumps({**ready,'exit':result,'after':after,
                                'tty_unavailable_errno':unavailable}))
temporary.replace(spec['result'])
raise SystemExit(result)
"""

SSH_ENTRY = """
import json,os,sys
from pathlib import Path
path=Path(sys.argv[1]);temporary=Path(sys.argv[1]+'.tmp')
temporary.write_text(json.dumps({'connection':os.getppid(),'entry':os.getpid()}))
temporary.replace(path)
os.execv(sys.argv[2],sys.argv[2:])
"""

SAFE_ENV = {
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "COLORTERM",
    "NO_COLOR",
    "TEXTUAL_COLOR_SYSTEM",
    "KUBETROL_CONFIG",
    "KUBETROL_LOG_FILE",
    "KUBETROL_LOG_LEVEL",
    "KUBECONFIG",
}


class TerminalTransport:
    """No ambient keys/config/agent, global daemon, or existing tmux server."""

    def __init__(self, directory: Path, kind: str) -> None:
        assert kind in {"ssh", "tmux", "ssh_tmux"}
        self.directory, self.kind = directory, kind
        self.directory.mkdir(mode=0o700)
        assert self.directory.stat().st_uid == os.getuid()
        self.directory.chmod(0o700)
        self.socket = directory / "tmux.socket"
        self.socket_directory: TemporaryDirectory[str] | None = None
        self.server: subprocess.Popen[bytes] | None = None
        self.server_log = None
        self.started = False
        self.disconnected = False
        self.record: dict[str, object] | None = None
        self.versions: dict[str, str] = {}
        self.tmux = self._tool("tmux") if "tmux" in kind else None
        if self.tmux is not None:
            self.versions["tmux"] = self._run([self.tmux, "-V"]).stdout.decode().strip()
            # Darwin pytest roots can exceed the Unix-domain socket path limit.
            # Own a separate short private directory rather than truncating or
            # sharing a socket with another fixture/user server.
            self.socket_directory = TemporaryDirectory(prefix="ktrl-tmux-", dir="/tmp")
            self.socket = Path(self.socket_directory.name) / "socket"
        if "ssh" in kind:
            self.ssh = self._tool("ssh")
            version = self._run([self.ssh, "-V"])
            self.versions["ssh"] = version.stderr.decode().strip()
            self.sshd = self._tool("sshd", "/usr/sbin/sshd")
            self.keygen = self._tool("ssh-keygen")
        (directory / "owner.py").write_text(OWNER)
        (directory / "ssh-entry.py").write_text(SSH_ENTRY)
        (directory / "tmux.conf").write_text(
            "set -g status off\nset -g default-terminal screen-256color\n"
            "set -g default-shell /bin/sh\nset -s escape-time 0\n"
        )

    @staticmethod
    def _tool(name: str, fallback: str | None = None) -> str:
        path = shutil.which(name) or fallback
        assert path and Path(path).is_file(), f"Required terminal test tool missing: {name}"
        return path

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(command, capture_output=True, check=True, timeout=10)

    def _start_ssh(self) -> None:
        directory = self.directory
        for name in ("host-key", "client-key"):
            self._run([self.keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(directory / name)])
        authorized = directory / "authorized_keys"
        authorized.write_bytes((directory / "client-key.pub").read_bytes())
        authorized.chmod(0o600)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        self.user = pwd.getpwuid(os.getuid()).pw_name
        config = directory / "sshd.conf"
        # /tmp parents fail OpenSSH StrictModes. This private fixture owns its
        # mode-0700 directory and mode-0600 generated key; the setting affects
        # only this daemon, which accepts only this generated public identity.
        config.write_text(
            "\n".join(
                (
                    f"Port {self.port}",
                    "ListenAddress 127.0.0.1",
                    f'HostKey "{directory / "host-key"}"',
                    f'PidFile "{directory / "sshd.pid"}"',
                    f'AuthorizedKeysFile "{authorized}"',
                    f"AllowUsers {self.user}",
                    "PasswordAuthentication no",
                    "KbdInteractiveAuthentication no",
                    "PubkeyAuthentication yes",
                    "AuthenticationMethods publickey",
                    "UsePAM no",
                    "StrictModes no",
                    "PermitUserRC no",
                    "PermitUserEnvironment no",
                    "DisableForwarding yes",
                    "PermitTTY yes",
                    f'SetEnv "ZDOTDIR={directory}" "HOME={directory}" "LANG=C.UTF-8"',
                    "LogLevel ERROR",
                    "",
                )
            )
        )
        host = (directory / "host-key.pub").read_text().split()
        (directory / "known_hosts").write_text(f"[127.0.0.1]:{self.port} {host[0]} {host[1]}\n")
        self.server_log = (directory / "sshd.log").open("wb")
        self.server = subprocess.Popen(
            [self.sshd, "-D", "-e", "-f", str(config)],
            stdout=self.server_log,
            stderr=self.server_log,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True,
        )
        deadline = time.monotonic() + 5
        while True:
            assert self.server.poll() is None, "Owned sshd failed; inspect its temporary log"
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                assert time.monotonic() < deadline, "Owned loopback sshd startup timed out"
                time.sleep(0.02)

    def __enter__(self) -> "TerminalTransport":
        try:
            if "ssh" in self.kind:
                self._start_ssh()
        except BaseException:
            self.close()
            raise
        return self

    def wrap(
        self, command: list[str], directory: Path, environment: dict[str, str]
    ) -> tuple[list[str], dict[str, str]]:
        safe = {name: value for name, value in environment.items() if name in SAFE_ENV}
        safe["HOME"] = str(self.directory)
        specification = {
            "command": command,
            "directory": str(directory),
            "environment": safe,
            "ready": str(self.directory / "ready.json"),
            "result": str(self.directory / "result.json"),
        }
        path = self.directory / "invocation.json"
        if not self.started:
            path.write_text(json.dumps(specification))
            path.chmod(0o600)
        wrapped = [sys.executable, str(self.directory / "owner.py"), str(path)]
        if self.tmux is not None:
            wrapped = [
                self.tmux,
                "-u",
                "-S",
                str(self.socket),
                "-f",
                str(self.directory / "tmux.conf"),
            ]
            wrapped += (
                ["attach-session", "-t", "owned"]
                if self.started
                else [
                    "new-session",
                    "-s",
                    "owned",
                    shlex.join([sys.executable, str(self.directory / "owner.py"), str(path)]),
                ]
            )
        if "ssh" in self.kind:
            wrapped = [
                sys.executable,
                str(self.directory / "ssh-entry.py"),
                str(self.directory / "connection.json"),
                *wrapped,
            ]
            wrapped = [
                self.ssh,
                "-F",
                "/dev/null",
                "-tt",
                "-e",
                "none",
                "-i",
                str(self.directory / "client-key"),
                "-p",
                str(self.port),
                "-o",
                "BatchMode=yes",
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "IdentityAgent=none",
                "-o",
                "GlobalKnownHostsFile=/dev/null",
                "-o",
                f"UserKnownHostsFile={self.directory / 'known_hosts'}",
                "-o",
                "StrictHostKeyChecking=yes",
                "-o",
                "ConnectTimeout=3",
                "-o",
                "EscapeChar=none",
                "-o",
                "LogLevel=ERROR",
                f"{self.user}@127.0.0.1",
                "exec " + shlex.join(wrapped),
            ]
        self.started = True
        self.disconnected = False
        return wrapped, safe

    def verify(self, expected: int) -> None:
        if self.disconnected and self.tmux is not None:
            ready = json.loads((self.directory / "ready.json").read_text())
            os.kill(ready["application"], 0)
            assert not (self.directory / "result.json").exists()
            self.record = {
                "kind": self.kind,
                "versions": self.versions,
                "connection_lost": True,
                "application_preserved_in_tmux": True,
                "inner_completion": "still running",
            }
            return
        deadline = time.monotonic() + 5
        path = self.directory / "result.json"
        while not path.exists():
            assert time.monotonic() < deadline, "Missing actual inner terminal completion"
            time.sleep(0.02)
        record = json.loads(path.read_text())
        assert record["exit"] == expected, record
        assert record["foreground"], "Application did not own the inner terminal"
        if self.disconnected and record["after"] is None:
            assert record["tty_unavailable_errno"] in (errno.EIO, errno.ENXIO, errno.ENOTTY), record
        else:
            assert record["before"] == record["after"], "Inner terminal attributes not restored"
        self.record = {
            "kind": self.kind,
            "versions": self.versions,
            "connection_lost": self.disconnected,
            **record,
        }

    def disconnect(self) -> None:
        assert self.server is not None and self.server.poll() is None
        rows = self._run(["ps", "-axo", "pid=,ppid="]).stdout.decode().splitlines()
        parents = {int(row.split()[0]): int(row.split()[1]) for row in rows}
        connection = json.loads((self.directory / "connection.json").read_text())["connection"]
        cursor = connection
        for _ in range(16):
            cursor = parents.get(cursor)
            if cursor == self.server.pid:
                break
            assert cursor is not None, "SSH connection does not belong to the owned daemon"
        else:
            raise AssertionError("SSH connection ancestry exceeded the fixture bound")
        self.disconnected = True
        os.kill(connection, signal.SIGTERM)

    def close(self) -> None:
        if self.tmux is not None and self.socket.exists():
            # Address only our explicit socket, never the user's tmux server.
            subprocess.run(
                [self.tmux, "-S", str(self.socket), "kill-server"],
                capture_output=True,
                timeout=5,
                check=False,
            )
        ready = self.directory / "ready.json"
        if ready.exists() and not (self.directory / "result.json").exists():
            record = json.loads(ready.read_text())
            for pid in (record["application"], record["owner"]):
                with suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGTERM)
        if self.server is not None and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
        if self.server_log is not None:
            self.server_log.close()
        if self.socket_directory is not None:
            self.socket_directory.cleanup()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.close()
