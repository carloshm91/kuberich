"""Table rendering caches release retired values without waiting for cyclic GC."""

import gc
import weakref
from unittest.mock import Mock

import pytest
from textual.cache import LRUCache
from textual.widgets import DataTable

from kuberich.ui import presentation
from kuberich.ui.presentation import FrameTable
from kuberich.ui.table_cache import RenderCache


class RenderValue:
    pass


@pytest.fixture
def created_caches(monkeypatch):
    created = []

    def create(capacity):
        cache = RenderCache(capacity)
        monkeypatch.setattr(cache, "clear", Mock(wraps=cache.clear))
        created.append(cache)
        return cache

    monkeypatch.setattr(presentation, "RenderCache", create)
    return created


@pytest.mark.parametrize("native_control", [True, False])
def test_cleared_table_cache_releases_values_before_cyclic_collection(
    native_control, created_caches
):
    if native_control:
        caches = [LRUCache(10000)]
        clear = caches[0].clear
    else:
        table = FrameTable()
        assert len(created_caches) == 6
        caches = created_caches
        clear = table.clear
    value = RenderValue()
    reference = weakref.ref(value)
    for cache in caches:
        cache["owned-render-value"] = value
    del value
    clear()
    if native_control:
        assert reference() is not None, "Control must reproduce the retired linked-list cycle"
        gc.collect()
    assert reference() is None, "Cleared cache still retains retired render data"


@pytest.mark.parametrize("capacity", [1, 3, 10000])
def test_render_cache_matches_native_lru_order_values_counters_and_capacity(capacity):
    native, owned = LRUCache(capacity), RenderCache(capacity)
    sentinel = object()

    def observe():
        assert list(owned.keys()) == list(native.keys())
        assert len(owned) == len(native)
        assert bool(owned) == bool(native)
        assert repr(owned) == repr(native)
        assert owned.maxsize == native.maxsize
        assert (owned.hits, owned.misses) == (native.hits, native.misses)

    observe()
    for key in range(8):
        for cache in (native, owned):
            cache[key] = f"value-{key}"
            cache.set(key, "must not replace or reorder an existing value")
        observe()
        for sought in (key, key - 1, -100):
            assert owned.get(sought) == native.get(sought)
            assert owned.get(sought, sentinel) == native.get(sought, sentinel)
            if sought in native:
                assert owned[sought] == native[sought]
            else:
                for cache in (native, owned):
                    with pytest.raises(KeyError) as error:
                        cache[sought]
                    assert error.value.args == (sought,)
            observe()
    for key in (5, -100, 7, 6):
        native.discard(key)
        owned.discard(key)
        observe()
    for cache in (native, owned):
        cache.grow(10)
        cache[20] = None
        cache[21] = sentinel
    observe()
    assert owned.get(20, sentinel) == native.get(20, sentinel)
    assert owned[21] is native[21] is sentinel
    for cache in (native, owned):
        cache.clear()
        cache.maxsize = 2
        cache.set(1, "first")
        cache.set(2, "second")
        cache.get(1)
        cache.set(3, "third")
    observe()
    assert list(owned.keys()) == [1, 3]
    for cache in (native, owned):
        cache.clear()
        cache.clear()
    observe()


@pytest.mark.parametrize("operation", ["clear", "discard", "retire"])
def test_render_cache_releases_values_without_cyclic_collection(operation):
    cache = RenderCache(100)
    value = RenderValue()
    reference = weakref.ref(value)
    cache[1] = value
    del value
    if operation == "clear":
        cache.clear()
    elif operation == "discard":
        cache.discard(1)
    else:
        del cache
    assert reference() is None


def test_only_owned_tables_replace_all_six_caches_without_reducing_capacities(created_caches):
    native = DataTable()
    names = (
        "_row_render_cache",
        "_cell_render_cache",
        "_row_renderable_cache",
        "_line_cache",
        "_offset_cache",
        "_ordered_row_cache",
    )
    controls = [getattr(native, name) for name in names]
    assert not created_caches
    owned = FrameTable()
    assert len(created_caches) == len(names) == 6
    for control, replacement in zip(controls, created_caches, strict=True):
        assert type(control) is LRUCache
        assert type(replacement) is RenderCache
        assert replacement.maxsize == control.maxsize
        replacement["owned-integration-probe"] = RenderValue()
    before = [cache.clear.call_count for cache in created_caches]
    owned.clear()
    assert all(
        cache.clear.call_count > count for cache, count in zip(created_caches, before, strict=True)
    ), "All six constructed caches must be installed and reached by public clear()"
