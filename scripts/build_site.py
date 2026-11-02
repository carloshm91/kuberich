"""Build the initial static landing/docs locally; this tool never deploys."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token
from packaging.version import Version

from scripts.documentation import Guide, Navigation, load_navigation
from scripts.site_reference import generated_guides

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = "kuberich-initial-site-v1"
MARKER = "build-manifest.json"
REPOSITORY = "https://github.com/carloshm91/kuberich"
SITE_ORIGIN = "https://kuberich.com"
DOCS_ORIGIN = "https://docs.kuberich.com"
DOCS_REDIRECTS = f"""/docs {DOCS_ORIGIN}/ 301
/docs/index.html {DOCS_ORIGIN}/ 301
/docs/* {DOCS_ORIGIN}/:splat 301
"""
HEADERS = """/*
  Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  X-Robots-Tag: noindex, nofollow
"""


def site_headers(public_launch: bool) -> str:
    return HEADERS.replace("noindex, nofollow", "index, follow") if public_launch else HEADERS


def robots_content(public_launch: bool) -> str:
    return "User-agent: *\nAllow: /\n" if public_launch else "User-agent: *\nDisallow: /\n"


NAVIGATION = load_navigation(ROOT)
GUIDES = NAVIGATION.guides
REFERENCES = NAVIGATION.references


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-") or "section"


def user_content(text: str) -> str:
    """Keep user guidance; developer rehearsal/evidence stays in the repository."""
    markers = (
        "## Verification",
        "## Maintainer rehearsal",
        "## Disposable-cluster verification",
    )
    end = min((text.index(m) for m in markers if m in text), default=len(text))
    return text[:end]


def heading_ids(tokens: list[Token]) -> list[tuple[str, str]]:
    used: dict[str, int] = {}
    sections: list[tuple[str, str]] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        title = "".join(
            t.content for t in tokens[index + 1].children or [] if t.type != "html_inline"
        )
        base = str(token.attrGet("id") or slug(title))
        count = used.get(base, 0)
        used[base] = count + 1
        identifier = base if count == 0 else f"{base}-{count}"
        token.attrSet("id", identifier)
        if token.tag == "h2":
            sections.append((identifier, title))
    return sections


def rewrite_links(
    tokens: list[Token], source: Path, root: Path, catalog: Navigation | None = None
) -> None:
    catalog = catalog or load_navigation(root)
    selected = catalog.source_pages
    legacy = {route.source: route for route in catalog.legacy_routes}
    for token in tokens:
        if token.children:
            rewrite_links(token.children, source, root, catalog)
        if token.type != "link_open":
            continue
        href = str(token.attrGet("href") or "")
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or (not parsed.path and not parsed.fragment):
            continue
        target = (source.parent / parsed.path).resolve() if parsed.path else source.resolve()
        relative = target.relative_to(root.resolve()).as_posix()
        fragment = unquote(parsed.fragment)
        name = relative.removeprefix("docs/")
        if relative.startswith("docs/") and name in selected:
            guide = selected[name]
            result = guide.filename
            if name in guide.sources[1:]:
                fragment = (
                    name.removesuffix(".md") + "--" + fragment if fragment else legacy[name].anchor
                )
            elif name in legacy:
                fragment = (
                    dict(legacy[name].fragments).get(fragment, fragment)
                    if fragment
                    else legacy[name].anchor
                )
            else:
                fragment = dict(guide.aliases).get(fragment, fragment)
        else:
            # Non-launch developer evidence remains in the source repository.
            result = f"{REPOSITORY}/blob/main/{relative}"
        if parsed.query:
            result += "?" + parsed.query
        if fragment:
            result += "#" + fragment
        token.attrSet("href", result)


def navigation(current: str, catalog: Navigation | None = None) -> str:
    catalog = catalog or NAVIGATION
    parts = [
        '<details class="docs-menu" open><summary>Browse documentation</summary>'
        '<nav class="docs-nav" aria-label="Documentation"><h2>Overview</h2>'
    ]
    active = ' aria-current="page"' if current == "index.html" else ""
    parts.append(f'<a href="index.html"{active}>{escape(catalog.index_title)}</a>')
    group = ""
    for guide in catalog.pages:
        if guide.group != group:
            group = guide.group
            parts.append(f"<h2>{escape(group)}</h2>")
        active = ' aria-current="page"' if guide.filename == current else ""
        parts.append(f'<a href="{guide.filename}"{active}>{escape(guide.title)}</a>')
    parts.append("</nav></details>")
    return "".join(parts)


def is_published(version: str, root: Path = ROOT) -> bool:
    record = json.loads((root / "docs/published-releases.json").read_text())
    if (
        not isinstance(record, dict)
        or record.get("schema_version") != 1
        or not isinstance(record.get("releases"), dict)
    ):
        raise ValueError("Invalid published release inventory")
    return version in record["releases"]


def preview_label(version: str, root: Path = ROOT) -> str:
    if Version(version).is_devrelease:
        return "Development preview"
    return "Public release" if is_published(version, root) else "Prepared release"


def installation_status(version: str, root: Path = ROOT) -> str:
    if is_published(version, root):
        return "Install from PyPI, the project Homebrew tap or GitHub Release archives."
    return (
        "Public PyPI/Homebrew packages are not available. Use the source checkout or a trusted "
        "local wheel."
    )


def preview_banner(version: str, root: Path = ROOT) -> str:
    return (
        '<aside class="preview-banner" aria-label="Release status">'
        f"<p><strong>{preview_label(version, root)} · {escape(version)}</strong>. "
        f"{installation_status(version, root)}</p></aside>"
    )


def page_frame(
    root: Path,
    content: str,
    title: str,
    version: str,
    *,
    docs: bool,
    standalone: bool = False,
    public_launch: bool = False,
    canonical: str | None = None,
) -> str:
    prefix = "." if standalone or not docs else ".."
    home = "https://kuberich.com" if standalone else ("../index.html" if docs else "index.html")
    values = {
        "title": escape(title),
        "description": f"KubeRich: a Python terminal workspace for Kubernetes. {preview_label(version, root)}.",
        "prefix": prefix,
        "home": home,
        "docs": (
            "index.html"
            if docs or standalone
            else DOCS_ORIGIN + "/"
            if public_launch
            else "docs/index.html"
        ),
        "body_class": "docs-page" if docs else "landing-page",
        "version": escape(version),
        "preview_label": preview_label(version, root),
        "content": content,
        "robots": "index,follow" if public_launch else "noindex,nofollow",
        "canonical": f'<link rel="canonical" href="{escape(canonical, quote=True)}">'
        if canonical and public_launch
        else "",
    }
    return Template((root / "website/frame.html").read_text()).substitute(values)


def resolved_aliases(
    tokens: list[Token], declared: tuple[tuple[str, str], ...]
) -> dict[str, list[str]]:
    identifiers = {str(token.attrGet("id")) for token in tokens if token.type == "heading_open"}
    aliases: dict[str, list[str]] = {}
    for identifier, target in declared:
        if target not in identifiers:
            raise ValueError(f"Documentation alias target is missing: {identifier} -> {target}")
        if identifier in identifiers:
            if identifier != target:
                raise ValueError("Documentation alias conflicts with an active heading")
            continue
        aliases.setdefault(target, []).append(identifier)
    return aliases


def with_heading_aliases(tokens: list[Token], aliases: dict[str, list[str]]) -> list[Token]:
    result: list[Token] = []
    for token in tokens:
        if token.type == "heading_open":
            for identifier in aliases.get(str(token.attrGet("id")), []):
                anchor = Token("link_open", "a", 1)
                anchor.attrSet("id", identifier)
                anchor.attrSet("aria-hidden", "true")
                result.extend((anchor, Token("link_close", "a", -1)))
        result.append(token)
    return result


def composed_guide(root: Path, guide: Guide, md: MarkdownIt, catalog: Navigation) -> list[Token]:
    tokens: list[Token] = []
    for index, name in enumerate(guide.sources):
        source = root / "docs" / name
        fragment = md.parse(user_content(source.read_text()))
        heading_ids(fragment)
        titles = [
            number
            for number, token in enumerate(fragment)
            if token.type == "heading_open" and token.tag == "h1"
        ]
        if len(titles) != 1:
            raise ValueError(f"A documentation fragment must have one title: {name}")
        if index == 0:
            title = Token("text", "", 0)
            title.content = guide.title
            fragment[titles[0] + 1].content = guide.title
            fragment[titles[0] + 1].children = [title]
        else:
            prefix = name.removesuffix(".md") + "--"
            for token in fragment:
                if token.type == "heading_open":
                    token.attrSet("id", prefix + str(token.attrGet("id")))
                if token.type in {"heading_open", "heading_close"}:
                    token.tag = f"h{min(int(token.tag[1:]) + 1, 6)}"
        rewrite_links(fragment, source, root, catalog)
        tokens.extend(fragment)
    identifiers = {str(token.attrGet("id")) for token in tokens if token.type == "heading_open"}
    aliases = resolved_aliases(tokens, guide.aliases)
    for route in catalog.legacy_routes:
        if route.target != guide.source:
            continue
        if route.heading not in identifiers:
            raise ValueError(f"Legacy documentation heading is missing: {route.source}")
        if route.anchor in identifiers:
            if route.anchor != route.heading:
                raise ValueError("Legacy documentation anchor conflicts with an existing heading")
            continue
        if any(route.anchor in values for values in aliases.values()):
            if route.anchor not in aliases.get(route.heading, []):
                raise ValueError("Legacy documentation anchor has conflicting targets")
            continue
        aliases.setdefault(route.heading, []).append(route.anchor)
    return with_heading_aliases(tokens, aliases)


def legacy_redirects(catalog: Navigation, *, prefix: str = "/") -> str:
    pages = {page.source: page for page in catalog.pages}
    lines: list[str] = []
    for route in catalog.legacy_routes:
        source = route.source.removesuffix(".md")
        target = prefix + pages[route.target].filename
        # RFC 9110 section 10.2.2: no Location fragment preserves the request hash.
        # https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.2
        # New consolidated pages retain old unprefixed and composed identifiers.
        if not route.fragments:
            target += "#" + route.anchor
        lines.extend(f"{prefix}{name} {target} 301" for name in (source, source + ".html"))
    return "\n".join(lines) + ("\n" if lines else "")


def guide_html(
    root: Path,
    guide: Guide,
    version: str,
    *,
    standalone: bool,
    generated: str | None = None,
    public_launch: bool = False,
    catalog: Navigation | None = None,
) -> str:
    catalog = catalog or load_navigation(root)
    source = root / "docs" / guide.source
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    lines = (
        len(generated.splitlines())
        if generated is not None
        else sum(len((root / "docs" / name).read_text().splitlines()) for name in guide.sources)
    )
    if lines > 250:
        raise ValueError(f"User documentation exceeds the 250-line budget: {guide.source}")
    tokens = (
        md.parse(generated) if generated is not None else composed_guide(root, guide, md, catalog)
    )
    sections = heading_ids(tokens)
    if generated is not None:
        tokens = with_heading_aliases(tokens, resolved_aliases(tokens, guide.aliases))
    for token in tokens:
        if token.type == "table_open":
            # Wide references scroll locally on mobile and must accept keyboard focus.
            token.attrSet("tabindex", "0")
    if generated is not None:
        rewrite_links(tokens, source, root, catalog)
    toc = (
        '<nav class="doc-toc" aria-label="On this page">'
        + "".join(f'<a href="#{identifier}">{escape(title)}</a>' for identifier, title in sections)
        + "</nav>"
    )
    rendered = md.renderer.render(tokens, md.options, {}).replace("<pre>", '<pre tabindex="0">')
    content = (
        f'<main id="main" tabindex="-1" class="docs-shell">{navigation(guide.filename, catalog)}'
        '<article class="doc-body">'
        f'{preview_banner(version, root)}<p class="eyebrow">{escape(guide.group).upper()}</p>'
        f"{rendered.split('</h1>', 1)[0]}</h1>{toc}{rendered.split('</h1>', 1)[1]}"
        '<div class="source-link">'
        + (
            f'Generated from <a href="{REPOSITORY}/blob/main/scripts/site_reference.py">'
            "application declarations and the maintained capability inventory</a>."
            if generated is not None
            else "Built from the maintained source guides on GitHub: "
            + ", ".join(
                f'<a href="{REPOSITORY}/blob/main/docs/{name}">{escape(name.removesuffix(".md").replace("-", " "))}</a>'
                for name in guide.sources
            )
            + "."
        )
        + "</div></article></main>"
    )
    return page_frame(
        root,
        content,
        guide.title,
        version,
        docs=True,
        standalone=standalone,
        public_launch=public_launch,
        canonical=DOCS_ORIGIN + "/" + guide.filename.removesuffix(".html"),
    )


def docs_index(root: Path, version: str, *, standalone: bool, public_launch: bool = False) -> str:
    catalog = load_navigation(root)
    links = "".join(
        f'<li><a href="{guide.filename}">{escape(guide.title)}</a> '
        f'<span class="muted">/ {escape(guide.group)}</span></li>'
        for guide in catalog.pages
    )
    content = (
        f'<main id="main" tabindex="-1" class="docs-shell">{navigation("index.html", catalog)}'
        f'<article class="doc-body">{preview_banner(version, root)}<p class="eyebrow">DOCUMENTATION</p>'
        '<h1>Get to know your workspace.</h1><p class="index-summary">Choose an installation '
        "method, select an intended context, and explore in read-only mode. These guides describe "
        "the implemented release, its prerequisites and its limits.</p>"
        "<h2>Choose your starting point</h2><ol>"
        "<li><strong>First visit:</strong> "
        '<a href="installation.html">install, upgrade or uninstall</a>, then '
        '<a href="quickstart.html">open an explicit read-only session</a>.</li>'
        "<li><strong>Daily use:</strong> follow the "
        '<a href="everyday-workflow.html">pod, container, logs and shell walkthrough</a>, '
        "then use the individual guides for each operation.</li>"
        "<li><strong>Something failed:</strong> identify the visible state in "
        '<a href="troubleshooting.html">troubleshooting</a> or check '
        '<a href="troubleshooting.html#legacy-terminal-compatibility">terminal compatibility</a>.</li></ol>'
        "<p>Use a trusted kubeconfig and the intended provider helper session. "
        "Selecting scope leaves kubeconfig unchanged and uses a separate connection. "
        "All tutorial names and screenshots use fictional resources.</p>"
        "<h2>All guides and references</h2>"
        f'<ul class="doc-index-links">{links}</ul></article></main>'
    )
    return page_frame(
        root,
        content,
        "Documentation",
        version,
        docs=True,
        standalone=standalone,
        public_launch=public_launch,
        canonical=DOCS_ORIGIN + "/",
    )


def prepare_output(output: Path, root: Path) -> None:
    if output.is_symlink():
        raise ValueError("Output cannot be a symlink")
    resolved = output.resolve()
    if resolved == root.resolve() or resolved in root.resolve().parents:
        raise ValueError("Output cannot replace the repository or its ancestors")
    if output.exists() and any(output.iterdir()):
        marker = output / MARKER
        if not marker.is_file() or marker.is_symlink():
            raise ValueError("Refusing to replace an unowned nonempty directory")
        prior = json.loads(marker.read_text())
        if prior.get("generator") != GENERATOR:
            raise ValueError("Output ownership marker does not match")
        files = {p.relative_to(output).as_posix() for p in output.rglob("*") if p.is_file()}
        if files != set(prior["files"]) | {MARKER} or any(
            p.is_symlink() for p in output.rglob("*")
        ):
            raise ValueError("Refusing to discard unexpected files or symlinks")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def source_inputs(root: Path) -> list[Path]:
    catalog = load_navigation(root)
    inputs = [
        root / "pyproject.toml",
        root / "scripts/build_site.py",
        root / "scripts/site_reference.py",
        root / "scripts/site_schema.py",
        root / "scripts/documentation.py",
        root / "docs/navigation.json",
        root / "docs/capabilities.json",
        root / "docs/published-releases.json",
    ]
    # Imported parser/registry dependencies are part of the receipt, including future modules.
    inputs += sorted((root / "src/kuberich").rglob("*.py"))
    inputs += sorted((root / "website").glob("*.html"))
    inputs += sorted((root / "website/assets").glob("*"))
    inputs += [root / "docs" / name for guide in catalog.guides for name in guide.sources]
    inputs += [root / "docs" / guide.source for guide in catalog.references]
    return inputs


def build(output: Path, root: Path = ROOT, *, public_launch: bool = False) -> dict[str, object]:
    catalog = load_navigation(root)
    inputs = source_inputs(root)
    for path in inputs:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or unsafe site input: {path.relative_to(root)}")
    media_manifest = root / "website/assets/media.json"
    media = json.loads(media_manifest.read_text())
    for name, record in media["images"].items():
        if digest(root / "website/assets" / name) != record["sha256"]:
            raise ValueError("Screenshot digest differs from reviewed media inventory")
    version = str(tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"])
    if public_launch and (Version(version).is_devrelease or not is_published(version, root)):
        raise ValueError("Public indexing requires a verified published release")
    references = generated_guides(root, version)
    prepare_output(output, root)
    for surface in ("www", "docs"):
        destination = output / surface
        (destination / "assets").mkdir(parents=True)
        for name in ("site.css", "site.js", "mark.svg", "workspace.svg", "logs.svg"):
            shutil.copyfile(root / "website/assets" / name, destination / "assets" / name)
        (destination / "_headers").write_text(site_headers(public_launch))
        (destination / "robots.txt").write_text(robots_content(public_launch))
        standalone = surface == "docs"
        if public_launch and not standalone:
            (destination / "_redirects").write_text(DOCS_REDIRECTS)
            continue
        (destination / "_redirects").write_text(
            legacy_redirects(catalog, prefix="/" if standalone else "/docs/")
        )
        docs_dir = destination if standalone else destination / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "index.html").write_text(
            docs_index(root, version, standalone=standalone, public_launch=public_launch)
        )
        for guide in catalog.pages:
            (docs_dir / guide.filename).write_text(
                guide_html(
                    root,
                    guide,
                    version,
                    standalone=standalone,
                    generated=references.get(guide.source),
                    public_launch=public_launch,
                    catalog=catalog,
                )
            )
    landing = Template((root / "website/landing.html").read_text()).substitute(
        version=version,
        preview_label=preview_label(version, root),
        installation_status=installation_status(version, root),
        docs_base=DOCS_ORIGIN + "/" if public_launch else "docs/",
    )
    (output / "www/index.html").write_text(
        page_frame(
            root,
            landing,
            "A terminal workspace for Kubernetes",
            version,
            docs=False,
            public_launch=public_launch,
            canonical=SITE_ORIGIN + "/",
        )
    )
    for surface in ("www", "docs"):
        content = (
            '<main id="main" class="hero"><div><p class="eyebrow">404</p>'
            "<h1>Back to the workspace.</h1><p>This page does not exist. "
            '<a href="index.html">Return to the start page</a>.</p></div></main>'
        )
        (output / surface / "404.html").write_text(
            page_frame(
                root,
                content,
                "Page not found",
                version,
                docs=False,
                standalone=surface == "docs",
                public_launch=public_launch,
            )
        )
    manifest: dict[str, object] = {
        "generator": GENERATOR,
        "version": version,
        "private_preparation": not public_launch,
        "indexing": "public" if public_launch else "preview",
        "application_qualification": "docs/internal/acceptance/workload-checkpoint.md",
        "publication_performed": False,
        "documentation_pages": catalog.user_page_count,
        "sources": {p.relative_to(root).as_posix(): digest(p) for p in inputs},
        "files": {
            p.relative_to(output).as_posix(): digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    (output / MARKER).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/site")
    parser.add_argument(
        "--public-launch",
        action="store_true",
        help="Prepare indexable pages for a verified published release; does not deploy.",
    )
    args = parser.parse_args()
    try:
        result = build(args.output, public_launch=args.public_launch)
    except (OSError, ValueError, KeyError) as error:
        print(f"Site build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output.resolve()), "version": result["version"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
