"""Read the canonical documentation navigation and its migration inventory."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

MAX_USER_PAGES = 20
KINDS = frozenset({"tutorial", "how-to", "reference", "explanation"})
GENERATED = frozenset({"cli-reference.md", "resource-reference.md", "capability-reference.md"})
ACTIONS = frozenset({"keep", "merge", "move", "delete"})


@dataclass(frozen=True)
class Guide:
    source: str
    title: str
    group: str
    kind: str = "how-to"
    fragments: tuple[str, ...] = ()
    generated: bool = False

    @property
    def filename(self) -> str:
        return self.source.removesuffix(".md") + ".html"

    @property
    def sources(self) -> tuple[str, ...]:
        return () if self.generated else self.fragments or (self.source,)


@dataclass(frozen=True)
class LegacyRoute:
    source: str
    target: str
    anchor: str
    heading: str


@dataclass(frozen=True)
class Navigation:
    pages: tuple[Guide, ...]
    index_title: str
    legacy_routes: tuple[LegacyRoute, ...] = ()

    @property
    def guides(self) -> tuple[Guide, ...]:
        return tuple(page for page in self.pages if not page.generated)

    @property
    def references(self) -> tuple[Guide, ...]:
        return tuple(page for page in self.pages if page.generated)

    @property
    def user_page_count(self) -> int:
        return 1 + len(self.pages)

    @property
    def source_pages(self) -> dict[str, Guide]:
        result = {
            source: page
            for page in self.pages
            for source in ((page.source,) if page.generated else page.sources)
        }
        canonical = {page.source: page for page in self.pages}
        result.update({route.source: canonical[route.target] for route in self.legacy_routes})
        return result


def mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, object], value)


def sequence(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return cast(list[object], value)


def text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 250
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} must be nonempty plain text")
    return value


def document_name(value: object) -> str:
    name = text(value, "Documentation source")
    if re.fullmatch(r"[a-z0-9][a-z0-9-]*\.md", name) is None:
        raise ValueError("Documentation sources must be plain Markdown filenames")
    return name


def read_document(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512 * 1024:
        raise ValueError(f"Missing or unsafe documentation input: {path.name}")
    return mapping(json.loads(path.read_text()), path.name)


def load_navigation(root: Path) -> Navigation:
    folder = root / "docs"
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Missing or unsafe documentation directory")
    data = read_document(folder / "navigation.json")
    if (
        type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
        or type(data.get("page_budget")) is not int
        or data.get("page_budget") != MAX_USER_PAGES
    ):
        raise ValueError("Unsupported documentation navigation version or page budget")
    pages = []
    kinds: set[str] = set()
    sources: set[str] = set()
    destinations: set[str] = set()
    references: set[str] = set()
    for raw_section in sequence(data.get("sections"), "Documentation sections"):
        section = mapping(raw_section, "Documentation section")
        kind = text(section.get("kind"), "Documentation type")
        if kind not in KINDS or kind in kinds:
            raise ValueError("Documentation types must be distinct Diataxis categories")
        kinds.add(kind)
        group = text(section.get("title"), "Documentation section title")
        entries = sequence(section.get("pages"), "Documentation pages")
        if not entries:
            raise ValueError("Documentation sections must contain pages")
        for raw_page in entries:
            entry = mapping(raw_page, "Documentation page")
            source = document_name(entry.get("source"))
            if source in destinations:
                raise ValueError("Duplicate canonical documentation page")
            destinations.add(source)
            title = text(entry.get("title"), "Documentation title")
            generated = entry.get("generated")
            if type(generated) is not bool:
                raise ValueError("Documentation generated flag must be a boolean")
            fragments = tuple(
                document_name(item) for item in sequence(entry.get("sources"), "Sources")
            )
            if generated:
                if kind != "reference" or source not in GENERATED or fragments:
                    raise ValueError("Generated references must use a supported generator")
                references.add(source)
            else:
                if kind == "reference" or not fragments or fragments[0] != source:
                    raise ValueError("An authored page must start with its canonical source")
                for fragment in fragments:
                    path = folder / fragment
                    if path.is_symlink() or not path.is_file():
                        raise ValueError(f"Missing or unsafe documentation source: {fragment}")
                    if fragment in sources:
                        raise ValueError("A documentation fragment may belong to only one page")
                    sources.add(fragment)
            pages.append(Guide(source, title, group, kind, fragments, generated))
    if kinds != KINDS or references != GENERATED:
        raise ValueError("Navigation must include all documentation types and generated references")
    routes = []
    route_sources: set[str] = set()
    for raw_route in sequence(data.get("legacy_routes"), "Legacy documentation routes"):
        route = mapping(raw_route, "Legacy documentation route")
        source = document_name(route.get("source"))
        target = document_name(route.get("target"))
        if source in destinations or source in route_sources or target not in destinations:
            raise ValueError(
                "Legacy documentation routes need distinct retired paths and canonical targets"
            )
        route_sources.add(source)
        anchor = text(route.get("anchor"), "Legacy documentation anchor")
        heading = text(route.get("heading"), "Legacy documentation heading")
        if any(re.fullmatch(r"[a-z0-9][a-z0-9-]*", value) is None for value in (anchor, heading)):
            raise ValueError("Legacy documentation anchors must use plain heading identifiers")
        routes.append(LegacyRoute(source, target, anchor, heading))
    route_targets = {route.source: route.target for route in routes}
    for page in pages:
        for source in page.sources[1:]:
            if route_targets.get(source) != page.source:
                raise ValueError(
                    "Every merged source needs its explicit legacy documentation route"
                )
    navigation = Navigation(
        tuple(pages), text(data.get("index_title"), "Documentation index title"), tuple(routes)
    )
    if navigation.user_page_count > MAX_USER_PAGES:
        raise ValueError("User documentation exceeds the 20-page budget")
    if sources & references:
        raise ValueError("Generated references cannot also be authored fragments")
    return navigation


def repository_document(name: str) -> bool:
    return (
        name.endswith(".md")
        or name.startswith("docs/")
        or name.startswith(".github/ISSUE_TEMPLATE/")
        or name in {"LICENSE", "NOTICE"}
    )


def relative_path(value: object) -> str:
    name = text(value, "Document inventory path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Document inventory paths must stay inside the repository")
    return name


def validate_documentation_plan(root: Path, tracked_paths: Sequence[str]) -> int:
    data = read_document(root / "docs/documentation-plan.json")
    if (
        type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
        or re.fullmatch(r"[0-9a-f]{40}", str(data.get("baseline_commit", ""))) is None
    ):
        raise ValueError("Unsupported documentation plan or missing baseline identity")
    mapped: set[str] = set()
    for raw_record in sequence(data.get("documents"), "Documentation inventory"):
        record = mapping(raw_record, "Documentation disposition")
        name = relative_path(record.get("source"))
        if name in mapped:
            raise ValueError("Duplicate documentation disposition")
        mapped.add(name)
        if record.get("action") not in ACTIONS:
            raise ValueError("Unknown documentation disposition action")
        destinations = sequence(record.get("destinations"), "Documentation destinations")
        if not destinations:
            raise ValueError("A document disposition must identify its replacement or destination")
        for destination in destinations:
            relative_path(destination)
        text(record.get("reason"), "Documentation disposition reason")
        text(record.get("audience"), "Documentation audience")
        checksum = record.get("baseline_sha256")
        if checksum is not None and (
            not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise ValueError("A baseline document checksum must be SHA-256")
    missing = {name for name in tracked_paths if repository_document(name)} - mapped
    if missing:
        raise ValueError(
            "Documents missing from the disposition map: " + ", ".join(sorted(missing))
        )
    return len(mapped)
