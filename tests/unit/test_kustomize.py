"""Finite local Kustomize dependency surface, remote refusal and exact argv."""

from pathlib import Path

import pytest
import yaml

from kuberich.domain.kustomize import kustomize_argv, kustomize_references, local_reference
from kuberich.errors import AppError


def config(**fields):
    return yaml.safe_dump(
        {"apiVersion": "kustomize.config.k8s.io/v1beta1", "kind": "Kustomization", **fields}
    ).encode()


def test_local_builtin_dependency_paths_are_enumerated_without_scanning_data():
    raw = config(
        resources=["../base", "one.yaml"],
        bases=["legacy"],
        components=["component"],
        configurations=["names.yaml"],
        crds=["schema.json"],
        patches=[{"path": "patch.yaml"}, {"patch": "secret-inline-sentinel"}],
        patchesJson6902=[{"path": "json.patch"}],
        patchesStrategicMerge=["strategic.yaml"],
        replacements=[{"path": "replacement.yaml"}, {"source": {"name": "data"}}],
        openapi={"path": "openapi.json"},
        configMapGenerator=[
            {
                "name": "settings",
                "files": ["key=content.txt"],
                "envs": ["values.env"],
                "literals": ["TOKEN=literal-sentinel"],
            }
        ],
        secretGenerator=[{"name": "secret", "files": ["secret.txt"]}],
        images=[{"name": "registry.example/image", "newTag": "v2"}],
        namespace="owned",
        namePrefix="prefix-",
        nameSuffix="-suffix",
    )
    references = kustomize_references(raw)
    assert [(ref.path, ref.role) for ref in references] == [
        ("../base", "resource"),
        ("one.yaml", "resource"),
        ("legacy", "resource"),
        ("component", "component"),
        ("names.yaml", "file"),
        ("schema.json", "file"),
        ("strategic.yaml", "file"),
        ("patch.yaml", "file"),
        ("json.patch", "file"),
        ("replacement.yaml", "file"),
        ("content.txt", "file"),
        ("values.env", "file"),
        ("secret.txt", "file"),
        ("openapi.json", "file"),
    ]
    assert "literal-sentinel" not in repr(references) and "secret-inline-sentinel" not in repr(
        references
    )
    assert kustomize_references(b"resources: []") == ()
    assert (
        kustomize_references(
            config(kind="Component", apiVersion="kustomize.config.k8s.io/v1alpha1")
        )
        == ()
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"resources": ["https://example.invalid/base"]},
        {"resources": ["github.com/team/repo/base"]},
        {"resources": ["git::repo"]},
        {"openapi": {"path": "https://example.invalid/openapi"}},
        {"generators": ["external.yaml"]},
        {"transformers": []},
        {"validators": []},
        {"helmCharts": []},
        {"helmGlobals": {}},
        {"unrecognizedFeature": {}},
        {"patchesStrategicMerge": ["kind: Deployment\nspec: {}"]},
        {"patches": ["invalid"]},
        {"resources": "not-a-list"},
        {"resources": [1]},
        {"configMapGenerator": [{"name": "test", "envs": [1]}]},
        {"secretGenerator": [{"name": "test", "files": ["key=https://example.invalid"]}]},
        {"configMapGenerator": [{"name": "test", "unknown": "remote"}]},
        {"openapi": {"unknown": "remote"}},
        {"openapi": []},
        {"namePrefix": 1},
        {"kind": "Deployment"},
        {"apiVersion": "unsupported/v1"},
    ],
)
def test_external_execution_remote_syntax_and_unknown_shapes_fail_closed(fields):
    with pytest.raises(AppError):
        kustomize_references(config(**fields))


@pytest.mark.parametrize("data", [b"# empty", b"x: 1\n---\nx: 2", b"x: !!python/object:unsafe {}"])
def test_invalid_configuration_never_returns_dependencies(data):
    with pytest.raises(AppError):
        kustomize_references(data)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "/absolute",
        "~/.config",
        "-option",
        "https://host/base",
        "git@host:repo",
        "host/repo?ref=main",
        "base#ref",
        "*.yaml",
        "a[0]",
        "a{b}",
        "a\\b",
        "a//b",
        "github.com/owner/repo",
        "../escape",
        "a\ncontrol",
    ],
)
def test_local_reference_rejects_remote_options_globs_controls_and_escape(value):
    with pytest.raises(AppError):
        local_reference("", value)


def test_local_normalization_parent_boundary_and_depth():
    assert local_reference("overlays/dev", "../../base") == "base"
    assert local_reference("", ".") == ""
    assert local_reference("base", "./nested/../one.yaml") == "base/one.yaml"
    for parent, value in [
        ("../wrong", "one"),
        ("/absolute", "one"),
        ("a\\b", "one"),
        ("", "/".join(["x"] * 33)),
    ]:
        with pytest.raises(AppError):
            local_reference(parent, value)


def test_renderer_argv_cannot_enable_network_plugins_helm_or_ambient_config(tmp_path):
    argv = kustomize_argv(
        "/usr/bin/kubectl", tmp_path / "target", tmp_path / "empty-config", tmp_path / "cache"
    )
    assert argv == (
        "/usr/bin/kubectl",
        f"--kubeconfig={tmp_path / 'empty-config'}",
        f"--cache-dir={tmp_path / 'cache'}",
        "kustomize",
        str(tmp_path / "target"),
        "--load-restrictor=LoadRestrictionsRootOnly",
        "--enable-alpha-plugins=false",
        "--enable-helm=false",
        "--network=false",
    )
    with pytest.raises(AppError):
        kustomize_argv("kubectl", tmp_path, Path("relative"), tmp_path)


def test_builtin_openapi_version_without_path_is_not_a_dependency():
    assert kustomize_references(config(openapi={"version": "v1.21.2"})) == ()
