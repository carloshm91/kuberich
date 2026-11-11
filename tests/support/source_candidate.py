"""Owned installation candidates and immutable published Homebrew baselines."""

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from packaging.version import Version

from scripts.build_standalone import source_inputs
from scripts.check_supply_chain import INPUT_FILES, generate
from scripts.homebrew import BOTTLE_BLOCK, FORMULA, bottle_root
from scripts.release import prepare
from tests.support.distribution import PROJECT, ROOT, run

TAP_URL = "https://github.com/kuberich/homebrew-tap"
# Reviewed bottle-only update; the registry separately pins its source formula.
BOTTLE_REVISIONS = {"0.2.0": "a878dbd38d7ae0ac81fd9fcba37b4b104bad641d"}


def published_baseline(
    candidate: str,
    releases: dict[str, dict[str, Any]] | None = None,
    *,
    predecessor: str | None = None,
) -> dict[str, Any]:
    """Select a real stable predecessor, never the candidate's own publication."""
    if releases is None:
        releases = json.loads((ROOT / "docs/published-releases.json").read_text())["releases"]
    versions = [
        Version(version)
        for version in releases
        if not Version(version).is_prerelease
        and not Version(version).is_devrelease
        and Version(version) < Version(candidate)
        and (predecessor is None or version == predecessor)
    ]
    if not versions:
        raise ValueError("No published stable predecessor for this candidate")
    version = str(max(versions))
    return {
        **releases[version],
        "version": version,
        "homebrew_bottle_commit": releases[version].get(
            "homebrew_bottle_commit", BOTTLE_REVISIONS.get(version)
        ),
    }


def published_has_legacy_alias(version: str) -> bool:
    """The published 0.4 transition removed both the shim and console entry."""
    return Version(version) < Version("0.4.0")


def source_upgrade_versions(
    candidate: str, published: dict[str, Any] | None = None
) -> tuple[str, str]:
    if published is not None:
        assert Version(published["version"]) < Version(candidate)
        return published["version"], candidate
    current = Version(candidate)
    return (
        ("0.1.0rc1", "0.1.0rc2")
        if current.is_prerelease
        else (f"{current.base_version}rc1", candidate)
    )


def published_tap(tap: Path, baseline: dict[str, Any], *, bottled: bool = False) -> dict[str, Any]:
    """Check out and bind actual published bytes, never a relabeled candidate."""
    revision = baseline["homebrew_bottle_commit" if bottled else "homebrew_formula_commit"]
    if revision is None:
        raise ValueError("The selected predecessor needs a reviewed immutable bottle revision")
    assert re.fullmatch(r"[0-9a-f]{40}", revision)
    assert re.fullmatch(r"[0-9a-f]{40}", baseline["homebrew_formula_commit"])
    tap.parent.mkdir(parents=True, exist_ok=True)
    if not tap.exists():
        run(["git", "clone", "--quiet", TAP_URL, str(tap)], tap.parent)
    run(["git", "checkout", "--quiet", "-B", "main", revision], tap)
    assert run(["git", "rev-parse", "HEAD"], tap).stdout.strip() == revision
    source = run(["git", "show", f"{baseline['homebrew_formula_commit']}:{FORMULA}"], tap).stdout
    text = (tap / FORMULA).read_text()
    assert text == run(["git", "show", f"{revision}:{FORMULA}"], tap).stdout
    assert text.startswith(
        f"# Source version: {baseline['version']}\n# Source commit: {baseline['source_commit']}\n"
    )
    assert not BOTTLE_BLOCK.search(source)
    assert (BOTTLE_BLOCK.sub("", text, count=1) if bottled else text) == source
    archive = re.search(r'^  url "(https://files\.pythonhosted\.org/[^"\n]+)"$', source, re.M)
    digest = re.search(r'^  sha256 "([0-9a-f]{64})"$', source, re.M)
    assert archive and digest
    assert archive[1].endswith(f"/kuberich-{baseline['version']}.tar.gz")
    bottles = {}
    if bottled:
        block = BOTTLE_BLOCK.search(text)
        assert block and f'root_url "{bottle_root(baseline["version"])}"' in block[0]
        bottles = dict(re.findall(r'\b(\w+):\s+"([0-9a-f]{64})"', block[0]))
        assert bottles
    return {
        **baseline,
        "tap_commit": revision,
        "formula_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_formula_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "sdist_url": archive[1],
        "sdist_sha256": digest[1],
        "bottles": bottles,
    }


def published_bottle_pour(baseline: dict[str, Any], output: str) -> dict[str, str]:
    matches = [
        tag
        for tag in baseline["bottles"]
        if re.search(
            rf"Pouring kuberich--?{re.escape(baseline['version'])}\.{re.escape(tag)}\.bottle\.tar\.gz",
            output,
        )
    ]
    assert len(matches) == 1, "The published baseline must actually pour its pinned bottle"
    assert "Resource kuberich--" not in output and "files.pythonhosted.org" not in output
    tag = matches[0]
    return {"tag": tag, "sha256": baseline["bottles"][tag]}


def source_candidate(directory: Path, version: str) -> tuple[Path, Path, str]:
    source = directory / "source"
    source.mkdir(parents=True)
    files = {
        *source_inputs(ROOT),
        *INPUT_FILES,
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "NOTICE",
        ".gitignore",
        "scripts/__init__.py",
        "scripts/homebrew.py",
        "packaging/homebrew/README.md",
        "packaging/homebrew/.github/workflows/verify.yml",
    }
    for name in files:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    project = source / "pyproject.toml"
    original = project.read_text()
    assert original.count(f'version = "{PROJECT["version"]}"') == 1
    project.write_text(
        original.replace(f'version = "{PROJECT["version"]}"', f'version = "{version}"', 1)
    )
    lock = source / "uv.lock"
    old = f'name = "kuberich"\nversion = "{PROJECT["version"]}"'
    assert lock.read_text().count(old) == 1
    lock.write_text(lock.read_text().replace(old, f'name = "kuberich"\nversion = "{version}"', 1))
    run(["uv", "lock", "--locked", "--offline", "--python", sys.executable], source)
    run(["git", "init", "--initial-branch=main"], source)
    run(["git", "add", "."], source)
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
            "test: unpublished owned source installation candidate",
        ],
        source,
    )
    sha = run(["git", "rev-parse", "HEAD"], source).stdout.strip()
    run(["uv", "build", "--python", sys.executable], source, 120)
    generate(source / "artifacts/security", source / "dist", root=source)
    bundle = directory / "bundle"
    # Explicitly source-only development qualification: no tag, authored public notes or natives.
    prepare(source, bundle, sha, version, root=source, candidate=True)
    assert not (bundle / "standalone").exists()
    return source, bundle, sha
