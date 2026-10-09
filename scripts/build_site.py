"""Build the initial static landing/docs locally; this tool never deploys."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token

from scripts.site_reference import generated_guides

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = "kuberich-initial-site-v1"
MARKER = "build-manifest.json"
REPOSITORY = "https://github.com/carloshm91/kuberich"
HEADERS = """/*
  Content-Security-Policy: default-src 'none'; img-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  X-Robots-Tag: noindex, nofollow
"""


@dataclass(frozen=True)
class Guide:
    source: str
    title: str
    group: str

    @property
    def filename(self) -> str:
        return self.source.removesuffix(".md") + ".html"


GUIDES = (
    Guide("quickstart.md", "Install & first launch", "Get started"),
    Guide("configuration.md", "Preferences & migration", "Get started"),
    Guide("context-sessions.md", "Contexts & kubeconfig", "Get started"),
    Guide("command-navigation.md", "Commands & keys", "Browse"),
    Guide("resource-workspace.md", "The workspace", "Browse"),
    Guide("standard-resources.md", "Resource views", "Browse"),
    Guide("resource-inspection.md", "Details, YAML & events", "Browse"),
    Guide("container-navigation.md", "Container selection", "Observe & connect"),
    Guide("log-viewer.md", "Container logs", "Observe & connect"),
    Guide("container-shell.md", "Embedded shells", "Observe & connect"),
    Guide("port-forwards.md", "Port forwarding", "Observe & connect"),
    Guide("mutations.md", "Guarded changes", "Change deliberately"),
    Guide("editing.md", "Manifest editing", "Change deliberately"),
    Guide("workloads.md", "Scale & rollout", "Change deliberately"),
    Guide("resource-operations.md", "Delete & Jobs", "Change deliberately"),
    Guide("eks-authentication.md", "AWS / EKS", "Authentication"),
    Guide("aks-authentication.md", "Azure / AKS", "Authentication"),
    Guide("kubeconfig-interoperability.md", "GKE, OIDC, certificates & proxies", "Authentication"),
)

REFERENCES = (
    Guide("cli-reference.md", "Command-line options", "Reference"),
    Guide("resource-reference.md", "Resource registry", "Reference"),
    Guide("capability-reference.md", "Capability progress", "Reference"),
)


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
        base = slug(title)
        count = used.get(base, 0)
        used[base] = count + 1
        identifier = base if count == 0 else f"{base}-{count}"
        token.attrSet("id", identifier)
        if token.tag == "h2":
            sections.append((identifier, title))
    return sections


def rewrite_links(tokens: list[Token], source: Path, root: Path) -> None:
    selected = {guide.source: guide.filename for guide in (*GUIDES, *REFERENCES)}
    for token in tokens:
        if token.children:
            rewrite_links(token.children, source, root)
        if token.type != "link_open":
            continue
        href = str(token.attrGet("href") or "")
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = (source.parent / parsed.path).resolve()
        relative = target.relative_to(root.resolve()).as_posix()
        if relative.startswith("docs/") and relative.removeprefix("docs/") in selected:
            result = selected[relative.removeprefix("docs/")]
        else:
            # Non-launch developer evidence remains in the source repository.
            result = f"{REPOSITORY}/blob/main/{relative}"
        if parsed.fragment:
            result += "#" + parsed.fragment
        token.attrSet("href", result)


def navigation(current: str) -> str:
    parts = [
        '<details class="docs-menu" open><summary>Browse documentation</summary>'
        '<nav class="docs-nav" aria-label="Documentation"><h2>Overview</h2>'
    ]
    active = ' aria-current="page"' if current == "index.html" else ""
    parts.append(f'<a href="index.html"{active}>Start here</a>')
    group = ""
    for guide in (*GUIDES, *REFERENCES):
        if guide.group != group:
            group = guide.group
            parts.append(f"<h2>{escape(group)}</h2>")
        active = ' aria-current="page"' if guide.filename == current else ""
        parts.append(f'<a href="{guide.filename}"{active}>{escape(guide.title)}</a>')
    parts.append("</nav></details>")
    return "".join(parts)


def preview_banner(version: str) -> str:
    return (
        '<aside class="preview-banner" aria-label="Preview status">'
        f"<p><strong>Development preview · {escape(version)}</strong>. "
        "Public PyPI/Homebrew packages are not available. Use the source checkout or a trusted "
        "local wheel. Full release qualification and real-cloud trials remain pending.</p></aside>"
    )


def page_frame(
    root: Path, content: str, title: str, version: str, *, docs: bool, standalone: bool = False
) -> str:
    prefix = "." if standalone or not docs else ".."
    home = "https://kuberich.com" if standalone else ("../index.html" if docs else "index.html")
    values = {
        "title": escape(title),
        "description": "KubeRich: a Python terminal workspace for Kubernetes. Development preview.",
        "prefix": prefix,
        "home": home,
        "docs": "index.html" if docs or standalone else "docs/index.html",
        "body_class": "docs-page" if docs else "landing-page",
        "version": escape(version),
        "content": content,
    }
    return Template((root / "website/frame.html").read_text()).substitute(values)


def guide_html(
    root: Path, guide: Guide, version: str, *, standalone: bool, generated: str | None = None
) -> str:
    source = root / "docs" / guide.source
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(generated if generated is not None else user_content(source.read_text()))
    sections = heading_ids(tokens)
    for token in tokens:
        if token.type == "table_open":
            # Wide references scroll locally on mobile and must accept keyboard focus.
            token.attrSet("tabindex", "0")
    rewrite_links(tokens, source, root)
    toc = (
        '<nav class="doc-toc" aria-label="On this page">'
        + "".join(f'<a href="#{identifier}">{escape(title)}</a>' for identifier, title in sections)
        + "</nav>"
    )
    rendered = md.renderer.render(tokens, md.options, {}).replace("<pre>", '<pre tabindex="0">')
    content = (
        f'<main id="main" tabindex="-1" class="docs-shell">{navigation(guide.filename)}'
        '<article class="doc-body">'
        f'{preview_banner(version)}<p class="eyebrow">{escape(guide.group).upper()}</p>'
        f"{rendered.split('</h1>', 1)[0]}</h1>{toc}{rendered.split('</h1>', 1)[1]}"
        '<div class="source-link">'
        + (
            f'Generated from <a href="{REPOSITORY}/blob/main/scripts/site_reference.py">'
            "application declarations and the maintained capability inventory</a>."
            if generated is not None
            else f'Built from the maintained <a href="{REPOSITORY}/blob/main/docs/{guide.source}">'
            "source guide on GitHub</a>."
        )
        + "</div></article></main>"
    )
    return page_frame(root, content, guide.title, version, docs=True, standalone=standalone)


def docs_index(root: Path, version: str, *, standalone: bool) -> str:
    links = "".join(
        f'<li><a href="{guide.filename}">{escape(guide.title)}</a> '
        f'<span class="muted">/ {escape(guide.group)}</span></li>'
        for guide in (*GUIDES, *REFERENCES)
    )
    content = (
        f'<main id="main" tabindex="-1" class="docs-shell">{navigation("index.html")}'
        f'<article class="doc-body">{preview_banner(version)}<p class="eyebrow">DOCUMENTATION</p>'
        '<h1>Get to know your workspace.</h1><p class="index-summary">Install a supplied local '
        "wheel or use a source checkout, select an intended context, and explore in read-only mode. These guides describe "
        "the implemented preview, its prerequisites and its limits.</p>"
        '<p>Start with <a href="quickstart.html">installation and first launch</a>. '
        "Use the same trusted kubeconfig and provider helper session that work with kubectl. "
        "KubeRich preserves your kubeconfig and owns each connection separately.</p>"
        f'<ul class="doc-index-links">{links}</ul></article></main>'
    )
    return page_frame(root, content, "Documentation", version, docs=True, standalone=standalone)


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
    inputs = [
        root / "pyproject.toml",
        root / "scripts/build_site.py",
        root / "scripts/site_reference.py",
        root / "docs/capabilities.json",
    ]
    # Imported parser/registry dependencies are part of the receipt, including future modules.
    inputs += sorted((root / "src/kuberich").rglob("*.py"))
    inputs += sorted((root / "website").glob("*.html"))
    inputs += sorted((root / "website/assets").glob("*"))
    inputs += [root / "docs" / guide.source for guide in GUIDES]
    return inputs


def build(output: Path, root: Path = ROOT) -> dict[str, object]:
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
    references = generated_guides(root, version)
    prepare_output(output, root)
    for surface in ("www", "docs"):
        destination = output / surface
        (destination / "assets").mkdir(parents=True)
        for name in ("site.css", "site.js", "mark.svg", "workspace.svg", "logs.svg"):
            shutil.copyfile(root / "website/assets" / name, destination / "assets" / name)
        (destination / "_headers").write_text(HEADERS)
        (destination / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
        standalone = surface == "docs"
        docs_dir = destination if standalone else destination / "docs"
        docs_dir.mkdir(exist_ok=True)
        (docs_dir / "index.html").write_text(docs_index(root, version, standalone=standalone))
        for guide in (*GUIDES, *REFERENCES):
            (docs_dir / guide.filename).write_text(
                guide_html(
                    root,
                    guide,
                    version,
                    standalone=standalone,
                    generated=references.get(guide.source),
                )
            )
    landing = Template((root / "website/landing.html").read_text()).substitute(version=version)
    (output / "www/index.html").write_text(
        page_frame(root, landing, "A terminal workspace for Kubernetes", version, docs=False)
    )
    for surface in ("www", "docs"):
        content = (
            '<main id="main" class="hero"><div><p class="eyebrow">404</p>'
            "<h1>Back to the workspace.</h1><p>This page does not exist. "
            '<a href="index.html">Return to the start page</a>.</p></div></main>'
        )
        (output / surface / "404.html").write_text(
            page_frame(
                root, content, "Page not found", version, docs=False, standalone=surface == "docs"
            )
        )
    manifest: dict[str, object] = {
        "generator": GENERATOR,
        "version": version,
        "private_preparation": True,
        "application_qualification": "docs/acceptance/identity-migration.md",
        "publication_performed": False,
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
    args = parser.parse_args()
    try:
        result = build(args.output)
    except (OSError, ValueError, KeyError) as error:
        print(f"Site build failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output.resolve()), "version": result["version"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
