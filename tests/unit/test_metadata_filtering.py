"""Local advanced filters use owned workers, bounded evaluation and one snapshot cache."""

import asyncio
import threading
from dataclasses import replace

import pytest

from kuberich.domain.navigation import ContextRow
from kuberich.domain.pods import pod_row
from kuberich.services import metadata_filtering as module
from kuberich.services.filtering import filter_rows
from tests.support.pods import pod, record


def examples():
    a, b, c = pod("api"), pod("worker", ready=False), pod("unknown")
    a["metadata"]["labels"] = {"app": "api", "tier": "frontend"}
    b["metadata"]["labels"] = {"app": "worker"}
    c["status"] = {}
    records = tuple(record(value) for value in (a, b, c))
    return tuple(pod_row(value) for value in records), records


def test_inverse_and_fuzzy_preserve_plain_regex_and_literal_controls():
    rows, _ = examples()
    assert filter_rows(rows, "!re:^team api").rows == rows[1:]
    assert filter_rows(rows, "fuzzy:wrkr").rows == (rows[1],)
    assert filter_rows(rows, "fuzzy:").rows == rows
    assert filter_rows(rows, "!re:[").rows == rows
    assert filter_rows(rows, "fuzzy:" + "x" * 257).problem
    assert filter_rows(rows, "!re:absent").rows == rows


@pytest.mark.parametrize(
    "query,errors,names,unknown",
    [
        ("label:app in (api,worker),!debug", False, ["api", "worker"], 0),
        ("label:app=worker", False, ["worker"], 0),
        ("field:metadata.name=api", False, ["api"], 0),
        ("field:status.phase=Running", True, ["worker"], 0),
        ("", True, ["worker"], 1),
        ("worker", True, ["worker"], 1),
        ("label:absent", True, [], 0),
    ],
)
def test_metadata_and_failures_are_local_and_unknown_is_separate(query, errors, names, unknown):
    rows, records = examples()
    result = module.metadata_filter(rows, records, query, "pods", errors, threading.Event())
    assert result.problem is None
    assert [row.name for row in result.rows] == names
    assert result.unknown == unknown


@pytest.mark.parametrize("query", ["label:", "field:data.token=x", "x" * 257])
def test_bad_selector_never_returns_partial_matches(query):
    rows, records = examples()
    result = module.metadata_filter(rows, records, query, "pods", False, threading.Event())
    assert result.problem and result.rows is rows


def test_deadline_cancellation_and_non_api_views_refuse_without_partial_rows(monkeypatch):
    rows, records = examples()
    event = threading.Event()
    event.set()
    assert module.metadata_filter(rows, records, "", "pods", True, event).problem
    monkeypatch.setattr(module, "METADATA_SECONDS", 0)
    assert module.metadata_filter(rows, records, "", "pods", True, threading.Event()).problem
    monkeypatch.setattr(module, "METADATA_SECONDS", 0.25)
    assert module.metadata_filter(
        (ContextRow("ctx", "cluster", "user", "team"),),
        (),
        "label:a",
        "contexts",
        False,
        threading.Event(),
    ).problem
    assert module.metadata_filter(
        rows, (), "field:metadata.name=a", "pods", False, threading.Event()
    ).problem


@pytest.mark.asyncio
async def test_ordinary_filter_never_decodes_and_advanced_cache_holds_snapshot_identity(
    monkeypatch,
):
    rows, records = examples()
    service = module.MetadataFilter()
    assert (await service.apply(rows, (), "api", "pods")).rows == rows[:1]
    original = module.metadata_filter
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(module, "metadata_filter", counted)
    first = await service.apply(rows, records, "label:app", "pods")
    assert await service.apply(rows, records, "label:app", "pods") is first
    assert len(calls) == 1
    changed = (replace(records[0], uid="new-uid"), *records[1:])
    await service.apply(rows, changed, "label:app", "pods")
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cancelling_projection_waits_for_its_owned_worker(monkeypatch):
    rows, records = examples()
    entered, released = threading.Event(), threading.Event()
    original = module.metadata_filter

    def blocking(*args):
        entered.set()
        assert released.wait(5)
        return original(*args)

    monkeypatch.setattr(module, "metadata_filter", blocking)
    task = asyncio.create_task(module.MetadataFilter().apply(rows, records, "label:app", "pods"))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    released.set()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_fuzzy_total_budget_retains_all_rows_without_partial_matches(monkeypatch):
    from kuberich.services import filtering

    rows, _ = examples()
    monkeypatch.setattr(filtering, "REGEX_SECONDS", 0)
    result = filter_rows(rows, "fuzzy:api")
    assert result.rows is rows and "time budget" in result.problem


@pytest.mark.asyncio
async def test_cached_metadata_matches_do_not_reuse_old_projected_cell_values():
    rows, records = examples()
    service = module.MetadataFilter()
    first = await service.apply(rows, records, "label:app=api", "pods")
    changed = (replace(rows[0], name="new displayed projection"), *rows[1:])
    result = await service.apply(changed, records, "label:app=api", "pods")
    assert result.rows == changed[:1] and result.rows != first.rows
    await service.apply(rows, records, "field:data.token=x", "pods")
    invalid = await service.apply(changed, records, "field:data.token=x", "pods")
    assert invalid.rows is changed and invalid.problem


def test_a_slow_final_manifest_decode_cannot_return_a_success_after_deadline(monkeypatch):
    from types import SimpleNamespace

    rows, records = examples()
    moments = iter((0, 0, 1))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: next(moments, 1)))
    result = module.metadata_filter(
        rows[:1], records[:1], "label:app=api", "pods", False, threading.Event()
    )
    assert result.problem and result.rows == rows[:1]


def test_unknown_api_reusing_core_plural_cannot_inherit_core_field_or_health_defaults():
    from kuberich.domain.resources import ApiResource, resource_record

    rows, _records = examples()
    custom = ApiResource(
        "owned.example.test", "v1", "pods", "OtherPod", True, frozenset({"get", "list", "watch"})
    )
    value = pod("api")
    value.update(apiVersion="owned.example.test/v1", kind="OtherPod")
    value["status"] = {"phase": "Succeeded"}
    item = resource_record(custom, value, "team")
    result = module.metadata_filter(
        rows[:1], (item,), "field:spec.hostNetwork=false", "pods", False, threading.Event()
    )
    assert result.problem and result.rows == rows[:1]
    result = module.metadata_filter(rows[:1], (item,), "", "pods", True, threading.Event())
    assert not result.rows and result.unknown == 1
