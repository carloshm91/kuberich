"""Real exported frames retain bounded identities for their captured local membership."""

import copy
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

import pytest

from kuberich.domain.curated_navigation import (
    AllResources,
    IngressClassName,
    LabelsMatch,
    PodRuntimeClass,
    ResolvedCollectionBookmark,
)
from kuberich.domain.events import EventOptions
from kuberich.domain.exports import TableSource, prepare_capture, read_artifact
from kuberich.domain.relationships import structured_selector
from kuberich.domain.resource_queries import ResourceQuery
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_resources import CuratedResourcesApi, curated_resources_api
from tests.support.events import EVENT_CANARY
from tests.support.workspace import wait_for
from tests.ui.test_curated_resources import app_for, started
from tests.ui.test_events_workspace import events_ready

ARTIFACT_ID = UUID("00000000-0000-0000-0000-000000000232")
MEMBERSHIP_CANARY = "private-membership-canary"


def screen_lease(app):
    return next(
        (
            lease
            for kind, lease in app.export_sources.capture(datetime.now(UTC))
            if kind == "screen"
        ),
        None,
    )


async def captured(app, pilot):
    await wait_for(lambda: screen_lease(app) is not None)
    await pilot.pause()
    lease = screen_lease(app)
    assert lease is not None and lease.current()
    assert isinstance(lease.capture.source, TableSource)
    return lease


