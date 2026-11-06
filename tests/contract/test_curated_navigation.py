"""Real owned HTTP navigation reads, scope capture, cancellation and exact identity."""

import asyncio
import threading
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.domain.authorization import (
    AuthorizationIntent,
    AuthorizationMode,
    AuthorizationScope,
    AuthorizationScopeKind,
)
from kuberich.domain.curated_navigation import (
    AllResources,
    AuthorizationDestination,
    CollectionDestination,
    CuratedLink,
    DeclaredObjectReference,
    LabelsMatch,
    ReferenceDestination,
    RelationshipDestination,
)
from kuberich.domain.relationships import RelationshipMode, structured_selector
from kuberich.domain.resources import Discovery, DiscoveryIssue, resource_record
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.curated_navigation import (
    CuratedNavigator,
    CuratedOrigin,
    ResolvedCollection,
    ResolvedObject,
)
from tests.support.curated_navigation import (
    NODES,
    PODS,
    ROOT,
    SOURCE,
    TARGET,
    navigation_fixture,
    path,
    payload,
    reference,
)


def navigator(
    client,
    api,
    *,
    current=lambda origin: True,
    selected_namespace=lambda: "team",
    discovery=None,
    policy=None,
):
    return CuratedNavigator(
        client,
        discovery or api.discovery,
        policy or AccessPolicy(True),
        current,
        selected_namespace=selected_namespace,
    )


def collection(
    *, resource=PODS, scope="object-namespace", namespace=None, predicate=None, version="v1"
):
    return CuratedLink(
        "collection",
        "Declared collection",
        "Declared source fields",
        CollectionDestination(
            resource.group, resource.name, version, scope, namespace, predicate or AllResources()
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("expected_uid", [None, "target-uid"])
async def test_reference_uses_two_bounded_gets_and_retains_actual_current_target_identity(
    tmp_path, expected_uid
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        target = payload(TARGET, "owned-target")
        api.responses[path(TARGET, "owned-target")] = target
        owner = navigator(client, api)
        result = await owner.resolve(origin, reference(uid=expected_uid))
        assert isinstance(result, ResolvedObject)
        assert result.resource == TARGET
        assert (result.record.name, result.record.uid, result.record.resource_version) == (
            "owned-target",
            "target-uid",
            "target-rv",
        )
        assert api.ledger == [
            ("GET", path(SOURCE, "owned-source"), ()),
            ("GET", path(TARGET, "owned-target"), ()),
        ]
        assert owner.operation_count == 0
        await owner.stop()
        # Navigator does not own or close the injected client.
        assert (await client.get_json(path(TARGET, "owned-target"))) == target


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination",
    [
        RelationshipDestination(RelationshipMode.USED_BY),
        AuthorizationDestination(
            AuthorizationIntent(
                AuthorizationMode.SUBJECTS,
                AuthorizationScope(AuthorizationScopeKind.NAMESPACE, "team"),
            )
        ),
    ],
)
async def test_pure_intents_require_read_guard_but_perform_zero_api_requests(tmp_path, destination):
    class ReadPolicy(AccessPolicy):
        def __init__(self):
            super().__init__(True)
            self.actions = []

        def require(self, action):
            self.actions.append(action)
            super().require(action)

    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        policy = ReadPolicy()
        owner = navigator(client, api, policy=policy)
        assert (
            await owner.resolve(origin, CuratedLink("pure", "Intent", "Explicit", destination))
            is destination
        )
        assert policy.actions and set(policy.actions) == {Action.READ}
        assert api.ledger == []
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"uid": "replacement"},
        {"resourceVersion": "new-rv"},
        {"name": "different"},
        {"namespace": "other"},
    ],
)
async def test_source_name_uid_namespace_and_rv_must_match_before_target_read(tmp_path, change):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        source = payload(SOURCE, "owned-source", uid="source-uid", rv="source-rv")
        source["metadata"].update(change)
        api.responses[path(SOURCE, "owned-source")] = source
        owner = navigator(client, api)
        with pytest.raises(AppError):
            await owner.resolve(origin, reference())
        assert [entry[1] for entry in api.ledger] == [path(SOURCE, "owned-source")]
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["source", "target"])
@pytest.mark.parametrize(
    "status,reason", [(403, "forbidden"), (404, "not found"), (503, "read failed")]
)
async def test_server_permission_and_missing_failures_are_distinct_safe_and_bounded(
    tmp_path, stage, status, reason
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        selected = SOURCE if stage == "source" else TARGET
        name = "owned-source" if stage == "source" else "owned-target"
        api.responses[path(selected, name)] = web.Response(
            status=status, text="token=synthetic-server-error-canary"
        )
        owner = navigator(client, api)
        with pytest.raises(AppError, match=reason) as error:
            await owner.resolve(origin, reference())
        assert "synthetic-server-error-canary" not in str(error.value)
        assert len(api.ledger) == (1 if stage == "source" else 2)
        assert {entry[0] for entry in api.ledger} == {"GET"}
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("uid", "replacement"), ("namespace", "other"), ("name", "different")]
)
async def test_target_replacement_or_wrong_identity_never_resolves(tmp_path, field, value):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        target = payload(TARGET, "owned-target")
        target["metadata"][field] = value
        api.responses[path(TARGET, "owned-target")] = target
        owner = navigator(client, api)
        with pytest.raises(AppError):
            await owner.resolve(origin, reference(uid="target-uid", require_uid=True))
        assert len(api.ledger) == 2
        await owner.stop()


