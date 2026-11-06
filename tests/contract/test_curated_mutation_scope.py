"""Direct effect entry points refuse new read-only families before network/drafts."""

import pytest
from aiohttp import web

from kuberich.domain.curated import READ_ONLY_FAMILIES
from kuberich.domain.operations import DeleteOptions, ResourceAction
from kuberich.domain.resources import ApiResource
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.editing import EditingService
from kuberich.services.mutations import MutationService
from kuberich.services.operations import BatchDeleteService, ResourceOperationService
from tests.support.resources import reader_fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("group,name", sorted(READ_ONLY_FAMILIES))
@pytest.mark.parametrize("entry", ["annotation", "editor", "delete", "batch"])
async def test_direct_curated_effect_is_blocked_before_any_http_or_editor_draft(
    tmp_path, group, name, entry
):
    requests = []

    async def handler(request):
        requests.append((request.method, request.path))
        return web.Response(status=403)

    async with reader_fixture(tmp_path, handler) as reader:
        resource = ApiResource(
            group,
            "unknown",
            name,
            "Unrecognized",
            True,
            frozenset({"get", "patch", "delete", "create", "list"}),
        )
        target = ResourceTarget(
            SessionIdentity(reader.session.context.name, 1),
            group,
            name,
            "team",
            "owned",
            "owned-uid",
        )
        args = reader.session, resource, target, AccessPolicy(False), lambda: True
        before = tuple(requests)
        with pytest.raises(AppError, match="reading, inspection and navigation"):
            if entry == "annotation":
                await MutationService(*args).prepare_annotation("example.test/key", "owned")
            elif entry == "editor":
                source = EditingService(*args)
                try:
                    await source.open()
                finally:
                    assert source.file is None and source.snapshot is None
            else:
                source = ResourceOperationService(*args, ResourceAction.DELETE)
                if entry == "batch":
                    await BatchDeleteService((source,)).prepare(DeleteOptions())
                else:
                    await source.prepare()
        assert tuple(requests) == before
