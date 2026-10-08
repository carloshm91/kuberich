"""Launch-site behavior and negative controls; application coverage is separate."""

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from scripts.build_site import GUIDES, MARKER, ROOT, build, heading_ids
from scripts.check_site import verify


def copy_source(destination: Path) -> Path:
    for relative in ("website", "docs"):
        shutil.copytree(ROOT / relative, destination / relative)
    (destination / "scripts").mkdir()
    shutil.copyfile(ROOT / "scripts/build_site.py", destination / "scripts/build_site.py")
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
    assert evidence["pages"] == 2 * len(GUIDES) + 5
    assert evidence["local_links_and_assets"] > 500
    for name in ("www/docs/quickstart.html", "docs/quickstart.html"):
        html = (first / name).read_text()
        assert "uv tool install --python 3.12" in html
        assert "kuberich --kubeconfig" in html
        assert "--readonly" in html and "--write" in html
        assert "uninstall" in html and "macOS/full hosted" in html
        assert "PyPI/Homebrew are not available" in html
        assert "Maintainer rehearsal" not in html


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
    verify(output)


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
    verify(output)


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
