"""Owned local browser, source freshness, private editor disclosure and separate Save."""

import asyncio
import threading
from pathlib import Path

import pytest

from kuberich.adapters.manifest_files import ManifestFiles
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy
from kuberich.services.local_manifests import LocalManifestService
from kuberich.services.mutations import Confirmation

MANIFEST = (
    b"apiVersion: v1\nkind: ConfigMap\nmetadata: {name: owned}\ndata: {key: raw-source-sentinel}\n"
)


def service(tmp_path, read_only=False, **kwargs):
    return LocalManifestService(
        AccessPolicy(read_only), {"PATH": "/usr/bin:/bin", "EDITOR": "true"}, tmp_path, **kwargs
    )


@pytest.mark.asyncio
async def test_browse_inspect_capture_and_source_invalidation_without_any_helper(tmp_path):
    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    assert local.root is None and local.current_source is None and local.operation_count == 0
    listing = await local.open_root(Path("."))
    assert listing.root.path == tmp_path and listing.entries[0].relative_path == "source.yaml"
    pages = await local.inspect_file("source.yaml")
    assert "raw-source-sentinel" not in str(pages) and local.current_source is None
    source = await local.capture("source.yaml", "file")
    assert source.documents[0].name == "owned" and source.documents[0].source_path == "source.yaml"
    await local.require_source(source)
    (tmp_path / "source.yaml").write_bytes(MANIFEST.replace(b"owned", b"changed"))
    with pytest.raises(AppError, match="changed"):
        await local.require_source(source)
    assert local.current_source is None
    with pytest.raises(AppError):
        await local.require_source(source)
    await local.close()
    await local.close()
    assert local.root is None and local.operation_count == 0
    for operation in (
        local.open_root(Path(".")),
        local.list(""),
        local.capture("source.yaml", "file"),
    ):
        with pytest.raises(AppError):
            await operation


@pytest.mark.asyncio
async def test_directory_invalid_yaml_is_not_silently_skipped_and_added_file_expires_review(
    tmp_path,
):
    (tmp_path / "one.yaml").write_bytes(MANIFEST)
    (tmp_path / "two.yaml").write_bytes(b"invalid: [")
    local = service(tmp_path)
    await local.open_root(Path("."))
    with pytest.raises(AppError):
        await local.capture("", "directory")
    assert local.current_source is None
    (tmp_path / "two.yaml").unlink()
    source = await local.capture("", "directory")
    (tmp_path / "two.yaml").write_bytes(MANIFEST.replace(b"owned", b"second"))
    with pytest.raises(AppError):
        await local.require_source(source)
    source = await local.capture("", "directory")
    assert [item.ordinal for item in source.documents] == [1, 2]
    local.invalidate()
    with pytest.raises(AppError):
        await local.require_source(source)
    await local.close()


@pytest.mark.asyncio
async def test_kustomization_inspection_masks_all_scalar_data_without_render(tmp_path):
    config = tmp_path / "kustomization.yaml"
    config.write_text(
        "kind: Kustomization\nconfigMapGenerator:\n- name: private-name\n  literals: [key=raw-generator-sentinel]\npatches:\n- patch: inline-patch-sentinel\n"
    )
    local = service(tmp_path, True)
    await local.open_root(Path("."))
    pages = await local.inspect_file("kustomization.yaml")
    assert (
        "raw-generator-sentinel" not in str(pages)
        and "inline-patch-sentinel" not in str(pages)
        and "private-name" not in str(pages)
    )
    assert "configMapGenerator" in str(pages) and local.current_source is None
    config.write_text("bad: [")
    with pytest.raises(AppError):
        await local.inspect_file("kustomization.yaml")
    await local.close()


