"""Single-attempt conditional Node patches and policy/v1 eviction receipts."""

from collections.abc import Callable
from dataclasses import dataclass

from kuberich.adapters.kubernetes import KubernetesSession, decode_json
from kuberich.adapters.mutations import WriteResponseMetadata, guarded_request
from kuberich.domain.mutations import MutationIntent, MutationResult, MutationState, status_result
from kuberich.domain.node_maintenance import PodReview, eviction_receipt, node_state, retry_delay
from kuberich.domain.resources import resource_object, resource_record
from kuberich.errors import AppError


@dataclass(frozen=True)
class EvictionAttempt:
    result: MutationResult
    retry_seconds: float | None = None
    status: int | None = None


async def patch_node(
    client: KubernetesSession, intent: MutationIntent, authorize: Callable[[], None], desired: bool
) -> MutationResult:
    def receipt(body: bytes) -> None:
        record = resource_record(intent.resource, decode_json(body))
        if node_state(record, intent.target) is not desired:
            raise AppError("Node patch receipt did not confirm the requested scheduling state.")

    return await guarded_request(
        client,
        authorize,
        method="PATCH",
        path=intent.path,
        body=intent.body,
        content_type="application/json-patch+json",
        accepted=(200,),
        receipt=receipt,
    )


async def evict_pod(
    client: KubernetesSession,
    pod: PodReview,
    authorize: Callable[[], None],
    wall_clock: Callable[[], float],
) -> EvictionAttempt:
    metadata: list[WriteResponseMetadata] = []
    delay: list[float] = []
    accepted: list[bool] = []

    def receipt(body: bytes) -> MutationResult:
        if not eviction_receipt(decode_json(body)):
            raise AppError("Eviction acceptance could not be verified.")
        # Retain validated acceptance synchronously, even if cancellation races parser completion.
        accepted.append(True)
        return MutationResult(
            MutationState.ACCEPTED, "Eviction accepted; original UID absence is pending."
        )

    def refusal(status: int, body: bytes) -> MutationResult:
        if status != 429:
            return status_result(status)
        seconds: object = None
        try:
            value = decode_json(body)
            seconds = resource_object(value.get("details", {})).get("retryAfterSeconds")
        except (AppError, ValueError, UnicodeError, RecursionError, TypeError):
            pass
        delay.append(retry_delay(metadata[-1].retry_after, seconds, wall_clock()))
        return MutationResult(
            MutationState.REJECTED, "Eviction refused (429); PDB or rate limit may require waiting."
        )

    target = pod.target
    result = await guarded_request(
        client,
        authorize,
        method="POST",
        path=f"/api/v1/namespaces/{target.namespace}/pods/{target.name}/eviction",
        body=pod.eviction_body,
        content_type="application/json",
        accepted=(200,),
        receipt=receipt,
        error_receipt=refusal,
        response_metadata=metadata.append,
    )
    if accepted:
        result = MutationResult(
            MutationState.ACCEPTED, "Eviction accepted; original UID absence is pending."
        )
    return EvictionAttempt(
        result, delay[0] if delay else None, metadata[0].status if metadata else None
    )
