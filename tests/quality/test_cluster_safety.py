"""The suite cannot silently authenticate to an ambient developer cluster."""

import os
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import kubernetes_asyncio.config as sdk_config
import pytest
import yaml
from kubernetes_asyncio.client import Configuration

from tests.support import clusters
from tests.support.clusters import DisposableContext, load_disposable_config


@pytest.fixture
def owned_context(tmp_path: Path) -> DisposableContext:
    root = tmp_path / "owned-cluster"
    root.mkdir()
    fixture = DisposableContext(
        root, root / "kubeconfig", "kubetrol-test-owned", "http://127.0.0.1:64321"
    )
    data = {
        "apiVersion": "v1",
        "kind": "Config",
        "current-context": fixture.context,
        "contexts": [{"name": fixture.context, "context": {"cluster": "owned", "user": "owned"}}],
        "clusters": [{"name": "owned", "cluster": {"server": fixture.server}}],
        "users": [{"name": "owned", "user": {"token": "synthetic-fixture-token"}}],
    }
    fixture.kubeconfig.write_text(yaml.safe_dump(data))
    return fixture


LOADERS = [
    (module, name)
    for module in (sdk_config, sdk_config.kube_config, sdk_config.incluster_config)
    for name in (
        "load_config",
        "load_kube_config",
        "load_kube_config_from_dict",
        "new_client_from_config",
        "new_client_from_config_dict",
        "load_incluster_config",
    )
    if hasattr(module, name)
]


@pytest.mark.parametrize("module,name", LOADERS)
def test_ambient_sdk_loaders_fail_before_reading_credentials(module: ModuleType, name: str) -> None:
    with pytest.raises(AssertionError, match="explicitly owned cluster fixture"):
        getattr(module, name)()
    assert not Path(os.environ["KUBECONFIG"]).exists()
    assert "KUBERNETES_SERVICE_HOST" not in os.environ
    assert "KUBERNETES_SERVICE_PORT" not in os.environ


