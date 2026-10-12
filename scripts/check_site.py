"""Verify static outputs, local links, media and explicit preview/public indexing."""

import argparse
import hashlib
import json
import tomllib
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.version import Version

from scripts.build_site import (
    GENERATOR,
    MARKER,
    ROOT,
    digest,
    is_published,
    robots_content,
    site_headers,
    source_inputs,
)


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.assets: list[str] = []
        self.h1 = 0
        self.has_main = False
        self.robots: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        identifier = attributes.get("id")
        if identifier:
            if identifier in self.ids:
                raise ValueError(f"Duplicate HTML id: {identifier}")
            self.ids.add(identifier)
        if tag == "a" and attributes.get("href"):
            self.links.append(str(attributes["href"]))
        if tag in {"script", "img"} and attributes.get("src"):
            self.assets.append(str(attributes["src"]))
        if tag == "link" and attributes.get("href"):
            self.assets.append(str(attributes["href"]))
        if tag == "img" and "alt" not in attributes:
            raise ValueError("Image lacks alternative text")
        if tag == "h1":
            self.h1 += 1
        if tag == "main":
            self.has_main = identifier == "main"
        if tag == "meta" and attributes.get("name") == "robots":
            if self.robots is not None:
                raise ValueError("Duplicate robots metadata")
            self.robots = str(attributes.get("content"))


def verify(output: Path, source: Path = ROOT) -> dict[str, int]:
    root = output.resolve()
    manifest = json.loads((root / MARKER).read_text())
    if manifest.get("generator") != GENERATOR or manifest.get("publication_performed") is not False:
        raise ValueError("Invalid local build manifest")
    indexing = manifest.get("indexing")
    if indexing not in ("preview", "public"):
        raise ValueError("Invalid site indexing mode")
    public_launch = indexing == "public"
    if manifest.get("private_preparation") is not (not public_launch):
        raise ValueError("Site preparation/indexing state is inconsistent")
    version = str(tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"])
    if manifest.get("version") != version:
        raise ValueError("Site version differs from its source")
    if public_launch and (Version(version).is_devrelease or not is_published(version, source)):
        raise ValueError("Public indexing requires a verified published release")
    inputs = source_inputs(source)
    if set(manifest["sources"]) != {path.relative_to(source).as_posix() for path in inputs}:
        raise ValueError("Site source inventory changed; rebuild both surfaces")
    for path in inputs:
        if (
            path.is_symlink()
            or not path.is_file()
            or (digest(path) != manifest["sources"][path.relative_to(source).as_posix()])
        ):
            raise ValueError("Site source drift; rebuild both surfaces")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {MARKER}:
        raise ValueError("Uninventoried or missing output file")
    for name, sha in manifest["files"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError("Output digest mismatch")
    pages: dict[Path, Page] = {}
    for path in root.rglob("*.html"):
        page = Page()
        page.feed(path.read_text())
        expected_robots = "index,follow" if public_launch else "noindex,nofollow"
        if page.h1 != 1 or not page.has_main or page.robots != expected_robots:
            raise ValueError(f"Invalid heading/main/indexing structure: {path.relative_to(root)}")
        pages[path.resolve()] = page
    checked = 0
    for path, page in pages.items():
        for target in page.links + page.assets:
            parsed = urlsplit(target)
            if target in page.assets and (parsed.scheme or parsed.netloc):
                raise ValueError("External runtime resource is forbidden")
            if parsed.scheme or parsed.netloc:
                if parsed.scheme not in {"https", "mailto"} or parsed.username or parsed.password:
                    raise ValueError("Unsafe external link")
                continue
            destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if destination.is_dir():
                destination /= "index.html"
            if not destination.is_relative_to(root) or not destination.is_file():
                raise ValueError(f"Broken local link in {path.name}: {target}")
            if parsed.fragment and (
                destination not in pages or unquote(parsed.fragment) not in pages[destination].ids
            ):
                raise ValueError(f"Broken anchor in {path.name}: {target}")
            checked += 1
    for surface in ("www", "docs"):
        if (root / surface / "_headers").read_text() != site_headers(public_launch):
            raise ValueError("Site headers differ from the selected indexing policy")
        if (root / surface / "robots.txt").read_text() != robots_content(public_launch):
            raise ValueError("Site robots file differs from the selected indexing policy")
        for name in ("workspace.svg", "logs.svg"):
            svg = (root / surface / "assets" / name).read_text()
            if "@font-face" in svg or 'url("https:' in svg or "<script" in svg:
                raise ValueError("Screenshot includes external/active content")
    return {"pages": len(pages), "local_links_and_assets": checked, "files": len(actual)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/site"))
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    print(json.dumps(verify(args.output, args.source)))
