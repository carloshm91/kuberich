"""Real terminal start/list/stop/resize/exit and restored terminal modes."""

import sys

from tests.support.forward_presets import named_terminal_forward
from tests.support.forward_terminal import terminal_forward


def test_actual_terminal_forward_ownership(tmp_path):
    terminal_forward([sys.executable, "-m", "kuberich"], tmp_path, "port-forwards")


def test_actual_named_forward_annotations_and_terminal_restoration(tmp_path, monkeypatch):
    named_terminal_forward(
        [sys.executable, "-m", "kuberich"], tmp_path, "forward-presets", monkeypatch
    )
