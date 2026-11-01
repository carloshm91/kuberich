"""Isolate all test families from default kubeconfig and in-cluster authentication."""

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

import kubernetes_asyncio.config as sdk_config
import pytest
from kubernetes_asyncio import client

from kuberich.adapters import credentials, kubernetes
from kuberich.config import catalog
from tests.support.clusters import reject_ambient_credentials
from tests.support.parts import assign, load_timings, parse_part

_CLIENT = client.ApiClient
_READ = catalog.regular_bytes
_INVOCATION = credentials.ExecToken.invocation
ROOT = Path(__file__).resolve().parents[1]
pytest_plugins = ["tests.support.tiers"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """With KUBERICH_TEST_PART=INDEX/COUNT, keep only the files assigned to that part."""
    # Child pytest runs started by evidence tests must see their whole selection.
    if not (value := os.environ.pop("KUBERICH_TEST_PART", None)):
        return
    index, count = parse_part(value)
    names = {item: item.path.resolve().relative_to(ROOT).as_posix() for item in items}
    parts = assign(names.values(), count, load_timings())
    deselected = [item for item in items if parts[names[item]] != index]
    items[:] = [item for item in items if parts[names[item]] == index]
    config.hook.pytest_deselected(items=deselected)


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
        for purpose, url in (("server", configuration.host), ("proxy", configuration.proxy)):
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
                or endpoint.scheme
                not in ({"http", "https", "socks5"} if purpose == "proxy" else {"http", "https"})
                or (
                    purpose == "server"
                    and (endpoint.username is not None or endpoint.password is not None)
                )
            ):
                raise AssertionError("Connection tests require an owned numeric loopback endpoint.")
        if configuration.proxy is not None and configuration.proxy not in owned_test_proxies:
            raise AssertionError(
                "Connection tests require an owned numeric loopback proxy registered by the test."
            )
        return _CLIENT(*args, **kwargs)

    def owned_invocation(self, *, interactive=False):
        command = _INVOCATION(self, interactive=interactive)
        if not command.directory.resolve().is_relative_to(tmp_path.resolve()):
            raise AssertionError("Credential helpers require an owned temporary working directory.")
        return command

    monkeypatch.setattr(catalog, "regular_bytes", owned_read)
    monkeypatch.setattr(kubernetes, "regular_bytes", owned_read)
    monkeypatch.setattr(client, "ApiClient", owned_client)
    monkeypatch.setattr(credentials.ExecToken, "invocation", owned_invocation)
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
