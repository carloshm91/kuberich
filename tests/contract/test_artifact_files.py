"""Actual private local files, anchored entry races and truthful transaction outcomes."""

import os
import stat
import threading
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from kuberich.adapters import artifact_files
from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.domain.exports import DocumentSource, ExportCapture, ExportScope, prepare_capture
from kuberich.errors import AppError, ExitCode


def prepared(text="retained safe text"):
    return prepare_capture(
        ExportCapture(
            scope=ExportScope(
                export_at=None,
                source_at=None,
                context=None,
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="local",
            ),
            source=DocumentSource(page="details", text=text),
        ),
        "screen",
        artifact_id=uuid4(),
    )


@pytest.fixture
def files(tmp_path):
    return ArtifactFiles(cwd=tmp_path)


def root(files, path):
    return files.directory(path, create=False, cancel=threading.Event())


def save(files, path, name="saved.txt", value=None):
    review = files.review(root(files, path), name, replace=False, cancel=threading.Event())
    return files.publish(value or prepared(), review, cancel=threading.Event())


def test_private_creation_captured_cwd_roundtrip_and_delete(files, tmp_path, monkeypatch):
    old = os.umask(0o777)
    try:
        directory = files.directory(
            tmp_path / "new" / "exports", create=True, cancel=threading.Event()
        )
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "new").stat().st_mode) == 0o700
    assert stat.S_IMODE(directory.path.stat().st_mode) == 0o700
    monkeypatch.chdir("/")
    assert root(files, Path("new/exports")) == directory
    outcome = save(files, directory.path)
    assert outcome.effect == "published" and outcome.durable and outcome.cleanup_complete
    assert stat.S_IMODE(outcome.ref.identity.mode) == 0o600
    assert outcome.ref.identity.nlink == 1
    assert files.read(outcome.ref, cancel=threading.Event()) == prepared().payload
    assert files.scan(directory, cancel=threading.Event()).refs[0].name == "saved.txt"
    assert files.delete(outcome.ref, cancel=threading.Event()).effect == "deleted"
    assert not tuple(directory.path.iterdir())


@pytest.mark.parametrize("path", ["../escape", "part/../escape", "bad\npath", "bad\x7fpath"])
def test_lexical_unsafe_paths_refused(files, path):
    with pytest.raises(AppError) as error:
        files.directory(Path(path), create=True, cancel=threading.Event())
    assert error.value.code is ExitCode.LOCAL_IO


