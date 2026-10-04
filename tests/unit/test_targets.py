"""Selection captures cannot follow a context switch or a same-name object recreation."""

import asyncio
from dataclasses import FrozenInstanceError, replace
from typing import cast
from uuid import UUID

import pytest

from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.errors import AppError
from kubetrol.security.arguments import MAX_ARGUMENT_CHARACTERS, freeze_arguments, validate_argument

SESSION = SessionIdentity("fixture-context", 1, UUID(int=1))


def target(**changes: object) -> ResourceTarget:
    values = dict(
        session=SESSION,
        group="",
        resource="pods",
        namespace="fixture-ns",
        name="fixture-pod",
        uid="synthetic-object-uid",
        container="main",
    )
    values.update(changes)
    return ResourceTarget(**values)  # Tests exercise runtime validation of foreign input.


@pytest.mark.parametrize("value", ["", None, 1, True, "x" * (MAX_ARGUMENT_CHARACTERS + 1)])
def test_arguments_refuse_invalid_types_and_size_without_echoing_values(value: object) -> None:
    with pytest.raises(AppError, match="bounded text"):
        validate_argument(cast(str, value))


@pytest.mark.parametrize(
    "value", ["pod\x00bad", "name\nforged", "\x1b]52;c;fake\x07", "bad\u202e", "\ud800"]
)
def test_argument_controls_are_rejected_without_silent_normalization(value: str) -> None:
    with pytest.raises(AppError, match="unsupported control") as error:
        validate_argument(value)
    assert value not in str(error.value)


@pytest.mark.parametrize(
    "value", ["café🙂", "path with spaces", "name; $(touch fake)", "--context=fixture"]
)
def test_literal_argv_preserves_unicode_spaces_and_shell_metacharacters(value: str) -> None:
    assert freeze_arguments(["kubectl", value]) == ("kubectl", value)


@pytest.mark.parametrize("values", [[], "kubectl get pods", b"kubectl"])
def test_argv_cannot_be_a_shell_command_or_empty_sequence(values: object) -> None:
    with pytest.raises(AppError, match="explicit argument sequence"):
        freeze_arguments(cast(list[str], values))


def test_argv_captures_values_before_the_original_list_changes() -> None:
    selected = ["kubectl", "--context=fixture", "get", "pods"]
    captured = freeze_arguments(selected)
    selected[1] = "--context=another-fixture"
    assert captured[1] == "--context=fixture"


@pytest.mark.parametrize("generation", [-1, True, 1.5, "1"])
def test_invalid_session_generations_are_rejected(generation: object) -> None:
    with pytest.raises(AppError, match="generation"):
        SessionIdentity("fixture", cast(int, generation))


def test_connection_ids_bind_even_identically_named_sessions_to_different_clients() -> None:
    first, second = SessionIdentity("fixture", 0), SessionIdentity("fixture", 0)
    assert first.connection_id != second.connection_id
    with pytest.raises(AppError, match="UUID"):
        SessionIdentity("fixture", 0, cast(UUID, "not-a-uuid"))


@pytest.mark.parametrize(
    "changes",
    [
        {"session": {}},
        {"name": "-f"},
        {"resource": "--force"},
        {"group": None},
        {"namespace": ""},
        {"container": ""},
        {"uid": ""},
        {"name": "pod\x1b[2J"},
    ],
)
def test_targets_reject_missing_or_unsafe_identity_fields(changes: dict[str, object]) -> None:
    with pytest.raises(AppError):
        target(**changes)


def test_core_group_cluster_scope_and_named_api_group_are_distinct_snapshots() -> None:
    core = target(namespace=None, container=None)
    grouped = target(group="apps", resource="deployments", container=None)
    assert core.group == "" and core.namespace is None
    assert grouped.group == "apps" and grouped.resource == "deployments"
    core.require_current(SESSION, uid=core.uid)
    with pytest.raises(FrozenInstanceError):
        core.name = "changed"
    with pytest.raises(FrozenInstanceError):
        core.session.context = "changed"


@pytest.mark.parametrize(
    "session,uid",
    [
        (replace(SESSION, context="another"), "synthetic-object-uid"),
        (replace(SESSION, generation=2), "synthetic-object-uid"),
        (replace(SESSION, connection_id=UUID(int=2)), "synthetic-object-uid"),
        (SESSION, "same-name-new-uid"),
    ],
)
def test_current_guard_refuses_context_generation_client_and_object_changes(
    session: SessionIdentity, uid: str
) -> None:
    with pytest.raises(AppError, match="target is stale"):
        target().require_current(session, uid=uid)


@pytest.mark.asyncio
async def test_capture_survives_a_selection_change_across_an_await() -> None:
    selected = {"name": "first-pod", "uid": "first-uid"}
    captured = target(**selected)
    await asyncio.sleep(0)
    selected.update(name="second-pod", uid="second-uid")
    assert (captured.name, captured.uid) == ("first-pod", "first-uid")
    with pytest.raises(AppError, match="target is stale"):
        captured.require_current(SESSION, uid=selected["uid"])