@pytest.mark.asyncio
async def test_editor_disclosure_one_use_private_raw_draft_and_separate_exact_save(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    captured = await local.capture("source.yaml", "file")
    disclosure = await local.prepare_editor("source.yaml")
    proof = local.confirm_disclosure(disclosure)
    command = await local.open_editor(proof)
    draft = Path(command.argv[-1])
    assert (
        draft != source
        and draft.read_bytes() == MANIFEST
        and (draft.stat().st_mode & 0o777) == 0o600
    )
    local.require_editor_current()
    assert await local.prepare_save() is None
    with pytest.raises(AppError):
        await local.open_editor(proof)
    edited = MANIFEST.replace(b"raw-source-sentinel", b"raw-edited-sentinel")
    draft.write_bytes(edited)
    intent = await local.prepare_save()
    assert intent is not None and "raw-edited-sentinel" not in str(intent.preview_pages)
    assert source.read_bytes() == MANIFEST
    saved = await local.save(local.confirm_save(intent))
    assert saved.effect == "published" and source.read_bytes() == edited and not draft.exists()
    assert local.current_source is None
    with pytest.raises(AppError):
        await local.require_source(captured)
    with pytest.raises(AppError):
        await local.save(proof)
    await local.close()


@pytest.mark.asyncio
async def test_forged_proof_consumes_disclosure_and_source_change_blocks_save(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    proof = local.confirm_disclosure(disclosure)
    with pytest.raises(AppError):
        await local.open_editor(Confirmation(proof.intent, proof.token))
    with pytest.raises(AppError):
        await local.open_editor(proof)
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    draft.write_bytes(MANIFEST.replace(b"owned", b"edited"))
    intent = await local.prepare_save()
    assert intent is not None
    approval = local.confirm_save(intent)
    source.write_bytes(MANIFEST.replace(b"owned", b"replaced"))
    with pytest.raises(AppError):
        await local.save(approval)
    assert b"replaced" in source.read_bytes()
    await local.close_draft()
    assert not draft.exists()
    await local.close()


@pytest.mark.asyncio
async def test_malformed_source_is_repairable_and_invalid_or_empty_edit_cannot_save(tmp_path):
    source = tmp_path / "source.yaml"
    source.write_bytes(b"malformed: [")
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    for invalid in (b"malformed: {", b"# empty"):
        draft.write_bytes(invalid)
        with pytest.raises(AppError):
            await local.prepare_save()
    draft.write_bytes(MANIFEST)
    intent = await local.prepare_save()
    assert intent is not None
    await local.save(local.confirm_save(intent))
    assert source.read_bytes() == MANIFEST
    await local.close()


@pytest.mark.asyncio
async def test_kustomization_editor_save_never_displays_generator_values(tmp_path):
    source = tmp_path / "kustomization.yaml"
    source.write_text("configMapGenerator: [{name: owned, literals: [key=old-secret]}]")
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("kustomization.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    Path(command.argv[-1]).write_text(
        "configMapGenerator: [{name: owned, literals: [key=new-secret]}]"
    )
    intent = await local.prepare_save()
    assert (
        intent is not None
        and "new-secret" not in str(intent.preview_pages)
        and "old-secret" not in str(intent.preview_pages)
    )
    await local.save(local.confirm_save(intent))
    assert "new-secret" in source.read_text()
    await local.close()


@pytest.mark.asyncio
async def test_read_only_policy_blocks_editor_save_even_after_disclosure_or_draft(tmp_path):
    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    approval = local.confirm_disclosure(disclosure)
    local.policy.tighten()
    with pytest.raises(AppError, match="Read-only"):
        await local.open_editor(approval)
    with pytest.raises(AppError, match="Read-only"):
        await local.prepare_editor("source.yaml")
    assert (await local.capture("source.yaml", "file")).documents
    await local.close()


@pytest.mark.asyncio
async def test_root_change_expires_editor_and_all_prior_source_reviews(tmp_path):
    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    (tmp_path / "other").mkdir()
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    await local.open_root(Path("other"))
    assert not draft.exists()
    with pytest.raises(AppError):
        local.require_editor_current()
    with pytest.raises(AppError):
        local.confirm_disclosure(disclosure)
    await local.close()


class CooperativeFiles(ManifestFiles):
    def __init__(self, *, cwd):
        super().__init__(cwd=cwd)
        self.entered = threading.Event()
        self.finished = threading.Event()

    def list(self, root, relative, *, cancel):
        if relative == "held":
            self.entered.set()
            cancel.wait(5)
            self.finished.set()
        return super().list(root, "", cancel=cancel)


@pytest.mark.asyncio
async def test_repeated_cancellation_drains_actual_cooperative_worker_before_close(tmp_path):
    files = CooperativeFiles(cwd=tmp_path)
    local = service(tmp_path, files=files)
    await local.open_root(Path("."))
    task = asyncio.create_task(local.list("held"))
    assert await asyncio.to_thread(files.entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert files.finished.is_set() and local.operation_count == 0
    await local.close()


@pytest.mark.asyncio
async def test_arbitrary_configuration_filename_masks_generator_literals(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "configMapGenerator: [{name: opaque-name, literals: [key=private-configuration-sentinel]}]"
    )
    local = service(tmp_path, True)
    await local.open_root(Path("."))
    pages = await local.inspect_file("settings.yaml")
    assert "private-configuration-sentinel" not in str(pages) and "opaque-name" not in str(pages)
    assert "structure" in str(pages)
    await local.close()


@pytest.mark.asyncio
async def test_source_resource_count_is_cumulative_across_directory_files(tmp_path):
    (tmp_path / "one.yaml").write_bytes(b"\n---\n".join(MANIFEST for _ in range(60)))
    (tmp_path / "two.yaml").write_bytes(b"\n---\n".join(MANIFEST for _ in range(41)))
    local = service(tmp_path)
    await local.open_root(Path("."))
    with pytest.raises(AppError, match="100 resources"):
        await local.capture("", "directory")
    assert local.current_source is None
    await local.close()


@pytest.mark.asyncio
async def test_save_forgery_is_consumed_and_changed_review_cannot_be_confirmed(tmp_path):
    from dataclasses import replace

    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    Path(command.argv[-1]).write_bytes(MANIFEST.replace(b"owned", b"changed"))
    intent = await local.prepare_save()
    assert intent is not None
    with pytest.raises(AppError):
        local.confirm_save(replace(intent, identity=intent.identity))
    proof = local.confirm_save(intent)
    with pytest.raises(AppError, match="invalid or already consumed"):
        await local.save(Confirmation(proof.intent, proof.token))
    with pytest.raises(AppError):
        await local.save(proof)
    await local.close()


@pytest.mark.asyncio
async def test_cancel_after_rename_retains_known_save_outcome_and_cleans_draft(
    tmp_path, monkeypatch
):
    import os

    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    draft.write_bytes(MANIFEST.replace(b"owned", b"changed"))
    intent = await local.prepare_save()
    assert intent is not None
    renamed, release = threading.Event(), threading.Event()
    original = os.replace

    def replace_file(*args, **kwargs):
        original(*args, **kwargs)
        renamed.set()
        release.wait(5)

    monkeypatch.setattr(os, "replace", replace_file)
    saving = asyncio.create_task(local.save(local.confirm_save(intent)))
    assert await asyncio.to_thread(renamed.wait, 5)
    saving.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await saving
    assert local.last_file_outcome is not None and local.last_file_outcome.effect == "published"
    assert b"changed" in (tmp_path / "source.yaml").read_bytes() and not draft.exists()
    await local.close()


class DelayedFiles(ManifestFiles):
    def __init__(self, *, cwd):
        super().__init__(cwd=cwd)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.completed = threading.Event()

    def root(self, path, *, cancel):
        if str(path) == "held":
            self.entered.set()
            self.release.wait(5)
            self.completed.set()
            path = Path(".")
        return super().root(path, cancel=cancel)

    def list(self, root, relative, *, cancel):
        if relative == "held":
            self.entered.set()
            cancel.wait(5)
            self.release.wait(5)
            self.completed.set()
        return super().list(root, "", cancel=cancel)


@pytest.mark.asyncio
async def test_obsolete_root_worker_cannot_publish_after_new_root_intent(tmp_path):
    files = DelayedFiles(cwd=tmp_path)
    local = service(tmp_path, files=files)
    opening = asyncio.create_task(local.open_root(Path("held")))
    assert await asyncio.to_thread(files.entered.wait, 5)
    await local.open_root(Path("."))
    files.release.set()
    with pytest.raises(AppError, match="obsolete"):
        await opening
    assert files.completed.is_set() and local.root.path == tmp_path
    await local.close()


@pytest.mark.asyncio
async def test_close_during_active_worker_drains_through_repeated_close_cancellation(tmp_path):
    files = DelayedFiles(cwd=tmp_path)
    local = service(tmp_path, files=files)
    await local.open_root(Path("."))
    listing = asyncio.create_task(local.list("held"))
    assert await asyncio.to_thread(files.entered.wait, 5)
    closing = asyncio.create_task(local.close())
    await asyncio.sleep(0)
    closing.cancel()
    await asyncio.sleep(0)
    closing.cancel()
    files.release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    with pytest.raises(asyncio.CancelledError):
        await listing
    assert files.completed.is_set() and local.operation_count == 0 and local.root is None


@pytest.mark.asyncio
async def test_editor_draft_creation_io_error_is_safe_and_never_changes_source(
    tmp_path, monkeypatch
):
    import tempfile

    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")

    def fail(*args, **kwargs):
        raise OSError("private-path-and-secret-sentinel")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", fail)
    with pytest.raises(AppError) as error:
        await local.open_editor(local.confirm_disclosure(disclosure))
    assert (
        "secret-sentinel" not in str(error.value)
        and (tmp_path / "source.yaml").read_bytes() == MANIFEST
    )
    await local.close()


@pytest.mark.asyncio
async def test_failed_private_draft_cleanup_retains_owner_for_explicit_retry(tmp_path, monkeypatch):
    from kuberich.adapters.editing import ManifestFile

    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    original = ManifestFile.close
    failures = 0

    def close_once(self):
        nonlocal failures
        failures += 1
        if failures == 1:
            raise OSError("private-draft-path-sentinel")
        return original(self)

    monkeypatch.setattr(ManifestFile, "close", close_once)
    with pytest.raises(AppError, match="cleanup could not be confirmed") as error:
        await local.close_draft()
    assert "private-draft-path-sentinel" not in str(error.value) and draft.exists()
    await local.close_draft()
    assert not draft.exists() and failures == 2
    await local.close()


@pytest.mark.asyncio
async def test_missing_source_invalidates_stored_capture_before_new_review(tmp_path):
    path = tmp_path / "source.yaml"
    path.write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    source = await local.capture("source.yaml", "file")
    path.unlink()
    with pytest.raises(AppError):
        await local.require_source(source)
    assert local.current_source is None
    await local.close()


@pytest.mark.asyncio
async def test_saved_source_retains_known_effect_when_private_draft_cleanup_fails(
    tmp_path, monkeypatch
):
    from kuberich.adapters.editing import ManifestFile

    path = tmp_path / "source.yaml"
    path.write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    draft.write_bytes(MANIFEST.replace(b"owned", b"changed"))
    intent = await local.prepare_save()
    assert intent is not None
    original = ManifestFile.close

    def refuse(self):
        raise OSError("private-cleanup-sentinel")

    monkeypatch.setattr(ManifestFile, "close", refuse)
    with pytest.raises(AppError):
        await local.save(local.confirm_save(intent))
    assert b"changed" in path.read_bytes() and draft.exists()
    assert (
        local.last_file_outcome.effect == "published"
        and not local.last_file_outcome.cleanup_complete
    )
    monkeypatch.setattr(ManifestFile, "close", original)
    await local.close_draft()
    assert not draft.exists()
    await local.close()


@pytest.mark.asyncio
async def test_concurrent_draft_closers_share_one_owned_cleanup_through_cancellation(
    tmp_path, monkeypatch
):
    from kuberich.adapters.editing import ManifestFile

    (tmp_path / "source.yaml").write_bytes(MANIFEST)
    local = service(tmp_path)
    await local.open_root(Path("."))
    disclosure = await local.prepare_editor("source.yaml")
    command = await local.open_editor(local.confirm_disclosure(disclosure))
    draft = Path(command.argv[-1])
    entered, release = threading.Event(), threading.Event()
    original = ManifestFile.close
    calls = 0

    def close(self):
        nonlocal calls
        calls += 1
        entered.set()
        release.wait(5)
        return original(self)

    monkeypatch.setattr(ManifestFile, "close", close)
    first = asyncio.create_task(local.close_draft())
    assert await asyncio.to_thread(entered.wait, 5)
    second = asyncio.create_task(local.close_draft())
    await asyncio.sleep(0)
    first.cancel()
    await asyncio.sleep(0)
    first.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    await second
    assert calls == 1 and not draft.exists() and local.operation_count == 0
    await local.close()
