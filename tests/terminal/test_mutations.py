"""Actual keyboard confirmation and restored terminal modes against an owned write API."""

import sys

from tests.support.mutation_terminal import terminal_mutation


def test_actual_terminal_explicit_confirmation(tmp_path):
    terminal_mutation([sys.executable, "-m", "kuberich"], tmp_path, "mutations")
