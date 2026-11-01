"""Generated owned kubeconfigs preserve precedence, provenance and source bytes."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kuberich.config.catalog import load_catalog, parse_kubeconfig
from kuberich.domain.connections import ConnectionRequest
from kuberich.errors import AppError
from tests.support.properties import NAMES, PROPERTY, VALUES


@PROPERTY
@given(configurations=st.lists(st.dictionaries(NAMES, VALUES, max_size=5), min_size=1, max_size=4))
def test_first_named_entry_wins_without_merging_or_rewriting_source(configurations):
    # The autouse connection guard supplies this test-owned root; every example
    # creates fresh children inside it, rather than reusing a fixture's files.
    owned_root = Path(os.environ["KUBECONFIG"]).parent
    with TemporaryDirectory(prefix="properties-", dir=owned_root) as directory:
        paths, original, expected = [], {}, {}
        current = None
        for index, entries in enumerate(configurations):
            path = Path(directory) / str(index) / "config.json"
            path.parent.mkdir()
            names = sorted(entries)
            document = {
                "contexts": [
                    {"name": name, "context": {"cluster": "owned", "user": name}} for name in names
                ],
                "clusters": [
                    {"name": "owned", "cluster": {"server": f"http://127.0.0.1:{12000 + index}"}}
                ],
                "users": [
                    {"name": name, "user": {"token": "synthetic-" + entries[name]}}
                    for name in names
                ],
            }
            if names:
                document["current-context"] = names[0]
                if current is None:
                    current = names[0]
            path.write_bytes(json.dumps(document).encode())
            path.chmod(0o600)
            paths.append(path)
            original[path] = path.read_bytes()
            for name, value in entries.items():
                expected.setdefault(name, (value, path.parent))
        catalog = load_catalog(
            ConnectionRequest(),
            {"KUBECONFIG": os.pathsep.join(str(path) for path in [*paths, paths[0]])},
        )
        assert catalog.current == current and catalog.names == tuple(sorted(expected))
        for name, (value, source) in expected.items():
            selected = catalog.select(name)
            assert selected.user.data == {"token": "synthetic-" + value}
            assert selected.user.directory == source
            assert selected.cluster.data["server"] == "http://127.0.0.1:12000"
            selected.user.data["token"] = "changed-by-test"
            assert catalog.select(name).user.data["token"] == "synthetic-" + value
        assert all(
            path.read_bytes() == original[path] and path.stat().st_mode & 0o777 == 0o600
            for path in paths
        )


@PROPERTY
@given(key=NAMES, first=VALUES, second=VALUES)
def test_duplicate_yaml_keys_are_rejected_even_when_values_are_identical(key, first, second):
    quoted = json.dumps(key)
    single = f"{quoted}: {json.dumps(first)}\n"
    assert parse_kubeconfig(single.encode()) == {key: first}
    raw = (single + f"{quoted}: {json.dumps(second)}\n").encode()
    with pytest.raises(AppError, match="unique"):
        parse_kubeconfig(raw)


@PROPERTY
@given(value=st.dictionaries(NAMES, VALUES, max_size=8))
def test_alias_free_json_is_valid_yaml_without_changing_strings(value):
    assert parse_kubeconfig(json.dumps(value).encode()) == value
