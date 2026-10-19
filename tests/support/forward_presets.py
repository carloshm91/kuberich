"""Named-port fixture shared by source and genuinely installed terminal trials."""

from tests.support import standard_terminal
from tests.support.forward_terminal import terminal_forward


def named_terminal_forward(command, directory, evidence, monkeypatch):
    original = standard_terminal.manifest

    def manifest(definition, **kwargs):
        value = original(definition, **kwargs)
        if definition.name == "services":
            value["spec"]["ports"] = [{"name": "web", "port": 80, "targetPort": 8081}]
            value["metadata"]["annotations"] = {"k9scli.io/port-forwards": "0:web"}
        return value

    monkeypatch.setattr(standard_terminal, "manifest", manifest)
    terminal_forward(command, directory, evidence, mapping=":web")