def reopened(lease, path):
    prepared = prepare_capture(lease.capture, "screen", artifact_id=ARTIFACT_ID)
    path.write_bytes(prepared.payload)
    result = read_artifact(path.read_bytes(), artifact_id=ARTIFACT_ID)
    assert result.metadata == prepared.metadata
    assert read_artifact(result.payload, artifact_id=ARTIFACT_ID).metadata == result.metadata
    assert result.metadata.schema_version == 1
    assert EVENT_CANARY.encode() not in prepared.payload
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["raw", "warnings", "grouped", "members"])
async def test_real_event_export_reopens_with_actual_presentation_and_membership(tmp_path, mode):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, api.resource("events", group="events.k8s.io"), count=7)
            requests = len(api.requests)
            warnings = mode != "raw"
            grouped = mode in {"grouped", "members"}
            options = EventOptions(grouped=grouped, warnings_only=warnings)
            app.navigator.events_options(options)
            await wait_for(lambda: app.events_table.options == options)
            group_key = None
            if mode == "members":
                for row in app.events_table.ordered_rows:
                    app.events_table.move_cursor(row=app.events_table.get_row_index(row.key))
                    group = app.events_table.selected_group()
                    if group is not None and len(group.member_uids) == 3:
                        group_key = group.row_key
                        break
                assert group_key is not None
                await pilot.press("enter")
                await wait_for(lambda: app.events_table.options.members is not None)
                grouped = False
            lease = await captured(app, pilot)
            result = reopened(lease, tmp_path / (mode + ".txt"))
            notices = result.metadata.notices
            assert (
                f"Event presentation: warnings_only={str(warnings).lower()}; grouped={str(grouped).lower()}."
                in notices
            )
            assert (
                "Event local membership: all retained Event objects."
                if group_key is None
                else f"Event local membership: {group_key} (exact captured group predicate identity; not a reconstructible query)."
            ) in notices
            assert len(api.requests) == requests


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["all", "labels", "runtime", "ingress"])
async def test_real_curated_export_reopens_with_captured_predicate_identity(tmp_path, kind):
    api = CuratedResourcesApi()
    resource = api.resource("ingresses" if kind == "ingress" else "pods")
    first = api.objects(resource)[0]
    first["metadata"].setdefault("labels", {})["membership"] = MEMBERSHIP_CANARY
    first["spec"]["ingressClassName" if kind == "ingress" else "runtimeClassName"] = (
        MEMBERSHIP_CANARY
    )
    api.put(resource, first)
    second = copy.deepcopy(first)
    second["metadata"].update(name="other-member", uid="other-member")
    second["metadata"]["labels"]["membership"] = "other"
    second["spec"]["ingressClassName" if kind == "ingress" else "runtimeClassName"] = "other"
    api.put(resource, second)
    predicate = (
        AllResources()
        if kind == "all"
        else LabelsMatch(structured_selector({"matchLabels": {"membership": MEMBERSHIP_CANARY}}))
        if kind == "labels"
        else PodRuntimeClass(MEMBERSHIP_CANARY)
        if kind == "runtime"
        else IngressClassName(MEMBERSHIP_CANARY)
    )
    digest = hashlib.sha256(
        json.dumps(
            asdict(predicate), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            app.navigator.open_resource(
                resource,
                "team",
                bookmark=ResolvedCollectionBookmark(resource, "team", predicate, ResourceQuery()),
            )
            await wait_for(
                lambda: (
                    app.state.scope is not None
                    and app.state.scope.resource == resource
                    and app.resources.row_count == (2 if kind == "all" else 1)
                )
            )
            lease = await captured(app, pilot)
            assert len(lease.capture.source.rows) == (2 if kind == "all" else 1)
            result = reopened(lease, tmp_path / (kind + ".txt"))
            assert (
                f"Captured local membership: {type(predicate).__name__}; SHA-256 {digest} (predicate identity only; not a reconstructible query)."
                in result.metadata.notices
            )
            assert MEMBERSHIP_CANARY not in " ".join(result.metadata.notices)


@pytest.mark.asyncio
async def test_event_pending_option_changes_revoke_old_leases_before_new_frames(tmp_path):
    api = CuratedEventsApi()
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, api.resource("events", group="events.k8s.io"), count=7)
            raw = await captured(app, pilot)
            before = len(api.requests)
            options = EventOptions(warnings_only=True)
            app.navigator.events_options(options)
            assert not raw.current()
            assert screen_lease(app) is None
            await wait_for(lambda: app.events_table.options == options)
            warnings = await captured(app, pilot)
            assert (
                "Event presentation: warnings_only=true; grouped=false."
                in reopened(warnings, tmp_path / "warnings.txt").metadata.notices
            )
            assert (
                "Event presentation: warnings_only=false; grouped=false."
                in reopened(raw, tmp_path / "captured-before-change.txt").metadata.notices
            )
            options = EventOptions(warnings_only=True, grouped=True)
            app.navigator.events_options(options)
            assert not warnings.current()
            assert screen_lease(app) is None
            await wait_for(lambda: app.events_table.options == options)
            grouped = await captured(app, pilot)
            assert (
                "Event presentation: warnings_only=true; grouped=true."
                in reopened(grouped, tmp_path / "grouped.txt").metadata.notices
            )
            group = app.events_table.selected_group()
            assert group is not None
            assert app.navigator.events_selected()
            assert not grouped.current()
            assert screen_lease(app) is None
            await wait_for(lambda: app.events_table.options.members is not None)
            members = await captured(app, pilot)
            assert (
                f"Event local membership: {group.row_key} (exact captured group predicate identity; not a reconstructible query)."
                in reopened(members, tmp_path / "members.txt").metadata.notices
            )
            assert not raw.current() and not warnings.current() and not grouped.current()
            assert len(api.requests) == before


@pytest.mark.asyncio
async def test_event_full_group_identity_is_hashed_without_copying_long_reason_to_metadata(
    tmp_path,
):
    api = CuratedEventsApi()
    resource = api.resource("events", group="events.k8s.io")
    prefix = "synthetic-group-identity-canary-" + "x" * 8000
    for body in api.objects(resource):
        index = int(body["metadata"]["name"].rsplit("-", 1)[1])
        if index in {0, 1, 2, 6}:
            body["reason"] = prefix + ("a" if index != 6 else "b")
            api.put(resource, body)
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            await app.run_command("events team")
            await events_ready(app, resource, count=7)
            options = EventOptions(grouped=True, warnings_only=True)
            app.navigator.events_options(options)
            await wait_for(lambda: app.events_table.options == options)
            groups = []
            for row in app.events_table.ordered_rows:
                app.events_table.move_cursor(row=app.events_table.get_row_index(row.key))
                group = app.events_table.selected_group()
                if group is not None and (group.key.reason or "").startswith(prefix):
                    groups.append(group)
            assert len(groups) == 2 and groups[0].row_key != groups[1].row_key
            notices = []
            for index, group in enumerate(groups):
                app.events_table.move_cursor(row=app.events_table.get_row_index(group.row_key))
                assert app.navigator.events_selected()
                await wait_for(lambda: app.events_table.options.members is not None)
                lease = await captured(app, pilot)
                result = reopened(lease, tmp_path / f"long-members-{index}.txt")
                expected = (
                    f"Event local membership: {group.row_key} "
                    "(exact captured group predicate identity; not a reconstructible query)."
                )
                assert expected in result.metadata.notices
                assert "synthetic-group-identity-canary" not in " ".join(result.metadata.notices)
                assert len("\n".join(result.metadata.notices).encode()) < 2048
                notices.append(expected)
                app.navigator.history_back()
                assert not lease.current()
                await wait_for(lambda: app.events_table.options == options)
                await events_ready(app, resource, count=4)
            assert notices[0] != notices[1]


@pytest.mark.asyncio
async def test_large_selector_identities_do_not_clip_or_follow_same_rows_after_navigation(tmp_path):
    api = CuratedResourcesApi()
    resource = api.resource("pods")
    values = [f"{MEMBERSHIP_CANARY}-{index:03d}-" + "x" * 30 for index in range(200)]
    predicates = tuple(
        LabelsMatch(
            structured_selector(
                {
                    "matchExpressions": [
                        {"key": "unobserved", "operator": "NotIn", "values": [*values, tail]}
                    ]
                }
            )
        )
        for tail in ("last-a", "last-b")
    )
    assert len(json.dumps(asdict(predicates[0])).encode()) > 8192
    async with curated_resources_api(tmp_path, api) as (url, _):
        app = app_for(tmp_path, url)
        async with app.run_test(size=(100, 30)) as pilot:
            await started(app, pilot)
            previous, memberships = None, []
            for index, predicate in enumerate(predicates):
                app.navigator.open_resource(
                    resource,
                    "team",
                    bookmark=ResolvedCollectionBookmark(
                        resource, "team", predicate, ResourceQuery()
                    ),
                )
                if previous is not None:
                    assert not previous.current()
                await wait_for(lambda: app.resources.row_count == 1)
                lease = await captured(app, pilot)
                result = reopened(lease, tmp_path / f"selector-{index}.txt")
                membership = next(
                    notice
                    for notice in result.metadata.notices
                    if notice.startswith("Captured local membership: LabelsMatch;")
                )
                assert MEMBERSHIP_CANARY not in " ".join(result.metadata.notices)
                assert len(membership.encode()) < 256
                memberships.append(membership)
                previous = lease
            assert memberships[0] != memberships[1]
