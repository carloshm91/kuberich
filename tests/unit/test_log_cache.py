"""Scalar cache diagnostics preserve bounds and stale-source identity oracles."""

from dataclasses import FrozenInstanceError

import pytest

from kuberich.ui.log_cache import LogCacheInfo, log_cache_info


def test_empty_and_linked_cache_snapshots_are_frozen_and_independent():
    empty = log_cache_info({}, {})
    assert empty == LogCacheInfo(0, 0, True)
    source = object()
    linked = log_cache_info({7: (None, (source,), None, None)}, {(7, 0): (source, object())})
    assert linked == LogCacheInfo(1, 1, True)
    assert empty == LogCacheInfo(0, 0, True)
    with pytest.raises(FrozenInstanceError):
        linked.current_sources = False  # type: ignore[misc]


@pytest.mark.parametrize("number,offset", [(8, 0), (7, -1), (7, 1)])
def test_retired_or_out_of_range_sources_are_reported_without_exposing_objects(number, offset):
    source = object()
    result = log_cache_info(
        {7: (None, (source,), None, None)}, {(number, offset): (source, object())}
    )
    assert result == LogCacheInfo(1, 1, False)


def test_equal_but_replaced_source_is_stale_by_identity():
    old, current = ["equal contents"], ["equal contents"]
    assert old == current and old is not current
    result = log_cache_info({7: (None, (current,), None, None)}, {(7, 0): (old, object())})
    assert result == LogCacheInfo(1, 1, False)
