"""Isolate all test families from default kubeconfig and in-cluster authentication."""

from pathlib import Path

import kubernetes_asyncio.config as sdk_config
import pytest

from tests.support.clusters import reject_ambient_credentials


@pytest.fixture(autouse=True)
def isolated_kubernetes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KUBECONFIG", str(tmp_path / "never-use-an-ambient-cluster"))
    for name in ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"):
        monkeypatch.delenv(name, raising=False)
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
