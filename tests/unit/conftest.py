"""Keep every CLI/unit check away from the maintainer's real application files."""

import os
from pathlib import Path

import pytest

from kubetrol.config import paths


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in os.environ:
        if name.startswith("KUBETROL_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(paths, "user_config_path", lambda *args, **kwargs: tmp_path / "config")
    monkeypatch.setattr(paths, "user_log_path", lambda *args, **kwargs: tmp_path / "logs")