def test_symlink_ancestor_final_and_replaced_root_refused(files, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    for name in ("alias", "alias/child"):
        with pytest.raises(AppError):
            files.directory(tmp_path / name, create=True, cancel=threading.Event())
    selected = tmp_path / "selected"
    selected.mkdir(mode=0o700)
    captured = root(files, selected)
    selected.rename(tmp_path / "original")
    selected.mkdir(mode=0o700)
    with pytest.raises(AppError):
        files.scan(captured, cancel=threading.Event())
    assert not (outside / "child").exists()


def test_ineligible_directory_and_owner_refused(files, tmp_path, monkeypatch):
    tmp_path.chmod(0o777)
    with pytest.raises(AppError):
        root(files, tmp_path)
    tmp_path.chmod(0o700)
    monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    with pytest.raises(AppError):
        root(files, tmp_path)


@pytest.mark.parametrize(
    "kind", ["symlink", "dangling", "hardlink", "fifo", "directory", "large", "foreign"]
)
def test_scan_and_review_reject_unsafe_entries(files, tmp_path, kind, monkeypatch):
    destination = tmp_path / "unsafe"
    if kind == "symlink":
        destination.symlink_to(tmp_path / "sentinel")
    elif kind == "dangling":
        destination.symlink_to(tmp_path / "missing")
    elif kind == "hardlink":
        destination.write_bytes(b"sentinel")
        os.link(destination, tmp_path / "second")
    elif kind == "fifo":
        os.mkfifo(destination)
    elif kind == "directory":
        destination.mkdir()
    elif kind == "large":
        destination.write_bytes(b"large")
        monkeypatch.setattr(artifact_files, "MAX_ARTIFACT_BYTES", 3)
    else:
        destination.write_bytes(b"foreign")
        original = os.stat

        def foreign(name, **kwargs):
            value = original(name, **kwargs)
            if name == "unsafe":
                fields = list(value)
                fields[4] = os.geteuid() + 1
                return os.stat_result(fields)
            return value

        monkeypatch.setattr(os, "stat", foreign)
    directory = root(files, tmp_path)
    assert files.scan(directory, cancel=threading.Event()).skipped >= 1
    with pytest.raises(AppError):
        files.review(directory, "unsafe", replace=True, cancel=threading.Event())


def test_exclusive_overwrite_identity_and_sentinel_safety(files, tmp_path):
    original = save(files, tmp_path)
    directory = original.ref.directory
    review = files.review(directory, original.ref.name, replace=False, cancel=threading.Event())
    assert review.expected == original.ref.identity
    with pytest.raises(AppError, match="exists"):
        files.publish(prepared("new"), review, cancel=threading.Event())
    confirmed = replace(review, replace=True)
    changed = files.publish(prepared("new"), confirmed, cancel=threading.Event())
    assert changed.ref.identity.inode != original.ref.identity.inode
    with pytest.raises(AppError):
        files.read(original.ref, cancel=threading.Event())
    with pytest.raises(AppError):
        files.publish(prepared(), confirmed, cancel=threading.Event())
    with pytest.raises(AppError):
        files.delete(original.ref, cancel=threading.Event())
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    (tmp_path / original.ref.name).unlink()
    (tmp_path / original.ref.name).symlink_to(sentinel)
    with pytest.raises(AppError):
        files.delete(changed.ref, cancel=threading.Event())
    assert sentinel.read_text() == "keep"


def test_late_final_symlink_swap_never_modifies_referent(files, tmp_path, monkeypatch):
    original = save(files, tmp_path)
    review = files.review(
        original.ref.directory, original.ref.name, replace=True, cancel=threading.Event()
    )
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    replace_call = os.replace

    def swap(source, destination, **kwargs):
        (tmp_path / destination).unlink()
        (tmp_path / destination).symlink_to(sentinel)
        replace_call(source, destination, **kwargs)

    monkeypatch.setattr(os, "replace", swap)
    assert (
        files.publish(prepared("replacement"), review, cancel=threading.Event()).effect
        == "published"
    )
    assert sentinel.read_text() == "keep"


def test_late_delete_symlink_swap_never_deletes_referent(files, tmp_path, monkeypatch):
    original = save(files, tmp_path)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    unlink = os.unlink

    def swap(name, **kwargs):
        unlink(name, **kwargs)
        (tmp_path / name).symlink_to(sentinel)
        unlink(name, **kwargs)

    monkeypatch.setattr(os, "unlink", swap)
    assert files.delete(original.ref, cancel=threading.Event()).effect == "deleted"
    assert sentinel.read_text() == "keep"


def test_bounded_prefix_hash_and_read_mutation(files, tmp_path, monkeypatch):
    value = prepared("a" * 20000)
    outcome = save(files, tmp_path, value=value)
    assert len(files.read(outcome.ref, prefix=True, cancel=threading.Event())) == 8193
    with pytest.raises(AppError):
        files.read(replace(outcome.ref, sha256="wrong"), cancel=threading.Event())
    original = os.read
    mutated = False

    def changed(descriptor, count):
        nonlocal mutated
        data = original(descriptor, count)
        if not mutated:
            mutated = True
            with (tmp_path / "saved.txt").open("ab") as stream:
                stream.write(b"changed")
        return data

    monkeypatch.setattr(os, "read", changed)
    with pytest.raises(AppError):
        files.read(outcome.ref, cancel=threading.Event())


def test_scan_bound_and_disappeared_entry(files, tmp_path, monkeypatch):
    for index in range(4):
        (tmp_path / str(index)).write_text("safe")
    monkeypatch.setattr(artifact_files, "MAX_ENTRIES", 2)
    scan = files.scan(root(files, tmp_path), cancel=threading.Event())
    assert scan.limited and len(scan.refs) == 2
    original = os.stat

    def disappeared(name, **kwargs):
        if "dir_fd" in kwargs:
            raise FileNotFoundError()
        return original(name, **kwargs)

    monkeypatch.setattr(os, "stat", disappeared)
    assert files.scan(root(files, tmp_path), cancel=threading.Event()).skipped == 2


@pytest.mark.parametrize("point", ["before", "write", "fsync", "changed", "link"])
def test_precommit_failure_preserves_prior_and_cleans_stage(files, tmp_path, monkeypatch, point):
    cancel = threading.Event()
    review = files.review(root(files, tmp_path), "saved.txt", replace=False, cancel=cancel)
    if point == "before":
        cancel.set()
    elif point == "write":
        monkeypatch.setattr(os, "write", lambda *_: 0)
    elif point == "fsync":
        monkeypatch.setattr(os, "fsync", lambda *_: (_ for _ in ()).throw(OSError()))
    elif point == "changed":
        original = os.fsync

        def change(fd):
            original(fd)
            (tmp_path / "saved.txt").write_text("outside change")

        monkeypatch.setattr(os, "fsync", change)
    else:
        monkeypatch.setattr(os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    with pytest.raises(AppError):
        files.publish(prepared(), review, cancel=cancel)
    assert not tuple(tmp_path.glob(".kuberich-export-*"))
    if point == "changed":
        assert (tmp_path / "saved.txt").read_text() == "outside change"
    else:
        assert not (tmp_path / "saved.txt").exists()


def test_postcommit_cancellation_and_durability_are_truthful(files, tmp_path, monkeypatch):
    cancel = threading.Event()
    original = os.link

    def commit(*args, **kwargs):
        original(*args, **kwargs)
        cancel.set()

    monkeypatch.setattr(os, "link", commit)
    sync = os.fsync

    def sync_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError()
        sync(fd)

    monkeypatch.setattr(os, "fsync", sync_directory)
    review = files.review(root(files, tmp_path), "saved.txt", replace=False, cancel=cancel)
    outcome = files.publish(prepared(), review, cancel=cancel)
    assert outcome.effect == "published" and not outcome.durable
    assert outcome.cleanup_complete and "durability" in outcome.notice
    assert (tmp_path / "saved.txt").read_bytes() == prepared().payload


def test_stage_cleanup_failure_reported_before_and_after_commit(files, tmp_path, monkeypatch):
    unlink = os.unlink

    def fail_stage(name, **kwargs):
        if name.startswith(".kuberich-export-"):
            raise OSError()
        unlink(name, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_stage)
    outcome = save(files, tmp_path)
    assert outcome.effect == "published" and not outcome.cleanup_complete
    assert "cleanup" in outcome.notice
    monkeypatch.setattr(os, "write", lambda *_: 0)
    review = files.review(
        root(files, tmp_path), "other.txt", replace=False, cancel=threading.Event()
    )
    outcome = files.publish(prepared(), review, cancel=threading.Event())
    assert outcome.effect == "none" and not outcome.cleanup_complete and outcome.ref is None


def test_delete_fsync_failure_and_os_read_errors(files, tmp_path, monkeypatch):
    outcome = save(files, tmp_path)
    read = os.read
    monkeypatch.setattr(os, "read", lambda *_: (_ for _ in ()).throw(OSError("private")))
    with pytest.raises(AppError) as error:
        files.read(outcome.ref, cancel=threading.Event())
    assert "private" not in str(error.value)
    monkeypatch.setattr(os, "read", read)
    monkeypatch.setattr(os, "fsync", lambda *_: (_ for _ in ()).throw(OSError()))
    deleted = files.delete(outcome.ref, cancel=threading.Event())
    assert deleted.effect == "deleted" and not deleted.durable


def test_invalid_hash_and_oversize_preparation_not_published(files, tmp_path, monkeypatch):
    review = files.review(
        root(files, tmp_path), "saved.txt", replace=False, cancel=threading.Event()
    )
    value = prepared()
    with pytest.raises(AppError):
        files.publish(replace(value, sha256="wrong"), review, cancel=threading.Event())
    monkeypatch.setattr(artifact_files, "MAX_ARTIFACT_BYTES", 2)
    with pytest.raises(AppError):
        files.publish(value, review, cancel=threading.Event())
    assert not tuple(tmp_path.iterdir())


def test_constructor_invalid_names_and_io_failures_are_fixed(files, tmp_path, monkeypatch):
    from pathlib import Path

    with pytest.raises(AppError):
        ArtifactFiles(cwd=Path("relative"))
    directory = root(files, tmp_path)
    with pytest.raises(AppError) as error:
        files.review(directory, "../escape", replace=False, cancel=threading.Event())
    assert error.value.code is ExitCode.LOCAL_IO
    value = save(files, tmp_path).ref
    with pytest.raises(AppError):
        files.read(replace(value, name="missing"), cancel=threading.Event())
    monkeypatch.setattr(os, "scandir", lambda *_: (_ for _ in ()).throw(OSError("private")))
    with pytest.raises(AppError) as error:
        files.scan(directory, cancel=threading.Event())
    assert "private" not in str(error.value)
    monkeypatch.setattr(os, "stat", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(AppError):
        files.review(directory, "saved.txt", replace=True, cancel=threading.Event())


def test_sensitive_file_requires_private_mode(files, tmp_path):
    from kuberich.domain.exports import ResourceSource
    from kuberich.domain.resources import ApiResource, resource_record

    resource = ApiResource("", "v1", "secrets", "Secret", True, frozenset({"get"}))
    record = resource_record(
        resource,
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "one", "namespace": "team", "uid": "uid", "resourceVersion": "1"},
            "data": {"chosen": "dmFsdWU="},
        },
        "team",
    )
    source = ResourceSource(resource=resource, record=record)
    value = prepare_capture(
        ExportCapture(
            scope=ExportScope(
                export_at=None,
                source_at=None,
                context=None,
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="local",
            ),
            source=source,
        ),
        "resource-yaml",
        artifact_id=uuid4(),
        sensitive=True,
    )
    save(files, tmp_path, value=value)
    (tmp_path / "saved.txt").chmod(0o644)
    ref = files.scan(root(files, tmp_path), cancel=threading.Event()).refs[0]
    with pytest.raises(AppError):
        files.read(ref, cancel=threading.Event())


def test_creation_race_uses_existing_directory_without_chmod(files, tmp_path, monkeypatch):
    mkdir = os.mkdir

    def race(name, mode, **kwargs):
        mkdir(name, 0o750, **kwargs)
        raise FileExistsError()

    monkeypatch.setattr(os, "mkdir", race)
    result = files.directory(tmp_path / "race", create=True, cancel=threading.Event())
    assert result.path.stat().st_mode & 0o777 == 0o750


def test_read_growth_over_bound_and_stage_replacement_cleanup(files, tmp_path, monkeypatch):
    outcome = save(files, tmp_path)
    ref = outcome.ref
    # Bound failure still applies if a writer extends a valid opened inode.
    original = os.read

    def grow(fd, count):
        return b"x" * count

    monkeypatch.setattr(os, "read", grow)
    monkeypatch.setattr(artifact_files, "MAX_ARTIFACT_BYTES", ref.identity.size)
    with pytest.raises(AppError):
        files.read(ref, cancel=threading.Event())
    monkeypatch.setattr(os, "read", original)
    monkeypatch.setattr(artifact_files, "MAX_ARTIFACT_BYTES", 16 * 1024 * 1024)
    sync = os.fsync

    def replace_stage(fd):
        sync(fd)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            stage = next(tmp_path.glob(".kuberich-export-*"))
            stage.unlink()
            stage.write_text("foreign-stage-entry")
            raise OSError()

    monkeypatch.setattr(os, "fsync", replace_stage)
    review = files.review(ref.directory, "other.txt", replace=False, cancel=threading.Event())
    result = files.publish(prepared(), review, cancel=threading.Event())
    assert result.effect == "none" and not result.cleanup_complete
    assert next(tmp_path.glob(".kuberich-export-*")).read_text() == "foreign-stage-entry"


def test_delete_unlink_failure_does_not_claim_deletion(files, tmp_path, monkeypatch):
    ref = save(files, tmp_path).ref
    monkeypatch.setattr(os, "unlink", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    with pytest.raises(AppError):
        files.delete(ref, cancel=threading.Event())
    assert (tmp_path / ref.name).exists()


def test_unavailable_home_expansion_is_a_fixed_local_error(files, monkeypatch):
    def unavailable(path):
        raise RuntimeError("private account detail")

    monkeypatch.setattr(Path, "expanduser", unavailable)
    with pytest.raises(AppError) as error:
        files.directory(Path("~unavailable"), create=False, cancel=threading.Event())
    assert error.value.code is ExitCode.LOCAL_IO
    assert "private account detail" not in str(error.value)
