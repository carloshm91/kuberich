"""CLI/TTY ownership decisions; the real UI and PTY are separately qualified."""

import io
import logging
import sys

import pytest

from kuberich.config.schema import Settings
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
    monkeypatch: pytest.MonkeyPatch, result: int
) -> None:
    class _App:
        return_code = result

        def __init__(self, settings: Settings, logger: logging.Logger, **kwargs: object) -> None:
            assert settings.theme == "k9s"

        def run(self) -> None:
            pass

    monkeypatch.setattr(sys, "stdin", _Terminal())
    monkeypatch.setattr(sys, "stdout", _Terminal())
    monkeypatch.setattr(launch, "KubeRichApp", _App)
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
    else:
        assert launch.run_terminal(Settings(), logging.Logger("fixture")) is None
