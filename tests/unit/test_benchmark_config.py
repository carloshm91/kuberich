"""Offline validated global/context defaults never acquire an execution capability."""

from dataclasses import replace
from pathlib import Path

import pytest

from kuberich.config.benchmarks import (
    BenchmarkSettings,
    benchmarks_from,
    parse_benchmark_settings,
    serialize_benchmark_settings,
)
from kuberich.config.schema import ConfigDocument
from kuberich.domain.benchmarks import LoadOptions
from kuberich.errors import AppError


def document(value):
    return replace(ConfigDocument(), extensions={"benchmarks": value})


def test_defaults_and_context_load_merge_without_discovery_or_execution():
    assert benchmarks_from(ConfigDocument()) == BenchmarkSettings()
    raw = {
        "schema_version": 1,
        "defaults": {"executable": "/opt/vegeta", "load": {"rate": 2}},
        "contexts": {"local": {"load": {"concurrency": 3}}, "disabled": {"executable": None}},
    }
    assert benchmarks_from(document(raw), "unknown") == BenchmarkSettings(
        Path("/opt/vegeta"), LoadOptions(rate=2)
    )
    assert benchmarks_from(document(raw), "local").load == LoadOptions(rate=2, concurrency=3)
    assert benchmarks_from(document(raw), "disabled").executable is None
    assert (
        parse_benchmark_settings(serialize_benchmark_settings(BenchmarkSettings()))
        == BenchmarkSettings()
    )
    selected = BenchmarkSettings(Path("/opt/vegeta"), LoadOptions(4, 2, 3, 1))
    assert parse_benchmark_settings(serialize_benchmark_settings(selected)) == selected


@pytest.mark.parametrize(
    "path",
    ["/wrongtype", Path("relative"), Path("/a/../b"), Path("/bad\n"), Path("/" + "a" * 4097)],
)
def test_executable_must_be_explicit_absolute_path(path):
    with pytest.raises(AppError):
        BenchmarkSettings(path)


def test_load_requires_validated_options():
    with pytest.raises(AppError):
        BenchmarkSettings(load={})


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unknown": 1},
        {"executable": 3},
        {"executable": "relative"},
        {"load": []},
        {"load": {"unknown": 1}},
        {"load": {"rate": True}},
    ],
)
def test_settings_refuse_unknown_and_unbounded_fields(value):
    with pytest.raises(AppError):
        parse_benchmark_settings(value)


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        {"unknown": 1},
        {"schema_version": True},
        {"schema_version": 2},
        {"contexts": []},
        {"contexts": {str(i): {} for i in range(129)}},
        {"contexts": {3: {}}},
        {"contexts": {"": {}}},
        {"contexts": {"a" * 254: {}}},
        {"contexts": {"bad\n": {}}},
        {"contexts": {"unselected": {"load": {"rate": 100}}}},
    ],
)
def test_entire_context_document_validated_even_when_context_not_selected(value):
    with pytest.raises(AppError):
        benchmarks_from(document(value), "other")
