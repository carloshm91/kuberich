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


def is_azure_helper(argv: Sequence[str]) -> bool:
    return (
        bool(argv)
        and Path(argv[0]).name == "kubelogin"
        and "get-token" in argv[1:]
        and any(value == "--server-id" or value.startswith("--server-id=") for value in argv[1:])
    )


def azure_login_mode(argv: Sequence[str], environment: dict[str, str]) -> str:
    # Leave all provider arguments untouched. This only controls whether a
    # browser may be launched automatically, never Azure's identity precedence.
    mode = "devicecode"
    disabled = False
    for index, argument in enumerate(argv[1:], 1):
        if argument in {"-l", "--login"} and index + 1 < len(argv):
            mode = argv[index + 1]
        elif argument.startswith("--login="):
            mode = argument.partition("=")[2]
        elif argument.startswith("-l") and len(argument) > 2:
            mode = argument[2:].removeprefix("=")
        if argument == "--disable-environment-override":
            disabled = True
        elif argument.startswith("--disable-environment-override="):
            disabled = argument.partition("=")[2].lower() in {"true", "1", "t"}
    return mode if disabled else environment.get("AAD_LOGIN_METHOD", mode)


def azure_prompt(output: bytes | bytearray) -> bool:
    value = output[:65536].lower()
    return b"to sign in" in value and (b"code" in value or b"browser" in value)


AZURE_LOGIN_REQUIRED = (
    "Azure sign-in needs interaction. Use :login in the native terminal, or complete "
    "the configured kubelogin login outside Kubetrol and retry."
)


def bearer_token(value: object) -> str:
    # JWTs containing many group claims can exceed the argument/name limit.
    # Keep the HTTP credential bound separate, and reject header controls/spaces.
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 65536
        or any(not 33 <= ord(character) <= 126 for character in value)
    ):
        raise ValueError("Invalid bearer credential.")
    return value


def helper_start_failure(argv: Sequence[str], *, missing: bool) -> str:
    if is_azure_helper(argv):
        return (
            "Azure kubelogin was not found. Install Azure kubelogin and check its exec command/PATH, then retry."
            if missing
            else "Cannot start Azure kubelogin. Check executable permissions and its exec command."
        )
    if not is_eks_helper(argv):
        return "Cannot start credential helper. Check its installation and permissions."
    if missing:
        return "AWS CLI was not found. Install aws and check the exec command/PATH, then retry."
    return "Cannot start AWS CLI. Check its executable permissions and exec command."


def helper_failure(argv: Sequence[str], stderr: bytes) -> str:
    if is_azure_helper(argv):
        return azure_failure(stderr)
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


def azure_failure(stderr: bytes) -> str:
    error = stderr[:65536].decode("utf-8", errors="replace").lower()
    if any(
        value in error
        for value in (
            "aadsts90002",
            "aadsts50020",
            "aadsts700016",
            "tenant id cannot be empty",
            "invalid tenant",
        )
    ):
        return "Azure tenant configuration or account access is invalid. Check the configured tenant, account/application and Azure environment, then retry."
    if any(value in error for value in ("aadsts7000222", "aadsts7000215")):
        return "Azure service-principal credentials are expired or invalid. Renew the configured secret/certificate outside Kubetrol, then retry."
    if any(value in error for value in ("aadsts70021", "federated token", "federated identity")):
        return "Azure workload identity failed. Check the declared federation, token file and tenant/client settings, then retry."
    if any(
        value in error
        for value in (
            "az executable",
            "azure cli not found",
            "az: not found",
            "executable az not found",
        )
    ):
        return "Azure CLI was not found. Install az for the configured azurecli login and check PATH, then retry."
    if any(
        value in error
        for value in (
            "az login",
            "aadsts700082",
            "aadsts70043",
            "aadsts50076",
            "aadsts50173",
            "interaction required",
        )
    ):
        return "Azure login is unavailable or expired. Run az login outside Kubetrol for azurecli, or :login for the configured device/browser flow, then retry."
    return "Azure kubelogin failed. Check the configured login mode, tenant and credentials outside Kubetrol, then retry; helper output is private."
