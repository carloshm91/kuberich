"""Provider hints never disclose helper-controlled text or mislabel other tools."""

import pytest

from kubetrol.domain.credential_helpers import (
    helper_failure,
    helper_start_failure,
    is_eks_helper,
)

AWS = ("/owned/bin/aws", "--region", "us-east-1", "eks", "get-token", "--cluster-name", "test")


@pytest.mark.parametrize(
    "argv,expected",
    [
        ((), False),
        (("kubelogin", "eks", "get-token"), False),
        (("aws",), False),
        (("aws", "--profile", "eks", "wrong"), False),
        (("aws", "sso", "login"), False),
        (("aws", "wrong", "get-token", "eks"), False),
        (("aws", "eks", "get-token"), True),
        (AWS, True),
    ],
)
def test_only_declared_aws_token_helpers_get_provider_hints(argv, expected):
    assert is_eks_helper(argv) is expected


@pytest.mark.parametrize("missing", [True, False])
def test_start_failures_distinguish_missing_aws_from_execution_permissions(missing):
    hint = helper_start_failure(AWS, missing=missing)
    assert ("not found" if missing else "permissions") in hint
    assert helper_start_failure(("other",), missing=missing).startswith("Cannot start credential")


@pytest.mark.parametrize(
    "stderr,expected",
    [
        (
            b"The SSO session associated with this profile has expired or is otherwise invalid.",
            "SSO",
        ),
        (b"Error loading SSO Token: Token for private-name does not exist", "SSO"),
        (b"Error when retrieving token from sso: Token has expired and refresh failed", "SSO"),
        (
            b"An error occurred (AccessDenied) when calling the AssumeRole operation",
            "role assumption",
        ),
        (b"AssumeRole: Access denied for private-name", "role assumption"),
        (b"AssumeRoleWithWebIdentity: not authorized", "role assumption"),
        (b"Unable to locate credentials", "unavailable"),
        (b"An error occurred (ExpiredToken) when calling the AssumeRole operation", "expired"),
        (b"AccessDenied: operation other than role assumption", "token helper failed"),
        (b"AssumeRole: unknown error", "token helper failed"),
        (b"\xffopaque-private-name", "token helper failed"),
        (b"x" * 65536 + b"Error loading SSO Token", "token helper failed"),
    ],
)
def test_failure_recognition_returns_only_fixed_private_safe_messages(stderr, expected):
    hint = helper_failure(AWS, stderr + b"\x1b[2Jprivate-name secret-token")
    assert expected in hint
    assert all(value not in hint for value in ("private-name", "secret-token", "\x1b"))
    assert helper_failure(("other",), stderr).startswith("Credential helper failed")