@pytest.mark.asyncio
async def test_uid_required_destination_without_uid_is_rejected_before_any_get(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        owner = navigator(client, api)
        with pytest.raises(AppError, match="explicit object UID"):
            await owner.resolve(origin, reference(require_uid=True))
        assert api.ledger == []
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["source", "target"])
@pytest.mark.parametrize("problem", ["kind", "version", "json", "oversized"])
async def test_real_reader_rejects_contradictory_malformed_and_oversized_api_bodies(
    tmp_path, stage, problem
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        resource = SOURCE if stage == "source" else TARGET
        name = "owned-source" if stage == "source" else "owned-target"
        value = payload(
            resource,
            name,
            uid="source-uid" if stage == "source" else "target-uid",
            rv="source-rv" if stage == "source" else "target-rv",
        )
        if problem == "kind":
            value["kind"] = "Wrong"
        elif problem == "version":
            value["apiVersion"] = "wrong/v1"
        elif problem == "json":
            value = web.Response(
                text='{"token":"synthetic-malformed-canary",', content_type="application/json"
            )
        else:
            value["unlisted"] = "x" * (8 * 1024 * 1024)
        api.responses[path(resource, name)] = value
        owner = navigator(client, api)
        with pytest.raises(AppError, match="invalid, oversized or unavailable") as error:
            await owner.resolve(origin, reference())
        assert "canary" not in str(error.value)
        assert len(api.ledger) == (1 if stage == "source" else 2)
        await owner.stop()


@pytest.mark.asyncio
async def test_exact_reference_version_never_upgrades_to_discovered_version(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        owner = navigator(client, api)
        with pytest.raises(AppError, match="exact version is unavailable"):
            await owner.resolve(origin, reference(resource=replace(TARGET, version="v9")))
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
async def test_exact_old_served_version_is_read_even_when_newer_version_is_preferred(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        old = replace(TARGET, version="v1beta1")
        api.resources += (old,)
        origin = api.origin(client)
        api.responses[path(old, "owned-target")] = payload(old, "owned-target")
        owner = navigator(client, api)
        result = await owner.resolve(origin, reference(resource=old))
        assert result.resource.version == "v1beta1"
        assert api.ledger[-1][1] == path(old, "owned-target")
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, "v1beta1"])
async def test_group_kind_reference_uses_unique_family_and_advertised_preferred_or_exact_version(
    tmp_path, version
):
    async with navigation_fixture(tmp_path) as (client, api):
        preferred = replace(NODES, version="v1beta1")
        api.resources = (preferred, *api.resources)
        origin = api.origin(client)
        target = preferred
        api.responses[path(target, "owned-node", None)] = payload(
            target, "owned-node", namespace=None
        )
        declared = DeclaredObjectReference("", version, "Node", None, "owned-node")
        owner = navigator(client, api)
        result = await owner.resolve(
            origin,
            CuratedLink(
                "parameters",
                "Parameters",
                "Declared Cluster scope",
                ReferenceDestination(declared, False),
            ),
        )
        assert result.resource == preferred
        assert result.record.namespace is None
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "discovery,reason",
    [
        (Discovery((SOURCE, TARGET, replace(TARGET, name="otherdeployments"))), "ambiguous"),
        (Discovery((SOURCE,)), "unavailable"),
        (
            Discovery((SOURCE,), (DiscoveryIssue("apps/v1", "forbidden", 403),)),
            "incomplete discovery",
        ),
    ],
)
async def test_ambiguous_unavailable_and_incomplete_discovery_have_distinct_safe_reasons(
    tmp_path, discovery, reason
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        owner = navigator(client, api, discovery=discovery)
        with pytest.raises(AppError, match=reason):
            await owner.resolve(origin, reference())
        assert api.ledger == []
        await owner.stop()


@pytest.mark.asyncio
async def test_declared_cluster_scope_is_not_filled_from_selected_namespace(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        declared = DeclaredObjectReference("apps", None, "Deployment", None, "owned-target")
        owner = navigator(client, api, selected_namespace=lambda: "other")
        with pytest.raises(AppError, match="declared namespace"):
            await owner.resolve(
                origin,
                CuratedLink(
                    "parameters",
                    "Parameters",
                    "Cluster scope",
                    ReferenceDestination(declared, False),
                ),
            )
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
async def test_relationship_reference_source_namespace_hint_canonicalizes_discovered_cluster_owner(
    tmp_path,
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        api.responses[path(NODES, "owned-target", None)] = payload(
            NODES, "owned-target", namespace=None
        )
        owner = navigator(client, api)
        result = await owner.resolve(
            origin, reference(resource=NODES, namespace="team", uid="target-uid", require_uid=True)
        )
        assert result.resource == NODES and result.record.namespace is None
        assert api.ledger[-1][1] == "/api/v1/nodes/owned-target"
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,source,resource,selected,declared,expected",
    [
        ("object-namespace", SOURCE, PODS, "other", "team", "team"),
        ("selected-namespace", ROOT, PODS, "other", None, "other"),
        ("selected-namespace", ROOT, PODS, None, None, None),
        ("cluster", SOURCE, NODES, "team", None, None),
    ],
)
async def test_collection_scope_is_exact_and_performs_only_source_revalidation(
    tmp_path, scope, source, resource, selected, declared, expected
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client, resource=source)
        predicate = LabelsMatch(structured_selector({"matchLabels": {"app": "owned"}}))
        owner = navigator(client, api, selected_namespace=lambda: selected)
        result = await owner.resolve(
            origin,
            collection(resource=resource, scope=scope, namespace=declared, predicate=predicate),
        )
        assert isinstance(result, ResolvedCollection)
        assert (result.resource, result.namespace, result.predicate) == (
            resource,
            expected,
            predicate,
        )
        assert result.query.empty
        assert api.ledger == [("GET", path(source, "owned-source", origin.namespace), ())]
        pod = resource_record(
            PODS,
            {
                **payload(PODS, "owned"),
                "metadata": {**payload(PODS, "owned")["metadata"], "labels": {"app": "other"}},
            },
        )
        assert not result.predicate.matches(PODS, pod)
        await owner.stop()


@pytest.mark.asyncio
async def test_header_namespace_is_captured_before_waiting_for_source_response(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client, resource=ROOT)
        entered, release = asyncio.Event(), asyncio.Event()
        selected = ["team"]
        source = api.responses[path(ROOT, "owned-source", None)]

        async def held(request):
            entered.set()
            await release.wait()
            return web.json_response(source)

        api.responses[path(ROOT, "owned-source", None)] = held
        owner = navigator(client, api, selected_namespace=lambda: selected[0])
        task = asyncio.create_task(owner.resolve(origin, collection(scope="selected-namespace")))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            selected[0] = "other"
            release.set()
            result = await task
            assert result.namespace == "team"
        finally:
            release.set()
            await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,source,resource,namespace",
    [
        ("object-namespace", ROOT, PODS, None),
        ("object-namespace", SOURCE, NODES, None),
        ("object-namespace", SOURCE, PODS, "other"),
        ("selected-namespace", SOURCE, PODS, "team"),
        ("selected-namespace", SOURCE, NODES, None),
        ("cluster", SOURCE, PODS, None),
        ("cluster", SOURCE, NODES, "team"),
        ("future", SOURCE, PODS, None),
    ],
)
async def test_invalid_collection_scope_never_widens_search(
    tmp_path, scope, source, resource, namespace
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client, resource=source)
        owner = navigator(client, api)
        with pytest.raises(AppError):
            await owner.resolve(
                origin, collection(resource=resource, scope=scope, namespace=namespace)
            )
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["source", "target"])
async def test_context_or_revision_guard_rejects_result_after_real_response(tmp_path, stage):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        valid = [True]
        resource = SOURCE if stage == "source" else TARGET
        name = "owned-source" if stage == "source" else "owned-target"
        body = payload(
            resource,
            name,
            uid="source-uid" if stage == "source" else "target-uid",
            rv="source-rv" if stage == "source" else "target-rv",
        )

        async def invalidate(request):
            valid[0] = False
            return web.json_response(body)

        api.responses[path(resource, name)] = invalidate
        owner = navigator(client, api, current=lambda captured: valid[0] and captured == origin)
        with pytest.raises(AppError, match="obsolete"):
            await owner.resolve(origin, reference())
        assert len(api.ledger) == (1 if stage == "source" else 2)
        await owner.stop()


