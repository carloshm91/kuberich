"""Membership reuse never crosses an immutable snapshot, scope or generation."""

import logging
from dataclasses import replace

import pytest
from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.views import ViewStatus
from kuberich.domain.watches import SyncStatus, SyncUpdate
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


class CountedRecords(tuple):
    def __new__(cls, values):
        result = super().__new__(cls, values)
        result.iterations = 0
        return result

    def __iter__(self):
        self.iterations += 1
        return super().__iter__()


@pytest.mark.asyncio
async def test_membership_is_checked_once_per_snapshot_and_immediately_rejects_new_scope(tmp_path):
    async def ns(request):
        return namespaces("team", "default")

    async def handler(request):
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(pod("first"), pod("last")))

    async with workspace_api(ns, handler) as url:
        app = KubeRichApp(
            Settings(read_only=True),
            logging.Logger("target-cache", level=100),
            catalog=catalog_fixture(tmp_path, url),
        )
        async with app.run_test():
            await wait_for(
                lambda: (
                    app.workspace.store.observation.status is ViewStatus.LIVE
                    and app.resources.row_count == 2
                )
            )
            store = app.workspace.store
            view = store.observation
            scope, initial = view.scope, view.snapshot
            assert scope is not None and initial is not None

            def publish(items):
                counted = CountedRecords(items)
                snapshot = replace(initial, items=counted)
                assert store.apply(view.revision, scope, SyncUpdate(SyncStatus.LIVE, snapshot))
                return counted

            counted = publish(initial.items)
            uid = initial.items[-1].uid
            assert uid is not None
            captured = app._capture_target(uid)
            assert captured is not None
            current = captured[-1]
            assert all(current() for _ in range(1000))
            assert counted.iterations == 1  # The initial explicit capture.

            counted = publish(initial.items)
            assert all(current() for _ in range(1000))
            assert counted.iterations == 1
            counted = publish(initial.items[:-1])
            assert all(not current() for _ in range(1000))
            assert counted.iterations == 1
            counted = publish(initial.items)
            assert all(current() for _ in range(1000)) and counted.iterations == 1

            store.observation = replace(store.observation, snapshot=None)
            assert not current()
            counted = publish(initial.items)
            assert current() and counted.iterations == 1
            store.begin("another-owned-context")
            assert all(not current() for _ in range(1000))
            assert counted.iterations == 1
