"""Group-aware projection caches discard wrong APIs and prune old UIDs."""

from dataclasses import replace

import pytest

from kubetrol.domain.registry import STANDARD_RESOURCES
from kubetrol.domain.resources import ResourceSnapshot
from kubetrol.services.pods import StandardProjection
from tests.support.standard import api, row_record


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
    assert updated[0].uid == "replacement" and first.uid not in projection._cache
    assert (
        await projection.project(
            replace(snapshot, resource=replace(snapshot.resource, group="wrong.example"))
        )
        == ()
    )
    assert not projection._cache
    assert await projection.project(snapshot)
    assert (
        await projection.project(
            replace(snapshot, resource=replace(snapshot.resource, name="wrong"))
        )
        == ()
    )
    assert await projection.project(None) == ()
