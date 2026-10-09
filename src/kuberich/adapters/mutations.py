"""One non-replayed conditional PATCH through an explicitly owned SDK connection."""

import asyncio
import ssl
from collections.abc import Awaitable, Callable

import aiohttp

from kuberich.adapters.kubernetes import KubernetesSession, _decode
from kuberich.domain.mutations import MutationIntent, MutationResult, MutationState, status_result
from kuberich.domain.resources import ApiResource, resource_record
from kuberich.errors import AppError


async def _single_attempt(
    request: aiohttp.ClientRequest,
    handler: Callable[[aiohttp.ClientRequest], Awaitable[aiohttp.ClientResponse]],
) -> aiohttp.ClientResponse:
    """Public middleware prevents aiohttp's idempotent-method connection replay.

    DELETE otherwise retries a lost persistent connection, even after the API
    applied it. Translate only retryable disconnects to a non-replayed public
    client error; connector failures retain their before-send classification.
    """
    try:
        return await handler(request)
    except aiohttp.ClientConnectorError:
        raise
    except (aiohttp.ClientOSError, aiohttp.ServerDisconnectedError):
        raise aiohttp.ClientPayloadError(
            "Write connection ended; outcome requires inspection."
        ) from None


async def conditional_patch(
    client: KubernetesSession,
    intent: MutationIntent,
    authorize: Callable[[], None],
    *,
    dry_run: bool = False,
) -> MutationResult:
    return await guarded_request(
        client,
        authorize,
        method="PATCH",
        path=intent.path,
        body=intent.body,
        content_type="application/json-patch+json",
        accepted=(200,),
        receipt=lambda data: _receipt(data, intent),
        dry_run=dry_run,
    )


async def guarded_request(
    client: KubernetesSession,
    authorize: Callable[[], None],
    *,
    method: str,
    path: str,
    body: bytes,
    content_type: str,
    accepted: tuple[int, ...],
    receipt: Callable[[bytes], MutationResult | None],
    dry_run: bool = False,
) -> MutationResult:
    """No redirects, 401 refresh/replay, HTTP retries or raw server error exposure.

    Once the request starts, an unconfirmed result is conservative: the object
    may have changed even if the response never arrives. A fresh confirmation
    must follow inspection; this function never retries the write.
    """
    started = False
    try:
        async with asyncio.timeout(client.timeout):
            authorize()
            api, configuration, credentials = client.api, client.configuration, client.credentials
            if api is None or configuration is None:
                return MutationResult(MutationState.STALE, "The captured connection is closed.")
            if credentials is not None:
                configuration.api_key["BearerToken"] = "Bearer " + await credentials.token()
            headers = [
                ("Accept", "application/json"),
                ("Accept-Encoding", "identity"),
                ("Content-Type", content_type),
                *client.impersonation,
            ]
            if token := configuration.api_key.get("BearerToken"):
                headers.append(("Authorization", token))
            authorize()
            started = True
            async with api.rest_client.pool_manager.request(
                method,
                str(configuration.host) + path,
                headers=headers,
                data=body,
                params={"fieldValidation": "Strict", **({"dryRun": "All"} if dry_run else {})},
                proxy=configuration.proxy,
                server_hostname=configuration.tls_server_name,
                allow_redirects=False,
                middlewares=(_single_attempt,),
                timeout=aiohttp.ClientTimeout(total=client.timeout),
            ) as response:
                if response.status not in accepted:
                    # Do not read arbitrary Status bodies into errors/history.
                    refusal = status_result(response.status)
                    return (
                        MutationResult(
                            MutationState.REJECTED
                            if refusal.state is MutationState.UNCERTAIN
                            else refusal.state,
                            "Server validation refused; no apply was sent.",
                        )
                        if dry_run
                        else refusal
                    )
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError
            decoding = asyncio.create_task(asyncio.to_thread(receipt, bytes(data)))
            try:
                result = await asyncio.shield(decoding)
            except asyncio.CancelledError:
                finishing = asyncio.gather(decoding, return_exceptions=True)
                while not finishing.done():
                    try:
                        await asyncio.shield(finishing)
                    except asyncio.CancelledError:
                        continue
                await finishing
                raise
            return result or MutationResult(
                MutationState.SUCCEEDED,
                "Server dry-run passed; nothing was persisted. Confirm separately to apply."
                if dry_run
                else "API confirmed the guarded patch. No retry was made.",
            )
    except asyncio.CancelledError:
        return MutationResult(
            MutationState.UNCERTAIN if started and not dry_run else MutationState.CANCELLED,
            "Validation cancelled; no apply was sent."
            if dry_run
            else "Write interrupted after request start. Inspect the current object; do not repeat blindly."
            if started
            else "Cancelled before the write request started.",
        )
    except TimeoutError:
        return MutationResult(
            MutationState.UNCERTAIN if started and not dry_run else MutationState.TIMEOUT,
            "Validation timed out; no apply was sent."
            if dry_run
            else "Write response timed out. Inspect the current object; do not repeat blindly."
            if started
            else "Timed out before the write request started.",
        )
    except aiohttp.ClientConnectorError:
        return MutationResult(
            MutationState.UNREACHABLE, "Connection/TLS failed before the write could be sent."
        )
    except (
        AppError,
        aiohttp.ClientError,
        ssl.SSLError,
        ValueError,
        UnicodeError,
        RecursionError,
        TypeError,
    ):
        return MutationResult(
            MutationState.UNCERTAIN if started and not dry_run else MutationState.REJECTED,
            "Validation response could not be verified; no apply was sent."
            if dry_run
            else "The write result could not be validated. Inspect the current object; do not repeat blindly."
            if started
            else "Write preparation was refused; no request was started.",
        )


def _receipt(data: bytes, intent: MutationIntent) -> None:
    resource = (
        ApiResource("autoscaling", "v1", "scales", "Scale", True, frozenset({"get", "patch"}))
        if intent.subresource == "scale"
        else intent.resource
    )
    record = resource_record(resource, _decode(data), intent.target.namespace)
    intent.target.require_current(intent.target.session, uid=record.uid or "")
    if record.name != intent.target.name or not record.resource_version:
        raise AppError("Patch response does not match the captured resource.")
