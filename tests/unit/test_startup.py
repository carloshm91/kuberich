"""Fresh offline invocations keep validation without loading terminal or SDK code."""

import json
import logging
import subprocess
import sys

import pytest
import yaml
from textual.theme import BUILTIN_THEMES

from kuberich import bootstrap
from kuberich.config.paths import ConfigLocation
from kuberich.config.schema import ConfigDocument, Settings
from kuberich.config.themes import BUILTINS, TEXTUAL_BUILTIN_THEMES
from kuberich.domain.connections import DEFAULT_CONNECTION, ConnectionRequest
from kuberich.services.appearance import PreferenceSource
from kuberich.services.commands import Command
from kuberich.ui import launch
from kuberich.ui.presentation import DEFAULT_PRESENTATION, Presentation
from tests.support.distribution import clean_environment

OFFLINE = r"""
import importlib.abc
import json
import sys
from pathlib import Path

attempts = []
forbidden = set(json.loads(sys.argv[3])) if len(sys.argv) > 3 else set()
class OfflineImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'textual', 'kubernetes_asyncio'} or fullname in forbidden:
            attempts.append(fullname)
            raise AssertionError('Offline command attempted a terminal or SDK import')

sys.meta_path.insert(0, OfflineImports())
try:
    from kuberich.cli import main
    try:
        code = main(json.loads(sys.argv[2]))
    except SystemExit as error:
        code = error.code
finally:
    Path(sys.argv[1]).write_text(json.dumps({
        'attempts': attempts,
        'loaded': sorted(name for name in sys.modules
                         if name.split('.')[0] in {'textual', 'kubernetes_asyncio'}
                         or name in forbidden),
    }))
raise SystemExit(code)
"""


def test_offline_builtin_names_match_the_pinned_public_framework_catalog():
    assert frozenset(BUILTIN_THEMES) == TEXTUAL_BUILTIN_THEMES
    assert frozenset({*BUILTIN_THEMES, "k9s", "kuberich-mono"}) == BUILTINS


@pytest.mark.parametrize("explicit", [False, True])
def test_lazy_bootstrap_preserves_captured_launch_arguments(tmp_path, monkeypatch, explicit):
    captured = []

    def terminal(settings, logger, **kwargs):
        captured.append((settings, logger, kwargs))

    monkeypatch.setattr(launch, "run_terminal", terminal)
    settings = Settings()
    logger = logging.Logger("owned-startup")
    if explicit:
        presentation = Presentation(True, True, True, True)
        connection = ConnectionRequest(context="owned-startup")
        preferences = PreferenceSource(
            ConfigLocation(tmp_path / "preferences", True), ConfigDocument()
        )
        bootstrap.run_terminal(
            settings,
            logger,
            presentation=presentation,
            initial_command=Command.CONTEXTS,
            connection=connection,
            preferences=preferences,
        )
    else:
        presentation, connection, preferences = DEFAULT_PRESENTATION, DEFAULT_CONNECTION, None
        bootstrap.run_terminal(settings, logger)
    actual_settings, actual_logger, arguments = captured.pop()
    assert actual_settings is settings and actual_logger is logger
    assert arguments["presentation"] is presentation
    assert arguments["connection"] is connection
    assert arguments["preferences"] is preferences
    assert arguments["initial_command"] is (Command.CONTEXTS if explicit else Command.EMPTY)
    assert captured == []


@pytest.mark.parametrize(
    "arguments",
    [
        ["--version"],
        ["--help"],
        ["help"],
        ["version"],
        ["version", "--short"],
        ["info"],
        ["config", "check"],
    ],
)
def test_offline_commands_never_attempt_terminal_or_sdk_imports(tmp_path, arguments):
    path = tmp_path / "preferences.yaml"
    path.write_text("schema_version: 1\n")
    report = tmp_path / "imports.json"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            OFFLINE,
            str(report),
            json.dumps(arguments),
            json.dumps(
                [
                    "logging",
                    "kuberich.domain.connections",
                    "kuberich.domain.connection_overrides",
                    "kuberich.domain.targets",
                ]
            ),
        ],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(report.read_text()) == {"attempts": [], "loaded": []}
    assert path.read_text() == "schema_version: 1\n"


