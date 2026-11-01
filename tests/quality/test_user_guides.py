"""Task-guide budgets, active redirects, exact history and source-generated lookup."""

import hashlib
import json
import re

import pytest

from scripts.build_site import ROOT, build
from scripts.check_site import verify
from scripts.documentation import load_navigation
from scripts.site_reference import check_reference_files, reference_files
from scripts.site_schema import fields
from tests.support.site_source import copy_source, refresh


def test_every_user_page_fits_budget_and_checked_reference_is_current():
    catalog = load_navigation(ROOT)
    generated = reference_files(ROOT)
    assert catalog.user_page_count == 20
    assert len(catalog.guides) == 15 and len(catalog.references) == 4
    for guide in catalog.pages:
        text = (
            generated[guide.source]
            if guide.generated
            else "\n".join((ROOT / "docs" / source).read_text() for source in guide.sources)
        )
        assert len(text.splitlines()) <= 250, guide.source
        assert not re.search(
            r"\b(?:owned|bounded|captured|qualified|lifecycle|projection|provenance|preflight|orchestration|invariant)\b",
            text,
            re.I,
        ), guide.source
        assert not re.search(r"/(?:issues|pull)/|actions/runs/|\b[A-Z][0-9]{2}\b", text), (
            guide.source
        )
    check_reference_files(ROOT)


def test_superseded_guides_preserve_exact_source_bytes_outside_website():
    record = json.loads((ROOT / "engineering/guide-history/source-map.json").read_text())
    archive = (ROOT / record["archive"]).read_bytes()
    assert record["source_commit"] == "a14d1ab65201a214fe178c0f01d1d4e9bcc59a1d"
    assert len(record["documents"]) == 30
    baseline = json.loads((ROOT / "docs/documentation-plan.json").read_text())
    mapped = {item["source"]: item for item in baseline["documents"]}
    for source in record["documents"]:
        content = archive[source["byte_start"] : source["byte_end"]]
        assert hashlib.sha256(content).hexdigest() == source["sha256"]
        assert mapped[source["source"]]["baseline_sha256"] == source["sha256"]
        assert record["archive"] in mapped[source["source"]]["destinations"]
    assert not any("guide-history" in guide.source for guide in load_navigation(ROOT).pages)


def test_all_retired_routes_and_deep_links_reach_active_guidance(tmp_path):
    source = copy_source(tmp_path / "source")
    catalog = load_navigation(source)
    links = []
    for route in catalog.legacy_routes:
        assert route.fragments
        for old, target in route.fragments:
            links.append(f"[Old guide]({route.source}#{old})")
            assert target != route.anchor
    quickstart = source / "docs/quickstart.md"
    # The link fixture is separate from the prose budget: do not make an enormous page.
    authored = quickstart.read_text()
    chunks = [links[index : index + 100] for index in range(0, len(links), 100)]
    for index, chunk in enumerate(chunks):
        quickstart.write_text(authored + "\n" + "\n".join(chunk) + "\n")
        output = tmp_path / f"output-{index}"
        manifest = build(output, source)
        verify(output, source)
        for surface in ("docs", "www/docs"):
            rendered = (output / surface / "quickstart.html").read_text()
            for route in catalog.legacy_routes:
                target = route.target.removesuffix(".md") + ".html"
                for old, active in route.fragments:
                    if f"[Old guide]({route.source}#{old})" in chunk:
                        assert f'href="{target}#{active}"' in rendered
            assert "guide-history" not in rendered
        assert manifest["documentation_pages"] == 20
    redirects = (output / "docs/_redirects").read_text()
    for route in catalog.legacy_routes:
        # No Location fragment discards the old hash; the active page keeps its ID.
        assert f"/{route.source[:-3]}.html /{route.target[:-3]}.html 301\n" in redirects


@pytest.mark.parametrize(
    "fault", ["missing_target", "unsafe_alias", "line_budget", "checked_snapshot"]
)
def test_docs_reject_invalid_aliases_oversize_pages_and_stale_reference(tmp_path, fault):
    source = copy_source(tmp_path / "source")
    navigation = source / "docs/navigation.json"
    data = json.loads(navigation.read_text())
    if fault in {"missing_target", "unsafe_alias"}:
        page = data["sections"][0]["pages"][0]
        page["anchors"]["probe" if fault == "missing_target" else "../outside"] = "missing-target"
        navigation.write_text(json.dumps(data))
    elif fault == "line_budget":
        (source / "docs/quickstart.md").write_text("# Oversized\n" + "Text\n" * 250)
    else:
        path = source / "docs/config-reference.md"
        path.write_text(path.read_text() + "stale\n")
        with pytest.raises(ValueError, match="stale"):
            check_reference_files(source)
        return
    with pytest.raises(ValueError, match=r"alias|budget"):
        build(tmp_path / "output", source)


