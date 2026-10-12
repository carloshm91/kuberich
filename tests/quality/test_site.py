"""Launch-site behavior and negative controls; application coverage is separate."""

import hashlib
import json
import re
import shutil
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from scripts.build_site import GUIDES, MARKER, REFERENCES, ROOT, build, heading_ids, user_content
from scripts.check_site import verify


def copy_source(destination: Path) -> Path:
    for relative in ("website", "docs", "src"):
        shutil.copytree(ROOT / relative, destination / relative)
    (destination / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/build_site.py", destination / "scripts/build_site.py")
    shutil.copyfile(ROOT / "scripts/site_reference.py", destination / "scripts/site_reference.py")
    shutil.copyfile(ROOT / "pyproject.toml", destination / "pyproject.toml")
    return destination


def refresh(output: Path, path: Path) -> None:
    manifest = json.loads((output / MARKER).read_text())
    manifest["files"][path.relative_to(output).as_posix()] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (output / MARKER).write_text(json.dumps(manifest))


def test_builds_both_surfaces_deterministically_and_rebuilds_owned_output(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    assert build(first) == build(second)
    assert build(first) == build(second)
    evidence = verify(first)
    assert evidence["pages"] == 2 * (len(GUIDES) + len(REFERENCES)) + 5
    assert evidence["local_links_and_assets"] > 500
    for name in ("www/docs/quickstart.html", "docs/quickstart.html"):
        html = (first / name).read_text()
        assert "uv tool install --python 3.12" in html
        assert "kuberich --kubeconfig" in html
        assert "--readonly" in html and "--write" in html
        assert "uninstall" in html and "Public release" in html
        assert "Install from PyPI, the project Homebrew tap or GitHub Release archives" in html
        assert "PyPI/Homebrew packages are not available" not in html
        assert "Maintainer rehearsal" not in html
    for surface in ("www/docs", "docs"):
        installation = (first / surface / "installation.html").read_text()
        assert "brew install kuberich/tap/kuberich" in installation
        assert "pipx upgrade kuberich" in installation
        assert "kuberich-0.1.0-linux-arm64.tar.gz" in installation
        assert "macOS 26" in installation and "glibc 2.35" in installation
        assert "terminal-compatibility.html" in installation
        assert "Public release" in installation
        assert "PyPI/Homebrew packages are not available" not in installation


@pytest.mark.parametrize(
    ("version", "label"),
    [("0.1.0", "Prepared release"), ("0.0.1.dev0", "Development preview")],
)
def test_site_version_does_not_imply_published_packages(tmp_path, version, label):
    source = copy_source(tmp_path / "source")
    (source / "docs/published-releases.json").write_text(
        json.dumps({"schema_version": 1, "releases": {}})
    )
    project = source / "pyproject.toml"
    project.write_text(
        re.sub(
            r'^version = "[^"]+"',
            f'version = "{version}"',
            project.read_text(),
            count=1,
            flags=re.M,
        )
    )
    output = tmp_path / "output"
    manifest = build(output, source)
    assert manifest["version"] == version and manifest["publication_performed"] is False
    for name in ("www/index.html", "docs/installation.html"):
        html = (output / name).read_text()
        assert label in html and version in html
        assert 'content="noindex' in html
    assert (
        "PyPI/Homebrew packages are not available"
        in (output / "docs/installation.html").read_text()
    )
    verify(output, source)


def test_published_inventory_does_not_activate_a_later_candidate(tmp_path):
    source = copy_source(tmp_path / "source")
    project = source / "pyproject.toml"
    project.write_text(project.read_text().replace('version = "0.1.0"', 'version = "0.2.0"', 1))
    output = tmp_path / "output"
    manifest = build(output, source)
    assert manifest["version"] == "0.2.0" and manifest["publication_performed"] is False
    assert "docs/published-releases.json" in manifest["sources"]
    for name in ("www/index.html", "docs/installation.html"):
        html = (output / name).read_text()
        assert "Prepared release" in html and "0.2.0" in html
        assert "Public PyPI/Homebrew packages are not available" in html
    verify(output, source)


def test_public_launch_prepares_indexable_both_surfaces_without_deploying(tmp_path):
    output = tmp_path / "public"
    manifest = build(output, public_launch=True)
    assert manifest["indexing"] == "public"
    assert manifest["private_preparation"] is False
    assert manifest["publication_performed"] is False
    assert verify(output)["pages"] == len(GUIDES) + len(REFERENCES) + 4
    assert not (output / "www/docs").exists()
    landing = (output / "www/index.html").read_text()
    assert 'href="https://docs.kuberich.com/"' in landing
    assert 'href="https://docs.kuberich.com/installation.html"' in landing
    assert 'href="docs/' not in landing
    assert 'rel="canonical" href="https://kuberich.com/"' in landing
    assert (
        'rel="canonical" href="https://docs.kuberich.com/quickstart"'
        in (output / "docs/quickstart.html").read_text()
    )
    assert (output / "www/_redirects").read_text() == (
        "/docs https://docs.kuberich.com/ 301\n"
        "/docs/index.html https://docs.kuberich.com/ 301\n"
        "/docs/* https://docs.kuberich.com/:splat 301\n"
    )
    for path in output.rglob("*.html"):
        assert '<meta name="robots" content="index,follow">' in path.read_text()
        assert '<meta name="robots" content="noindex' not in path.read_text()
        assert "Development preview · 0.0.1.dev0" not in path.read_text()
        assert "Public PyPI/Homebrew packages are not available" not in path.read_text()
        assert "Full release qualification" not in path.read_text()
    for surface in ("www", "docs"):
        headers = (output / surface / "_headers").read_text()
        assert "X-Robots-Tag: index, follow" in headers
        assert "Content-Security-Policy:" in headers
        assert (output / surface / "robots.txt").read_text() == "User-agent: *\nAllow: /\n"


@pytest.mark.parametrize("fault", ["canonical", "guide-link", "redirect", "duplicate"])
def test_public_documentation_host_policy_rejects_inventoried_drift(tmp_path, fault):
    output = tmp_path / "output"
    build(output, public_launch=True)
    if fault == "redirect":
        path = output / "www/_redirects"
        path.write_text(path.read_text().replace("docs.kuberich.com", "wrong.example"))
    elif fault == "duplicate":
        path = output / "www/docs/index.html"
        path.parent.mkdir()
        path.write_text((output / "docs/index.html").read_text())
    else:
        path = output / "www/index.html"
        text = path.read_text()
        text = (
            text.replace(
                'rel="canonical" href="https://kuberich.com/"',
                'rel="canonical" href="https://wrong.example/"',
            )
            if fault == "canonical"
            else text.replace(
                'href="https://docs.kuberich.com/installation.html"',
                'href="https://docs.kuberich.com/missing.html"',
            )
        )
        path.write_text(text)
    refresh(output, path)
    with pytest.raises(ValueError, match=r"canonical|Broken|redirects|dedicated"):
        verify(output)


@pytest.mark.parametrize("version", ["0.1.0", "0.2.0", "0.0.1.dev0"])
def test_public_indexing_refuses_unpublished_versions_before_replacing_owned_output(
    tmp_path, version
):
    source = copy_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    original = (output / MARKER).read_bytes()
    project = source / "pyproject.toml"
    project.write_text(
        project.read_text().replace('version = "0.1.0"', f'version = "{version}"', 1)
    )
    (source / "docs/published-releases.json").write_text(
        json.dumps({"schema_version": 1, "releases": {}})
    )
    with pytest.raises(ValueError, match="verified published release"):
        build(output, source, public_launch=True)
    assert (output / MARKER).read_bytes() == original


@pytest.mark.parametrize("public_launch", [False, True])
@pytest.mark.parametrize(
    "fault", ["missing-meta", "opposite-meta", "headers", "robots", "state", "mode", "version"]
)
def test_checker_refuses_indexing_drift_with_refreshed_output_digests(
    tmp_path, public_launch, fault
):
    output = tmp_path / "output"
    build(output, public_launch=public_launch)
    if fault in {"state", "mode", "version"}:
        marker = output / MARKER
        manifest = json.loads(marker.read_text())
        if fault == "state":
            manifest["private_preparation"] = public_launch
        elif fault == "mode":
            manifest["indexing"] = {}
        else:
            manifest["version"] = "0.2.0"
        marker.write_text(json.dumps(manifest))
    else:
        path = (
            output
            / "docs"
            / {"headers": "_headers", "robots": "robots.txt"}.get(fault, "index.html")
        )
        text = path.read_text()
        if fault == "missing-meta":
            text = re.sub(r'  <meta name="robots"[^>]+>\n', "", text)
        elif fault == "opposite-meta":
            text = (
                text.replace('content="index,follow"', 'content="noindex,nofollow"')
                if public_launch
                else text.replace('content="noindex,nofollow"', 'content="index,follow"')
            )
        elif fault == "headers":
            text += "  Unexpected-Header: drift\n"
        else:
            text = "User-agent: *\n"
        path.write_text(text)
        refresh(output, path)
    with pytest.raises(ValueError, match=r"indexing|robots|headers|version"):
        verify(output)


@pytest.mark.parametrize(
    "record",
    [None, [], {"schema_version": 2, "releases": {}}, {"schema_version": 1, "releases": []}],
)
def test_invalid_publication_inventory_fails_the_build(tmp_path, record):
    source = copy_source(tmp_path / "source")
    (source / "docs/published-releases.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Invalid published release inventory"):
        build(tmp_path / "output", source)


def test_source_document_changes_flow_into_the_built_guide(tmp_path):
    source = copy_source(tmp_path / "source")
    quickstart = source / "docs/quickstart.md"
    text = quickstart.read_text().replace(
        "## If something fails",
        "## Owned guide change\n\nFresh maintained text.\n\n## If something fails",
    )
    quickstart.write_text(text)
    output = tmp_path / "output"
    result = build(output, source)
    assert "Fresh maintained text." in (output / "docs/quickstart.html").read_text()
    assert (
        result["sources"]["docs/quickstart.md"]
        == hashlib.sha256(quickstart.read_bytes()).hexdigest()
    )
    verify(output, source)


def test_duplicate_headings_have_distinct_anchors():
    tokens = MarkdownIt().parse("# Guide\n\n## One `key`\n\n## One `key`\n")
    assert heading_ids(tokens) == [("one-key", "One key"), ("one-key-1", "One key")]


def test_untrusted_markdown_html_is_text_and_unsafe_urls_do_not_become_links(tmp_path):
    source = copy_source(tmp_path / "source")
    guide = source / "docs/quickstart.md"
    guide.write_text(
        guide.read_text().replace(
            "## If something fails",
            '<script>alert("owned")</script>\n\n[bad](javascript:alert(1))\n\n## If something fails',
        )
    )
    output = tmp_path / "output"
    build(output, source)
    html = (output / "docs/quickstart.html").read_text()
    assert '<script>alert("owned")</script>' not in html
    assert 'href="javascript:' not in html
    assert "&lt;script&gt;" in html
    verify(output, source)


@pytest.mark.parametrize("mode", ["nonempty", "unexpected", "symlink"])
def test_build_does_not_discard_foreign_output(tmp_path, mode):
    output = tmp_path / "output"
    if mode == "nonempty":
        output.mkdir()
    else:
        build(output)
    private = output / "maintainer-file.txt"
    private.write_text("owned caller bytes")
    if mode == "symlink":
        linked = tmp_path / "linked"
        linked.symlink_to(output, target_is_directory=True)
        output = linked
    with pytest.raises(ValueError):
        build(output)
    assert private.read_text() == "owned caller bytes"


def test_changed_screenshot_requires_an_explicit_media_inventory_update(tmp_path):
    source = copy_source(tmp_path / "source")
    (source / "website/assets/workspace.svg").write_text("<svg/>")
    with pytest.raises(ValueError, match="Screenshot digest"):
        build(tmp_path / "output", source)
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "target", ["missing.html", "quickstart.html#missing", "javascript:alert(1)"]
)
def test_checker_rejects_broken_and_unsafe_links(tmp_path, target):
    output = tmp_path / "output"
    build(output)
    page = output / "docs/index.html"
    page.write_text(
        page.read_text().replace(
            "</article>", f'<a href="{target}">Owned negative control</a></article>'
        )
    )
    refresh(output, page)
    with pytest.raises(ValueError, match=r"Broken|Unsafe"):
        verify(output)


def test_checker_rejects_stale_digests_and_uninventoried_payloads(tmp_path):
    output = tmp_path / "output"
    build(output)
    page = output / "docs/index.html"
    page.write_text(page.read_text() + "stale")
    with pytest.raises(ValueError, match="digest"):
        verify(output)
    refresh(output, page)
    (output / "kubeconfig").write_text("owned negative control")
    with pytest.raises(ValueError, match="Uninventoried"):
        verify(output)


def test_reviewed_screenshots_are_inert_offline_vectors_with_current_identity():
    namespace = "{http://www.w3.org/2000/svg}"
    for name in ("workspace.svg", "logs.svg"):
        text = (ROOT / "website/assets" / name).read_text()
        svg = ET.fromstring(text)
        assert svg.tag == namespace + "svg"
        assert "KubeRich" in text and "@font-face" not in text
        assert "synthetic" not in text and "127.0.0.1" not in text
        for element in svg.iter():
            assert element.tag not in {
                namespace + "script",
                namespace + "foreignObject",
                namespace + "image",
            }
            assert not any(key.startswith("on") for key in element.attrib)


def test_reference_uses_selected_checkout_contracts_and_preserves_planned_status(tmp_path):
    source = copy_source(tmp_path / "source")
    cli = source / "src/kuberich/cli.py"
    cli.write_text(
        cli.read_text().replace(
            "    return parser",
            '    parser.add_argument("--owned-reference-probe", help="Owned reference probe")\n'
            "    return parser",
        )
    )
    registry = source / "src/kuberich/domain/registry.py"
    registry.write_text(
        registry.read_text().replace(
            '"deploy deployment"',
            '"deploy deployment owned-probe"',
        )
    )
    output = tmp_path / "output"
    build(output, source)
    for surface in ("www/docs", "docs"):
        assert "--owned-reference-probe" in (output / surface / "cli-reference.html").read_text()
        assert "owned-probe" in (output / surface / "resource-reference.html").read_text()
        progress = (output / surface / "capability-reference.html").read_text()
        assert "Status: planned" in progress and "CLI01" not in progress
        assert "Tasks:" not in progress and "#87" not in progress
        assert "not a promise of complete parity" in progress
    verify(output, source)


def test_public_guides_use_product_language_and_fictional_tutorials(tmp_path):
    """Visible user docs must not inherit issue IDs from internal acceptance records."""

    class VisibleText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []

        def handle_data(self, data):
            self.parts.append(data)

    output = tmp_path / "output"
    build(output)
    inventory = json.loads((ROOT / "docs/capabilities.json").read_text())
    for guide in GUIDES:
        authored = user_content((ROOT / "docs" / guide.source).read_text())
        assert not re.search(r"#[0-9]+|\b[A-Z][0-9]{2}\b|/(issues|pull)/", authored)
    for surface in ("www/docs", "docs"):
        for path in (output / surface).glob("*.html"):
            parser = VisibleText()
            html = path.read_text()
            parser.feed(html)
            text = " ".join(parser.parts)
            assert not re.search(r"#[0-9]+|\b[A-Z][0-9]{2}\b", text), path
            assert not re.search(r"github\.com/[^\s\"<>]+/(issues|pull)/", html), path
        progress = (output / surface / "capability-reference.html").read_text()
        for row in inventory["rows"]:
            assert row["id"] not in progress
            assert row["public_summary"]
        workflow = (output / surface / "everyday-workflow.html").read_text()
        assert "Every name here is fictional" in workflow and "demo-lab" in workflow
        assert "Ctrl+]" in workflow and "scale 3" in workflow
        troubleshooting = (output / surface / "troubleshooting.html").read_text()
        assert "Authentication fails while kubectl works" in troubleshooting
        assert "Report a problem" in troubleshooting
    verify(output)


def test_public_capability_summary_updates_without_rendering_tracking_fields(tmp_path):
    source = copy_source(tmp_path / "source")
    inventory_path = source / "docs/capabilities.json"
    inventory = json.loads(inventory_path.read_text())
    inventory["rows"][0]["public_summary"] = "Reviewed reader-facing behavior."
    inventory["rows"][0]["difference"] = "Internal historical issue #12345."
    inventory_path.write_text(json.dumps(inventory))
    output = tmp_path / "output"
    build(output, source)
    for surface in ("www/docs", "docs"):
        html = (output / surface / "capability-reference.html").read_text()
        assert "Reviewed reader-facing behavior." in html
        assert "#12345" not in html and "CLI01" not in html
    verify(output, source)


def test_checker_rejects_source_drift_and_new_unreceipted_modules(tmp_path):
    source = copy_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    guide = source / "docs/quickstart.md"
    original = guide.read_text()
    guide.write_text(original + "\nChanged after the build.\n")
    with pytest.raises(ValueError, match="source drift"):
        verify(output, source)
    guide.write_text(original)
    (source / "src/kuberich/new_contract.py").write_text('"""New application declaration."""\n')
    with pytest.raises(ValueError, match="source inventory"):
        verify(output, source)
