"""Fail closed on ambient SDK loaders; permit only an explicitly owned local fixture."""

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import kubernetes_asyncio.config as sdk_config
import yaml
from kubernetes_asyncio.client import Configuration

# Capture before pytest installs the ambient-loader traps. This is the single
# deliberate escape hatch, with validation BEFORE any SDK parsing/authentication.
_LOAD_FIXTURE = sdk_config.kube_config.load_kube_config


class FixtureLoader(yaml.SafeLoader):
    """Reject ambiguous keys; this loader is only for test-owned fixture files."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise yaml.YAMLError("Invalid or duplicate fixture key")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def fixture_yaml(contents: bytes) -> dict:
    depth = 0
    for count, event in enumerate(yaml.parse(contents.decode("utf-8")), start=1):
        if isinstance(event, yaml.AliasEvent) or count > 4096:
            raise ValueError
        if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
            if depth > 20:
                raise ValueError
        elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1
    data = yaml.load(contents, Loader=FixtureLoader)
    if not isinstance(data, dict):
        raise ValueError
    return data


@dataclass(frozen=True)
class DisposableContext:
    directory: Path
    kubeconfig: Path
    context: str
    server: str

    def validate(self) -> Path:
        """Fixture names alone are insufficient: bind the file, scope and endpoint."""
        try:
            directory = self.directory.resolve(strict=True)
            path = self.kubeconfig.resolve(strict=True)
            if not directory.is_dir() or not path.is_relative_to(directory) or not path.is_file():
                raise ValueError
            if not self.context.startswith(("kuberich-test-", "kind-kuberich-test-")):
                raise ValueError
            url = urlsplit(self.server)
            if (
                url.scheme not in {"http", "https"}
                or not ipaddress.ip_address(url.hostname or "").is_loopback
                or url.port is None
                or url.port == 0
                or url.username is not None
                or url.password is not None
                or url.path not in {"", "/"}
                or url.query
                or url.fragment
            ):
                raise ValueError
            with path.open("rb") as stream:
                contents = stream.read(65537)
            if len(contents) > 65536:
                raise ValueError
            data = fixture_yaml(contents)
            if data.get("current-context") != self.context:
                raise ValueError
            contexts, clusters = data["contexts"], data["clusters"]
            if (
                not isinstance(contexts, list)
                or not isinstance(clusters, list)
                or len(contexts) != 1
                or len(clusters) != 1
            ):
                raise ValueError
            selected, cluster = contexts[0], clusters[0]
            if (
                selected["name"] != self.context
                or selected["context"]["cluster"] != cluster["name"]
                or cluster["cluster"]["server"] != self.server
            ):
                raise ValueError
            cluster_keys = {
                "server",
                "certificate-authority-data",
                "insecure-skip-tls-verify",
                "tls-server-name",
            }
            if not isinstance(cluster["cluster"], dict) or cluster["cluster"].keys() - cluster_keys:
                raise ValueError
            # Local fake-API/kind fixtures have no external credential helpers.
            # Provider-helper fixtures will need their own deliberate qualification.
            user_keys = {"token", "client-key-data", "client-certificate-data"}
            users = data.get("users", [])
            if not isinstance(users, list) or len(users) > 1:
                raise ValueError
            for user in users:
                credentials = user["user"]
                if not isinstance(credentials, dict) or credentials.keys() - user_keys:
                    raise ValueError
        except (OSError, ValueError, TypeError, KeyError, IndexError, yaml.YAMLError):
            raise AssertionError(
                "Cluster tests require an owned temporary kubeconfig, explicit fixture context "
                "and matching local endpoint without external credential helpers."
            ) from None
        return path


async def load_disposable_config(fixture: DisposableContext) -> Configuration:
    path = fixture.validate()
    configuration = Configuration()
    await _LOAD_FIXTURE(
        config_file=str(path),
        context=fixture.context,
        client_configuration=configuration,
        persist_config=False,
    )
    return configuration


def reject_ambient_credentials(*args: object, **kwargs: object) -> None:
    raise AssertionError("Use load_disposable_config with an explicitly owned cluster fixture.")