@pytest.mark.parametrize("declaration", ["alias", "key", "flag", "schema"])
def test_reference_drift_follows_actual_selected_checkout_declarations(tmp_path, declaration):
    source = copy_source(tmp_path / "source")
    changes = {
        "alias": (
            "services/commands.py",
            '    "about": Command.ABOUT,',
            '    "probealias": Command.ABOUT,\n    "about": Command.ABOUT,',
        ),
        "key": ("domain/keyboard.py", '("down", "j")', '("down", "b")'),
        "flag": (
            "cli.py",
            "    return parser",
            '    parser.add_argument("--probe-reference", help="Reference probe")\n    return parser',
        ),
        "schema": (
            "domain/appearance.py",
            '        "full_gvr_titles",',
            '        "full_gvr_titles",\n        "probe_schema",',
        ),
    }
    filename, old, replacement = changes[declaration]
    path = source / "src/kuberich" / filename
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, replacement, 1))
    with pytest.raises(ValueError, match="stale"):
        check_reference_files(source)
    if declaration == "schema":
        assert "appearance.probe_schema" in {item["path"] for item in fields(source)}


def test_schema_includes_optional_fields_and_real_defaults_without_loading_user_files():
    schema = {item["path"]: item["omitted"] for item in fields(ROOT)}
    assert schema["appearance.full_gvr_titles"] == "false"
    assert schema["navigation.mouse"] == "false"
    assert schema["navigation.favorites"] == "{}"
    assert schema["plugins.commands.NAME.dangerous"] == "true"
    assert schema["plugins.commands.NAME.output_limit"] == "65536"
    assert schema["plugins.commands.NAME.inputs[].required"] == "true"
    assert schema["forwarding.presets.NAME.retries"] == "0"
    assert "jumps.definitions.NAME.source" in schema
    assert "navigation.views.RESOURCE.columns[].alignment" in schema


def test_rehashed_missing_external_legacy_fragment_is_rejected(tmp_path):
    source = copy_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    path = output / "docs/context-sessions.html"
    path.write_text(
        path.read_text().replace('id="supported-local-contracts"', 'id="wrong-contracts"')
    )
    refresh(output, path)
    with pytest.raises(ValueError, match="redirect"):
        verify(output, source)


def test_nullable_defaults_and_forwarding_context_schema_follow_actual_branches():
    schema = {item["path"]: item["omitted"] for item in fields(ROOT)}
    assert schema["plugins.commands.NAME.shortcut"] == "null (before validation)"
    assert schema["forwarding.contexts.NAME.auto_annotations"] == "false"
    assert schema["forwarding.contexts.NAME.presets"] == "{}"
    assert "forwarding.contexts.NAME.schema_version" not in schema
    assert "forwarding.contexts.NAME.contexts" not in schema


def test_annotated_accepted_field_sets_are_not_silently_lost(tmp_path):
    source = copy_source(tmp_path / "source")
    path = source / "src/kuberich/domain/appearance.py"
    path.write_text(
        path.read_text().replace("COLORS = frozenset(", "COLORS: frozenset[str] = frozenset(", 1)
    )
    schema = {item["path"] for item in fields(source)}
    assert "appearance.themes.NAME.primary" in schema
    assert "appearance.themes.NAME.background" in schema
    assert "appearance.themes.NAME.dark" in schema


def test_unknown_schema_field_set_cannot_silently_drop_part_of_a_union(tmp_path):
    source = copy_source(tmp_path / "source")
    path = source / "src/kuberich/domain/appearance.py"
    path.write_text(
        path.read_text().replace(
            'fields.keys() - COLORS - {"dark"}', 'fields.keys() - UNDECLARED - {"dark"}', 1
        )
    )
    with pytest.raises(ValueError, match="Unresolved schema"):
        fields(source)


def test_renamed_generated_reference_headings_keep_old_deep_links(tmp_path):
    source = copy_source(tmp_path / "source")
    output = tmp_path / "output"
    build(output, source)
    for guide in load_navigation(source).references:
        html = (output / "docs" / guide.filename).read_text()
        for old, active in guide.aliases:
            assert f'id="{old}"' in html
            assert f'id="{active}"' in html
    verify(output, source)


def test_new_preference_extension_requires_a_real_schema_generator(tmp_path):
    source = copy_source(tmp_path / "source")
    path = source / "src/kuberich/config/schema.py"
    text = path.read_text()
    assert '"context_settings"' in text
    path.write_text(
        text.replace('"context_settings"', '"context_settings", "unmapped_extension"', 1)
    )
    with pytest.raises(ValueError, match="schema parsers"):
        reference_files(source)
