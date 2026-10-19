"""Context rename/delete planning edits exactly one file and never touches credentials."""

from pathlib import Path

import pytest

from kuberich.domain.kubeconfig_edit import (
    ContextChange,
    KubeconfigDocument,
    context_name,
    plan_context_edit,
)
from kuberich.errors import AppError

CLUSTERS = [{"name": "owned", "cluster": {"server": "https://127.0.0.1:1"}}]
USERS = [{"name": "owned", "user": {"token": "synthetic-token"}}]


def document(name, contexts, current=None, *, commented=False):
    data = {
        "contexts": [{"name": item, "context": {"cluster": "owned"}} for item in contexts],
        "clusters": CLUSTERS,
        "users": USERS,
    }
    if current is not None:
        data["current-context"] = current
    return KubeconfigDocument(Path(f"/owned/{name}"), data, f"digest-{name}", commented)


def test_rename_changes_only_the_owning_entry_and_its_current_context():
    first = document("first", ["alpha", "beta"], current="alpha", commented=True)
    plan = plan_context_edit((first,), ContextChange.RENAME, "alpha", "short")
    assert plan.path == Path("/owned/first") and plan.digest == "digest-first"
    assert [entry["name"] for entry in plan.document["contexts"]] == ["short", "beta"]
    assert plan.document["current-context"] == "short"
    assert plan.document["clusters"] == CLUSTERS and plan.document["users"] == USERS
    assert first.data["contexts"][0]["name"] == "alpha"  # the reviewed input is untouched
    assert plan.renames_current and not plan.clears_current and plan.confirmation is None
    summary = "\n".join(plan.summary)
    assert "File: /owned/first" in summary and "alpha → short" in summary
    assert "renamed too" in summary and "Comments" in summary and "backup" in summary


def test_rename_in_second_file_leaves_other_current_context_alone():
    first = document("first", ["alpha"], current="alpha")
    second = document("second", ["beta"], current="beta")
    plan = plan_context_edit((first, second), ContextChange.RENAME, "beta", "gamma")
    assert plan.path == Path("/owned/second")
    assert plan.document["current-context"] == "gamma" and plan.renames_current
    other = plan_context_edit((first, second), ContextChange.RENAME, "alpha", "delta")
    assert other.path == Path("/owned/first") and other.document["current-context"] == "delta"
    plain = plan_context_edit(
        (document("plain", ["one", "two"]),), ContextChange.RENAME, "two", "z"
    )
    assert "current-context" not in plain.document and not plain.renames_current


def test_delete_clears_owned_current_context_only_with_stronger_confirmation():
    first = document("first", ["alpha", "beta"], current="alpha")
    plain = plan_context_edit((first,), ContextChange.DELETE, "beta")
    assert [entry["name"] for entry in plain.document["contexts"]] == ["alpha"]
    assert plain.document["current-context"] == "alpha" and plain.confirmation == "DELETE"
    assert "Delete context: beta" in plain.summary
    current = plan_context_edit((first,), ContextChange.DELETE, "alpha", connected="beta")
    assert "current-context" not in current.document
    assert current.clears_current and current.confirmation == "DELETE CURRENT"
    assert any("cleared" in line for line in current.summary)


def test_missing_contexts_section_and_unset_current_context():
    empty = KubeconfigDocument(Path("/owned/empty"), {}, "digest-empty")
    owner = document("owner", ["alpha"])
    plan = plan_context_edit((empty, owner), ContextChange.DELETE, "alpha")
    assert plan.document["contexts"] == [] and not plan.clears_current


@pytest.mark.parametrize(
    "documents,change,name,new_name,connected,message",
    [
        ((), ContextChange.DELETE, "alpha", None, None, "not defined"),
        (
            (document("a", ["alpha"]), document("b", ["alpha"])),
            ContextChange.DELETE,
            "alpha",
            None,
            None,
            "more than one",
        ),
        (
            (document("a", ["beta"], current="alpha"), document("b", ["alpha"])),
            ContextChange.RENAME,
            "alpha",
            "gamma",
            None,
            "Another kubeconfig file",
        ),
        (
            (document("a", ["alpha", "beta"]),),
            ContextChange.RENAME,
            "alpha",
            "beta",
            None,
            "already",
        ),
        (
            (document("a", ["alpha"]), document("b", ["beta"])),
            ContextChange.RENAME,
            "alpha",
            "beta",
            None,
            "already",
        ),
        ((document("a", ["alpha"]),), ContextChange.RENAME, "alpha", "alpha", None, "different"),
        ((document("a", ["alpha"]),), ContextChange.RENAME, "alpha", None, None, "1-253"),
        ((document("a", ["alpha"]),), ContextChange.DELETE, "alpha", "x", None, "new name"),
        ((document("a", ["alpha"]),), ContextChange.DELETE, "alpha", None, "alpha", "Switch"),
        ((document("a", ["alpha"]),), "rename", "alpha", None, None, "rename or delete"),
    ],
)
def test_ambiguous_or_invalid_edits_are_refused(
    documents, change, name, new_name, connected, message
):
    with pytest.raises(AppError, match=message):
        plan_context_edit(documents, change, name, new_name, connected=connected)


@pytest.mark.parametrize("contexts", ["invalid", [{"context": {}}], ["alpha"], [{"name": 3}]])
def test_malformed_context_sections_are_refused(contexts):
    malformed = KubeconfigDocument(Path("/owned/bad"), {"contexts": contexts}, "digest")
    with pytest.raises(AppError, match="named entries"):
        plan_context_edit((malformed,), ContextChange.DELETE, "alpha")


@pytest.mark.parametrize("value", ["", " padded", "padded ", "x" * 254, 3, None, "bad\x1bname"])
def test_context_names_are_bounded_text(value):
    with pytest.raises(AppError):
        context_name(value)


def test_long_valid_names_such_as_eks_arns_are_accepted():
    arn = "arn:aws:eks:us-east-1:123456789012:cluster/owned-production"
    assert context_name(arn) == arn
