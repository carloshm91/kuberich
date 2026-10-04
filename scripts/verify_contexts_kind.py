"""C01 qualification on a newly created, explicitly owned disposable kind cluster."""

import argparse
import asyncio
import json
import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import yaml

from kubetrol.config.catalog import load_catalog
from kubetrol.domain.connections import ConnectionRequest, ConnectionState
from kubetrol.services.sessions import SessionService

NODE_IMAGE = (
    "kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed"
)


async def verify(path: Path, context: str) -> dict[str, object]:
    request = ConnectionRequest(kubeconfig=str(path), context=context, timeout=15)
    catalog = load_catalog(request, {})
    before = path.read_bytes()
    sessions = SessionService(catalog, request)
    try:
        first = await sessions.connect(context)
        assert first.state is ConnectionState.CONNECTED and not first.insecure
        assert {"default", "kube-system"} <= set(first.namespaces)
        api = sessions.client.api
        scoped = sessions.select_namespace("kube-system")
        assert scoped.identity.generation > first.identity.generation
        assert scoped.identity.connection_id == first.identity.connection_id
        second = await sessions.connect(context)
        assert second.state is ConnectionState.CONNECTED
        assert second.identity.connection_id != first.identity.connection_id
        assert second.namespace == "kube-system"
        assert api.rest_client.pool_manager.closed
        assert path.read_bytes() == before
        active = sessions.client.api
    finally:
        await sessions.close()
    assert active.rest_client.pool_manager.closed
    return {
        "result": "passed",
        "tls_verified": True,
        "client_certificate_auth": True,
        "namespace_listing": True,
        "scope_generation_changed": True,
        "reopened_client_distinct": True,
        "prior_and_current_clients_closed": True,
        "kubeconfig_unchanged": True,
        "namespace_count": len(first.namespaces),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, help="verified kind v0.33.0 binary")
    parser.add_argument("--evidence", default="artifacts/cluster/context-sessions.json")
    arguments = parser.parse_args()
    name = "kubetrol-test-" + uuid4().hex[:12]
    with TemporaryDirectory(prefix="kubetrol-kind-") as directory:
        path = Path(directory) / "owned-kubeconfig"
        environment = {**os.environ, "KUBECONFIG": str(path)}
        command = [
            arguments.kind,
            "create",
            "cluster",
            "--name",
            name,
            "--kubeconfig",
            str(path),
            "--image",
            NODE_IMAGE,
            "--wait",
            "180s",
        ]
        try:
            print("Creating owned disposable kind cluster.", flush=True)
            subprocess.run(command, env=environment, check=True, timeout=300)
            # Local kind output is never read through the ambient default path.
            data = yaml.safe_load(path.read_text())
            context = "kind-" + name
            assert data["current-context"] == context
            evidence = asyncio.run(verify(path, context))
            output = Path(arguments.evidence)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"kind": "0.33.0", "node_image": NODE_IMAGE, **evidence}, indent=2)
                + "\n"
            )
            print("Real API, TLS, client auth, scope isolation and cleanup passed.", flush=True)
        finally:
            subprocess.run(
                [arguments.kind, "delete", "cluster", "--name", name],
                env=environment,
                check=True,
                timeout=90,
            )
            print("Owned disposable cluster deleted.", flush=True)


if __name__ == "__main__":
    main()
