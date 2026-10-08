"""Noninteractive, bounded exec credentials with owned process cleanup."""

import asyncio
import json
import os
import shutil
import signal
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kuberich.config.catalog import Entry, mapping, text
from kuberich.domain.connections import ConnectionProblem, ConnectionState
from kuberich.domain.credential_helpers import (
    AZURE_LOGIN_REQUIRED,
    azure_login_mode,
    azure_prompt,
    bearer_token,
    helper_failure,
    helper_start_failure,
    is_azure_helper,
    is_eks_helper,
)
from kuberich.domain.processes import ProcessCommand, ProcessMode, ProcessPurpose
from kuberich.errors import AppError


def auth_problem(message: str) -> ConnectionProblem:
    return ConnectionProblem(ConnectionState.AUTH_ERROR, message)


async def _drain(stream: asyncio.StreamReader, limit: int, *, azure: bool = False) -> bytes:
    output = bytearray()
    while chunk := await stream.read(16384):
        output.extend(chunk)
        if len(output) > limit:
            raise auth_problem("Credential helper output exceeds its size limit.")
        if azure and azure_prompt(output):
            raise auth_problem(AZURE_LOGIN_REQUIRED)
    return bytes(output)


async def _execute(
    argv: list[str], environment: dict[str, str], directory: Path, timeout: float
) -> bytes:
    try:
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *argv,
                env=environment,
                cwd=directory,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        )
        try:
            process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            process = await spawning
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
            raise
    except OSError as error:
        raise auth_problem(
            helper_start_failure(argv, missing=isinstance(error, FileNotFoundError))
        ) from None
    assert process.stdout is not None and process.stderr is not None
    readers = [
        asyncio.create_task(_drain(process.stdout, 1024 * 1024)),
        asyncio.create_task(_drain(process.stderr, 65536, azure=is_azure_helper(argv))),
    ]
    try:
        async with asyncio.timeout(timeout):
            stdout, stderr = await asyncio.gather(*readers)
            if await process.wait() != 0:
                raise auth_problem(helper_failure(argv, stderr))
            return stdout
    except TimeoutError:
        raise auth_problem(
            "Credential helper timed out. Complete provider login and retry."
        ) from None
    finally:
        # Kill the owned process group even if the direct child has exited:
        # descendants can still hold the pipe descriptors open.
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        for reader in readers:
            reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        await process.wait()


