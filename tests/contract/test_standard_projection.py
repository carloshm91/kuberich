"""Group-aware projection caches discard wrong APIs and prune old UIDs."""

from dataclasses import replace

import pytest

from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.domain.resources import ResourceSnapshot
from kuberich.services.pods import StandardProjection
from tests.support.standard import api, row_record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"version": "v99"},
        {"kind": "Other"},
        {"namespaced": False},
        {"group": "other.example"},
        {"name": "other"},
    ],
)
async def test_explicit_standard_descriptor_rejects_replaced_versions_kinds_and_scopes(change):
    definition = next(d for d in STANDARD_RESOURCES if d.name == "services")
    descriptor = api(definition)
    projection = StandardProjection(definition, descriptor)
    snapshot = ResourceSnapshot(descriptor, "team", "owned-rv", (row_record(definition),))
    first = (await projection.project(snapshot))[0]
    assert projection.cached_count == 1
    assert await projection.project(replace(snapshot, resource=replace(descriptor, **change))) == ()
    assert projection.cached_count == 0
    assert (await projection.project(snapshot))[0] is not first


@pytest.mark.asyncio
@pytest.mark.parametrize("definition", STANDARD_RESOURCES, ids=[d.name for d in STANDARD_RESOURCES])
async def test_standard_projection_is_group_scoped_incremental_and_uid_bound(definition):
    projection = StandardProjection(definition)
    first = row_record(definition)
    snapshot = ResourceSnapshot(
        api(definition), "team" if definition.namespaced else None, "opaque/list", (first,)
    )
    rows = await projection.project(snapshot)
    assert rows and rows[0].uid == first.uid
    assert (await projection.project(snapshot))[0] is rows[0]
    replacement = row_record(definition, uid="replacement")
    updated = await projection.project(replace(snapshot, items=(replacement,)))
    assert updated[0].uid == "replacement"
    restored = await projection.project(snapshot)
    assert restored[0] is not rows[0]
    assert (
        await projection.project(
            replace(snapshot, resource=replace(snapshot.resource, group="wrong.example"))
        )
        == ()
    )
    assert (await projection.project(snapshot))[0] is not restored[0]
    assert await projection.project(snapshot)
    assert (
        await projection.project(
            replace(snapshot, resource=replace(snapshot.resource, name="wrong"))
        )
        == ()
    )
    assert await projection.project(None) == ()
