"""Isolate all test families from default kubeconfig and in-cluster authentication."""

import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

import kubernetes_asyncio.config as sdk_config
import pytest
from kubernetes_asyncio import client

from kubetrol.adapters import credentials, kubernetes
from kubetrol.config import catalog
from tests.support.clusters import reject_ambient_credentials

_CLIENT = client.ApiClient
_READ = catalog.regular_bytes
_EXECUTE = credentials._execute


@pytest.fixture
def owned_test_proxies() -> set[str]:
    """Explicit qualification registry; empty for every ordinary test."""
    return set()


@pytest.fixture(autouse=True)
def isolated_kubernetes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, owned_test_proxies: set[str]
) -> None:
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "never-use-an-ambient-cluster"))
    for name in ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"):
        monkeypatch.delenv(name, raising=False)

    def owned_read(path: Path) -> bytes:
        if not path.resolve().is_relative_to(tmp_path.resolve()):
            raise AssertionError("Connection tests may read only their owned temporary files.")
        return _READ(path)

    def owned_client(*args, **kwargs):
        configuration = kwargs.get("configuration")
        if configuration is None:
            raise AssertionError("Connection tests require an explicit SDK configuration.")
        for url in (configuration.host, configuration.proxy):
            if url is None:
                continue
            endpoint = urlsplit(url)
            try:
                permitted = ipaddress.ip_address(endpoint.hostname or "").is_loopback
            except ValueError:
                permitted = False
            if (
                not permitted
                or endpoint.port is None
                or endpoint.scheme not in {"http", "https"}
                or endpoint.username is not None
                or endpoint.password is not None
            ):
                raise AssertionError("Connection tests require an owned numeric loopback endpoint.")
        if configuration.proxy is not None and configuration.proxy not in owned_test_proxies:
            raise AssertionError(
                "Connection tests require an owned numeric loopback proxy registered by the test."
            )
        return _CLIENT(*args, **kwargs)

    async def owned_execute(argv, environment, directory, timeout):
        if not directory.resolve().is_relative_to(tmp_path.resolve()):
            raise AssertionError("Credential helpers require an owned temporary working directory.")
        return await _EXECUTE(argv, environment, directory, timeout)

    monkeypatch.setattr(catalog, "regular_bytes", owned_read)
    monkeypatch.setattr(kubernetes, "regular_bytes", owned_read)
    monkeypatch.setattr(client, "ApiClient", owned_client)
    monkeypatch.setattr(credentials, "_execute", owned_execute)
    for module in (sdk_config, sdk_config.kube_config, sdk_config.incluster_config):
        for name in (
            "load_config",
            "load_kube_config",
            "load_kube_config_from_dict",
            "new_client_from_config",
            "new_client_from_config_dict",
            "load_incluster_config",
        ):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, reject_ambient_credentials)