class ExecToken:
    """Session-local cache. Never logs helper output or inherits a terminal input."""

    def __init__(self, entry: Entry, cluster: dict[str, Any], timeout: float) -> None:
        self.entry = entry
        self.cluster = cluster
        self.timeout = timeout
        self.cached: str | None = None
        self.expiration: datetime | None = None
        self.lock = asyncio.Lock()
        self.revision = 0
        self.environment = dict(os.environ)
        self.eks = False
        self.azure = False
        self.command: str | None = None

    def invalidate(self, rejected_revision: int | None = None) -> None:
        # A delayed 401 for an older request must not erase an already refreshed
        # token. This synchronous comparison contains no scheduling boundary.
        if rejected_revision is None or self.revision == rejected_revision:
            self.cached = None

    def delegated_environment(self, inherited: Mapping[str, str]) -> dict[str, str]:
        environment = dict(inherited)
        if self.eks or self.azure:
            prefixes = ("AWS_",) if self.eks else ("AZURE_", "AAD_", "ARM_", "AZURESUBSCRIPTION_")
            names = {"HOME", "PATH", "KUBECACHEDIR"} if self.azure else {"HOME"}
            for name in tuple(environment):
                if name.startswith(prefixes) or name in names:
                    del environment[name]
            environment.update(
                (name, value)
                for name, value in self.environment.items()
                if name.startswith(prefixes) or name in names
            )
        return environment

    def invocation(self, *, interactive: bool = False) -> ProcessCommand:
        try:
            spec = mapping(self.entry.data)
            version = text(spec.get("apiVersion"))
            if version not in {
                "client.authentication.k8s.io/v1",
                "client.authentication.k8s.io/v1beta1",
            }:
                raise auth_problem("Unsupported exec credential API version. Use v1 or v1beta1.")
            mode = spec.get("interactiveMode", None if version.endswith("/v1") else "IfAvailable")
            if mode not in {"Never", "IfAvailable", "Always"}:
                raise auth_problem(
                    "Exec v1 requires interactiveMode: Never, IfAvailable, or Always."
                )
            command = text(spec.get("command"))
            if "/" in command and not Path(command).is_absolute():
                command = str(self.entry.directory / command)
            args = spec.get("args", [])
            if args is None:
                args = []
            if not isinstance(args, list) or len(args) > 256:
                raise auth_problem("Credential helper args must be a list of at most 256 strings.")
            argv = [command, *(text(arg) for arg in args)]
            environment = dict(self.environment)
            variables = spec.get("env", [])
            if variables is None:
                variables = []
            if not isinstance(variables, list) or len(variables) > 256:
                raise auth_problem("Credential helper env must be a list of at most 256 entries.")
            for value in variables:
                variable = mapping(value)
                name = text(variable.get("name"))
                if "=" in name:
                    raise auth_problem("Credential helper environment names cannot contain '='.")
                value = variable.get("value")
                environment[name] = "" if value == "" else text(value)
            self.eks, self.azure = is_eks_helper(argv), is_azure_helper(argv)
            if interactive and not self.azure:
                raise auth_problem(
                    "Explicit :login currently requires a declared Azure kubelogin get-token helper."
                )
            if not interactive and mode == "Always":
                raise auth_problem(
                    AZURE_LOGIN_REQUIRED
                    if self.azure
                    else "This helper requires terminal input. Log in externally; interactive authentication awaits C08 #47."
                )
            if (
                self.azure
                and not interactive
                and azure_login_mode(argv, environment) == "interactive"
            ):
                raise auth_problem(AZURE_LOGIN_REQUIRED)
            provide = spec.get("provideClusterInfo", False)
            if type(provide) is not bool:
                raise auth_problem("provideClusterInfo must be true or false.")
            available = interactive and mode != "Never"
            info: dict[str, Any] = {"interactive": available}
            if provide:
                info["cluster"] = self.cluster
            environment["KUBERNETES_EXEC_INFO"] = json.dumps(
                {"apiVersion": version, "kind": "ExecCredential", "spec": info}
            )
            if (self.eks or self.azure) and "/" not in command:
                search_path = os.pathsep.join(
                    str(self.entry.directory / path) if not Path(path).is_absolute() else path
                    for path in environment.get("PATH", os.defpath).split(os.pathsep)
                )
                argv[0] = shutil.which(command, path=search_path) or command
            return ProcessCommand(
                tuple(argv),
                tuple(environment.items()),
                self.entry.directory,
                ProcessMode.FOREGROUND if interactive else ProcessMode.CAPTURE,
                ProcessPurpose.AUTHENTICATE,
                terminal_input=available,
            )
        except (AppError, ValueError, UnicodeError, RecursionError):
            raise auth_problem(
                "Invalid credential helper configuration or response. Check its ExecCredential contract."
            ) from None

    def accept(self, output: bytes, command: ProcessCommand) -> str:
        try:
            version = json.loads(dict(command.environment)["KUBERNETES_EXEC_INFO"])["apiVersion"]
            response = mapping(json.loads(output))
            if response.get("kind") != "ExecCredential" or response.get("apiVersion") != version:
                raise auth_problem(
                    "Credential helper returned a mismatched ExecCredential kind/version."
                )
            status = mapping(response.get("status"))
            if "clientCertificateData" in status or "clientKeyData" in status:
                raise auth_problem(
                    "Exec certificate credentials require rotation qualification (C08 #47). Use static certificates or an exec token."
                )
            token = bearer_token(status.get("token"))
            expiration = status.get("expirationTimestamp")
            expires = (
                datetime.fromisoformat(text(expiration).replace("Z", "+00:00"))
                if expiration is not None
                else None
            )
            if expires is not None and (expires.tzinfo is None or expires <= datetime.now(UTC)):
                raise auth_problem(
                    "Credential helper returned expired or timezone-less credentials."
                )
            self.cached, self.expiration, self.command = token, expires, command.argv[0]
            self.revision += 1
            return token
        except (AppError, ValueError, UnicodeError, RecursionError):
            raise auth_problem(
                "Invalid credential helper configuration or response. Check its ExecCredential contract."
            ) from None

    async def token(self) -> str:
        async with self.lock:
            if self.cached is not None and (
                self.expiration is None or self.expiration > datetime.now(UTC)
            ):
                return self.cached
            command = self.invocation()
            output = await _execute(
                list(command.argv), dict(command.environment), command.directory, self.timeout
            )
            return self.accept(output, command)


CredentialLogin = Callable[[ExecToken], Awaitable[str]]
