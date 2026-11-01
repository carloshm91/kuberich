"""Removed widgets must not stay rooted by a shared background-color cache."""

import gc
import weakref

import pytest
from textual._styles_cache import StylesCache
from textual.color import Color
from textual.widgets import Static

from kuberich.ui import app as app_module
from tests.support.aggregate_logs import AggregateApi
from tests.support.workspace import wait_for, workspace_api
from tests.ui.test_aggregate_logs import app_for, ns


@pytest.mark.asyncio
@pytest.mark.parametrize("native_control", [False, True])
async def test_retired_render_cache_is_not_owned_by_background_colors(
    tmp_path, monkeypatch, native_control
):
    if native_control:
        monkeypatch.setattr(app_module, "ColorStylesCache", StylesCache)
    api = AggregateApi(count=1)
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            widget = Static("owned rendering cache", id="cache-probe", markup=False)
            await app.screen.mount(widget)
            await pilot.pause()
            cache = widget._styles_cache
            cache.get_inner_outer(Color.parse("#123456"), Color.parse("#abcdef"))
            reference = weakref.ref(cache)
            await widget.remove()
            await pilot.pause()
            # Layout caches may legitimately retain the removed Widget. Retire
            # its renderer explicitly to isolate color memoization ownership.
            widget._styles_cache = StylesCache()
            del widget, cache
            gc.collect()
            if native_control:
                assert reference() is not None
                StylesCache.get_inner_outer.cache_clear()
                gc.collect()
            assert reference() is None, "Retired render cache retained by color memoization"


@pytest.mark.asyncio
async def test_owned_color_styles_preserve_native_alpha_composition_and_remounting(tmp_path):
    api = AggregateApi(count=1)
    async with workspace_api(ns, api.handler) as url:
        app = app_for(tmp_path, url)
        async with app.run_test() as pilot:
            await wait_for(lambda: app.resources.row_count == 1)
            widget = Static("literal [color] 界", id="cache-probe", markup=False)
            await app.screen.mount(widget, before=app.screen.children[0])
            original = StylesCache()
            for base in ("#000000", "#123456", "#ffffff"):
                for overlay in ("#abcdef", "#abcdef80", "transparent"):
                    colors = Color.parse(base), Color.parse(overlay)
                    assert widget._styles_cache.get_inner_outer(
                        *colors
                    ) == original.get_inner_outer(*colors)
            for theme, size in (("textual-light", (40, 12)), ("textual-dark", (100, 30))):
                app.theme = theme
                await pilot.resize_terminal(*size)
                await pilot.pause()
                assert widget.content == "literal [color] 界"
                assert widget.render_lines(widget.content_region.at_offset((0, 0)))
            await widget.remove()
            await app.screen.mount(widget, after=app.screen.children[-1])
            await pilot.pause()
            assert widget.is_mounted and widget.content == "literal [color] 界"
