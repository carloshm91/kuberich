"""Opt-in, read-only EKS authentication checks on an explicitly supplied test context."""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kuberich.adapters.credentials import _execute
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import load_catalog, mapping, text
from kuberich.domain.connections import ConnectionProblem, ConnectionRequest
from kuberich.domain.credential_helpers import is_azure_helper, is_eks_helper
from kuberich.errors import AppError
from kuberich.services.delegation import ConnectionFile


def pod_list(payload: object) -> None:
    data = mapping(payload)
    if data.get("kind") != "PodList" or not isinstance(data.get("items"), list):
        raise AppError("The read-only check did not return a PodList.")
    if len(data["items"]) > 1:
        raise AppError("The read-only check exceeded its one-pod response bound.")


async def verify(
    request: ConnectionRequest, kubectl: Path, *, provider: str = "eks"
) -> dict[str, object]:
    if request.kubeconfig is None or request.context is None or request.namespace is None:
        raise AppError(
            "Supply an explicit test kubeconfig, context and namespace; no ambient fallback."
        )
    catalog = load_catalog(request, {})
    selected = catalog.select(request.context)
    spec = mapping(selected.user.data.get("exec"))
    args = spec.get("args", [])
    if provider not in {"eks", "aks"}:
        raise AppError("Select an explicitly supported test provider.")
    recognize = is_eks_helper if provider == "eks" else is_azure_helper
    if not isinstance(args, list) or not recognize([text(spec.get("command")), *args]):
        raise AppError(
            "The selected test user must declare "
            + ("aws eks get-token." if provider == "eks" else "Azure kubelogin get-token.")
        )
    session = KubernetesSession(selected, request.timeout)
    connection_file = ConnectionFile(Path(session.directory.name) / "read-only-kubectl.json")
    path = f"/api/v1/namespaces/{request.namespace}/pods"
    try:
        await session.open()
        credentials = session.credentials
        assert credentials is not None
        pod_list(await session.get_json(path, params={"limit": "1"}, max_bytes=1024 * 1024))
        if credentials.expiration is None:
            raise AppError("Provider qualification requires an ExecCredential expirationTimestamp.")
        revision = credentials.revision
        # Force the client's cache deadline, not AWS credentials or SSO files.
        # This avoids waiting fourteen minutes and is recorded as a forced
        # refresh, rather than evidence of a naturally expired real AWS token.
        credentials.expiration = datetime.now(UTC) - timedelta(seconds=1)
        results = await asyncio.gather(
            *(
                session.get_json(path, params={"limit": "1"}, max_bytes=1024 * 1024)
                for _ in range(5)
            )
        )
        for result in results:
            pod_list(result)
        if credentials.revision != revision + 1:
            raise AppError("Concurrent reads did not share one credential refresh.")
        configuration = session.delegated_config()
        connection_file.write(json.dumps(configuration, allow_nan=False))
        environment = credentials.delegated_environment(os.environ)
        environment["KUBECONFIG"] = str(connection_file.path)
        try:
            output = await _execute(
                [
                    str(kubectl.absolute()),
                    f"--kubeconfig={connection_file.path}",
                    f"--context={request.context}",
                    f"--namespace={request.namespace}",
                    f"--request-timeout={request.timeout}s",
                    "get",
                    "--raw",
                    path + "?limit=1",
                ],
                environment,
                credentials.entry.directory,
                request.timeout,
            )
        except ConnectionProblem:
            raise AppError(
                "Read-only kubectl check failed. Check installation and access with the selected test context; output remains private."
            ) from None
        pod_list(json.loads(output))
        return {
            "result": "passed",
            "scope": "operator-selected test context; read-only authentication smoke",
            "exec_api_version": spec["apiVersion"],
            "api_pod_read": True,
            "forced_expiry_concurrent_refresh": True,
            "delegated_kubectl_pod_read": True,
            "natural_expiry_or_sso_role_matrix_qualified"
            if provider == "eks"
            else "natural_expiry_or_entra_login_matrix_qualified": False,
            "python": sys.version.split()[0],
            "platform": sys.platform,
        }
    finally:
        try:
            connection_file.remove()
        finally:
            await session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--kubectl", required=True)
    parser.add_argument("--acknowledge-test-cluster", action="store_true", required=True)
    arguments = parser.parse_args()
    try:
        request = ConnectionRequest(
            kubeconfig=arguments.kubeconfig,
            context=arguments.context,
            namespace=arguments.namespace,
            timeout=30,
        )
        evidence = asyncio.run(verify(request, Path(arguments.kubectl)))
    except (AppError, ConnectionProblem, OSError, ValueError, TypeError, UnicodeError):
        # No exception repr: filesystem, JSON or process errors can retain
        # private connection/provider fields. Inspect the chosen context locally.
        print(
            "EKS smoke failed. Check the selected test configuration, AWS login and read permissions. No private output was retained.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
