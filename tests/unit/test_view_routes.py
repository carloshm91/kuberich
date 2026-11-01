"""Typed routes preserve canonical resource identity and existing display keys."""

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from kuberich.domain.navigation import Viewport
from kuberich.domain.registry import RESOURCE_ALIASES
from kuberich.domain.view_routes import ViewKind, ViewRoute
from kuberich.domain.views import ResourceSelection
from kuberich.errors import AppError


@pytest.mark.parametrize(
    ("route", "kind", "display", "name"),
    [
        (ViewRoute.pods(), ViewKind.PODS, "pods", "pods"),
        (ViewRoute.namespaces(), ViewKind.NAMESPACES, "namespaces", "namespaces"),
        (ViewRoute.contexts(), ViewKind.CONTEXTS, "contexts", None),
        (
            ViewRoute.standard(RESOURCE_ALIASES["deploy"]),
            ViewKind.STANDARD,
            "deployments",
            "deployments",
        ),
        (ViewRoute.standard(RESOURCE_ALIASES["cm"]), ViewKind.STANDARD, "configmaps", "configmaps"),
        (
            ViewRoute.custom(ResourceSelection("widgets", "example.test", "v1beta1", True)),
            ViewKind.CUSTOM,
            "widgets.example.test",
            "widgets",
        ),
        (
            ViewRoute.custom(ResourceSelection("pods", "", "v1", True)),
            ViewKind.CUSTOM,
            "pods.core",
            "pods",
        ),
        (
            ViewRoute.custom(ResourceSelection("contexts", "example.test", "v1", True)),
            ViewKind.CUSTOM,
            "contexts.example.test",
            "contexts",
        ),
    ],
)
def test_route_distinguishes_local_view_and_canonical_api_identity(route, kind, display, name):
    assert route.kind is kind and route.display_key == display and route.resource_name == name
    with pytest.raises(FrozenInstanceError):
        route.kind = ViewKind.CONTEXTS


@pytest.mark.parametrize("kind", [ViewKind.PODS, ViewKind.NAMESPACES])
@pytest.mark.parametrize("version", [None, "v1", "v42"])
def test_builtin_route_preserves_version_request_for_discovery_to_validate(kind, version):
    selection = ResourceSelection(kind.value, version=version)
    route = ViewRoute(kind, selection)
    assert route.selection is selection and route.selection.version == version
    assert route.display_key == kind.value


@pytest.mark.parametrize(
    ("kind", "selection"),
    [
        ("pods", ResourceSelection()),
        (ViewKind.PODS, object()),
        (ViewKind.CONTEXTS, ResourceSelection()),
        (ViewKind.PODS, None),
        (ViewKind.PODS, ResourceSelection(server_columns=True)),
        (ViewKind.CUSTOM, ResourceSelection("widgets")),
        (ViewKind.PODS, ResourceSelection("services")),
        (ViewKind.PODS, ResourceSelection("pods", "example.test")),
        (ViewKind.NAMESPACES, ResourceSelection("pods")),
        (ViewKind.STANDARD, ResourceSelection("pods")),
        (ViewKind.STANDARD, ResourceSelection("namespaces")),
    ],
)
def test_invalid_routing_shapes_are_domain_errors(kind, selection):
    with pytest.raises(AppError):
        ViewRoute(kind, selection)


def test_existing_viewport_import_retains_the_same_frozen_domain_value():
    from kuberich.ui.pods import Viewport as PublicViewport

    assert PublicViewport is Viewport
    original = PublicViewport("owned", 3, 4.0, 5.0, None)
    assert original == Viewport("owned", 3, 4.0, 5.0, None)
    with pytest.raises(FrozenInstanceError):
        original.x = 9.0


@pytest.mark.parametrize("module", ["kuberich.domain.navigation", "kuberich.domain.view_routes"])
def test_navigation_metadata_imports_no_terminal_or_kubernetes_sdk(module):
    program = """
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps([name for name in sys.modules
    if name.startswith(("textual", "kubernetes_asyncio", "kuberich.ui"))]))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, module],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == []


@pytest.mark.parametrize("module", ["kuberich.ui.target_capture", "kuberich.ui.command_routing"])
def test_capture_and_command_ports_import_no_app_terminal_or_kubernetes_sdk(module):
    program = """
import importlib, json, sys
importlib.import_module(sys.argv[1])
print(json.dumps([name for name in sys.modules
    if name.startswith(("textual", "kubernetes_asyncio", "kuberich.ui.app"))]))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", program, module],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert json.loads(result.stdout) == []
