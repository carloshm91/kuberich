"""Provider hints never disclose helper-controlled text or mislabel other tools."""

import pytest

from kuberich.domain.credential_helpers import (
    azure_login_mode,
    azure_prompt,
    bearer_token,
    helper_failure,
    helper_start_failure,
    is_azure_helper,
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


AZURE = ("/owned/bin/kubelogin", "get-token", "--server-id", "synthetic")


@pytest.mark.parametrize(
    "argv,expected",
    [
        ((), False),
        (("other", "get-token", "--server-id", "x"), False),
        (("kubelogin", "convert-kubeconfig", "--server-id", "x"), False),
        (("kubelogin", "get-token", "--oidc-issuer-url", "https://example.invalid"), False),
        (("kubelogin", "get-token", "--server-id=x"), True),
        (AZURE, True),
    ],
)
def test_azure_recognition_does_not_mislabel_oidc_kubelogin(argv, expected):
    assert is_azure_helper(argv) is expected


@pytest.mark.parametrize(
    "args,env,expected",
    [
        ((), {}, "devicecode"),
        (("--login", "azurecli"), {}, "azurecli"),
        (("-l", "spn"), {}, "spn"),
        (("--login=interactive",), {}, "interactive"),
        (("-ldevicecode",), {}, "devicecode"),
        (("-l=workloadidentity",), {}, "workloadidentity"),
        (("-l",), {}, "devicecode"),
        (("--login=spn",), {"AAD_LOGIN_METHOD": "interactive"}, "interactive"),
        (
            ("--login=spn", "--disable-environment-override"),
            {"AAD_LOGIN_METHOD": "interactive"},
            "spn",
        ),
        (
            ("--login=spn", "--disable-environment-override=true"),
            {"AAD_LOGIN_METHOD": "interactive"},
            "spn",
        ),
        (
            ("--disable-environment-override", "--disable-environment-override=false"),
            {"AAD_LOGIN_METHOD": "interactive"},
            "interactive",
        ),
        (("--login=spn", "--login=azurecli"), {}, "azurecli"),
    ],
)
def test_browser_preflight_observes_native_mode_and_environment_precedence(args, env, expected):
    assert azure_login_mode((*AZURE, *args), env) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        (b"To sign in use a browser", True),
        (bytearray(b"To sign in enter CODE"), True),
        (b"code but no prompt", False),
        (b"To sign in later", False),
        (b"x" * 65536 + b"to sign in browser", False),
    ],
)
def test_only_bounded_provider_prompts_request_explicit_login(value, expected):
    assert azure_prompt(value) is expected


@pytest.mark.parametrize(
    "value", [None, 1, "", "x" * 65537, "secret\nheader", "x y", "x\x7fy", "é", "x\0y"]
)
def test_bearer_credentials_reject_controls_whitespace_and_unbounded_values(value):
    with pytest.raises(ValueError, match="Invalid bearer"):
        bearer_token(value)


def test_large_group_claim_credentials_use_an_independent_http_bound():
    assert bearer_token("x" * 65536) == "x" * 65536
    assert bearer_token("a.b_c-d+/~=") == "a.b_c-d+/~="


@pytest.mark.parametrize("missing", [True, False])
def test_azure_installation_and_permissions_have_separate_hints(missing):
    assert ("not found" if missing else "permissions") in helper_start_failure(
        AZURE, missing=missing
    )


@pytest.mark.parametrize(
    "error,hint",
    [
        (b"AADSTS90002", "tenant configuration"),
        (b"AADSTS50020", "tenant configuration"),
        (b"AADSTS700016", "tenant configuration"),
        (b"tenant ID cannot be empty", "tenant configuration"),
        (b"invalid tenant", "tenant configuration"),
        (b"AADSTS7000222", "service-principal"),
        (b"AADSTS7000215", "service-principal"),
        (b"AADSTS70021", "workload identity"),
        (b"federated token file", "workload identity"),
        (b"federated identity not configured", "workload identity"),
        (b"Azure CLI not found", "CLI was not found"),
        (b"az executable", "CLI was not found"),
        (b"az: not found", "CLI was not found"),
        (b"executable az not found", "CLI was not found"),
        (b"az login", "login is unavailable"),
        (b"AADSTS700082", "login is unavailable"),
        (b"AADSTS70043", "login is unavailable"),
        (b"AADSTS50076", "login is unavailable"),
        (b"AADSTS50173", "login is unavailable"),
        (b"interaction required", "login is unavailable"),
        (b"unknown", "kubelogin failed"),
        (b"x" * 65536 + b"AADSTS90002", "kubelogin failed"),
    ],
)
def test_azure_provider_codes_return_fixed_hints_without_private_output(error, hint):
    message = helper_failure(AZURE, error + b"\xff\x1b[2J private-tenant secret-token")
    assert hint in message
    assert all(value not in message for value in ("private-tenant", "secret-token", "\x1b"))
