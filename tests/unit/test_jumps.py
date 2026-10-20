"""Jump definitions render literal field paths from a row manifest, never code."""

import pytest

from kuberich.domain.jumps import JumpTarget, parse_jumps, resolve_jump, template
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService, ScopedCommand, suggestions

DEPLOYMENT = {
    "metadata": {
        "name": "web",
        "namespace": "team",
        "labels": {"app.kubernetes.io/name": "web", "tier": "front"},
    },
    "spec": {"replicas": 2, "paused": False, "selector": {"matchLabels": {"app": "web"}}},
}


def jumps(**definitions):
    return parse_jumps({"schema_version": 1, "definitions": definitions})


def test_label_map_expands_and_namespace_defaults_to_the_row():
    config = jumps(
        pods={
            "source": "apps/v1/deployments",
            "target": "v1/pods",
            "labels": "{{ spec.selector.matchLabels }}",
        }
    )
    (jump,) = config.available("apps/v1/deployments")
    assert config.available("v1/pods") == ()
    assert resolve_jump(jump, DEPLOYMENT, "team", True) == JumpTarget(
        "v1/pods", "team", "label:app=web"
    )


def test_quoted_keys_scalars_and_literal_text_render_into_one_selector():
    (jump,) = jumps(
        same={
            "source": "apps/v1/deployments",
            "target": "apps/v1/replicasets",
            "namespace": "*",
            "labels": 'app.kubernetes.io/name={{metadata.labels["app.kubernetes.io/name"]}},'
            "tier={{ metadata.labels['tier'] }},paused={{spec.paused}},n={{spec.replicas}}",
        }
    ).definitions
    target = resolve_jump(jump, DEPLOYMENT, "team", True)
    assert target == JumpTarget(
        "apps/v1/replicasets",
        "*",
        "label:app.kubernetes.io/name=web,tier=front,paused=false,n=2",
    )


def test_field_selector_from_cluster_scoped_row_lists_all_namespaces():
    (jump,) = jumps(
        node={
            "source": "v1/nodes",
            "target": "v1/pods",
            "fields": "spec.nodeName={{metadata.name}}",
        }
    ).definitions
    node = {"metadata": {"name": "worker-1"}}
    assert resolve_jump(jump, node, None, True) == JumpTarget(
        "v1/pods", "*", "field:spec.nodeName=worker-1"
    )


def test_explicit_namespace_template_and_cluster_scoped_targets():
    (jump,) = jumps(
        ns={"source": "v1/pods", "target": "v1/configmaps", "namespace": "{{metadata.namespace}}"}
    ).definitions
    assert resolve_jump(jump, DEPLOYMENT, "other", True) == JumpTarget("v1/configmaps", "team", "")
    (node,) = jumps(node={"source": "v1/pods", "target": "v1/nodes"}).definitions
    assert resolve_jump(node, DEPLOYMENT, "team", False) == JumpTarget("v1/nodes", None, "")
    (bad,) = jumps(
        node={"source": "v1/pods", "target": "v1/nodes", "namespace": "team"}
    ).definitions
    with pytest.raises(AppError, match="cluster-scoped"):
        resolve_jump(bad, DEPLOYMENT, "team", False)


@pytest.mark.parametrize(
    "manifest, labels, message",
    [
        ({}, "{{spec.selector.matchLabels}}", "has no spec.selector.matchLabels"),
        ({"spec": {"x": {}}}, "{{spec.x}}", "empty label map"),
        ({"spec": {"x": [1]}}, "{{spec.x}}", "not a single value"),
        ({"spec": {"x": "a,b=c"}}, "k={{spec.x}}", "cannot carry"),
        ({"spec": {"x": "a b"}}, "k={{spec.x}}", "cannot carry"),
        ({"spec": {"x": {"a": "x)"}}}, "{{spec.x}}", "cannot carry"),
        ({"spec": {"x": {"a": "b"}}}, "k={{spec.x}}", "not a single value"),
        ({"spec": {"x": "v"}}, "{{spec.x}},a b", "Invalid local selector"),
        ({"spec": "text"}, "k={{spec.x}}", "has no spec.x"),
    ],
)
def test_missing_or_unsafe_values_refuse_the_jump(manifest, labels, message):
    (jump,) = jumps(j={"source": "v1/pods", "target": "v1/pods", "labels": labels}).definitions
    with pytest.raises(AppError, match=message):
        resolve_jump(jump, manifest, "team", True)


