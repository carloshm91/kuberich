"""Freeze reviewed notes without granting release validation a writer token."""

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.release_policy import release_tag, require_sha

MAX_NOTES_BYTES = 32 * 1024
SECTIONS = (
    "Features",
    "Fixes",
    "Compatibility and migrations",
    "Installation",
    "Upgrade and uninstall",
    "Known limits",
)


def text(value: Any, *, maximum: int = MAX_NOTES_BYTES) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(
            (ord(character) < 32 and character not in "\n\t") or 127 <= ord(character) < 160
            for character in value
        )
    ):
        raise ValueError("Release notes require bounded UTF-8 text without terminal controls")
    return value


def parse_preview(value: str) -> dict[str, Any] | None:
    if not value:
        return None
    if len(value.encode("utf-8")) > MAX_NOTES_BYTES + 1024:
        raise ValueError("Generated notes preview exceeds its bound")
    try:
        parsed = json.loads(value)
    except ValueError as error:
        raise ValueError("Generated notes preview must be a JSON object") from error
    if not isinstance(parsed, dict):
        raise ValueError("Generated notes preview must be a JSON object")
    return parsed


def preview_body(preview: dict[str, Any], sha: str, version: str) -> str:
    if (
        set(preview) != {"schema_version", "commit", "version", "tag", "body"}
        or type(preview["schema_version"]) is not int
        or preview["schema_version"] != 1
        or preview["commit"] != sha
        or preview["version"] != version
        or preview["tag"] != release_tag(version)
    ):
        raise ValueError("Generated notes preview source/version/tag identity differs")
    return text(preview["body"])


def freeze(
    root: Path, sha: str, version: str, preview: dict[str, Any] | None = None
) -> dict[str, Any]:
    require_sha(sha)
    release_tag(version)
    relative = f"docs/release-notes/{version}.md"
    path = root / relative
    if (
        any(parent.is_symlink() for parent in (path, path.parent, path.parent.parent))
        or not path.is_file()
        or path.stat().st_size > MAX_NOTES_BYTES
    ):
        raise ValueError("Public candidates need committed per-version authored notes")
    try:
        original = path.read_bytes()
        authored = text(original.decode("utf-8"))
    except UnicodeError as error:
        raise ValueError("Authored release notes must be UTF-8") from error
    try:
        entry = subprocess.check_output(
            ["git", "-C", str(root), "ls-tree", "-z", sha, "--", relative],
            stderr=subprocess.PIPE,
            timeout=10,
        )
        fields = entry.decode("utf-8").split("\t")
        mode, kind, object_id = fields[0].split()
        if (
            len(fields) != 2
            or fields[1] != relative + "\0"
            or mode not in {"100644", "100755"}
            or kind != "blob"
            or not 0
            < int(
                subprocess.check_output(
                    ["git", "-C", str(root), "cat-file", "-s", object_id],
                    stderr=subprocess.PIPE,
                    timeout=10,
                )
            )
            <= MAX_NOTES_BYTES
        ):
            raise ValueError("Authored release notes need a bounded regular Git blob")
        committed = subprocess.check_output(
            ["git", "-C", str(root), "show", f"{sha}:{relative}"],
            stderr=subprocess.PIPE,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as error:
        raise ValueError("Authored release notes must belong to the exact source commit") from error
    if committed != original:
        raise ValueError("Authored release notes differ from the exact committed source bytes")
    if not authored.startswith(f"# KubeRich {version}\n"):
        raise ValueError("Authored release notes version differs")
    for section in SECTIONS:
        heading = f"\n## {section}\n"
        if (
            authored.count(heading) != 1
            or not authored.split(heading, 1)[1].split("\n## ", 1)[0].strip()
        ):
            raise ValueError(f"Authored release notes need a nonempty {section} section")
    combined = (
        authored if preview is None else authored + "\n\n" + preview_body(preview, sha, version)
    )
    text(combined, maximum=MAX_NOTES_BYTES * 2 + 2)
    return {
        "authored_path": relative,
        "authored_sha256": hashlib.sha256(original).hexdigest(),
        "generated_preview": preview,
        "body_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "body": combined,
    }


def frozen_body(directory: Path, sha: str, version: str) -> str:
    """Check the frozen body identity before the first publisher API request."""
    try:
        manifest = json.loads((directory / "release.json").read_text())
        notes = manifest["notes"]
        body = text(notes["body"], maximum=MAX_NOTES_BYTES * 2 + 2)
        if (
            manifest["commit"] != sha
            or manifest["version"] != version
            or manifest["tag"] != release_tag(version)
            or manifest["candidate_only"] is not False
            or notes["authored_path"] != f"docs/release-notes/{version}.md"
            or notes["body_sha256"] != hashlib.sha256(body.encode("utf-8")).hexdigest()
            or (directory / "release-notes.md").read_bytes() != body.encode("utf-8")
        ):
            raise ValueError("Frozen release note body/source/version differs")
        if notes["generated_preview"] is not None:
            generated = preview_body(notes["generated_preview"], sha, version)
            if not body.endswith("\n\n" + generated):
                raise ValueError("Frozen generated release notes differ")
        return body
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("Frozen release notes are missing or malformed") from error
