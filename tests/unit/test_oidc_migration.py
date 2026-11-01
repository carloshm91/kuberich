"""Migration emits real literal helper options and no existing secret material."""

import base64
import copy

import pytest

from kuberich.domain.oidc_migration import CLIENT_SECRET_PLACEHOLDER, oidc_exec_fragment
from kuberich.errors import AppError


def provider(**values):
    return {
        "name": "oidc",
        "config": {
            "idp-issuer-url": "https://issuer.example.invalid/realm",
            "client-id": "demo",
            **values,
        },
    }


def test_fragment_is_a_real_v1_helper_with_only_reviewed_metadata(tmp_path):
    original = provider(
        **{
            "id-token": "private-id",
            "refresh-token": "private-refresh",
            "client-secret": "private-secret",
            "extra-scopes": "private-scope",
        }
    )
    before = copy.deepcopy(original)
    actual = oidc_exec_fragment(original, tmp_path)
    assert actual == {
        "exec": {
            "apiVersion": "client.authentication.k8s.io/v1",
            "command": "kubelogin",
            "args": [
                "get-token",
                "--oidc-issuer-url=https://issuer.example.invalid/realm",
                "--oidc-client-id=demo",
                "--oidc-client-secret=" + CLIENT_SECRET_PLACEHOLDER,
            ],
            "interactiveMode": "IfAvailable",
            "provideClusterInfo": False,
        }
    }
    assert "private" not in repr(actual) and original == before


@pytest.mark.parametrize("optional", [{}, {"client-secret": ""}, {"client-secret": None}])
def test_public_client_does_not_receive_an_invented_secret(optional, tmp_path):
    args = oidc_exec_fragment(provider(**optional), tmp_path)["exec"]["args"]
    assert len(args) == 3 and not any("secret" in value for value in args)


def test_relative_ca_uses_original_user_file_directory_without_reading_it(tmp_path):
    result = oidc_exec_fragment(
        provider(**{"idp-certificate-authority": "issuer-ca.pem"}), tmp_path
    )
    assert result["exec"]["args"][-1] == "--certificate-authority=" + str(
        tmp_path / "issuer-ca.pem"
    )
    assert not (tmp_path / "issuer-ca.pem").exists()


def test_inline_ca_overrides_file_and_absolute_file_keeps_its_identity(tmp_path):
    ca = base64.b64encode(
        b"-----BEGIN CERTIFICATE-----\nZGVtbw==\n-----END CERTIFICATE-----\n"
    ).decode()
    result = oidc_exec_fragment(
        provider(
            **{"idp-certificate-authority-data": ca, "idp-certificate-authority": "never-read"}
        ),
        tmp_path,
    )
    assert result["exec"]["args"][-1] == "--certificate-authority-data=" + ca
    result = oidc_exec_fragment(
        provider(**{"idp-certificate-authority": str(tmp_path / "ca")}), tmp_path
    )
    assert result["exec"]["args"][-1] == "--certificate-authority=" + str(tmp_path / "ca")


@pytest.mark.parametrize(
    "value,field",
    [
        (None, "auth-provider.name"),
        ({}, "auth-provider.name"),
        ({"name": "gcp"}, "auth-provider.name"),
        ({"name": "oidc"}, "auth-provider.config"),
        ({"name": "oidc", "config": []}, "auth-provider.config"),
        ({"name": "oidc", "config": {1: "x"}}, "auth-provider.config"),
        ({"name": "oidc", "config": {"x": False}}, "auth-provider.config"),
        ({"name": "oidc", "config": {str(i): "x" for i in range(33)}}, "auth-provider.config"),
        (provider(**{"idp-issuer-url": ""}), "config.idp-issuer-url"),
        (provider(**{"client-id": None}), "config.client-id"),
        (provider(**{"client-id": "private\x1b"}), "config.client-id"),
        (provider(**{"idp-issuer-url": "http://issuer.example.invalid"}), "config.idp-issuer-url"),
        (
            provider(**{"idp-issuer-url": "https://private@issuer.example.invalid"}),
            "config.idp-issuer-url",
        ),
        (
            provider(**{"idp-issuer-url": "https://issuer.example.invalid?private=x"}),
            "config.idp-issuer-url",
        ),
        (
            provider(**{"idp-issuer-url": "https://issuer.example.invalid#private"}),
            "config.idp-issuer-url",
        ),
        (
            provider(**{"idp-issuer-url": "https://issuer.example.invalid:0"}),
            "config.idp-issuer-url",
        ),
        (
            provider(**{"idp-issuer-url": "https://issuer.example.invalid:private"}),
            "config.idp-issuer-url",
        ),
        (
            provider(**{"idp-certificate-authority-data": "private-not-base64"}),
            "config.idp-certificate-authority-data",
        ),
        (
            provider(
                **{"idp-certificate-authority-data": base64.b64encode(b"PRIVATE KEY").decode()}
            ),
            "config.idp-certificate-authority-data",
        ),
        (
            provider(
                **{
                    "idp-certificate-authority-data": base64.b64encode(
                        b"-----BEGIN CERTIFICATE-----\nPRIVATE KEY\n-----END CERTIFICATE-----"
                    ).decode()
                }
            ),
            "config.idp-certificate-authority-data",
        ),
        (provider(**{"client-id": "x" * 8192}), "exec.args"),
    ],
)
def test_refusals_name_fields_without_echoing_private_input(value, field, tmp_path):
    with pytest.raises(AppError) as caught:
        oidc_exec_fragment(value, tmp_path)
    assert field in str(caught.value)
    assert "private" not in str(caught.value) and "\x1b" not in str(caught.value)


def test_relative_ca_needs_real_provenance():
    from pathlib import Path

    with pytest.raises(AppError, match="original absolute kubeconfig directory"):
        oidc_exec_fragment(provider(**{"idp-certificate-authority": "ca"}), Path("relative"))
