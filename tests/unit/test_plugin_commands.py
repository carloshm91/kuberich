"""Plugin resolution is local; its manifest gates execution before helper lookup."""

import pytest

from kuberich.cli import main
from kuberich.domain.plugins import PluginSelection
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService, PluginCommand, suggestions


@pytest.mark.parametrize("readonly", [False, True])
def test_plugin_name_resolves_for_explicit_manifest_review_in_both_policies(readonly):
    service = CommandService(AccessPolicy(readonly))
    assert service.resolve(":plugin inspect") == PluginCommand("inspect")
    assert service.resolve(":plugins") is Command.PLUGINS
    assert service.resolve(":pluginjobs") is Command.PLUGIN_JOBS
    assert suggestions("plugin in", (), (), plugins=("inspect", "other")) == ("plugin inspect",)
    with pytest.raises(AppError, match="one configured"):
        service.resolve("plugin one two")


@pytest.mark.parametrize("readonly", [False, True])
def test_startup_rejects_execution_before_any_connection_or_credential_work(
    tmp_path, monkeypatch, capsys, readonly
):
    from kuberich.adapters.kubernetes import KubernetesSession

    async def forbidden(*args, **kwargs):
        pytest.fail("must reject before opening a connection")

    monkeypatch.setattr(KubernetesSession, "open", forbidden)
    (tmp_path / "config.yaml").write_text("schema_version: 1\n")
    arguments = ["--config", str(tmp_path / "config.yaml"), "--command", "plugin inspect"]
    if readonly:
        arguments.append("--readonly")
    assert main(arguments) != 0
    assert "interactive resource selection" in capsys.readouterr().err


@pytest.mark.parametrize(
    "resource,namespace,group",
    [("v1/pods", None, ""), ("v1/pods", "team", ""), ("apps/v1/deployments", "team", "apps")],
)
def test_empty_resource_views_retain_captured_scope_without_inventing_an_object(
    resource, namespace, group
):
    values = PluginSelection("demo", resource, namespace=namespace).values()
    assert values["GROUP"] == group and values["VERSION"] == "v1"
    assert values["RESOURCE"] == resource.split("/")[-1]
    assert values["NAMESPACE"] == (namespace or "")
    assert "NAME" not in values and "CONTAINER" not in values
