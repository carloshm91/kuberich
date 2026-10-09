"""Actual private files/archives: no traversal, links, special files or silent overwrite."""

import io
import os
import stat
import tarfile

import pytest

from kuberich.adapters import transfer_files
from kuberich.adapters.transfer_files import DownloadDestination, snapshot_upload
from kuberich.errors import AppError


def archive(path, entries, *, format=tarfile.PAX_FORMAT):
    with tarfile.open(path, "w", format=format) as output:
        for name, kind, data in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                entry.linkname = "../outside"
            elif kind == tarfile.REGTYPE:
                entry.size = len(data)
            output.addfile(entry, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
    return path


@pytest.mark.parametrize("directory", [False, True])
def test_download_extracts_private_regular_tree_and_publishes_exact_destination(
    tmp_path, directory
):
    entries = (
        [
            ("root", tarfile.DIRTYPE, b""),
            ("root/space café.bin", tarfile.REGTYPE, bytes(range(256))),
            ("root/sub", tarfile.DIRTYPE, b""),
            ("root/sub/empty", tarfile.REGTYPE, b""),
        ]
        if directory
        else [("root", tarfile.REGTYPE, bytes(range(256)))]
    )
    source = archive(tmp_path / "archive", entries)
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        inventory = destination.extract(source, "root")
        assert inventory.size == 256 and inventory.directory is directory
        assert not (tmp_path / "chosen").exists()
        destination.publish("root", inventory)
        assert destination.published
        selected = tmp_path / "chosen/space café.bin" if directory else tmp_path / "chosen"
        assert selected.read_bytes() == bytes(range(256))
        assert stat.S_IMODE(selected.stat().st_mode) == 0o600
    finally:
        destination.close()
    destination.close()
    assert not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.parametrize(
    "kind", ["exists", "directory", "symlink", "hardlink", "fifo", "parent-symlink"]
)
def test_destination_refuses_unreviewed_overwrite_links_and_special_files(tmp_path, kind):
    target = tmp_path / "chosen"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        target.symlink_to(tmp_path / "outside")
    elif kind == "hardlink":
        (tmp_path / "outside").write_bytes(b"private")
        os.link(tmp_path / "outside", target)
    elif kind == "fifo":
        os.mkfifo(target)
    elif kind == "parent-symlink":
        (tmp_path / "link").symlink_to(tmp_path, target_is_directory=True)
        target = tmp_path / "link/chosen"
    else:
        target.write_bytes(b"original")
    with pytest.raises((AppError, OSError)):
        DownloadDestination(target, False)
    assert not list(tmp_path.glob(".kuberich-copy-*"))


def test_explicit_overwrite_is_reviewed_and_changed_destination_is_refused(tmp_path):
    target = tmp_path / "chosen"
    target.write_bytes(b"original")
    source = archive(tmp_path / "archive", [("root", tarfile.REGTYPE, b"new")])
    destination = DownloadDestination(target, True)
    try:
        inventory = destination.extract(source, "root")
        target.write_bytes(b"changed")
        with pytest.raises(AppError, match="changed"):
            destination.publish("root", inventory)
        assert target.read_bytes() == b"changed"
    finally:
        destination.close()
    destination = DownloadDestination(target, True)
    try:
        inventory = destination.extract(source, "root")
        destination.publish("root", inventory)
    finally:
        destination.close()
    assert target.read_bytes() == b"new"


@pytest.mark.parametrize(
    "entries",
    [
        [("../outside", tarfile.REGTYPE, b"x")],
        [("/root", tarfile.REGTYPE, b"x")],
        [("root/../outside", tarfile.REGTYPE, b"x")],
        [("root//x", tarfile.REGTYPE, b"x")],
        [("root/./x", tarfile.REGTYPE, b"x")],
        [("root\x1b", tarfile.REGTYPE, b"x")],
        [("root", tarfile.SYMTYPE, b"")],
        [("root", tarfile.LNKTYPE, b"")],
        [("root", tarfile.FIFOTYPE, b"")],
        [("root", tarfile.CHRTYPE, b"")],
        [("root", tarfile.REGTYPE, b"x"), ("root", tarfile.REGTYPE, b"y")],
        [
            ("root", tarfile.DIRTYPE, b""),
            ("root/A", tarfile.REGTYPE, b"x"),
            ("root/a", tarfile.REGTYPE, b"y"),
        ],
        [("root", tarfile.DIRTYPE, b""), ("root/" + "/".join(["x"] * 32), tarfile.REGTYPE, b"x")],
        [("root", tarfile.REGTYPE, b"x"), ("root/child", tarfile.REGTYPE, b"x")],
        [("root/sub", tarfile.REGTYPE, b"x")],
    ],
)
def test_malicious_archives_cannot_publish_or_write_outside_private_staging(tmp_path, entries):
    source = archive(tmp_path / "archive", entries)
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        with pytest.raises((AppError, OSError, tarfile.TarError)):
            destination.extract(source, "root")
    finally:
        destination.close()
    assert not (tmp_path / "chosen").exists() and not (tmp_path / "outside").exists()
    assert not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.parametrize(
    "failure",
    ["size", "entries", "bad-header", "truncated", "no-end", "trailing", "extended-metadata"],
)
def test_archive_wire_metadata_and_payload_limits_are_enforced(tmp_path, monkeypatch, failure):
    source = archive(tmp_path / "archive", [("root", tarfile.REGTYPE, b"abc")])
    if failure == "size":
        monkeypatch.setattr(transfer_files, "MAX_TRANSFER_BYTES", 2)
    elif failure == "entries":
        monkeypatch.setattr(transfer_files, "MAX_TRANSFER_ENTRIES", 0)
    elif failure == "bad-header":
        source.write_bytes(b"x" * 10240)
    elif failure == "truncated":
        source.write_bytes(source.read_bytes()[:512] + bytes(512))
    elif failure == "no-end":
        source.write_bytes(source.read_bytes()[:1024])
    elif failure == "trailing":
        source.write_bytes(source.read_bytes() + b"x")
    else:
        entry = tarfile.TarInfo("pax")
        entry.type = tarfile.XHDTYPE
        entry.size = 65537
        source.write_bytes(entry.tobuf() + bytes(66048) + bytes(1024))
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        with pytest.raises((AppError, tarfile.TarError)):
            destination.extract(source, "root")
    finally:
        destination.close()


@pytest.mark.parametrize("directory", [False, True])
def test_upload_snapshot_is_private_bounded_and_independent_of_later_source_changes(
    tmp_path, directory
):
    source = tmp_path / "source"
    output = tmp_path / "snapshot"
    if directory:
        source.mkdir()
        (source / "sub").mkdir()
        (source / "sub/space.bin").write_bytes(bytes(range(256)))
    else:
        source.write_bytes(bytes(range(256)))
    inventory = snapshot_upload(source, output)
    selected = output / "sub/space.bin" if directory else output
    assert (
        selected.read_bytes() == bytes(range(256))
        and inventory.size == 256
        and inventory.directory is directory
    )
    assert stat.S_IMODE(selected.stat().st_mode) == 0o600
    if not directory:
        source.write_bytes(b"changed")
        assert output.read_bytes() == bytes(range(256))


@pytest.mark.parametrize(
    "failure",
    ["symlink", "parent-link", "hardlink", "fifo", "nested-link", "size", "entries", "depth"],
)
def test_upload_rejects_link_special_and_excessive_sources(tmp_path, monkeypatch, failure):
    source = tmp_path / "source"
    original = tmp_path / "outside"
    original.write_bytes(b"private")
    if failure == "symlink":
        source.symlink_to(original)
    elif failure == "parent-link":
        source.symlink_to(tmp_path, target_is_directory=True)
        source = source / "outside"
    elif failure == "hardlink":
        os.link(original, source)
    elif failure == "fifo":
        os.mkfifo(source)
    elif failure == "nested-link":
        source.mkdir()
        (source / "link").symlink_to(original)
    else:
        source.write_bytes(b"abc")
        monkeypatch.setattr(
            transfer_files,
            {
                "size": "MAX_TRANSFER_BYTES",
                "entries": "MAX_TRANSFER_ENTRIES",
                "depth": "MAX_TRANSFER_DEPTH",
            }[failure],
            0,
        )
    with pytest.raises((AppError, OSError)):
        snapshot_upload(source, tmp_path / "snapshot")
    assert original.read_bytes() == b"private"


def test_download_directory_cannot_replace_reviewed_existing_file(tmp_path):
    target = tmp_path / "chosen"
    target.write_bytes(b"original")
    source = archive(
        tmp_path / "archive",
        [("root", tarfile.DIRTYPE, b""), ("root/child", tarfile.REGTYPE, b"x")],
    )
    destination = DownloadDestination(target, True)
    try:
        inventory = destination.extract(source, "root")
        with pytest.raises(AppError, match="directory"):
            destination.publish("root", inventory)
        assert target.read_bytes() == b"original"
    finally:
        destination.close()


def test_directory_publication_failure_rolls_back_only_new_owned_destination(tmp_path, monkeypatch):
    source = archive(
        tmp_path / "archive",
        [
            ("root", tarfile.DIRTYPE, b""),
            ("root/a", tarfile.REGTYPE, b"x"),
            ("root/b", tarfile.REGTYPE, b"y"),
        ],
    )
    destination = DownloadDestination(tmp_path / "chosen", False)
    inventory = destination.extract(source, "root")
    original = transfer_files.os.rename
    calls = 0

    def fail_after_first(*arguments, **options):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("owned injected destination failure")
        return original(*arguments, **options)

    monkeypatch.setattr(transfer_files.os, "rename", fail_after_first)
    try:
        with pytest.raises(OSError):
            destination.publish("root", inventory)
        assert not (tmp_path / "chosen").exists() and not destination.published
    finally:
        destination.close()


def test_archive_parent_entries_can_follow_children_without_escaping(tmp_path):
    source = archive(
        tmp_path / "archive",
        [
            ("root/sub/child", tarfile.REGTYPE, b"x"),
            ("root/sub", tarfile.DIRTYPE, b""),
            ("root", tarfile.DIRTYPE, b""),
        ],
    )
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        inventory = destination.extract(source, "root")
        destination.publish("root", inventory)
        assert (tmp_path / "chosen/sub/child").read_bytes() == b"x"
    finally:
        destination.close()


@pytest.mark.parametrize(
    "failure",
    [
        "wire-small",
        "wire-large",
        "header-count",
        "negative-size",
        "payload-truncated",
        "end-marker",
    ],
)
def test_archive_header_negative_controls_before_materializing_payload(
    tmp_path, monkeypatch, failure
):
    source = archive(tmp_path / "archive", [("root", tarfile.REGTYPE, b"abc")])
    if failure == "wire-small":
        source.write_bytes(bytes(512))
    elif failure == "wire-large":
        monkeypatch.setattr(transfer_files, "MAX_ARCHIVE_BYTES", 1024)
    elif failure == "header-count":
        monkeypatch.setattr(transfer_files, "MAX_TRANSFER_ENTRIES", 0)
    elif failure == "negative-size":
        entry = tarfile.TarInfo("root")
        entry.size = -1
        source.write_bytes(entry.tobuf(format=tarfile.GNU_FORMAT) + bytes(1024))
    elif failure == "payload-truncated":
        entry = tarfile.TarInfo("root")
        entry.size = 16384
        source.write_bytes(entry.tobuf() + bytes(1024))
    else:
        source.write_bytes(source.read_bytes()[:1024] + bytes(512) + b"x" * 512)
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        with pytest.raises(AppError):
            destination.extract(source, "root")
    finally:
        destination.close()


@pytest.mark.parametrize(
    "failure", ["growing", "shrinking", "directory-change", "directory-count", "dot-parent"]
)
def test_upload_refuses_actual_source_mutation_and_unbounded_listing(
    tmp_path, monkeypatch, failure
):
    source = tmp_path / "source"
    if failure in ("directory-change", "directory-count"):
        source.mkdir()
        (source / "a").write_bytes(b"abc")
        (source / "b").write_bytes(b"def")
    else:
        source.write_bytes(b"abc")
    if failure == "directory-count":
        monkeypatch.setattr(transfer_files, "MAX_TRANSFER_ENTRIES", 1)
    elif failure == "dot-parent":
        (tmp_path / "child").mkdir()
        source = tmp_path / "child/../source"
    else:
        original = transfer_files.os.fstat
        selected = (source / "a" if failure == "directory-change" else source).stat().st_ino
        changed = False

        def mutate_after_stat(descriptor):
            nonlocal changed
            before = original(descriptor)
            if before.st_ino == selected and not changed:
                changed = True
                if failure == "directory-change":
                    (source / "added").write_bytes(b"x")
                elif failure == "growing":
                    source.write_bytes(b"abcdefgh")
                else:
                    source.write_bytes(b"")
            return before

        monkeypatch.setattr(transfer_files.os, "fstat", mutate_after_stat)
    with pytest.raises((AppError, OSError)):
        snapshot_upload(source, tmp_path / "snapshot")


@pytest.mark.parametrize(
    "kind", ["implicit-limit", "implicit-collision", "sparse-pax", "sparse-header", "metadata-sum"]
)
def test_implicit_directories_and_sparse_or_excessive_metadata_are_bounded_before_extraction(
    tmp_path, monkeypatch, kind
):
    source = tmp_path / "archive"
    if kind == "implicit-limit":
        archive(source, [("root", tarfile.DIRTYPE, b""), ("root/a/b/c", tarfile.REGTYPE, b"x")])
        monkeypatch.setattr(transfer_files, "MAX_TRANSFER_ENTRIES", 3)
    elif kind == "implicit-collision":
        archive(
            source,
            [
                ("root", tarfile.DIRTYPE, b""),
                ("root/A/x", tarfile.REGTYPE, b"x"),
                ("root/a/y", tarfile.REGTYPE, b"y"),
            ],
        )
    elif kind == "sparse-header":
        entry = tarfile.TarInfo("root")
        entry.type = tarfile.GNUTYPE_SPARSE
        source.write_bytes(entry.tobuf(format=tarfile.GNU_FORMAT) + bytes(1024))
    else:
        with tarfile.open(source, "w", format=tarfile.PAX_FORMAT) as output:
            entry = tarfile.TarInfo("root")
            entry.size = 1
            entry.pax_headers = (
                {"GNU.sparse.major": "1", "GNU.sparse.minor": "0"}
                if kind == "sparse-pax"
                else {"mtime": "123.4"}
            )
            output.addfile(entry, io.BytesIO(b"x"))
        if kind == "metadata-sum":
            monkeypatch.setattr(transfer_files, "MAX_EXTENDED_METADATA_BYTES", 1)
    destination = DownloadDestination(tmp_path / "chosen", False)
    try:
        with pytest.raises(AppError):
            destination.extract(source, "root")
    finally:
        destination.close()
    assert not (tmp_path / "chosen").exists() and not list(tmp_path.glob(".kuberich-copy-*"))
