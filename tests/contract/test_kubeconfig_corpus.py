"""Provider-shaped templates execute against owned TLS, files and helper programs."""

import base64
import copy
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog
from kuberich.domain.connections import ConnectionRequest
from tests.support.connections import certificate
from tests.support.kubeconfig_api import captured_api

CORPUS = Path(__file__).parents[1] / "fixtures/connection_shapes"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    ["eks", "aks", "gke", "rancher", "openshift", "k3s", "kind", "teleport", "tailscale"],
)
async def test_provider_shape_uses_exact_owned_helper_identity_and_transport(
    tmp_path, monkeypatch, provider
):
    source = CORPUS / (provider + ".yaml")
    original = source.read_bytes()
    data = yaml.safe_load(original)
    cluster = data["clusters"][0]["cluster"]
    user = data["users"][0]["user"]
    original_user = copy.deepcopy(user)
    prefix = urlsplit(cluster["server"]).path
    tls, material = certificate(
        tmp_path,
        client_auth=provider in {"k3s", "kind", "teleport"},
        dns_name=cluster.get("tls-server-name"),
    )
    for entry in (cluster, user):
        for key in tuple(entry):
            if key.endswith("-data"):
                entry[key] = material[key]
            elif key in {"certificate-authority", "client-certificate", "client-key"}:
                path = tmp_path / entry[key]
                path.parent.mkdir(exist_ok=True)
                path.write_bytes(base64.b64decode(material[key + "-data"]))
                path.chmod(0o600)
    if "certificate-authority" not in cluster:
        cluster["certificate-authority-data"] = material["certificate-authority-data"]
    expected = "Bearer " + user["token"] if "token" in user else None
    if "exec" in user:
        spec = user["exec"]
        expected_args = spec.get("args", [])
        helper_dir = tmp_path / "bin"
        helper_dir.mkdir()
        status = (
            {
                "clientCertificateData": base64.b64decode(
                    material["client-certificate-data"]
                ).decode(),
                "clientKeyData": base64.b64decode(material["client-key-data"]).decode(),
            }
            if provider == "teleport"
            else {"token": "synthetic-" + provider}
        )
        expected = None if provider == "teleport" else "Bearer synthetic-" + provider
        helper = helper_dir / spec["command"]
        helper.write_text(
            f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\nassert sys.argv[1:] == {expected_args!r}\ninfo=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\nassert info['spec']['interactive'] is False\nPath('helper-was-invoked').write_text('owned')\nprint(json.dumps({{'apiVersion':{spec['apiVersion']!r},'kind':'ExecCredential','status':{status!r}}}))\n"
        )
        helper.chmod(0o700)
        monkeypatch.setenv("PATH", str(helper_dir) + os.pathsep + os.defpath)
    async with captured_api(tls, prefix=prefix) as (url, calls):
        cluster["server"] = url + prefix
        path = tmp_path / "kubeconfig"
        path.write_text(yaml.safe_dump(data))
        path.chmod(0o600)
        before = path.read_bytes()
        request = ConnectionRequest(kubeconfig=str(path))
        catalog = load_catalog(request, {})
        selected = catalog.select(catalog.current)
        assert selected.namespace == "default"
        client = KubernetesSession(selected, 3)
        try:
            await client.open()
            assert await client.namespaces() == ("team",)
            assert calls == [("GET", expected, "identity")]
            delegated = client.delegated_config()
            assert delegated["clusters"][0]["cluster"]["server"] == url + prefix
            if "exec" in original_user:
                assert (tmp_path / "helper-was-invoked").read_text() == "owned"
                assert delegated["users"][0]["user"]["exec"].get("args", []) == original_user[
                    "exec"
                ].get("args", [])
        finally:
            directory = Path(client.directory.name)
            await client.close()
        assert not directory.exists() and path.read_bytes() == before
    assert source.read_bytes() == original
