"""Real lifecycle values, immutable identities and shared bounded local filtering."""

from dataclasses import replace

import pytest

from kubetrol.domain.namespaces import namespace_row
from kubetrol.domain.resources import api_resource, resource_record
from kubetrol.errors import AppError
from kubetrol.services.filtering import apply_filter, filter_rows
from kubetrol.services.pods import NamespaceProjection
from tests.support.pods import NOW
from tests.support.resources import descriptor

RESOURCE = api_resource("v1", descriptor("namespaces", namespaced=False, kind="Namespace"))


def namespace(name="team", *, uid=None, phase="Active", deleted=False):
    metadata = {
        "name": name,
        "uid": uid or f"namespace-{name}",
        "resourceVersion": "owned-ns-object",
        "creationTimestamp": NOW.isoformat(),
    }
    if deleted:
        metadata["deletionTimestamp"] = NOW.isoformat()
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": metadata,
        "status": {"phase": phase},
    }


@pytest.mark.parametrize(
    "phase,deleted,expected",
    [
        ("Active", False, "Active"),
        ("Terminating", False, "Terminating"),
        (None, False, "Unknown"),
        ("", False, "Unknown"),
        ([], False, "Unknown"),
        ("Active", True, "Terminating"),
    ],
)
def test_namespace_rows_keep_lifecycle_uid_and_typed_age(phase, deleted, expected):
    record = resource_record(RESOURCE, namespace(phase=phase, deleted=deleted))
    row = namespace_row(record)
    assert row.uid == "namespace-team" and row.status == expected
    assert row.cells(NOW) == ("team", expected, "0s")
    assert replace(row, created_at=None).cells(NOW)[-1] == "—"
    with pytest.raises(AppError, match="UID identity"):
        namespace_row(replace(record, uid=None))


@pytest.mark.asyncio
async def test_namespace_filters_share_regex_bounds_and_report_the_correct_resource():
    rows = tuple(
        namespace_row(resource_record(RESOURCE, namespace(name)))
        for name in ("team", "team-blue", "default")
    )
    assert [row.name for row in (await apply_filter(rows, "BLUE", "namespaces")).rows] == [
        "team-blue"
    ]
    assert len((await apply_filter(rows, "re:^team", "namespaces")).rows) == 2
    assert (await apply_filter(rows, "", "namespaces")).rows == rows
    assert "namespaces" in filter_rows(rows, "re:[", "namespaces").problem
    assert "namespaces" in filter_rows(rows, "x" * 257, "namespaces").problem
    projection = NamespaceProjection()
    assert await projection.project(None) == ()
