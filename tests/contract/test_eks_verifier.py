"""The opt-in cloud verifier refuses ambient scopes and owns temporary files."""

import json
import os
import sys
from pathlib import Path

import pytest
from aiohttp import web

from kubetrol.domain.connections import ConnectionRequest
from kubetrol.errors import AppError
from scripts.verify_eks_auth import verify
from tests.support.connections import catalog_fixture
from tests.support.eks import aws_entry, calls
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["kubeconfig", "context", "namespace"])
async def test_verifier_requires_all_explicit_scopes_before_loading(missing, tmp_path):
    fields = {"kubeconfig": str(tmp_path / "missing"), "context": "synthetic", "namespace": "team"}
    del fields[missing]
    with pytest.raises(AppError, match="no ambient fallback"):
        await verify(ConnectionRequest(**fields), tmp_path / "kubectl")


@pytest.mark.asyncio
async def test_verifier_refuses_non_eks_helpers_without_running_them(tmp_path):
    catalog_fixture(tmp_path, "http://127.0.0.1:12345", {"exec": {"command": "kubelogin"}})
    with pytest.raises(AppError, match="aws eks get-token"):
        await verify(
            ConnectionRequest(
                kubeconfig=str(tmp_path / "fixture-config"),
                context="kubetrol-test-one",
                namespace="team",
            ),
            tmp_path / "kubectl",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "kubectl", "payload"])
async def test_local_verifier_checks_api_refresh_and_delegation_with_cleanup(
    tmp_path, failure, monkeypatch
):
    for name in tuple(os.environ):
        if name.startswith("AWS_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))
    entry = aws_entry(tmp_path)
    payload = {"kind": "PodList", "metadata": {}, "items": []}
    private = tmp_path / "private-path"
    kubectl = tmp_path / "kubectl"
    kubectl.write_text(
        f"#!{sys.executable}\nimport json,sys,stat\nfrom pathlib import Path\n"
        "path=Path(sys.argv[1].split('=',1)[1])\n"
        "assert stat.S_IMODE(path.stat().st_mode)==0o600\n"
        f"Path({str(private)!r}).write_text(str(path))\n"
        "assert '--context=kubetrol-test-one' in sys.argv\n"
        "assert '--namespace=team' in sys.argv\n"
        "assert sys.argv[-2:] == ['--raw', '/api/v1/namespaces/team/pods?limit=1']\n"
        "spec=json.loads(path.read_text())['users'][0]['user']['exec']\n"
        "assert spec['args'][3:5] == ['get-token', '--cluster-name']\n"
        + ("print('private-error',file=sys.stderr);sys.exit(1)\n" if failure == "kubectl" else "")
        + "print("
        + repr(json.dumps({} if failure == "payload" else payload))
        + ")\n"
    )
    kubectl.chmod(0o700)

    async def handler(request):
        assert request.query["limit"] == "1"
        return web.json_response(payload)

    async with reader_fixture(tmp_path, handler, user=entry) as reader:
        catalog_fixture(tmp_path, reader.session.configuration.host, entry)
        before = (tmp_path / "fixture-config").read_bytes()
        request = ConnectionRequest(
            kubeconfig=str(tmp_path / "fixture-config"),
            context="kubetrol-test-one",
            namespace="team",
        )
        if failure is None:
            evidence = await verify(request, kubectl)
            assert evidence["result"] == "passed"
            assert evidence["natural_expiry_or_sso_role_matrix_qualified"] is False
            assert "private" not in json.dumps(evidence)
        else:
            with pytest.raises(AppError):
                await verify(request, kubectl)
        assert (tmp_path / "fixture-config").read_bytes() == before
        assert not Path(private.read_text()).exists()
        assert not Path(private.read_text()).parent.exists()
        assert len(calls(tmp_path)) == 3  # fixture open + verifier open/forced refresh
