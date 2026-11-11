"""Offline draft identities, disclosure, bounded editor adoption and origin guards."""

import asyncio
import json
from pathlib import Path

import pytest

from kuberich.domain.manifests import canonical_manifest
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.mutations import Confirmation
from kuberich.services.resource_creation import ResourceCreationService

PRIVATE = "owned-creation-draft-private"
BODY = canonical_manifest(
    {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "owned"}, "data": {"x": PRIVATE}}
)


@pytest.mark.asyncio
async def test_capture_is_offline_immutable_and_preserves_private_source(tmp_path):
    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    try:
        source = await service.capture_bytes(BODY, "paste", "Explicit paste")
        assert source.body == BODY and source.documents[0].name == "owned"
        assert PRIVATE not in repr(source)
        await service.require_source(source)
        replacement = await service.capture_bytes(BODY, "clipboard", "Explicit clipboard")
        assert (
            source.identity != replacement.identity and replacement.generation > source.generation
        )
        with pytest.raises(AppError, match="changed"):
            await service.require_source(source)
    finally:
        await service.close()
    assert service.operation_count == 0 and service.current_source is None


@pytest.mark.asyncio
async def test_declared_private_template_stays_opaque_after_editor_moves_value(tmp_path):
    from kuberich.domain.manifests import manifest_preview
    from kuberich.domain.resource_templates import TemplateCatalogEntry, parse_resource_template
    from kuberich.services.resource_templates import TemplateCatalogService

    template = parse_resource_template(
        canonical_manifest(
            {
                "schema_version": 1,
                "kind": "ResourceTemplate",
                "id": "private-image",
                "revision": 1,
                "title": "Private image",
                "parameters": {
                    "image": {
                        "type": "string",
                        "required": True,
                        "sensitive": True,
                        "paths": ["/0/spec/containers/0/image"],
                    },
                },
                "objects": [
                    {
                        "apiVersion": "v1",
                        "kind": "Pod",
                        "metadata": {"name": "owned"},
                        "spec": {"containers": [{"name": "owned", "image": ""}]},
                    }
                ],
            }
        )
    )
    entry = TemplateCatalogEntry(
        origin="builtin",
        relative_path="private-image",
        identity=("builtin", template.id, 1, template.source_sha256),
        template=template,
    )
    catalog = TemplateCatalogService(tmp_path / "config.yaml", tmp_path)
    catalog.entries = (entry,)
    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    try:
        source = await service.capture_template(entry, {"image": PRIVATE}, catalog)
        assert source.private_preview and PRIVATE in source.body.decode()
        assert PRIVATE not in repr(source)
        before = "".join(manifest_preview(None, source.body, private=source.private_preview))
        assert PRIVATE not in before and "containers" not in before
        disclosure = await service.prepare_editor()
        command = await service.open_editor(service.confirm_disclosure(disclosure))
        value = json.loads(source.body)
        private = value["spec"]["containers"][0].pop("image")
        value["metadata"]["annotations"] = {PRIVATE: private}
        Path(command.argv[-1]).write_bytes(
            canonical_manifest(
                {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "added-first"}}
            )
            + b"\n---\n"
            + canonical_manifest(value)
        )
        changed = await service.finish_editor(succeeded=True)
        assert changed is not None and changed.private_preview
        assert tuple(item.name for item in changed.documents) == ("added-first", "owned")
        assert PRIVATE in changed.body.decode() and PRIVATE not in repr(changed)
        after = "".join(manifest_preview(None, changed.body, private=changed.private_preview))
        assert PRIVATE not in after and "annotations" not in after
    finally:
        await service.close()
        await catalog.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["success", "noop", "failure", "invalid"])
async def test_editor_adopts_only_valid_success_in_memory_and_retires_private_file(tmp_path, mode):
    path = tmp_path / "owned.yaml"
    path.write_bytes(BODY)
    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    try:
        original = await service.capture_file(path)
        disclosure = await service.prepare_editor()
        proof = service.confirm_disclosure(disclosure)
        command = await service.open_editor(proof)
        draft = Path(command.argv[-1])
        assert draft.read_bytes() == BODY and draft.stat().st_mode & 0o777 == 0o600
        assert draft.parent.stat().st_mode & 0o777 == 0o700
        with pytest.raises(AppError, match="consumed"):
            service.open_editor(proof)
        if mode == "success":
            value = json.loads(BODY)
            value["metadata"]["labels"] = {"example.io/created": "reviewed"}
            draft.write_bytes(canonical_manifest(value))
        elif mode == "invalid":
            draft.write_bytes(b"invalid: [private")
        if mode == "invalid":
            with pytest.raises(AppError):
                await service.finish_editor(succeeded=True)
        else:
            result = await service.finish_editor(succeeded=mode != "failure")
            assert (result is not None) is (mode == "success")
        assert not draft.parent.exists() and path.read_bytes() == BODY
        if mode == "success":
            assert service.current_source is not original
            assert service.current_source.documents[0].name == "owned"
            with pytest.raises(AppError):
                await service.require_source(original)
        else:
            assert service.current_source is original
        await service.require_source(service.current_source)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_file_origin_remains_bound_after_successful_private_edit(tmp_path):
    path = tmp_path / "owned.yaml"
    path.write_bytes(BODY)
    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    try:
        await service.capture_file(path)
        disclosure = await service.prepare_editor()
        command = await service.open_editor(service.confirm_disclosure(disclosure))
        Path(command.argv[-1]).write_bytes(BODY + b"\n")
        source = await service.finish_editor(succeeded=True)
        assert source is not None
        path.write_bytes(BODY + b"\nchanged: true\n")
        with pytest.raises(AppError, match=r"changed|unavailable"):
            await service.require_source(source)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_read_only_allows_offline_capture_but_refuses_disclosed_editor(tmp_path):
    policy = AccessPolicy(False)
    policy.restrict(True)
    service = ResourceCreationService(policy, {}, tmp_path)
    try:
        await service.capture_bytes(BODY, "file", "Owned")
        with pytest.raises(AppError, match="Read-only"):
            await service.prepare_editor()
        policy.restrict(False)
        intent = await service.prepare_editor()
        proof = service.confirm_disclosure(intent)
        policy.tighten()
        with pytest.raises(AppError, match="Read-only"):
            service.open_editor(proof)
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_forged_editor_proof_consumes_original_approval_without_creating_file(tmp_path):
    from uuid import uuid4

    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    try:
        await service.capture_bytes(BODY, "file", "Owned")
        intent = await service.prepare_editor()
        proof = service.confirm_disclosure(intent)
        with pytest.raises(AppError, match="consumed"):
            service.open_editor(Confirmation(intent.identity, uuid4()))
        with pytest.raises(AppError, match="consumed"):
            service.open_editor(proof)
        assert not tuple(tmp_path.iterdir())
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_close_drains_held_source_worker_before_return(tmp_path, monkeypatch):
    import threading

    from kuberich.adapters.manifest_files import ManifestFiles

    service = ResourceCreationService(AccessPolicy(False), {}, tmp_path)
    path = tmp_path / "owned.yaml"
    path.write_bytes(BODY)
    entered, release = threading.Event(), threading.Event()
    read = ManifestFiles.read

    def held(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return read(*args, **kwargs)

    monkeypatch.setattr(ManifestFiles, "read", held)
    operation = asyncio.create_task(service.capture_file(path))
    await asyncio.to_thread(entered.wait)
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    assert not closing.done()
    release.set()
    await closing
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert service.operation_count == 0 and service.current_source is None
