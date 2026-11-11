"""Offline archive trust boundaries exercised with original malicious packages."""

import gzip
import io
import json
import tarfile

import pytest

from kuberich.domain.helm_archive import chart_crd_files, inspect_chart_package, values_mapping
from kuberich.errors import AppError
from tests.support.helm_catalog import chart_package, dependency_lock


def inspect(package, name="owned-chart", version="1.0.0"):
    return inspect_chart_package(package, expected_name=name, expected_version=version)


def crds(package, name="owned-chart", version="1.0.0"):
    return chart_crd_files(package, expected_name=name, expected_version=version)


def raw_package(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content, kind in entries:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.size = len(content) if kind == tarfile.REGTYPE else 0
            if kind in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
                item.linkname = "/private/escape"
            archive.addfile(item, io.BytesIO(content))
    return output.getvalue()


def test_crd_paths_match_native_extensions_across_compressed_and_directory_subcharts():
    child = chart_package(
        "compressed",
        files={
            "crds/types.JSON": b"synthetic private body",
            "charts/leaf/Chart.yaml": b"apiVersion: v2\nname: leaf\nversion: 1.0.0\n",
            "charts/leaf/crds/.yaml": b"synthetic leaf",
        },
    )
    package = chart_package(
        files={
            "crds/nested/types.YmL": b"synthetic root",
            "crds/README.md": b"not a CRD",
            "crds/.json": b"synthetic dot file",
            "crds/json": b"no manifest extension",
            "templates/crds/rendered.yaml": b"not a skipped CRD file",
            "crds-other/types.yaml": b"not the crds directory",
            "charts/compressed-1.0.0.tgz": child,
            "charts/directory/Chart.yaml": b"apiVersion: v2\nname: directory\nversion: 1.0.0\n",
            "charts/directory/crds/type.yaml": b"synthetic directory",
        }
    )
    assert crds(package) == (
        "owned-chart/charts/compressed/charts/leaf/crds/.yaml",
        "owned-chart/charts/compressed/crds/types.JSON",
        "owned-chart/charts/directory/crds/type.yaml",
        "owned-chart/crds/.json",
        "owned-chart/crds/nested/types.YmL",
    )
    assert crds(chart_package()) == ()


@pytest.mark.parametrize("legacy", ["requirements.yaml", "requirements.lock"])
@pytest.mark.parametrize("location", ["root", "compressed", "directory"])
def test_legacy_native_metadata_overrides_are_refused_at_every_chart_depth(legacy, location):
    files = {legacy: b"dependencies: []\n"}
    if location == "compressed":
        files = {"charts/child.tgz": chart_package("child", files=files)}
    elif location == "directory":
        files = {
            f"charts/child/{legacy}": files[legacy],
            "charts/child/Chart.yaml": b"apiVersion: v2\nname: child\nversion: 1.0.0\n",
        }
    package = chart_package(files=files)
    for inspect_package in (inspect, crds):
        with pytest.raises(AppError):
            inspect_package(package)


def test_crd_inventory_uses_whole_archive_policy_and_shared_nested_budget(monkeypatch):
    child = chart_package("child", files={"crds/child.yaml": b"synthetic child"})
    package = chart_package(files={"charts/child.tgz": child})
    assert crds(package) == ("owned-chart/charts/child/crds/child.yaml",)
    # Each archive fits this real byte budget separately; their expansion together does not.
    assert len(gzip.decompress(package)) <= 15_000
    assert len(gzip.decompress(child)) <= 15_000
    monkeypatch.setattr("kuberich.domain.helm_archive.MAX_EXPANDED_BYTES", 15_000)
    with pytest.raises(AppError):
        crds(package)


def test_crd_inventory_refuses_unsafe_non_crd_content_and_file_budget_overflow():
    package = chart_package(
        files={"values.schema.json": b'{"$ref":"https://trap.invalid/private"}'}
    )
    with pytest.raises(AppError):
        crds(package)
    entries = [(f"owned-chart/crds/{index}.yaml", b"", tarfile.REGTYPE) for index in range(2001)]
    with pytest.raises(AppError):
        crds(raw_package(entries))
    with pytest.raises(AppError):
        crds(chart_package(), name="other")


@pytest.mark.parametrize(
    "data",
    [
        None,
        b"",
        b"- sequence\n",
        b"value: .inf\n",
        b"value: 1\nvalue: 2\n",
        b"value: &alias [*alias]\n",
        b"value: !!python/object:private {}\n",
        b"\xff",
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_values_are_one_bounded_json_compatible_mapping_without_source_errors(data):
    with pytest.raises(AppError) as error:
        values_mapping(data)
    assert "!!python" not in str(error.value)


def test_valid_schema_fragments_and_known_offline_metaschemas_are_accepted():
    for schema in (
        True,
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$defs": {"message": {"type": "string"}},
            "properties": {"message": {"$ref": "#/$defs/message"}},
            "$id": "",
        },
        {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "allOf": [{"$recursiveRef": "#"}, {"$dynamicRef": "#local"}],
        },
    ):
        assert inspect(
            chart_package(files={"values.schema.json": json.dumps(schema).encode()})
        ).startswith(b"message:")
    assert values_mapping(b"{}\n") == {}
    assert inspect(chart_package(files={"values.yaml": b"{}\n"})) == b"{}\n"


@pytest.mark.parametrize(
    "schema",
    [
        [],
        "schema",
        {"$ref": "https://trap.invalid/schema"},
        {"$ref": "file:///private/schema.json"},
        {"$ref": "urn:unresolved:silently-true"},
        {"$dynamicRef": "external.json#local"},
        {"$recursiveRef": 1},
        {"$id": "https://trap.invalid/base"},
        {"$schema": "https://trap.invalid/meta"},
        {"$schema": 1},
        {"$vocabulary": {}},
        {"properties": {"nested": {"$id": "file:///private"}}},
        {"allOf": [{"$ref": "../escape"}]},
        {"maximum": float("inf")},
    ],
)
def test_schema_policy_blocks_external_loaders_and_unresolved_urn_fallback(schema):
    with pytest.raises(AppError):
        inspect(chart_package(files={"values.schema.json": json.dumps(schema).encode()}))


@pytest.mark.parametrize(
    "data", [b'{"type":"string","type":"object"}', b"{", b"\xff", b" " * (1024 * 1024 + 1)]
)
def test_schema_parse_is_bounded_and_never_exposes_parser_source(data):
    with pytest.raises(AppError):
        inspect(chart_package(files={"values.schema.json": data}))


@pytest.mark.parametrize(
    "metadata",
    [
        {"apiVersion": "v1"},
        {"type": "other"},
        {"type": []},
        {"type": "library"},
        {"name": None},
        {"version": None},
        {"dependencies": {}},
        {"dependencies": [None]},
        {"dependencies": [{"name": "absent", "version": "1.0.0"}]},
        {"dependencies": [{"name": "absent", "version": 1}]},
        {"dependencies": [{"name": "absent", "version": "1.0.0", "unknown": "data"}]},
    ],
)
def test_chart_metadata_and_missing_dependencies_cannot_reach_native_helm(metadata):
    with pytest.raises(AppError):
        inspect(chart_package(metadata=metadata))


def test_bundled_dependency_and_lock_match_exact_original_bytes():
    declarations = [
        {"name": "owned-library", "version": "^1.0.0", "repository": "https://charts.invalid"}
    ]
    locked = [{"name": "owned-library", "version": "1.2.3", "repository": "https://charts.invalid"}]
    child = chart_package("owned-library", "1.2.3", metadata={"type": "library"})
    package = chart_package(
        metadata={"dependencies": declarations},
        files={
            "charts/owned-library-1.2.3.tgz": child,
            "Chart.lock": dependency_lock(declarations, locked),
        },
    )
    assert inspect(package).startswith(b"message:")
    for files in (
        {"charts/owned-library-1.2.3.tgz": child},
        {"charts/owned-library-1.2.3.tgz": child, "Chart.lock": b"dependencies: []\n"},
        {
            "charts/owned-library-1.2.3.tgz": child,
            "Chart.lock": dependency_lock(declarations, [{**locked[0], "version": "2.0.0"}]),
        },
        {"charts/owned-library-1.2.3.tgz": child, "Chart.lock": b"dependencies: invalid\n"},
    ):
        with pytest.raises(AppError):
            inspect(chart_package(metadata={"dependencies": declarations}, files=files))
    changed = child + b"broken"
    with pytest.raises(AppError):
        inspect(
            chart_package(
                metadata={"dependencies": [{**declarations[0], "version": "2.0.0"}]},
                files={"charts/owned-library-1.2.3.tgz": changed},
            )
        )


def test_unpacked_nested_schema_is_checked_and_ambiguous_children_refused():
    child_metadata = b"apiVersion: v2\nname: nested\nversion: 1.0.0\ntype: library\n"
    assert inspect(chart_package(files={"charts/nested/Chart.yaml": child_metadata})).startswith(
        b"message:"
    )
    for files in (
        {
            "charts/nested/Chart.yaml": child_metadata,
            "charts/nested/values.schema.json": b'{"$ref":"https://trap.invalid"}',
        },
        {"charts/other/Chart.yaml": child_metadata},
        {"charts/nested/Chart.yaml": child_metadata, "charts/nested.tgz": chart_package("nested")},
        {"charts/plain-file": b"unsupported"},
        {"Chart.lock": b"dependencies: []\n"},
    ):
        with pytest.raises(AppError):
            inspect(chart_package(files=files))


@pytest.mark.parametrize(
    "path,kind",
    [
        ("/absolute", tarfile.REGTYPE),
        ("owned-chart/../escape", tarfile.REGTYPE),
        ("owned-chart/./escape", tarfile.REGTYPE),
        ("owned-chart//escape", tarfile.REGTYPE),
        ("owned-chart/\\escape", tarfile.REGTYPE),
        ("owned-chart/line\nbreak", tarfile.REGTYPE),
        ("single", tarfile.REGTYPE),
        ("owned-chart/link", tarfile.SYMTYPE),
        ("owned-chart/hard", tarfile.LNKTYPE),
        ("owned-chart/device", tarfile.CHRTYPE),
        ("owned-chart/fifo", tarfile.FIFOTYPE),
    ],
)
def test_archive_never_extracts_unsafe_paths_links_or_special_files(path, kind):
    with pytest.raises(AppError):
        inspect(raw_package([(path, b"untrusted", kind)]))


def test_archive_rejects_duplicate_paths_roots_truncation_and_nonpackages():
    for package in (
        None,
        b"",
        b"not gzip",
        gzip.compress(b"not tar"),
        chart_package()[:-15],
        raw_package(
            [
                ("owned-chart/a", b"first", tarfile.REGTYPE),
                ("owned-chart/a", b"second", tarfile.REGTYPE),
            ]
        ),
        raw_package(
            [("owned-chart/a", b"first", tarfile.REGTYPE), ("other/b", b"second", tarfile.REGTYPE)]
        ),
        raw_package([("owned-chart", b"", tarfile.DIRTYPE)]),
    ):
        with pytest.raises(AppError):
            inspect(package)
    with pytest.raises(AppError):
        inspect(chart_package(), name="other")
    with pytest.raises(AppError):
        inspect(chart_package(), version="2.0.0")


@pytest.mark.parametrize(
    "constraint",
    [
        "1.2.3",
        "=1.2.3",
        "==1.2.3",
        "!=2.0.0",
        ">1.0.0",
        ">=1.2.3",
        "<2.0.0",
        "<=1.2.3",
        "~1.2.0",
        "^1.0.0",
        "*",
        "x",
        "1.x",
        "1.2.*",
        "1.2",
        "2.x || 1.2.x",
    ],
)
def test_bundled_exact_locks_satisfy_supported_semver_constraints(constraint):
    declarations = [{"name": "dependency", "version": constraint}]
    locked = [{"name": "dependency", "version": "1.2.3"}]
    child = chart_package("dependency", "1.2.3")
    assert inspect(
        chart_package(
            metadata={"dependencies": declarations},
            files={
                "charts/dependency.tgz": child,
                "Chart.lock": dependency_lock(declarations, locked),
            },
        )
    )


@pytest.mark.parametrize(
    "constraint,version", [("^0.1.0", "0.1.3"), ("^0.0.1", "0.0.1"), ("~0.0.1", "0.0.4")]
)
def test_zero_major_dependency_constraints_use_their_actual_compatibility_window(
    constraint, version
):
    declarations = [{"name": "dependency", "version": constraint}]
    locked = [{"name": "dependency", "version": version}]
    child = chart_package("dependency", version)
    assert inspect(
        chart_package(
            metadata={"dependencies": declarations},
            files={
                "charts/dependency.tgz": child,
                "Chart.lock": dependency_lock(declarations, locked),
            },
        )
    )


@pytest.mark.parametrize(
    "constraint",
    [
        "2.0.0",
        ">=2.0.0 <3.0.0",
        "2.x",
        "",
        " || ",
        "1.0.0 || " * 9,
        ">1.0.0 " * 17,
        ">*",
        ">=1.2",
        "invalid",
    ],
)
def test_unresolved_or_unsupported_bundled_constraints_are_not_sent_to_helm(constraint):
    declarations = [{"name": "dependency", "version": constraint}]
    with pytest.raises(AppError):
        inspect(
            chart_package(
                metadata={"dependencies": declarations},
                files={"charts/dependency.tgz": chart_package("dependency", "1.2.3")},
            )
        )


def test_real_parser_node_depth_and_archive_cumulative_budgets():
    nested = True
    for _ in range(66):
        nested = {"allOf": [nested]}
    for schema in (
        nested,
        {"allOf": [True] * 50_001},
        {"x" * 4097: True},
        {"$ref": "#" + "x" * 4097},
    ):
        with pytest.raises(AppError):
            inspect(chart_package(files={"values.schema.json": json.dumps(schema).encode()}))
    entries = [(f"owned-chart/file-{index}", b"", tarfile.REGTYPE) for index in range(2001)]
    with pytest.raises(AppError):
        inspect(raw_package(entries))
    huge = tarfile.TarInfo("owned-chart/huge")
    huge.size = 64 * 1024 * 1024 + 1
    with pytest.raises(AppError):
        inspect(gzip.compress(huge.tobuf() + b"\0" * 1024))
    with pytest.raises(AppError):
        inspect(chart_package(files={"padding": b"\0" * (64 * 1024 * 1024)}))


def test_nested_archive_and_unpacked_directory_depth_share_the_same_limit():
    child = chart_package("level9")
    for level in range(8, -1, -1):
        child = chart_package(f"level{level}", files={f"charts/level{level + 1}.tgz": child})
    with pytest.raises(AppError):
        inspect(child, name="level0")
    files = {}
    prefix = ""
    for level in range(10):
        files[prefix + "Chart.yaml"] = (
            f"apiVersion: v2\nname: level{level}\nversion: 1.0.0\n".encode()
        )
        prefix += f"charts/level{level + 1}/"
    with pytest.raises(AppError):
        inspect(chart_package("level0", files=files), name="level0")


def test_invalid_yaml_lock_duplicates_bundled_identity_and_root_mismatch():
    for content in (b"---\n", b"[", b"one: 1\none: 2\n"):
        with pytest.raises(AppError):
            inspect(chart_package(files={"Chart.yaml": content}))
    child = chart_package("dependency")
    declarations = [{"name": "dependency", "version": "1.0.0"}]
    for metadata, files in (
        ({"dependencies": [dict(declarations[0]), dict(declarations[0])]}, {}),
        ({"dependencies": [{**declarations[0], "repository": 4}]}, {}),
        ({}, {"charts/first.tgz": child, "charts/second.tgz": child}),
        (
            {"dependencies": declarations},
            {
                "charts/dependency.tgz": child,
                "Chart.lock": b"digest: sha256:invalid\ndependencies:\n- name: dependency\n  version: 1.0.0\n",
            },
        ),
    ):
        with pytest.raises(AppError):
            inspect(chart_package(metadata=metadata, files=files))
    metadata = b"apiVersion: v2\nname: owned-chart\nversion: 1.0.0\n"
    with pytest.raises(AppError):
        inspect(raw_package([("different/Chart.yaml", metadata, tarfile.REGTYPE)]))
    assert (
        inspect(
            raw_package(
                [
                    ("owned-chart", b"", tarfile.DIRTYPE),
                    ("owned-chart/Chart.yaml", metadata, tarfile.REGTYPE),
                ]
            )
        )
        == b"{}\n"
    )
    with pytest.raises(AppError):
        inspect(raw_package([("owned-chart/" + "a" * 4097, b"", tarfile.REGTYPE)]))
    # Bytes beyond tar's normal end markers still count against the decompression bound.
    tar = gzip.decompress(chart_package())
    assert inspect(gzip.compress(tar + b"\0" * 20000)).startswith(b"message:")