@pytest.mark.asyncio
async def test_replaced_client_context_and_mismatched_session_are_rejected(tmp_path):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        owner = navigator(client, api)
        original_context = client.context
        client.context = replace(original_context, name="other-context")
        with pytest.raises(AppError, match="obsolete"):
            await owner.resolve(origin, reference())
        client.context = original_context
        with pytest.raises(AppError, match="obsolete"):
            await owner.resolve(
                replace(origin, session=replace(origin.session, context="other-context")),
                reference(),
            )
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["caller", "stop", "latest"])
async def test_owned_real_http_read_is_cancelled_and_drained_for_caller_stop_and_latest_intent(
    tmp_path, ending
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        entered, release = asyncio.Event(), asyncio.Event()
        source = api.responses[path(SOURCE, "owned-source")]
        calls = 0

        async def held(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await release.wait()
            return web.json_response(source)

        api.responses[path(SOURCE, "owned-source")] = held
        api.responses[path(TARGET, "owned-target")] = payload(TARGET, "owned-target")
        owner = navigator(client, api)
        first = asyncio.create_task(owner.resolve(origin, reference()))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert owner.operation_count == 1
            if ending == "caller":
                first.cancel()
            elif ending == "stop":
                await owner.stop()
            else:
                second = asyncio.create_task(owner.resolve(origin, reference()))
                third = asyncio.create_task(owner.resolve(origin, collection()))
                with pytest.raises(asyncio.CancelledError):
                    await second
                assert isinstance(await third, ResolvedCollection)
            with pytest.raises(asyncio.CancelledError):
                await first
            assert owner.operation_count == 0
            # The superseded object read never proceeds to its target.
            assert path(TARGET, "owned-target") not in [entry[1] for entry in api.ledger]
            await owner.stop()
            await owner.stop()
            with pytest.raises(AppError, match="obsolete"):
                await owner.resolve(origin, reference())
            assert await client.get_json(path(TARGET, "owned-target")) == payload(
                TARGET, "owned-target"
            )
        finally:
            release.set()
            await owner.stop()
            await asyncio.gather(first, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "link",
    [
        CuratedLink("disabled", "Disabled", "Missing", None),
        CuratedLink("disabled", "Disabled", "Invalid", reference().destination, "Unavailable"),
    ],
)
async def test_disabled_links_have_safe_fixed_error_and_no_reads(tmp_path, link):
    async with navigation_fixture(tmp_path) as (client, api):
        owner = navigator(client, api)
        with pytest.raises(AppError, match="link is unavailable"):
            await owner.resolve(api.origin(client), link)
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,reason",
    [
        ({"resource_version": None}, "resource version"),
        ({"namespace": None}, "source scope"),
        ({"resource": replace(SOURCE, version="v9")}, "source descriptor"),
    ],
)
async def test_incomplete_or_undiscovered_source_capture_is_not_revalidated_via_guessed_endpoint(
    tmp_path, change, reason
):
    async with navigation_fixture(tmp_path) as (client, api):
        owner = navigator(client, api)
        with pytest.raises(AppError, match=reason):
            await owner.resolve(replace(api.origin(client), **change), reference())
        assert not api.ledger
        await owner.stop()


@pytest.mark.parametrize(
    "change",
    [
        {"revision": True},
        {"revision": -1},
        {"record_name": "bad/name"},
        {"record_uid": ""},
        {"namespace": "bad namespace"},
        {"resource_version": ""},
    ],
)
def test_captured_origin_validates_identity_without_normalization(change):
    from kuberich.domain.targets import SessionIdentity

    with pytest.raises(AppError):
        CuratedOrigin(
            **{
                "session": SessionIdentity("owned", 1),
                "revision": 1,
                "resource": SOURCE,
                "record_name": "owned-source",
                "record_uid": "source-uid",
                "namespace": "team",
                "resource_version": "source-rv",
                **change,
            }
        )


def test_observed_source_version_is_an_optional_bounded_opaque_capture():
    from kuberich.domain.targets import SessionIdentity

    origin = CuratedOrigin(
        SessionIdentity("owned", 1),
        1,
        SOURCE,
        "owned-source",
        "source-uid",
        "team",
        "fresh-opaque",
        "observed-opaque",
    )
    assert origin.observed_resource_version == "observed-opaque"
    with pytest.raises(AppError):
        replace(origin, observed_resource_version="")


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["cancel-superseding-caller", "cancel-stop-caller"])
async def test_cancellation_during_actual_reader_parser_drains_before_owner_returns(
    tmp_path, monkeypatch, ending
):
    from kuberich.services import resources

    original_parser = resources.resource_record
    entered, release = threading.Event(), threading.Event()
    calls = 0

    def held_parser(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            release.wait(3)
        return original_parser(*args, **kwargs)

    monkeypatch.setattr(resources, "resource_record", held_parser)
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        later = replace(origin, revision=origin.revision + 1)
        second_entered = asyncio.Event()

        def current(captured):
            if captured == later:
                second_entered.set()
            return True

        owner = navigator(client, api, current=current)
        first = asyncio.create_task(owner.resolve(origin, reference()))
        cleanup = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            if ending == "cancel-superseding-caller":
                cleanup = asyncio.create_task(owner.resolve(later, collection()))
                await asyncio.wait_for(second_entered.wait(), 1)
            else:
                cleanup = asyncio.create_task(owner.stop())
                await asyncio.sleep(0)
            cleanup.cancel()
            await asyncio.sleep(0)
            assert not cleanup.done()
            assert owner.operation_count == 1
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await cleanup
            with pytest.raises(asyncio.CancelledError):
                await first
            assert owner.operation_count == 0
            assert [entry[1] for entry in api.ledger] == [path(SOURCE, "owned-source")]
            await owner.stop()
            assert (
                await client.get_json(path(SOURCE, "owned-source"))
                == api.responses[path(SOURCE, "owned-source")]
            )
        finally:
            release.set()
            await owner.stop()
            await asyncio.gather(first, *([cleanup] if cleanup else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resource,link,reason",
    [
        (replace(TARGET, verbs=frozenset({"list"})), reference(), "object reads"),
        (replace(PODS, verbs=frozenset({"get"})), collection(), "collection reads"),
    ],
)
async def test_target_read_verbs_must_be_advertised_without_probing_other_endpoints(
    tmp_path, resource, link, reason
):
    async with navigation_fixture(tmp_path) as (client, api):
        api.resources = tuple(
            resource if item.group == resource.group and item.name == resource.name else item
            for item in api.resources
        )
        owner = navigator(client, api)
        with pytest.raises(AppError, match=reason):
            await owner.resolve(api.origin(client), link)
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "destination,reason",
    [
        (ReferenceDestination("not-a-reference", False), "reference is invalid"),
        (replace(reference().destination, require_uid="true"), "reference is invalid"),
        (
            replace(
                reference().destination, ref=replace(reference().destination.ref, kind="bad-kind")
            ),
            "reference kind",
        ),
        (
            replace(collection().destination, predicate=lambda resource, item: True),
            "literal predicate",
        ),
        (RelationshipDestination("future-mode"), "relationship intent"),
        (AuthorizationDestination("not-an-intent"), "authorization intent"),
        ("not-a-destination", "type is unsupported"),
    ],
)
async def test_malformed_closed_destination_records_fail_safely_without_api(
    tmp_path, destination, reason
):
    async with navigation_fixture(tmp_path) as (client, api):
        owner = navigator(client, api)
        with pytest.raises(AppError, match=reason):
            await owner.resolve(
                api.origin(client), CuratedLink("malformed", "Malformed", "Synthetic", destination)
            )
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"namespaced": "true"}, {"kind": "bad-kind"}])
async def test_malformed_discovered_source_descriptor_fails_before_building_http_path(
    tmp_path, change
):
    async with navigation_fixture(tmp_path) as (client, api):
        origin = api.origin(client)
        malformed = replace(SOURCE, **change)
        api.resources = (malformed, TARGET)
        owner = navigator(client, api)
        with pytest.raises(AppError, match="valid discovered descriptor"):
            await owner.resolve(replace(origin, resource=malformed), reference())
        assert not api.ledger
        await owner.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["uid", "resourceVersion"])
async def test_get_only_target_still_requires_real_uid_and_resource_version(tmp_path, field):
    async with navigation_fixture(tmp_path) as (client, api):
        resource = replace(TARGET, verbs=frozenset({"get"}))
        api.resources = (SOURCE, resource)
        origin = api.origin(client)
        target = payload(resource, "owned-target")
        del target["metadata"][field]
        api.responses[path(resource, "owned-target")] = target
        owner = navigator(client, api)
        with pytest.raises(AppError, match="target changed or was replaced"):
            await owner.resolve(origin, reference(resource=resource))
        assert len(api.ledger) == 2
        await owner.stop()
