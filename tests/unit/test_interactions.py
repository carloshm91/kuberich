"""Session commands, draft restoration, UID ranges and explicit preferences."""

import pytest

from kuberich.config.navigation import NavigationPreferences, parse_navigation
from kuberich.domain.interactions import CommandHistory, RangeSelection, interaction_command
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import CommandService, suggestions


def test_entry_history_is_bounded_memory_only_and_restores_draft():
    history = CommandHistory()
    assert history.move("draft", -1) == "draft"
    with pytest.raises(AppError, match="previous"):
        history.repeat()
    history.record("")
    history.record("!!")
    for i in range(40):
        history.record(f"ns team-{i}")
    history.record(":ns team-39")
    assert len(history.entries) == 32 and history.repeat() == "ns team-39"
    assert history.move("draft", 1) == "draft"
    assert history.move("draft", -1) == "ns team-39"
    assert history.move("", -1) == "ns team-38"
    assert history.move("", 1) == "ns team-39"
    assert history.move("", 1) == "draft"
    for _ in range(40):
        history.move("incomplete", -1)
    assert history.position == 0
    history.record("po")
    assert history.position is None


@pytest.mark.parametrize(
    "text",
    [
        "wide",
        "errors",
        "copy",
        "copyns",
        "copytext",
        "!!",
        "headless",
        "crumbsless",
        "fullscreen",
        "mark",
        "range",
        "selectall",
        "selectnone",
        "favorites",
        "favorite add team",
        "favorite remove team",
    ],
)
def test_navigation_commands_share_resolver_and_do_not_break_familiar_completions(text):
    assert CommandService(AccessPolicy(True)).resolve(text) == interaction_command(text)
    assert suggestions("p", (), ())[0] == "po"
    assert suggestions("c", (), ())[0] == "context"
    assert interaction_command("pods") is None


@pytest.mark.parametrize(
    "text", ["wide x", "favorite", "favorite bad team", "favorite add", "favorite add bad/name"]
)
def test_invalid_navigation_arguments_are_refused(text):
    with pytest.raises(AppError):
        interaction_command(text)


def test_ranges_follow_visible_order_and_prune_deleted_uid_not_recreated_name():
    selection = RangeSelection()
    selection.apply("mark", None, ())
    selection.apply("range", "a", ("a", "b", "c", "d"))
    assert selection.anchor == "a" and selection.marked == {"a"}
    selection.apply("range", "c", ("a", "b", "c", "d"))
    assert selection.marked == {"a", "b", "c"}
    selection.apply("mark", "b", ("a", "b", "c", "d"))
    assert selection.marked == {"a", "c"}
    selection.prune(("new-a", "c", "d"))
    assert selection.marked == {"c"} and selection.anchor is None
    selection.apply("selectall", None, ("c", "d"))
    assert selection.marked == {"c", "d"}
    selection.apply("selectnone", None, ("c", "d"))
    assert not selection.marked
    with pytest.raises(AppError, match="100"):
        selection.apply("selectall", None, tuple(str(i) for i in range(101)))
    assert not selection.marked


@pytest.mark.parametrize(
    "value",
    [
        {"mouse": "true"},
        {"favorites": []},
        {"favorites": {str(i): [] for i in range(129)}},
        {"favorites": {1: []}},
        {"favorites": {"": []}},
        {"favorites": {"x" * 254: []}},
        {"favorites": {"bad\ncontext": []}},
        {"favorites": {"ctx": "team"}},
        {"favorites": {"ctx": [["unhashable"]]}},
        {"favorites": {"ctx": ["team", "team"]}},
        {"favorites": {"ctx": [f"team-{i}" for i in range(65)]}},
        {"favorites": {"ctx": ["bad/name"]}},
    ],
)
def test_invalid_local_interaction_preferences_fail_closed(value):
    with pytest.raises(AppError):
        parse_navigation({"schema_version": 1, **value})


def test_favorites_are_exact_context_local_and_mouse_is_explicit():
    value = parse_navigation(
        {"schema_version": 1, "mouse": True, "favorites": {"ctx-a": ["team-z", "team-a"]}}
    )
    assert value.mouse and dict(value.favorites)["ctx-a"] == ("team-a", "team-z")
    updated = value.with_favorite("ctx-b", "team-a")
    assert dict(updated.favorites) == {"ctx-a": ("team-a", "team-z"), "ctx-b": ("team-a",)}
    assert not dict(updated.with_favorite("ctx-b", "team-a", remove=True).favorites)["ctx-b"]
    assert parse_navigation(updated.mapping()) == updated
    assert not NavigationPreferences().mouse
