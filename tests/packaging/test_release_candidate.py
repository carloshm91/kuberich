"""Actual qualified package bytes survive local release preparation unchanged."""

import json
import shutil
import sys

import pytest

from scripts import release
from scripts.check_supply_chain import INPUT_FILES, generate, write_json
from scripts.release import metadata, prepare, verify_bundle
from scripts.supply_chain import digest
from tests.support.distribution import PROJECT, ROOT, run
from tests.support.release_server import release_server


@pytest.fixture(scope="session")
def release_candidate(security_evidence, tmp_path_factory):
    security, distribution = security_evidence
    directory = tmp_path_factory.mktemp("release-candidate")
    source = directory / "qualified"
    shutil.copytree(distribution, source / "dist")
    shutil.copytree(security, source / "artifacts/security")
    sha = json.loads((security / "provenance.json").read_text())["source_commit"]
    output = directory / "bundle"
    manifest = prepare(source, output, sha, PROJECT["version"], candidate=True)
    assert manifest["candidate_only"] and manifest["tag"] is None
    return output, sha


def test_real_artifacts_and_sidecars_are_preserved_in_an_exclusive_candidate(
    release_candidate, tmp_path
):
    bundle, sha = release_candidate
    manifest = verify_bundle(bundle, sha, PROJECT["version"], candidate=True)
    assert len(manifest["files"]) == 12
    for name, value in manifest["files"].items():
        assert digest(bundle / name) == value
    result = run(
        [
            sys.executable,
            "-m",
            "scripts.release",
            "verify",
            "--candidate",
            "--bundle",
            str(bundle),
            "--commit",
            sha,
            "--version",
            PROJECT["version"],
        ],
        tmp_path,
        environment={"PYTHONPATH": str(ROOT)},
    )
    assert json.loads(result.stdout) == {"candidate_only": True, "verified": True}
    with pytest.raises(ValueError):
        verify_bundle(bundle, sha, PROJECT["version"], candidate=False)
    with pytest.raises(FileExistsError):
        prepare(bundle, bundle, sha, PROJECT["version"], candidate=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "artifact",
        "artifact_rehashed",
        "extra",
        "checksum",
        "symlink",
        "source",
        "version",
        "candidate",
        "notice",
    ],
)
def test_altered_release_bundle_cannot_pass_verification(release_candidate, tmp_path, mutation):
    original, sha = release_candidate
    bundle = tmp_path / "bundle"
    shutil.copytree(original, bundle)
    manifest = json.loads((bundle / "release.json").read_text())
    wheel = next((bundle / "dist").glob("*.whl"))
    if mutation.startswith("artifact"):
        wheel.write_bytes(wheel.read_bytes() + b"changed")
        if mutation == "artifact_rehashed":
            manifest["files"][wheel.relative_to(bundle).as_posix()] = digest(wheel)
            write_json(bundle / "release.json", manifest)
            expected = {**manifest["files"], "release.json": digest(bundle / "release.json")}
            (bundle / "SHA256SUMS").write_text(
                "".join(f"{value}  {name}\n" for name, value in sorted(expected.items()))
            )
    elif mutation == "extra":
        (bundle / "unreviewed.txt").write_text("extra")
    elif mutation == "checksum":
        (bundle / "SHA256SUMS").write_text("incorrect")
    elif mutation == "symlink":
        wheel.rename(tmp_path / "outside.whl")
        wheel.symlink_to(tmp_path / "outside.whl")
    elif mutation in {"source", "version", "candidate"}:
        key = {"source": "commit", "version": "version", "candidate": "candidate_only"}[mutation]
        manifest[key] = {"source": "d" * 40, "version": "0.0.1", "candidate": False}[mutation]
        write_json(bundle / "release.json", manifest)
    else:
        (bundle / "artifacts/security/locked-NOTICES.txt").write_text("rewritten notice")
    with pytest.raises(ValueError):
        verify_bundle(bundle, sha, PROJECT["version"], candidate=True)


