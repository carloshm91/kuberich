"""Context/scope ownership and safe connection states without widget dependencies."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from kubetrol.adapters.credentials import CredentialLogin
from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.catalog import KubeCatalog
from kubetrol.domain.connections import (
    ConnectionProblem,
    ConnectionRequest,
    ConnectionState,
    SessionObservation,
    namespace_name,
)
from kubetrol.domain.targets import SessionIdentity
from kubetrol.errors import AppError


class SessionService:
    def __init__(self, catalog: KubeCatalog, request: ConnectionRequest) -> None:
        self.catalog = catalog
        self.request = request
        self.observation = SessionObservation()
        self.client: KubernetesSession | None = None
        self.generation = 0
        self.scopes: dict[str, str | None] = {}
        self.lock = asyncio.Lock()
        self.before_close: Callable[[KubernetesSession], Awaitable[None]] | None = None

    async def connect(
        self, context: str, *, authenticate: CredentialLogin | None = None
    ) -> SessionObservation:
        async with self.lock:
            await self.close()
            self.generation += 1
            identity = SessionIdentity(context, self.generation)
            namespace = None
            self.observation = SessionObservation(
                ConnectionState.CONNECTING, "Connecting to the selected context.", identity
            )
            try:
                selected = self.catalog.select(context, self.request.overrides)
                namespace = self.scopes.get(
                    context,
                    None
                    if self.request.all_namespaces
                    else self.request.namespace or selected.namespace,
                )
                self.client = KubernetesSession(selected, self.request.timeout)
                if authenticate is None:
                    await self.client.open()
                else:
                    await self.client.open(authenticate=authenticate)
                namespaces = await self.client.namespaces()
                self.observation = SessionObservation(
                    ConnectionState.CONNECTED,
                    "Connected · :ctx contexts · :ns namespaces.",
                    identity,
                    namespace,
                    namespaces,
                    self.client.insecure,
                )
                self.scopes[context] = namespace
            except AppError:
                self.observation = SessionObservation(
                    ConnectionState.CONFIG_ERROR,
                    "Selected context has missing or invalid cluster/credential references. Choose a context with F2.",
                    identity,
                    namespace,
                )
                await self.close()
            except ConnectionProblem as error:
                insecure = self.client.insecure if self.client is not None else False
                self.observation = SessionObservation(
                    error.state, str(error), identity, namespace, insecure=insecure
                )
                if error.state is not ConnectionState.LIMITED:
                    await self.close()
            except BaseException:
                await self.close()
                raise
            return self.observation

    def select_namespace(self, namespace: str | None) -> SessionObservation:
        if (
            self.client is None
            or self.observation.identity is None
            or self.observation.state not in {ConnectionState.CONNECTED, ConnectionState.LIMITED}
        ):
            raise AppError("Connect to a context before selecting a namespace.")
        if namespace is not None:
            namespace_name(namespace)
        self.generation += 1
        self.scopes[self.observation.identity.context] = namespace
        self.observation = replace(
            self.observation,
            namespace=namespace,
            identity=replace(self.observation.identity, generation=self.generation),
        )
        return self.observation

    async def close(self) -> None:
        if self.client is not None:
            client = self.client
            try:
                if self.before_close is not None:
                    await self.before_close(client)
            finally:
                await client.close()
                self.client = None
