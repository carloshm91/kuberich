"""Owned authored-note bytes and Git source fixtures, never a public release."""

import json
import subprocess

from scripts.release_notes import freeze
from scripts.release_policy import release_tag


def authored(version):
    return (
        f"# KubeRich {version}\n"
        "\n## Features\n\nOwned fixture behavior only.\n"
        "\n## Fixes\n\nNo public fix claim.\n"
        "\n## Compatibility and migrations\n\nNo configuration migration.\n"
        "\n## Installation\n\nInstall the exact owned local artifact.\n"
        "\n## Upgrade and uninstall\n\nNo previous public release is fabricated.\n"
        "\n## Known limits\n\nThis synthetic release is never published.\n"
    )


def commit_notes(root, version):
    path = root / f"docs/release-notes/{version}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(authored(version), encoding="utf-8")
    for arguments in (
        ("init", "--quiet"),
        ("add", "."),
        (
            "-c",
            "user.name=Release Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Owned authored notes",
        ),
    ):
        subprocess.run(
            ["git", "-C", str(root), *arguments], check=True, capture_output=True, timeout=10
        )
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()


def note_bundle(directory, root, sha, version, preview=None):
    notes = freeze(root, sha, version, preview)
    (directory / "release-notes.md").write_text(notes["body"], encoding="utf-8")
    (directory / "release.json").write_text(
        json.dumps(
            {
                "commit": sha,
                "version": version,
                "tag": release_tag(version),
                "candidate_only": False,
                "notes": notes,
            }
        ),
        encoding="utf-8",
    )
    return notes["body"]
