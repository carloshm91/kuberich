"""Narrow local-artifact scan budgets preserve the generic default contract."""

import threading

import pytest

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.errors import AppError


def test_custom_scan_budget_reports_overflow_without_adopting_more_entries(tmp_path):
    files = ArtifactFiles()
    for name in ("one", "two", "three"):
        (tmp_path / name).write_text(name)
    root = files.directory(tmp_path, create=False, cancel=threading.Event())
    assert len(files.scan(root, cancel=threading.Event()).refs) == 3
    bounded = files.scan(root, max_entries=2, cancel=threading.Event())
    assert len(bounded.refs) == 2 and bounded.limited
    for value in (True, 0, -1, 2049, 1.0):
        with pytest.raises(AppError):
            files.scan(root, max_entries=value, cancel=threading.Event())
