"""Explicit read-only AKS verifier controls and sanitized evidence."""

import json
import sys
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.domain.connections import ConnectionRequest
from kubetrol.errors import AppError
from scripts.verify_eks_auth import verify
from tests.support.azure import azure_calls, azure_entry
from tests.support.connections import catalog_fixture
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["kubeconfig", "context", "namespace"])
async def test_aks_verifier_refuses_implicit_scopes_before_loading(tmp_path, missing):
    values = {"kubeconfig": str(tmp_path / "absent"), "context": "synthetic", "namespace": "team"}
    del values[missing]
    with pytest.raises(AppError, match="no ambient fallback"):
        await verify(ConnectionRequest(**values), tmp_path / "kubectl", provider="aks")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["aks", "unknown"])
async def test_aks_verifier_refuses_wrong_or_unknown_provider(tmp_path, provider):
    catalog_fixture(tmp_path, "http://127.0.0.1:1", {"exec": {"command": "other", "args": []}})
    with pytest.raises(
        AppError, match="Azure kubelogin" if provider == "aks" else "supported test provider"
    ):
        await verify(
            ConnectionRequest(
                kubeconfig=str(tmp_path / "fixture-config"),
                context="kubetrol-test-one",
                namespace="team",
            ),
            tmp_path / "kubectl",
            provider=provider,
        )


@pytest.mark.asyncio
async def test_aks_verifier_forced_refresh_reads_and_private_file_cleanup(tmp_path):
    entry = azure_entry(tmp_path)
    payload = {"kind": "PodList", "metadata": {}, "items": []}
    record = tmp_path / "private-path"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        f"#!{sys.executable}\nimport json,stat,sys\nfrom pathlib import Path\np=Path(sys.argv[1].partition('=')[2])\nassert stat.S_IMODE(p.stat().st_mode)==0o600\nassert json.loads(p.read_text())['users'][0]['user']['exec']['args']=={entry['exec']['args']!r}\nPath({str(record)!r}).write_text(str(p))\nprint({json.dumps(payload)!r})\n"
    )
    kubectl.chmod(0o700)

    async def handler(request):
        assert request.query["limit"] == "1"
        return web.json_response(payload)

    async with reader_fixture(tmp_path, handler, user=entry) as reader:
        catalog_fixture(tmp_path, reader.session.configuration.host, entry)
        before = (tmp_path / "fixture-config").read_bytes()
        result = await verify(
            ConnectionRequest(
                kubeconfig=str(tmp_path / "fixture-config"),
                context="kubetrol-test-one",
                namespace="team",
            ),
            kubectl,
            provider="aks",
        )
        assert (
            result["result"] == "passed"
            and not result["natural_expiry_or_entra_login_matrix_qualified"]
        )
        assert len(azure_calls(tmp_path)) == 3
        assert (tmp_path / "fixture-config").read_bytes() == before
        assert not Path(record.read_text()).parent.exists()
        assert all(value not in json.dumps(result) for value in ("synthetic", "private", "token"))
