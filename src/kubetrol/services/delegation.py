"""Snapshot and stage an owned client's private kubectl connection material."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.errors import AppError
from kubetrol.services.processes import _finish_owned


@dataclass(frozen=True, repr=False)
class Delegation:
    path: Path
    configuration: str
    environment: tuple[tuple[str, str], ...]
    directory: Path


def capture_delegation(
    client: KubernetesSession, environment: Mapping[str, str], directory: Path, *, prefix: str
) -> Delegation:
    if prefix not in {"exec", "forward"}:
        raise AppError("Unsupported delegated connection purpose.")
    captured_environment = dict(environment)
    captured_directory = directory.absolute()
    credentials = client.credentials
    if credentials is not None and (credentials.eks or credentials.azure):
        captured_environment = credentials.delegated_environment(captured_environment)
        captured_directory = credentials.entry.directory
    try:
        configuration = json.dumps(client.delegated_config(), allow_nan=False)
    except (TypeError, ValueError):
        raise AppError(
            "Selected connection cannot be delegated to kubectl. Check kubeconfig extension/credential fields."
        ) from None
    return Delegation(
        Path(client.directory.name) / f"{prefix}-{uuid4().hex}.json",
        configuration,
        tuple(captured_environment.items()),
        captured_directory,
    )


class ConnectionFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.created = False

    def write(self, configuration: str) -> None:
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.created = True
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(configuration)

    def remove(self) -> None:
        if self.created:
            self.path.unlink(missing_ok=True)


@asynccontextmanager
async def stage_connection(path: Path, configuration: str) -> AsyncIterator[None]:
    connection_file = ConnectionFile(path)
    writing = asyncio.create_task(asyncio.to_thread(connection_file.write, configuration))
    try:
        try:
            await asyncio.shield(writing)
        except asyncio.CancelledError:
            await _finish_owned(asyncio.gather(writing, return_exceptions=True))
            raise
        except OSError:
            raise AppError(
                "Cannot prepare private kubectl connection. Check local file permissions."
            ) from None
        yield
    finally:
        cleanup = asyncio.create_task(asyncio.to_thread(connection_file.remove))
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await _finish_owned(cleanup)
            raise
        except OSError:
            raise AppError(
                "Cannot remove the private kubectl connection. Check local file permissions."
            ) from None
