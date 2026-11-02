"""Check real documentation contracts and report optional editorial observations."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from markdown_it import MarkdownIt

from scripts.documentation import load_navigation
from scripts.documentation_external import probe_links
from scripts.documentation_links import links, validate_repository_links
from scripts.site_reference import check_reference_files

ROOT = Path(__file__).resolve().parents[1]
LINE_TARGETS = {
    "AGENTS.md": 60,
    "CONTRIBUTING.md": 150,
    "docs/architecture.md": 300,
    "docs/quality.md": 250,
    "docs/first-preview.md": 50,
    "docs/STYLE.md": 250,
}


def avoid_words(root: Path) -> dict[str, str]:
    """Use the authored STYLE table instead of maintaining a second word list."""
    result = {}
    for line in (root / "docs/STYLE.md").read_text().splitlines():
        match = re.fullmatch(r"\| ([a-z]+) \| (.+) \|", line)
        if match:
            result[match[1]] = match[2]
    return result


def observations(
    path: str, text: str, words: dict[str, str]
) -> tuple[list[dict[str, object]], set[str]]:
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(text)
    findings: list[dict[str, object]] = []
    previous = 0
    for token in tokens:
        line = token.map[0] + 1 if token.map is not None else 1
        if token.type == "heading_open":
            level = int(token.tag[1:])
            if previous and level > previous + 1:
                findings.append(
                    {
                        "file": path,
                        "line": line,
                        "rule": "heading-level",
                        "message": "A heading skips a level",
                    }
                )
            previous = level
        if token.type == "fence" and not token.info.strip():
            findings.append(
                {
                    "file": path,
                    "line": line,
                    "rule": "fence-language",
                    "message": "Name the code block language",
                }
            )
        if token.type != "inline":
            continue
        prose = " ".join(child.content for child in token.children or [] if child.type == "text")
        for word, replacement in words.items():
            if re.search(r"\b" + re.escape(word) + r"\b", prose, re.I):
                findings.append(
                    {
                        "file": path,
                        "line": line,
                        "rule": "plain-language",
                        "message": f"Consider replacing {word!r}: {replacement}",
                    }
                )
    for number, source_line in enumerate(text.splitlines(), 1):
        trailing = len(source_line) - len(source_line.rstrip())
        if trailing not in {0, 2}:
            findings.append(
                {
                    "file": path,
                    "line": number,
                    "rule": "trailing-space",
                    "message": "Remove accidental trailing whitespace",
                }
            )
    if text and not text.endswith("\n"):
        findings.append(
            {
                "file": path,
                "line": len(text.splitlines()),
                "rule": "final-newline",
                "message": "End the file with a newline",
            }
        )
    line_target = LINE_TARGETS.get(path, 250 if path.startswith("docs/") else None)
    if line_target is not None and len(text.splitlines()) > line_target:
        findings.append(
            {
                "file": path,
                "line": line_target + 1,
                "rule": "page-length",
                "message": f"Consider a shorter page ({line_target}-line guidance)",
            }
        )
    external = set()
    for target in links(tokens):
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc:
            external.add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, "")))
    for finding in findings:
        finding["severity"] = "advisory"
    return findings, external


def check(root: Path, *, external: bool = False) -> dict[str, object]:
    # These reuse the real generators, navigation and link validator; stale code
    # references and missing active files remain functional failures.
    check_reference_files(root)
    catalog = load_navigation(root)
    internal = validate_repository_links(root)
    paths = {
        root / "docs" / name for page in catalog.pages for name in (page.source, *page.sources)
    }
    if (root / "README.md").is_file():
        paths.add(root / "README.md")
    paths.update(root / name for name in LINE_TARGETS)
    words = avoid_words(root)
    findings = []
    urls = set()
    for path in sorted(paths):
        name = path.relative_to(root).as_posix()
        # Contributor material may use exact engineering terminology. Its line
        # and Markdown observations still belong in the same advisory report.
        prose_words = {} if name in LINE_TARGETS and name != "docs/first-preview.md" else words
        items, external_urls = observations(name, path.read_text(), prose_words)
        findings.extend(items)
        if name not in LINE_TARGETS:
            urls.update(external_urls)
    return {
        "functional_checks_passed": True,
        "canonical_user_pages": catalog.user_page_count,
        "local_markdown_links": internal,
        "scope": "Source references and internal paths are required; editorial and network observations are advisory for 0.x",
        "editorial_advisories": findings,
        "external_links": probe_links(urls) if external else [],
        "external_scope": "Bounded public HTTPS HEAD only; no fixture/private endpoints, redirects or fragment validation",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument(
        "--report", type=Path, default=Path("artifacts/site-qa/documentation-report.json")
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="Include bounded advisory public HTTPS HEAD observations",
    )
    arguments = parser.parse_args()
    code = 0
    try:
        report = check(arguments.source.resolve(), external=arguments.external)
    except (OSError, ValueError) as error:
        report = {"functional_checks_passed": False, "error": str(error)}
        code = 1
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2) + "\n")
    if code:
        print(f"Documentation source checks failed; see {arguments.report}")
    else:
        print(
            f"Documentation source checks passed; editorial/network observations are advisory: {arguments.report}"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
