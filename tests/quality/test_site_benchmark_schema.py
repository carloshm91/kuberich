"""Benchmark reference fields follow real global/context parser declarations."""

from scripts.build_site import ROOT
from scripts.site_schema import fields
from tests.support.site_source import copy_source


def test_benchmark_schema_uses_real_root_and_per_context_load_fields():
    paths = {item["path"] for item in fields(ROOT) if item["path"].startswith("benchmarks.")}
    assert paths == {"benchmarks.schema_version", "benchmarks.defaults", "benchmarks.contexts"} | {
        f"benchmarks.{scope}.{key}"
        for scope in ("defaults", "contexts.NAME")
        for key in (
            "executable",
            "load",
            "load.rate",
            "load.concurrency",
            "load.duration_seconds",
            "load.timeout_seconds",
        )
    }
    assert all("body" not in path and "headers" not in path for path in paths)


def test_reference_tracks_a_parser_field_change_for_global_and_context_settings(tmp_path):
    source = copy_source(tmp_path / "source")
    parser = source / "src/kuberich/config/benchmarks.py"
    before = parser.read_text()
    assert '"timeout_seconds"' in before
    parser.write_text(before.replace('"timeout_seconds"', '"future_timeout"'))
    paths = {item["path"] for item in fields(source)}
    for scope in ("defaults", "contexts.NAME"):
        assert f"benchmarks.{scope}.load.future_timeout" in paths
        assert f"benchmarks.{scope}.load.timeout_seconds" not in paths
