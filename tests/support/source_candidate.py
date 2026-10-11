"""Build actual unpublished canonical source bundles; do not fabricate native records."""

import shutil
import sys
from pathlib import Path

from scripts.build_standalone import source_inputs
from scripts.check_supply_chain import INPUT_FILES, generate
from scripts.release import prepare
from tests.support.distribution import PROJECT, ROOT, run


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
