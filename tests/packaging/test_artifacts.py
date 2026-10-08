"""Validate complete payloads, rebuild equivalence and private-file rejection."""

import configparser
import shutil
import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

from tests.support.distribution import PROJECT, ROOT, run


def package_payload(root: Path = ROOT) -> dict[str, bytes]:
    package = root / "src/kuberich"
    return {
        path.relative_to(root / "src").as_posix(): path.read_bytes()
        for path in package.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and (path.suffix in {".py", ".tcss"} or path.name == "py.typed")
    }


def wheel_payload(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names)), "Duplicate wheel members"
        return {name: archive.read(name) for name in names}


def sdist_payload(path: Path) -> dict[str, bytes]:
    expected_root = f"kuberich-{PROJECT['version']}"
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        assert len(members) == len({member.name for member in members})
        output = {}
        for member in members:
            assert member.isfile(), "Source distributions contain regular files only"
            parts = Path(member.name).parts
            assert parts[0] == expected_root and ".." not in parts
            reader = archive.extractfile(member)
            assert reader is not None
            output[Path(*parts[1:]).as_posix()] = reader.read()
        return output


def assert_metadata(payload: bytes) -> None:
    metadata = BytesParser().parsebytes(payload)
    assert metadata["Name"] == PROJECT["name"]
    assert metadata["Version"] == PROJECT["version"]
    assert SpecifierSet(metadata["Requires-Python"]) == SpecifierSet(PROJECT["requires-python"])
    assert metadata["License-Expression"] == "MIT"
    assert metadata.get_all("License-File") == ["LICENSE"]
    assert set(metadata.get_all("Classifier")) == set(PROJECT["classifiers"])
    declared = {
        (canonicalize_name(req.name), str(req.specifier), str(req.marker))
        for value in PROJECT["dependencies"]
        for req in (Requirement(value),)
    }
    actual = {
        (canonicalize_name(req.name), str(req.specifier), str(req.marker))
        for value in metadata.get_all("Requires-Dist", [])
        for req in (Requirement(value),)
    }
    assert actual == declared
    assert set(metadata.get_all("Project-URL")) == {
        f"{name}, {url}" for name, url in PROJECT["urls"].items()
    }
    assert metadata["Description-Content-Type"] == "text/markdown"
    assert payload.split(b"\n\n", 1)[1] == (ROOT / "README.md").read_bytes()


def test_complete_wheel_payload_and_runtime_metadata(artifacts):
    payload = wheel_payload(artifacts[0])
    prefix = f"kuberich-{PROJECT['version']}.dist-info"
    metadata_files = {
        f"{prefix}/{name}"
        for name in ("METADATA", "WHEEL", "RECORD", "entry_points.txt", "licenses/LICENSE")
    }
    package = package_payload()
    assert payload.keys() == package.keys() | metadata_files
    assert {name: payload[name] for name in package} == package
    assert payload[f"{prefix}/licenses/LICENSE"] == (ROOT / "LICENSE").read_bytes()
    assert_metadata(payload[f"{prefix}/METADATA"])
    entries = configparser.ConfigParser()
    entries.read_string(payload[f"{prefix}/entry_points.txt"].decode())
    assert dict(entries["console_scripts"]) == {
        "kuberich": "kuberich.cli:main",
        "kubetrol": "kuberich.cli:main",
    }
    assert list(entries) == ["DEFAULT", "console_scripts"]
    wheel = BytesParser().parsebytes(payload[f"{prefix}/WHEEL"])
    assert wheel["Root-Is-Purelib"] == "true"
    assert wheel.get_all("Tag") == ["py3-none-any"]


def test_complete_sdist_payload_without_development_or_private_files(artifacts):
    payload = sdist_payload(artifacts[1])
    expected = {f"src/{name}": value for name, value in package_payload().items()}
    expected.update(
        {
            name: (ROOT / name).read_bytes()
            for name in ("pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", ".gitignore")
        }
    )
    assert payload.keys() == expected.keys() | {"PKG-INFO"}
    assert {name: payload[name] for name in expected} == expected
    assert_metadata(payload["PKG-INFO"])


def test_sdist_rebuild_produces_identical_wheel_payload(artifacts, tmp_path):
    with tarfile.open(artifacts[1]) as archive:
        archive.extractall(tmp_path, filter="data")
    source = next(tmp_path.glob("kuberich-*"))
    uv = shutil.which("uv")
    assert uv is not None
    output = tmp_path / "rebuilt"
    run([uv, "build", "--python", sys.executable, "--wheel", "--out-dir", str(output)], source)
    rebuilt = next(output.glob("*.whl"))
    assert wheel_payload(rebuilt) == wheel_payload(artifacts[0])


def test_build_rejects_untracked_credentials_caches_and_development_files(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "LICENSE", "CHANGELOG.md", ".gitignore"):
        shutil.copy2(ROOT / name, source / name)
    sentinel = b"synthetic-packaging-private-token"
    for name in (
        "kubeconfig",
        ".env",
        ".git/config",
        "tests/trap.py",
        "scripts/trap.py",
        "tmp/user.log",
        ".venv/cache.py",
        "src/kuberich/credential.key",
        "src/kuberich/kubeconfig.yaml",
        "src/kuberich/.env",
        "src/kuberich/debug.log",
        "src/kuberich/__pycache__/cache.py",
        "src/kuberich/__pycache__/cache.pyc",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sentinel)
    uv = shutil.which("uv")
    assert uv is not None
    output = tmp_path / "built"
    run([uv, "build", "--python", sys.executable, "--out-dir", str(output)], source)
    wheel = wheel_payload(next(output.glob("*.whl")))
    sdist = sdist_payload(next(output.glob("*.tar.gz")))
    assert not any(sentinel in data for data in (*wheel.values(), *sdist.values()))
    assert {name: wheel[name] for name in package_payload(source)} == package_payload(source)
    assert {name: sdist[f"src/{name}"] for name in package_payload(source)} == package_payload(
        source
    )
