"""Captured shell decisions and safe local connection snapshots."""

from dataclasses import replace

import pytest
from kubernetes_asyncio import client

from kubetrol.adapters.credentials import ExecToken
from kubetrol.adapters.kubernetes import KubernetesSession
from kubetrol.config.catalog import ContextConfig, Entry
from kubetrol.config.schema import (
    ConfigDocument,
    Settings,
    parse_document,
    resolve_settings,
    settings_from,
)
from kubetrol.domain.processes import ProcessResult, ProcessStatus
from kubetrol.domain.shell import shell_result, verify_shell_target
from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError
from kubetrol.services.access import AccessPolicy
from kubetrol.services.commands import Command, CommandService
from tests.support.pods import pod, record


def target(**changes):
    base = ResourceTarget(
        SessionIdentity("fixture", 1), "", "pods", "team", "api", "api-uid", "app"
    )
    return replace(base, **changes)


@pytest.mark.parametrize(
    "value",
    [
        [],
        "bash -l",
        None,
        {},
        ["sh"] * 33,
        [1],
        ["--option"],
        ["sh", ""],
        ["sh", "bad\x1bvalue"],
        ["x" * 8193],
    ],
)
def test_shell_preferences_reject_invalid_arguments_without_echoing_values(value):
    with pytest.raises(AppError, match="shell") as error:
        settings_from({"shell": value})
    assert "bad" not in str(error.value)
    with pytest.raises(AppError, match="shell"):
        Settings(shell=value)


def test_shell_preferences_are_captured_and_round_trip_as_arguments():
    arguments = ["/bin/bash", "-l"]
    settings = settings_from({"shell": arguments})
    arguments[0] = "changed"
    assert settings.shell == ("/bin/bash", "-l")
    document = parse_document({"schema_version": 1, "shell": ["bash", "-l"], "future": 1})
    assert document.unknown == {"future": 1}
    assert parse_document(document.to_mapping()) == document
    assert resolve_settings(ConfigDocument(), {}, {"shell": ["sh", "-l"]}).shell == ("sh", "-l")
    assert Settings().shell == ("sh",)


@pytest.mark.parametrize("verb", ["shell", "exec"])
def test_shell_command_is_available_only_after_readonly_policy(verb):
    assert CommandService(AccessPolicy(False)).resolve(":" + verb) is Command.SHELL
    assert CommandService(AccessPolicy(False)).resolve(verb + " sh") is Command.UNAVAILABLE
    with pytest.raises(AppError, match="Read-only"):
        CommandService(AccessPolicy(True)).resolve(verb)


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (ProcessStatus.SUCCEEDED, 0, "closed"),
        (ProcessStatus.CANCELLED, -15, "cancelled"),
        (ProcessStatus.SIGNALLED, -2, "interrupted"),
        (ProcessStatus.FAILED, 130, "interrupted"),
        (ProcessStatus.FAILED, 143, "interrupted"),
        (ProcessStatus.FAILED, 126, "unavailable"),
        (ProcessStatus.FAILED, 127, "unavailable"),
        (ProcessStatus.FAILED, 1, "pods/exec"),
        (ProcessStatus.TIMED_OUT, -9, "unexpectedly"),
        (ProcessStatus.OUTPUT_LIMIT, -9, "unexpectedly"),
        (ProcessStatus.IO_ERROR, -9, "unexpectedly"),
    ],
)
def test_shell_results_do_not_display_raw_process_output(status, code, expected):
    message = shell_result(ProcessResult(status, code, b"private-token", b"private-token"))
    assert expected in message and "private-token" not in message