@pytest.mark.parametrize(
    "preferences,code,message",
    [
        ({"theme": "nord"}, 0, "preferences are valid"),
        *(
            ({section: {}}, 0, "preferences are valid")
            for section in ("navigation", "forwarding", "jumps", "context_settings")
        ),
        ({"plugins": {"schema_version": 1}}, 0, "preferences are valid"),
        ({"plugins": {}}, 2, "plugins.schema_version"),
        ({"navigation": [], "forwarding": [], "jumps": []}, 2, "navigation accepts"),
        ({"navigation": {}, "forwarding": [], "jumps": []}, 2, "forwarding accepts"),
        (
            {
                "navigation": {},
                "forwarding": {},
                "jumps": {},
                "context_settings": {},
                "plugins": {"schema_version": 1},
            },
            0,
            "preferences are valid",
        ),
        *(
            (
                {
                    "navigation": {},
                    "forwarding": {},
                    "jumps": {},
                    "context_settings": {},
                    "plugins": {"schema_version": 1},
                    section: [],
                },
                2,
                message,
            )
            for section, message in (
                ("navigation", "navigation accepts"),
                ("forwarding", "forwarding accepts"),
                ("jumps", "jumps accepts"),
                ("context_settings", "context_settings must contain"),
                ("plugins", "plugins accepts"),
            )
        ),
        (
            {
                "navigation": {},
                "plugins": {
                    "schema_version": 1,
                    "contexts": {"owned-context": {"locations": ["missing-scoped-plugin.yaml"]}},
                },
            },
            2,
            "Cannot load configured plugin file",
        ),
        (
            {
                "navigation": {"schema_version": 1, "keys": {"resources": {"down": "a"}}},
                "plugins": {
                    "schema_version": 1,
                    "contexts": {
                        "owned-context": {
                            "commands": {
                                "inspect": {
                                    "command": "never-executed",
                                    "shortcut": "a",
                                    "scopes": ["v1/pods"],
                                }
                            }
                        }
                    },
                },
            },
            2,
            "Plugin shortcut requires override",
        ),
        (
            {
                "theme": "ocean",
                "appearance": {
                    "themes": {
                        "ocean": {
                            "primary": "#5fd7ff",
                            "foreground": "#ffffff",
                            "background": "#000000",
                        }
                    }
                },
            },
            0,
            "preferences are valid",
        ),
        ({"theme": "missing-theme"}, 2, "Selected theme is unavailable"),
        ({"appearance": {"contexts": {"owned-startup": "missing-theme"}}}, 2, "unavailable theme"),
        (
            {
                "appearance": {
                    "themes": {
                        "ocean": {
                            "primary": "#ffffff",
                            "foreground": "#111111",
                            "background": "#000000",
                        }
                    }
                }
            },
            2,
            "contrast",
        ),
        (
            {"plugins": {"schema_version": 1, "locations": ["missing-plugin.yaml"]}},
            2,
            "Cannot load configured plugin file",
        ),
    ],
)
def test_offline_config_check_preserves_theme_and_plugin_validation(
    tmp_path, preferences, code, message
):
    path = tmp_path / "preferences.yaml"
    original = yaml.safe_dump({"schema_version": 1, **preferences})
    path.write_text(original)
    report = tmp_path / "imports.json"
    result = subprocess.run(
        [sys.executable, "-c", OFFLINE, str(report), '["config", "check"]'],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == code, result.stdout + result.stderr
    assert message in result.stdout + result.stderr
    assert json.loads(report.read_text()) == {"attempts": [], "loaded": []}
    assert path.read_text() == original


@pytest.mark.parametrize(
    "section", ["navigation", "forwarding", "jumps", "context_settings", "plugins"]
)
@pytest.mark.parametrize("value", [{}, [], None, False])
def test_configured_extensions_always_validate_even_when_empty_or_false(
    tmp_path, monkeypatch, capsys, section, value
):
    from kuberich.cli import main

    path = tmp_path / "preferences.yaml"
    original = yaml.safe_dump({"schema_version": 1, section: value})
    path.write_text(original)
    monkeypatch.setenv("KUBERICH_CONFIG", str(path))
    code = main(["config", "check"])
    output = capsys.readouterr()
    if value == {} and section != "plugins":
        assert code == 0 and "preferences are valid" in output.out and output.err == ""
    else:
        assert code == 2 and output.out == "" and "kuberich:" in output.err
    assert path.read_text() == original


@pytest.mark.parametrize("configured_navigation", [False, True])
def test_config_check_reads_global_and_every_context_plugin_layer_without_executing(
    tmp_path, configured_navigation
):
    from kuberich.config.store import read_config
    from kuberich.errors import AppError
    from kuberich.ui.config_check import validate_preferences

    plugin_file = tmp_path / "context-plugin.yaml"
    definition = {"command": "never-executed", "shortcut": "a", "scopes": ["v1/pods"]}
    if configured_navigation:
        definition["override"] = True
    plugin_file.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "plugins": {"schema_version": 1, "commands": {"inspect": definition}},
            }
        )
    )
    preferences = {
        "schema_version": 1,
        "forwarding": {},
        "jumps": {},
        "context_settings": {},
        "plugins": {
            "schema_version": 1,
            "commands": {"global-inspect": {"command": "never-executed"}},
            "contexts": {
                "unused-context": {"locations": [plugin_file.name]},
                "another-context": {},
            },
        },
    }
    if configured_navigation:
        preferences["navigation"] = {"schema_version": 1, "keys": {"resources": {"down": "a"}}}
    path = tmp_path / "preferences.yaml"
    path.write_text(yaml.safe_dump(preferences))
    document = read_config(path)
    location = ConfigLocation(path, True)
    validate_preferences(document, location, document.settings)
    # Even an unselected context must be validated rather than hidden by the
    # effective/global layer. No configured command is ever invoked.
    plugin_file.unlink()
    with pytest.raises(AppError, match="Cannot load configured plugin file"):
        validate_preferences(document, location, document.settings)


def test_existing_help_screen_import_resolves_to_the_canonical_type():
    from kuberich.ui import app
    from kuberich.ui.app import HelpScreen
    from kuberich.ui.help import HelpScreen as CanonicalHelpScreen

    assert HelpScreen is CanonicalHelpScreen
    with pytest.raises(AttributeError, match="no attribute 'missing_public_view'"):
        assert app.missing_public_view
