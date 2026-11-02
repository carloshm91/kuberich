"""Validate active Markdown links and byte-exact, source-bound historical records."""

import hashlib
import json
import posixpath
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

MAX_HISTORY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class OriginalContext:
    source: str
    commit: str
    paths: frozenset[str]


def repository_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Documentation paths must be repository-relative text")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("Documentation paths must stay inside the repository")
    return value


def git_bytes(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *arguments], stderr=subprocess.PIPE, timeout=10
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError("The recorded documentation source is unavailable") from error


def original_contexts(root: Path) -> dict[Path, OriginalContext]:
    plan = json.loads((root / "docs/documentation-plan.json").read_text())
    records = plan.get("preserved_sources", [])
    if not isinstance(records, list):
        raise ValueError("Preserved documentation sources must be a list")
    result: dict[Path, OriginalContext] = {}
    trees: dict[str, frozenset[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Preserved documentation source must be an object")
        name, source = repository_path(record.get("path")), repository_path(record.get("source"))
        commit, checksum = record.get("commit"), record.get("sha256")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError("A historical source needs an exact commit")
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise ValueError("A historical source needs its SHA-256")
        path = root / name
        if path in result or path.is_symlink() or not path.is_file():
            raise ValueError("Missing, duplicate or unsafe historical documentation source")
        if (
            not path.resolve().is_relative_to(root.resolve())
            or path.stat().st_size > MAX_HISTORY_BYTES
        ):
            raise ValueError("Historical documentation source exceeds its path/size boundary")
        content = path.read_bytes()
        if not name.endswith(".md") or not source.endswith(".md"):
            raise ValueError("Historical documentation must be Markdown")
        if hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError("Historical documentation bytes changed")
        size = int(git_bytes(root, "cat-file", "-s", f"{commit}:{source}"))
        if (
            size > MAX_HISTORY_BYTES
            or git_bytes(root, "cat-file", "blob", f"{commit}:{source}") != content
        ):
            raise ValueError("Historical documentation differs from its recorded source")
        if commit not in trees:
            names = (
                git_bytes(root, "ls-tree", "-r", "--name-only", "-z", commit).decode().split("\0")
            )
            paths = {name for name in names if name}
            paths.update(
                parent.as_posix() for name in tuple(paths) for parent in PurePosixPath(name).parents
            )
            trees[commit] = frozenset(paths)
        result[path] = OriginalContext(source, commit, trees[commit])
    return result


def links(tokens: list[Token]) -> list[str]:
    values: list[str] = []
    for token in tokens:
        if token.type == "link_open":
            values.append(str(token.attrGet("href")))
        elif token.type == "image":
            values.append(str(token.attrGet("src")))
        if token.children:
            values.extend(links(token.children))
    return values


def validate_markdown(root: Path, path: Path, context: OriginalContext | None = None) -> int:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    source = context.source if context is not None else path.relative_to(root).as_posix()
    count = 0
    for target in links(parser.parse(path.read_text())):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        relative = unquote(parsed.path)
        if (
            PurePosixPath(relative).is_absolute()
            or "\\" in relative
            or any(ord(c) < 32 for c in relative)
        ):
            raise ValueError(f"Unsafe local documentation link in {path}: {target}")
        name = posixpath.normpath(posixpath.join(posixpath.dirname(source), relative))
        if name == ".." or name.startswith("../"):
            raise ValueError(f"Documentation link escapes the repository in {path}: {target}")
        if context is not None:
            exists = name in context.paths
        else:
            destination = root / name
            exists = destination.exists() and destination.resolve().is_relative_to(root.resolve())
        if not exists:
            raise ValueError(f"Broken link in {path}: {target}")
        count += 1
    return count


def validate_repository_links(root: Path) -> int:
    contexts = original_contexts(root)
    names = git_bytes(root, "ls-files", "-z").decode().split("\0")
    total = 0
    for name in names:
        if not name.endswith(".md"):
            continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Missing or unsafe Markdown source: {name}")
        total += validate_markdown(root, path, contexts.get(path))
    return total
