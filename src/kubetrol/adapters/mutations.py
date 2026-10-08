"""One non-replayed conditional PATCH through an explicitly owned SDK connection."""

import asyncio
import ssl
from collections.abc import Callable

import aiohttp

from kubetrol.adapters.kubernetes import KubernetesSession, _decode
from kubetrol.domain.mutations import MutationIntent, MutationResult, MutationState, status_result
from kubetrol.domain.resources import resource_record
from kubetrol.errors import AppError


async def conditional_patch(
    client: KubernetesSession, intent: MutationIntent, authorize: Callable[[], None]
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
                ("Content-Type", "application/json-patch+json"),
                *client.impersonation,
            ]
            if token := configuration.api_key.get("BearerToken"):
                headers.append(("Authorization", token))
            authorize()
            started = True
            async with api.rest_client.pool_manager.request(
                "PATCH",
                str(configuration.host) + intent.path,
                headers=headers,
                data=intent.body,
                proxy=configuration.proxy,
                server_hostname=configuration.tls_server_name,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=client.timeout),
            ) as response:
                if response.status != 200:
                    # Do not read arbitrary Status bodies into errors/history.
                    return status_result(response.status)
                data = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    data.extend(chunk)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError
            decoding = asyncio.create_task(asyncio.to_thread(_receipt, bytes(data), intent))
            try:
                await asyncio.shield(decoding)
            except asyncio.CancelledError:
                finishing = asyncio.gather(decoding, return_exceptions=True)
                while not finishing.done():
                    try:
                        await asyncio.shield(finishing)
                    except asyncio.CancelledError:
                        continue
                await finishing
                raise
            return MutationResult(
                MutationState.SUCCEEDED, "API confirmed the guarded patch. No retry was made."
            )
    except asyncio.CancelledError:
        return MutationResult(
            MutationState.UNCERTAIN if started else MutationState.CANCELLED,
            "Write interrupted after request start. Inspect the current object; do not repeat blindly."
            if started
            else "Cancelled before the write request started.",
        )
    except TimeoutError:
        return MutationResult(
            MutationState.UNCERTAIN if started else MutationState.TIMEOUT,
            "Write response timed out. Inspect the current object; do not repeat blindly."
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
            MutationState.UNCERTAIN if started else MutationState.REJECTED,
            "The write result could not be validated. Inspect the current object; do not repeat blindly."
            if started
            else "Write preparation was refused; no request was started.",
        )


def _receipt(data: bytes, intent: MutationIntent) -> None:
    record = resource_record(intent.resource, _decode(data), intent.target.namespace)
    intent.target.require_current(intent.target.session, uid=record.uid or "")
    if record.name != intent.target.name or not record.resource_version:
        raise AppError("Patch response does not match the captured resource.")
