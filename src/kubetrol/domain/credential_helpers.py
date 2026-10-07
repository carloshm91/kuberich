"""Fixed diagnostics for declared helpers; never return their private output."""

from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path


def is_eks_helper(argv: Sequence[str]) -> bool:
    return (
        bool(argv)
        and Path(argv[0]).name == "aws"
        and any(left == "eks" and right == "get-token" for left, right in pairwise(argv[1:]))
    )


def helper_start_failure(argv: Sequence[str], *, missing: bool) -> str:
    if not is_eks_helper(argv):
        return "Cannot start credential helper. Check its installation and permissions."
    if missing:
        return "AWS CLI was not found. Install aws and check the exec command/PATH, then retry."
    return "Cannot start AWS CLI. Check its executable permissions and exec command."


def helper_failure(argv: Sequence[str], stderr: bytes) -> str:
    if not is_eks_helper(argv):
        return "Credential helper failed. Complete provider login and retry."
    # Recognition is best effort, not an assertion about the account. Only these
    # fixed messages cross the boundary; no profile, ARN or raw output escapes.
    error = stderr[:65536].decode("utf-8", errors="replace").lower()
    if any(
        marker in error
        for marker in (
            "the sso session associated with this profile",
            "error loading sso token",
            "error when retrieving token from sso",
        )
    ):
        return (
            "AWS SSO login is unavailable or expired. Run aws sso login --profile PROFILE "
            "outside Kubetrol, using the kubeconfig's profile, then retry."
        )
    if "assumerole" in error and any(
        marker in error for marker in ("accessdenied", "access denied", "not authorized")
    ):
        return (
            "AWS denied role assumption. Check the configured role/profile and its IAM "
            "permissions and trust policy, then retry."
        )
    if "unable to locate credentials" in error:
        return "AWS credentials are unavailable. Configure the selected AWS profile or log in, then retry."
    if "expiredtoken" in error:
        return "AWS credentials have expired. Renew the selected AWS session outside Kubetrol, then retry."
    return (
        "AWS token helper failed. Check aws eks get-token with the same profile/role "
        "outside Kubetrol, then retry; helper output is private."
    )