@pytest.mark.parametrize("operation", ["tag", "pypi-missing", "github-assets", "preflight"])
def test_candidate_cli_cannot_reach_publication_or_tag_operations(tmp_path, operation):
    result = run(
        [
            sys.executable,
            "-m",
            "scripts.release",
            operation,
            "--candidate",
            "--commit",
            "a" * 40,
            "--version",
            PROJECT["version"],
        ],
        tmp_path,
        check=False,
        environment={"PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 1 and "Local candidates cannot publish" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_actual_artifact_names_and_metadata_reject_wrong_version(artifacts, tmp_path):
    for path in artifacts:
        shutil.copyfile(path, tmp_path / path.name)
    metadata(tmp_path, PROJECT["version"])
    with pytest.raises(ValueError):
        metadata(tmp_path, "0.0.1")


def test_partial_pypi_staging_preserves_the_exact_missing_file_bytes(
    artifacts, tmp_path, monkeypatch
):
    bundle = tmp_path / "bundle"
    (bundle / "dist").mkdir(parents=True)
    expected = {}
    for path in artifacts:
        name = path.name.replace(PROJECT["version"], "0.0.1")
        shutil.copyfile(path, bundle / "dist" / name)
        expected[name] = digest(path)
    with release_server(tmp_path / "service") as server:
        names = sorted(expected)
        value = {
            "info": {"name": "kubetrol", "version": "0.0.1"},
            "urls": [
                {"filename": names[0], "digests": {"sha256": expected[names[0]]}, "yanked": False}
            ],
        }
        server.reads["/pypi/kubetrol/0.0.1/json"] = value
        real_request = release.request

        def local_request(url):
            assert url == "https://test.pypi.org/pypi/kubetrol/0.0.1/json"
            return real_request(server.url + "pypi/kubetrol/0.0.1/json")

        monkeypatch.setattr(release, "request", local_request)
        output = tmp_path / "missing"
        assert release.pypi_remaining(bundle, "0.0.1", "testpypi", output) == [names[1]]
        assert digest(output / names[1]) == expected[names[1]]
        assert server.posts == []
        value["urls"][0]["digests"]["sha256"] = "f" * 64
        with pytest.raises(ValueError):
            release.pypi_remaining(bundle, "0.0.1", "testpypi", tmp_path / "bad")
        assert not (tmp_path / "bad").exists()


def test_actual_canonical_rc_build_audit_bundle_and_installed_version(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    files = {
        *INPUT_FILES,
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        ".gitignore",
        "scripts/__init__.py",
    }
    for name in files:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, path)
    project = source / "pyproject.toml"
    project.write_text(
        project.read_text().replace(f'version = "{PROJECT["version"]}"', 'version = "0.0.1rc1"', 1)
    )
    lock = source / "uv.lock"
    entry = f'name = "kubetrol"\nversion = "{PROJECT["version"]}"'
    assert lock.read_text().count(entry) == 1
    lock.write_text(lock.read_text().replace(entry, 'name = "kubetrol"\nversion = "0.0.1rc1"', 1))
    checked = run(
        ["uv", "lock", "--locked", "--offline", "--python", sys.executable], source, 60, check=False
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    run(["git", "init", "--initial-branch=main"], source)
    run(["git", "add", "src", *sorted(files)], source)
    run(
        [
            "git",
            "-c",
            "user.name=Release Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-s",
            "-m",
            "test: owned unpublished release candidate",
        ],
        source,
    )
    sha = run(["git", "rev-parse", "HEAD"], source).stdout.strip()
    run(["uv", "build", "--python", sys.executable], source, 120)
    generate(source / "artifacts/security", source / "dist", root=source)
    bundle = tmp_path / "release-candidate"
    prepared = prepare(source, bundle, sha, "0.0.1rc1", root=source)
    assert prepared["tag"] == "v0.0.1-rc.1" and prepared["candidate_only"] is False
    verify_bundle(bundle, sha, "0.0.1rc1", root=source)
    outside = tmp_path / "outside"
    outside.mkdir()
    installed = tmp_path / "installed"
    run(["uv", "venv", "--python", sys.executable, str(installed)], outside, 60)
    wheel = next((bundle / "dist").glob("*.whl"))
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(installed / "bin/python"),
            "--only-binary",
            ":all:",
            str(wheel),
        ],
        outside,
        120,
    )
    assert (
        run([str(installed / "bin/kubetrol"), "--version"], outside).stdout == "kubetrol 0.0.1rc1\n"
    )
    result = run([str(installed / "bin/kubetrol"), "--help"], outside)
    assert "--context" in result.stdout and "--readonly" in result.stdout
    manifest = json.loads((bundle / "release.json").read_text())
    assert all(digest(bundle / name) == value for name, value in manifest["files"].items())
    project.write_text(project.read_text() + "\n# dirty release input\n")
    with pytest.raises(ValueError, match="clean committed"):
        verify_bundle(bundle, sha, "0.0.1rc1", root=source)
    retained = ROOT / "artifacts/releases"
    retained.mkdir(parents=True, exist_ok=True)
    write_json(
        retained / "local-rc.json",
        {
            "version": "0.0.1rc1",
            "commit": sha,
            "artifacts": {path.name: digest(path) for path in (bundle / "dist").iterdir()},
            "installed_outside_checkout": True,
            "publications": 0,
            "index": "local fixture",
        },
    )
