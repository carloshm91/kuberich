"""Single-attempt diagnostic Pod writes with independently retained create identity."""

import asyncio
import hashlib
import json
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kuberich.adapters.kubernetes import KubernetesSession, decode_json
from kuberich.adapters.mutations import guarded_request
from kuberich.domain.mutations import MutationResult, MutationState
from kuberich.domain.node_shell import NodeShellIntent, OwnedPod, admitted_profile, owned_pod
from kuberich.domain.node_shell_journal import connection_fingerprint
from kuberich.domain.resources import api_segment
from kuberich.errors import AppError
from kuberich.services.ownership import finish_owned

REQUEST_SECONDS = 10


@dataclass(frozen=True, slots=True)
class CreateReceipt:
    result: MutationResult
    owned: OwnedPod | None
    profile: bytes | None


async def create_pod(
    client: KubernetesSession,
    intent: NodeShellIntent,
    authorize: Callable[[], None],
    *,
    dry_run: bool = False,
) -> CreateReceipt:
    owned: OwnedPod | None = None
    profile: bytes | None = None

    def receipt(data: bytes) -> MutationResult:
        nonlocal owned, profile
        value = decode_json(data)
        # Ownership is recorded before validating any execution-relevant field.
        # A rejected admitted profile must never lose an already returned UID.
        if not dry_run:
            owned = owned_pod(intent, value)
        profile = admitted_profile(intent, value)
        return MutationResult(
            MutationState.SUCCEEDED,
            "Server dry-run passed; no Pod was persisted."
            if dry_run
            else "API confirmed creation of the diagnostic Pod; no retry was made.",
        )

    async with asyncio.timeout(REQUEST_SECONDS):
        result = await guarded_request(
            client,
            authorize,
            method="POST",
            path="/api/v1/namespaces/" + api_segment(str(intent.settings.namespace)) + "/pods",
            body=intent.body,
            content_type="application/json",
            accepted=(201,),
            receipt=receipt,
            dry_run=dry_run,
        )
    return CreateReceipt(result, owned, profile)


async def delete_pod(
    client: KubernetesSession,
    owned: OwnedPod,
    authorize: Callable[[], None],
) -> MutationResult:
    import json

    body = json.dumps(
        {
            "apiVersion": "v1",
            "kind": "DeleteOptions",
            "gracePeriodSeconds": 5,
            "propagationPolicy": "Background",
            "preconditions": {"uid": owned.uid},
        },
        separators=(",", ":"),
    ).encode()
    async with asyncio.timeout(REQUEST_SECONDS):
        return await guarded_request(
            client,
            authorize,
            method="DELETE",
            path=pod_path(owned),
            body=body,
            content_type="application/json",
            accepted=(200, 202),
            receipt=lambda _: MutationResult(
                MutationState.ACCEPTED,
                "UID-guarded deletion accepted; absence is not yet verified.",
            ),
        )


def pod_path(owned: OwnedPod) -> str:
    return "/api/v1/namespaces/" + api_segment(owned.namespace) + "/pods/" + api_segment(owned.name)


async def session_fingerprint(client: KubernetesSession) -> str:
    configuration = client.configuration
    if configuration is None:
        raise AppError("Node shell requires the explicitly connected session.")
    # Capture paths and routing on the loop; only private captured files/default
    # TLS trust are read in the owned worker. Never reload ambient kubeconfig.
    ca, certificate = configuration.ssl_ca_cert, configuration.cert_file
    endpoint, verify = str(configuration.host), bool(configuration.verify_ssl)
    server_name, proxy = configuration.tls_server_name, client.request_proxy
    user = {
        key: value
        for key, value in client.context.user.data.items()
        if key
        not in {
            "token",
            "tokenFile",
            "password",
            "client-key",
            "client-key-data",
            "client-certificate",
            "client-certificate-data",
        }
    }
    if isinstance(user.get("auth-provider"), dict):
        provider = dict(user["auth-provider"])
        provider["config"] = {
            key: value
            for key, value in provider.get("config", {}).items()
            if key not in {"access-token", "id-token", "refresh-token", "expiry", "expiry-key"}
        }
        user["auth-provider"] = provider
    identity = (
        (
            "configured-identity-sha256",
            hashlib.sha256(
                json.dumps(user, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        ),
        *client.impersonation,
    )
    if not certificate and not any(user.get(key) for key in ("username", "exec", "auth-provider")):
        # No stable configured identity survives token removal. Bind only this
        # explicitly connected private session; a reconnect cannot claim these
        # records. The private path itself is never persisted or displayed.
        identity += (
            (
                "ambiguous-identity-session",
                hashlib.sha256(client.directory.name.encode()).hexdigest(),
            ),
        )

    def fingerprint() -> str:
        trust = (
            Path(ca).read_bytes()
            if ca
            else b"".join(sorted(ssl.create_default_context().get_ca_certs(binary_form=True)))
            if verify and endpoint.startswith("https:")
            else b""
        )
        scope = identity
        if certificate:
            scope += (
                (
                    "client-certificate-sha256",
                    hashlib.sha256(Path(certificate).read_bytes()).hexdigest(),
                ),
            )
        return connection_fingerprint(
            endpoint=endpoint,
            verify_ssl=verify,
            tls_server_name=server_name,
            trust=trust,
            proxy=proxy,
            identity_scope=scope,
        )

    worker = asyncio.create_task(asyncio.to_thread(fingerprint))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await finish_owned(worker)
        raise