@pytest.mark.asyncio
async def test_owned_loader_uses_a_separate_configuration_and_preserves_the_file(
    owned_context: DisposableContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = owned_context.kubeconfig.read_bytes()

    def forbid_global_configuration(*args: object, **kwargs: object) -> None:
        pytest.fail("An owned fixture must not mutate SDK defaults")

    monkeypatch.setattr(Configuration, "set_default", forbid_global_configuration)
    configuration = await load_disposable_config(owned_context)
    assert configuration.host == owned_context.server
    assert configuration.api_key["BearerToken"] == "Bearer synthetic-fixture-token"
    assert owned_context.kubeconfig.read_bytes() == original
    # Loading a fixture grants no permission to ambient loaders afterward.
    with pytest.raises(AssertionError, match="explicitly owned"):
        sdk_config.load_kube_config()


@pytest.mark.parametrize(
    "server",
    [
        "https://production.invalid:6443",
        "https://192.0.2.1:6443",
        "http://localhost:6443",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:bad",
        "ftp://127.0.0.1:6443",
        "http://user:password@127.0.0.1:6443",
        "http://127.0.0.1:6443/redirect",
        "http://127.0.0.1:6443?next=production",
        "http://127.0.0.1:6443#production",
    ],
)
def test_name_alone_never_qualifies_a_remote_or_ambiguous_endpoint(
    owned_context: DisposableContext, server: str
) -> None:
    with pytest.raises(AssertionError, match="matching local endpoint"):
        replace(owned_context, server=server).validate()


@pytest.mark.parametrize("server", ["http://127.0.0.1:64321", "https://[::1]:64321/"])
def test_explicit_numeric_loopback_endpoints_are_accepted(
    owned_context: DisposableContext, server: str
) -> None:
    data = yaml.safe_load(owned_context.kubeconfig.read_text())
    data["clusters"][0]["cluster"]["server"] = server
    owned_context.kubeconfig.write_text(yaml.safe_dump(data))
    assert replace(owned_context, server=server).validate() == owned_context.kubeconfig


@pytest.mark.parametrize("context", ["production", "", "kind-production"])
def test_developer_contexts_are_rejected(owned_context: DisposableContext, context: str) -> None:
    with pytest.raises(AssertionError, match="explicit fixture context"):
        replace(owned_context, context=context).validate()


@pytest.mark.parametrize(
    "field", ["exec", "auth-provider", "tokenFile", "client-key", "client-certificate"]
)
@pytest.mark.asyncio
async def test_external_credential_sources_are_rejected_before_sdk_loading(
    owned_context: DisposableContext, field: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = yaml.safe_load(owned_context.kubeconfig.read_text())
    data["users"][0]["user"][field] = {"command": "never-run-fixture-helper"}
    owned_context.kubeconfig.write_text(yaml.safe_dump(data))
    monkeypatch.setattr(clusters, "_LOAD_FIXTURE", lambda **kwargs: pytest.fail("SDK was called"))
    with pytest.raises(AssertionError, match="without external credential helpers"):
        await load_disposable_config(owned_context)


@pytest.mark.parametrize("field", ["certificate-authority", "proxy-url"])
def test_external_ca_files_and_proxy_endpoints_are_rejected(
    owned_context: DisposableContext, field: str
) -> None:
    data = yaml.safe_load(owned_context.kubeconfig.read_text())
    data["clusters"][0]["cluster"][field] = "https://production.invalid:6443"
    owned_context.kubeconfig.write_text(yaml.safe_dump(data))
    with pytest.raises(AssertionError):
        owned_context.validate()


@pytest.mark.parametrize(
    "contents",
    [
        b"current-context: kubetrol-test-owned\ncurrent-context: production\n",
        b"contexts: &contexts [fixture]\nclusters: *contexts\n",
        b"!unsafe fixture",
        b"\xff",
        b"[unclosed",
        b"[fixture]",
        b"contexts: " + b"[" * 21 + b"x" + b"]" * 21,
        b"contexts: [" + b"x," * 4097 + b"]",
        b"token: " + b"x" * 65536,
    ],
)
def test_ambiguous_malformed_and_oversized_fixture_yaml_fails_closed(
    owned_context: DisposableContext, contents: bytes
) -> None:
    owned_context.kubeconfig.write_bytes(contents)
    with pytest.raises(AssertionError, match="owned temporary kubeconfig"):
        owned_context.validate()


@pytest.mark.parametrize(
    "patch",
    [
        {"current-context": "production"},
        {"contexts": []},
        {"clusters": None},
        {"contexts": {}},
        {"contexts": [None]},
        {"clusters": [{"name": "another", "cluster": {"server": "http://127.0.0.1:64321"}}]},
        {"users": [{"name": "owned", "user": None}]},
        {"users": {}},
        {"users": [{"user": {}}, {"user": {}}]},
    ],
)
def test_fixture_scope_and_schema_must_match_exactly(
    owned_context: DisposableContext, patch: dict[str, object]
) -> None:
    data = yaml.safe_load(owned_context.kubeconfig.read_text())
    data.update(patch)
    owned_context.kubeconfig.write_text(yaml.safe_dump(data))
    with pytest.raises(AssertionError, match="owned temporary kubeconfig"):
        owned_context.validate()


@pytest.mark.parametrize("kind", ["outside", "symlink", "missing", "directory", "fifo"])
def test_fixture_paths_cannot_escape_the_owned_directory_or_use_special_files(
    owned_context: DisposableContext, tmp_path: Path, kind: str
) -> None:
    outside = tmp_path / "outside-kubeconfig"
    outside.write_bytes(owned_context.kubeconfig.read_bytes())
    unsafe = owned_context.directory / "unsafe"
    if kind == "outside":
        unsafe = outside
    elif kind == "symlink":
        unsafe.symlink_to(outside)
    elif kind == "directory":
        unsafe.mkdir()
    elif kind == "fifo":
        os.mkfifo(unsafe)
    with pytest.raises(AssertionError, match="owned temporary kubeconfig"):
        replace(owned_context, kubeconfig=unsafe).validate()
