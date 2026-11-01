"""CLI/TTY ownership decisions; the real UI and PTY are separately qualified."""

import io
import json
import logging
import sys
from pathlib import Path

import pytest

from kuberich.config.navigation import NavigationPreferences
from kuberich.config.schema import Settings
from kuberich.diagnostics import reports
from kuberich.errors import AppError
from kuberich.ui import launch


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.mark.parametrize("stdin_tty,stdout_tty", [(False, True), (True, False)])
def test_both_streams_must_belong_to_an_interactive_terminal(
    monkeypatch: pytest.MonkeyPatch, stdin_tty: bool, stdout_tty: bool
) -> None:
    monkeypatch.setattr(sys, "stdin", _Terminal() if stdin_tty else io.StringIO())
    monkeypatch.setattr(sys, "stdout", _Terminal() if stdout_tty else io.StringIO())
    with pytest.raises(AppError, match="interactive terminal"):
        launch.run_terminal(Settings(), logging.Logger("fixture"))


@pytest.mark.parametrize("result", [0, 1, 129, 143])
def test_terminal_return_code_is_propagated_safely(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, result: int
) -> None:
    class _App:
        return_code = result
        navigation = NavigationPreferences()

        def __init__(self, settings: Settings, logger: logging.Logger, **kwargs: object) -> None:
            assert settings.theme == "k9s"

        def run(self, *, mouse: bool) -> None:
            assert mouse is False

    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr(sys, "stdout", _Terminal())
    monkeypatch.setattr(launch, "KubeRichApp", _App)
    monkeypatch.setattr(reports, "user_state_path", lambda *args, **kwargs: tmp_path)
    if result == 129:
        with pytest.raises(AppError, match="Terminal disconnected") as error:
            launch.run_terminal(Settings(), logging.Logger("fixture"))
        assert error.value.code == 129
    elif result == 143:
        with pytest.raises(AppError, match="terminated; terminal restored") as error:
            launch.run_terminal(Settings(), logging.Logger("fixture"))
        assert error.value.code == 143
    elif result:
        with pytest.raises(AppError, match="Terminal interface failed") as error:
            launch.run_terminal(Settings(), logging.Logger("fixture"))
        assert error.value.code == 1
        bundles = list((tmp_path / "reports").glob("*.json"))
        assert len(bundles) == 1
        assert str(bundles[0]) in str(error.value)
        assert json.loads(bundles[0].read_text())["config_check"] == "unavailable"
    else:
        assert launch.run_terminal(Settings(), logging.Logger("fixture")) is None


def test_fatal_launch_exception_reports_after_cleanup_and_report_failure_is_safe(
    monkeypatch, tmp_path
):
    restored = False

    class Broken:
        navigation = NavigationPreferences()

        def __init__(self, *args, **kwargs):
            pass

        def run(self, **kwargs):
            nonlocal restored
            try:
                raise RuntimeError("private-fatal-value")
            finally:
                restored = True

    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr(sys, "stdout", _Terminal())
    monkeypatch.setattr(launch, "KubeRichApp", Broken)
    monkeypatch.setattr(reports, "user_state_path", lambda *args, **kwargs: tmp_path)
    with pytest.raises(AppError, match="Redacted crash report") as error:
        launch.run_terminal(Settings(), logging.Logger("fixture"))
    assert restored and "private-fatal-value" not in str(error.value)
    payload = next((tmp_path / "reports").glob("*.json")).read_text()
    assert "RuntimeError" in payload and "private-fatal-value" not in payload

    def refused(**kwargs):
        assert restored
        raise OSError("private-write-value")

    monkeypatch.setattr(reports, "write_report", refused)
    with pytest.raises(AppError, match="report could not be created") as error:
        launch.run_terminal(Settings(), logging.Logger("fixture"))
    assert error.value.code == 1 and "private-write-value" not in str(error.value)
