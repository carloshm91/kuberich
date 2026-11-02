"""Published predecessor selection and real Git/formula bindings, without Homebrew."""

import hashlib
import json

import pytest

from scripts.homebrew import FORMULA, bottle_root, with_bottles
from tests.support import source_candidate as candidates
from tests.support.distribution import ROOT, run


@pytest.mark.parametrize(
    "candidate,expected",
    [("0.3.0rc1", "0.2.0"), ("0.3.0", "0.2.0"), ("0.3.1", "0.3.0"), ("0.4.0", "0.3.0")],
)
def test_newest_stable_publication_is_strictly_before_the_candidate(candidate, expected):
    releases = {v: {} for v in ("0.1.0", "0.2.0", "0.3.0rc1", "0.3.0", "0.4.0.dev1")}
    assert candidates.published_baseline(candidate, releases)["version"] == expected
    with pytest.raises(ValueError, match="predecessor"):
        candidates.published_baseline("0.1.0", releases)


def test_prepared_source_keeps_private_rc_and_real_published_upgrade_paths():
    releases = json.loads((ROOT / "docs/published-releases.json").read_text())["releases"]
    baseline = candidates.published_baseline("0.3.0", releases)
    assert baseline["source_commit"] == releases[baseline["version"]]["source_commit"]
    assert (
        baseline["homebrew_formula_commit"]
        == releases[baseline["version"]]["homebrew_formula_commit"]
    )
    assert candidates.source_upgrade_versions("0.3.0") == ("0.3.0rc1", "0.3.0")
    assert candidates.source_upgrade_versions("0.3.0", baseline) == ("0.2.0", "0.3.0")
    assert candidates.source_upgrade_versions("0.3.0rc1") == ("0.1.0rc1", "0.1.0rc2")
    with pytest.raises(AssertionError):
        candidates.source_upgrade_versions("0.2.0", baseline)


@pytest.fixture
def published_repository(tmp_path, monkeypatch):
    repository = tmp_path / "upstream"
    repository.mkdir()
    run(["git", "init", "--initial-branch=main"], repository)
    formula = repository / FORMULA
    formula.parent.mkdir()
    source_commit = "a" * 40
    source = (
        f"# Source version: 0.2.0\n# Source commit: {source_commit}\n"
        "class Kuberich < Formula\n"
        '  url "https://files.pythonhosted.org/packages/owned/kuberich-0.2.0.tar.gz"\n'
        f'  sha256 "{hashlib.sha256(b"owned published source").hexdigest()}"\n'
        '  license "Apache-2.0"\nend\n'
    )

    def commit(text):
        formula.write_text(text)
        run(["git", "add", FORMULA], repository)
        run(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-m", "test: immutable owned formula"], repository)  # fmt: skip
        return run(["git", "rev-parse", "HEAD"], repository).stdout.strip()

    baseline = {
        "version": "0.2.0",
        "source_commit": source_commit,
        "homebrew_formula_commit": commit(source),
    }
    digest = hashlib.sha256(b"owned published bottle").hexdigest()
    text = with_bottles(
        source, {"x86_64_linux": {"cellar": ":any", "sha256": digest}}, bottle_root("0.2.0")
    )
    baseline["homebrew_bottle_commit"] = commit(text)
    monkeypatch.setattr(candidates, "TAP_URL", repository.as_uri())
    return baseline, source, text, digest


def test_published_paths_use_pinned_git_bytes_and_bind_the_same_distribution(
    published_repository, tmp_path
):
    baseline, source, bottled, digest = published_repository
    tap = tmp_path / "tap"
    plain = candidates.published_tap(tap, baseline)
    assert plain["tap_commit"] == baseline["homebrew_formula_commit"]
    assert plain["formula_sha256"] == hashlib.sha256(source.encode()).hexdigest()
    assert plain["bottles"] == {}
    actual = candidates.published_tap(tap, baseline, bottled=True)
    assert actual["tap_commit"] == baseline["homebrew_bottle_commit"]
    assert actual["formula_sha256"] == hashlib.sha256(bottled.encode()).hexdigest()
    assert (actual["sdist_url"], actual["sdist_sha256"]) == (
        plain["sdist_url"],
        plain["sdist_sha256"],
    )
    assert actual["bottles"] == {"x86_64_linux": digest}
    (tap / FORMULA).write_text(bottled.replace(digest, "b" * 64))
    with pytest.raises(AssertionError):
        candidates.published_tap(tap, baseline, bottled=True)


@pytest.mark.parametrize("field,value", [("version", "0.3.0"), ("source_commit", "b" * 40)])
def test_mismatched_publication_metadata_cannot_relabel_the_pinned_formula(
    published_repository, tmp_path, field, value
):
    baseline, _, _, _ = published_repository
    with pytest.raises(AssertionError):
        candidates.published_tap(tmp_path / "tap", {**baseline, field: value})


def test_bottle_upgrade_requires_a_reviewed_revision_and_an_actual_pour(
    published_repository, tmp_path
):
    baseline, _, _, digest = published_repository
    with pytest.raises(ValueError, match="reviewed immutable"):
        candidates.published_tap(
            tmp_path / "unreviewed", {**baseline, "homebrew_bottle_commit": None}, bottled=True
        )
    actual = candidates.published_tap(tmp_path / "tap", baseline, bottled=True)
    poured = "Pouring kuberich--0.2.0.x86_64_linux.bottle.tar.gz"
    assert candidates.published_bottle_pour(actual, poured) == {
        "tag": "x86_64_linux",
        "sha256": digest,
    }
    for wrong in (
        "Building from source",
        poured.replace("0.2.0", "0.3.0"),
        poured + " Resource kuberich--dep",
        poured + " files.pythonhosted.org",
    ):
        with pytest.raises(AssertionError):
            candidates.published_bottle_pour(actual, wrong)