def test_rendered_namespace_and_fields_are_validated():
    (jump,) = jumps(
        j={"source": "v1/pods", "target": "v1/pods", "namespace": "{{metadata.name}}"}
    ).definitions
    with pytest.raises(AppError, match="Namespace"):
        resolve_jump(jump, {"metadata": {"name": "Upper"}}, "team", True)
    (field,) = jumps(
        j={"source": "v1/pods", "target": "v1/pods", "fields": "spec.secret={{metadata.name}}"}
    ).definitions
    with pytest.raises(AppError, match="Unsupported local field"):
        resolve_jump(field, DEPLOYMENT, "team", True)


@pytest.mark.parametrize(
    "value, message",
    [
        ([], "only schema_version and definitions"),
        ({"other": 1}, "only schema_version and definitions"),
        ({"schema_version": 2}, "schema_version"),
        ({"schema_version": True}, "schema_version"),
        ({"definitions": []}, "at most 64"),
        ({"definitions": {f"j{i}": {} for i in range(65)}}, "at most 64"),
        ({"definitions": {"Bad": {}}}, "Jump names"),
        ({"definitions": {"j": []}}, "accepts only"),
        ({"definitions": {"j": {"source": "v1/pods", "run": "x"}}}, "accepts only"),
        ({"definitions": {"j": {"source": "v1/pods"}}}, "needs source and target"),
        (
            {
                "definitions": {
                    "j": {"source": "v1/pods", "target": "v1/pods", "labels": "a", "fields": "b"}
                }
            },
            "not both",
        ),
        (
            {"definitions": {"j": {"source": "v1/pods", "target": "v1/pods", "description": 3}}},
            "description",
        ),
        ({"definitions": {"j": {"source": "pods", "target": "v1/pods"}}}, "VERSION/RESOURCE"),
        (
            {"definitions": {"j": {"source": "server:v1/pods", "target": "v1/pods"}}},
            "VERSION/RESOURCE",
        ),
    ],
)
def test_definitions_are_strict(value, message):
    with pytest.raises(AppError, match=message):
        parse_jumps(value)


@pytest.mark.parametrize(
    "text, message",
    [
        ("", "1-256"),
        (3, "1-256"),
        ("{{ spec.x | upper }}", "field paths"),
        ("{{ __import__('os') }}", "field paths"),
        ("{{ spec.x() }}", "field paths"),
        ("{{ spec[0] }}", "field paths"),
        ("{{ }}", "1-16 parts"),
        ("{{" + ".".join("a" * 17) + "}}", "1-16 parts"),
        ("{{a}}" * 9, "at most 8"),
        ("{{ spec.x", "unclosed"),
        ("spec.x }}", "unclosed"),
    ],
)
def test_templates_are_field_paths_only(text, message):
    with pytest.raises(AppError, match=message):
        template(text, "labels")


def test_definitions_are_sorted_and_described():
    config = jumps(
        zeta={"source": "v1/pods", "target": "v1/nodes", "description": "Node"},
        alpha={"source": "v1/pods", "target": "v1/services"},
    )
    assert [jump.name for jump in config.available("v1/pods")] == ["alpha", "zeta"]
    assert config.definitions[1].description == "Node"
    assert parse_jumps({}).definitions == ()


def test_jump_command_accepts_one_name_and_completes_configured_names():
    service = CommandService(AccessPolicy(True))
    assert service.resolve(":jump") is Command.JUMP
    assert service.resolve(":jump pods") == ScopedCommand(Command.JUMP, "pods")
    with pytest.raises(AppError, match="one configured jump name"):
        service.resolve(":jump Pods")
    assert suggestions("jump p", (), (), jumps=("node-pods", "pods")) == ("jump pods",)
