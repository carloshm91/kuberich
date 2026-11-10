"""Single-attempt ephemeral append with independent permanent-addition identity."""

from collections.abc import Callable
from dataclasses import dataclass

from kuberich.adapters.kubernetes import KubernetesSession, decode_json
from kuberich.adapters.mutations import guarded_request
from kuberich.domain.ephemeral_debug import (
    AppendIdentity,
    EphemeralDebugIntent,
    admitted_profile,
    append_identity,
)
from kuberich.domain.mutations import MutationResult, MutationState, status_result
from kuberich.errors import AppError


@dataclass(frozen=True, slots=True)
class AppendReceipt:
    result: MutationResult
    append: AppendIdentity | None
    profile: bytes | None


def _refusal(status: int, _data: bytes) -> MutationResult:
    if status in {405, 415}:
        return MutationResult(
            MutationState.REJECTED,
            "The cluster does not support the reviewed ephemeral-container patch API.",
        )
    if status == 422:
        return MutationResult(
            MutationState.REJECTED,
            "Ephemeral addition refused: an identity/version condition or admission validation failed. Prepare a new review.",
        )
    return status_result(status)


async def append_container(
    client: KubernetesSession,
    intent: EphemeralDebugIntent,
    authorize: Callable[[], None],
    *,
    dry_run: bool = False,
    expected_profile: bytes | None = None,
) -> AppendReceipt:
    appended: AppendIdentity | None = None
    profile: bytes | None = None

    def receipt(data: bytes) -> MutationResult:
        nonlocal appended, profile
        value = decode_json(data)
        if not dry_run:
            appended = append_identity(intent, value)
        try:
            admitted = admitted_profile(intent, value)
            if expected_profile is not None and admitted != expected_profile:
                raise AppError(
                    "The append response differs from the reviewed admitted declaration."
                )
        except AppError:
            if appended is None:
                raise
            return MutationResult(
                MutationState.SUCCEEDED,
                "The debug addition is permanent, but its admitted profile could not be verified. Attachment is blocked.",
            )
        profile = admitted
        return MutationResult(
            MutationState.SUCCEEDED,
            "Server dry-run passed; nothing was persisted. Confirm separately to add permanently."
            if dry_run
            else "API confirmed the permanent debug addition; no retry was made.",
        )

    result = await guarded_request(
        client,
        authorize,
        method="PATCH",
        path=intent.path,
        body=intent.body,
        content_type="application/json-patch+json",
        accepted=(200,),
        receipt=receipt,
        dry_run=dry_run,
        error_receipt=_refusal,
    )
    return AppendReceipt(result, appended, profile)
