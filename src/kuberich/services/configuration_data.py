"""Fresh, version-bound reads for deliberate configuration disclosure."""

from collections.abc import Callable
from functools import partial

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.domain.configuration_data import (
    ConfigurationIndex,
    configuration_index,
    configuration_value,
)
from kuberich.domain.resources import ApiResource, ResourceRecord
from kuberich.domain.targets import ResourceTarget
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.resources import ResourceReader, parse_owned


class ConfigurationService:
    def __init__(
        self,
        client: KubernetesSession,
        resource: ApiResource,
        target: ResourceTarget,
        policy: AccessPolicy,
        current: Callable[[], bool],
    ) -> None:
        self.client, self.resource, self.target = client, resource, target
        self.policy, self.current = policy, current

    def require_current(self) -> None:
        self.policy.require(Action.READ)
        if (
            not self.current()
            or self.client.context.name != self.target.session.context
            or self.resource.group
            or self.resource.name not in {"configmaps", "secrets"}
            or self.resource.kind
            != {"configmaps": "ConfigMap", "secrets": "Secret"}[self.resource.name]
            or not self.resource.namespaced
            or self.target.namespace is None
            or self.target.group != self.resource.group
            or self.target.resource != self.resource.name
            or "get" not in self.resource.verbs
        ):
            raise AppError("Configuration target changed or is unsupported; select it again.")

    async def _read(self) -> ResourceRecord:
        self.require_current()
        record = await ResourceReader(self.client).get(
            self.resource, self.target.name, self.target.namespace
        )
        self.require_current()
        self.target.require_current(self.target.session, uid=record.uid or "")
        return record

    async def index(self) -> ConfigurationIndex:
        record = await self._read()
        result = await parse_owned(partial(configuration_index, record))
        self.require_current()
        return result

    async def value(self, key: tuple[str, str], version: str, *, encoded: bool) -> str:
        record = await self._read()
        if record.resource_version != version:
            raise AppError(
                "Configuration changed; reload the key list before revealing or copying."
            )
        result = await parse_owned(partial(configuration_value, record, key, encoded=encoded))
        self.require_current()
        return result