def test_pod_identity_container_and_state_are_verified():
    manifest = pod("api", uid="api-uid")
    verify_shell_target(target(), record(manifest))
    manifest["status"] = None
    verify_shell_target(target(), record(manifest))
    manifest["spec"]["initContainers"] = [{"name": "init"}]
    verify_shell_target(target(container="init"), record(manifest))
    missing_uid = pod("api")
    del missing_uid["metadata"]["uid"]
    with pytest.raises(AppError, match="UID"):
        record(missing_uid)
    with pytest.raises(AppError, match="stale"):
        verify_shell_target(target(), replace(record(manifest), uid=None))
    for selected, value, expected in [
        (target(), pod("api", uid="replacement"), "stale"),
        (target(), pod("api", uid=""), "stale"),
        (target(), pod("other", uid="api-uid"), "match"),
        (target(), pod("api", uid="api-uid", namespace="other"), "match"),
        (target(container="missing"), manifest, "unavailable"),
    ]:
        with pytest.raises(AppError, match=expected):
            verify_shell_target(selected, record(value))
    for field, value, expected in [
        ("metadata", {"deletionTimestamp": "now"}, "deleted"),
        ("status", {"phase": "Succeeded"}, "finished"),
        ("status", {"phase": "Failed"}, "finished"),
    ]:
        value_manifest = pod("api", uid="api-uid")
        value_manifest[field].update(value)
        with pytest.raises(AppError, match=expected):
            verify_shell_target(target(), record(value_manifest))


@pytest.mark.parametrize(
    "mechanism", ["anonymous", "token", "cert", "exec-relative", "exec-absolute", "exec-path"]
)
def test_delegation_pins_prepared_connection_and_only_the_active_identity(tmp_path, mechanism):
    selected = ContextConfig(
        "fixture",
        "team",
        Entry(
            {"server": "ignored", "extensions": [{"name": "safe", "extension": {"x": 1}}]}, tmp_path
        ),
        Entry({}, tmp_path),
    )
    session = KubernetesSession(selected, 1)
    configuration = client.Configuration()
    configuration.host = "https://selected.example"
    configuration.verify_ssl = True
    configuration.ssl_ca_cert = "/private/ca"
    configuration.tls_server_name = "selected.example"
    configuration.proxy = "http://proxy.example"
    session.configuration = configuration
    try:
        if mechanism == "token":
            configuration.api_key["BearerToken"] = "Bearer synthetic-secret"
        if mechanism == "cert":
            configuration.cert_file, configuration.key_file = "/private/cert", "/private/key"
        if mechanism.startswith("exec"):
            command = {
                "exec-relative": "./helper",
                "exec-absolute": "/bin/helper",
                "exec-path": "helper",
            }[mechanism]
            session.credentials = ExecToken(
                Entry(
                    {
                        "command": command,
                        "apiVersion": "client.authentication.k8s.io/v1",
                        "interactiveMode": "Never",
                    },
                    tmp_path,
                ),
                {},
                1,
            )
        snapshot = session.delegated_config()
        cluster = snapshot["clusters"][0]["cluster"]
        assert cluster == {
            "server": "https://selected.example",
            "insecure-skip-tls-verify": False,
            "certificate-authority": "/private/ca",
            "tls-server-name": "selected.example",
            "proxy-url": "http://proxy.example",
            "extensions": [{"name": "safe", "extension": {"x": 1}}],
        }
        assert snapshot["contexts"][0]["name"] == "fixture"
        assert snapshot["contexts"][0]["context"]["namespace"] == "team"
        user = snapshot["users"][0]["user"]
        if mechanism == "token":
            assert user == {"token": "synthetic-secret"}
        elif mechanism == "cert":
            assert user == {"client-certificate": "/private/cert", "client-key": "/private/key"}
        elif mechanism.startswith("exec"):
            assert (
                user["exec"]["command"] == str(tmp_path / "helper")
                if mechanism == "exec-relative"
                else user["exec"]["command"] == command
            )
            session.credentials.entry.data["command"] = "changed"
            assert snapshot["users"][0]["user"]["exec"]["command"] != "changed"
        else:
            assert user == {}
        configuration.host = "https://changed.example"
        selected.cluster.data["extensions"][0]["extension"]["x"] = 2
        assert (
            cluster["server"] == "https://selected.example"
            and cluster["extensions"][0]["extension"]["x"] == 1
        )
        session.configuration = None
        with pytest.raises(AppError, match="closed"):
            session.delegated_config()
    finally:
        session.directory.cleanup()
