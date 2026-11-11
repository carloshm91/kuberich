"""Real no-follow private catalog storage, conflicts and failed publication cleanup."""

import json
import os
import threading
from dataclasses import replace

import pytest

from kuberich.adapters.helm_catalog_files import CatalogFiles
from kuberich.domain.helm_catalog import (
    CatalogSnapshot,
    HelmRepository,
    HelmRepositoryKind,
    RepositoryCredentials,
)
from kuberich.errors import AppError
from kuberich.services.access import AccessPolicy, Action


def mutate():
    AccessPolicy(False).require(Action.MUTATE)


def read(files):
    return files.read(
        guard=lambda: AccessPolicy(True).require(Action.READ), cancel=threading.Event()
    )


def publish(files, receipt, *, name="owned", credentials=None):
    repositories = (
        HelmRepository(name, "https://charts.invalid", HelmRepositoryKind.HTTP, "a" * 64),
    )
    return files.write(
        CatalogSnapshot(receipt.snapshot.generation + 1, repositories),
        {name: credentials or RepositoryCredentials()},
        receipt,
        guard=mutate,
        cancel=threading.Event(),
    )


def test_private_generation_store_has_no_ambient_helm_or_credentials_import(tmp_path):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    first = read(files)
    assert first.snapshot == CatalogSnapshot() and not root.exists()
    committed = publish(files, first, credentials=RepositoryCredentials(token="synthetic-private"))
    assert read(files) == committed
    assert (
        files.credentials(committed, guard=mutate, cancel=threading.Event())["owned"].token
        == "synthetic-private"
    )
    assert root.stat().st_mode & 0o777 == 0o700
    assert len(tuple(root.iterdir())) == 2
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
    assert b"synthetic-private" not in (root / "catalog.json").read_bytes()
    assert "synthetic-private" not in repr(committed)


@pytest.mark.parametrize(
    "fault",
    [
        "root-link",
        "parent-link",
        "root-mode",
        "metadata-link",
        "metadata-mode",
        "metadata-hardlink",
        "credential-link",
        "credential-mode",
        "credential-hardlink",
        "credential-tamper",
        "unknown-entry",
    ],
)
def test_local_trust_boundary_refuses_links_modes_and_foreign_inventory(tmp_path, fault):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    receipt = publish(files, read(files))
    metadata = root / "catalog.json"
    secret = root / receipt.credentials_file
    if fault == "root-link":
        moved = tmp_path / "moved"
        root.rename(moved)
        root.symlink_to(moved, target_is_directory=True)
    elif fault == "parent-link":
        parent = tmp_path / "linked"
        parent.symlink_to(tmp_path, target_is_directory=True)
        files = CatalogFiles(parent / "catalog")
    elif fault == "root-mode":
        root.chmod(0o755)
    elif fault == "unknown-entry":
        (root / "foreign").write_bytes(b"foreign")
    else:
        path = metadata if fault.startswith("metadata") else secret
        if fault.endswith("mode"):
            path.chmod(0o644)
        elif fault.endswith("hardlink"):
            os.link(path, tmp_path / "retained-hardlink")
        elif fault.endswith("link"):
            moved = tmp_path / "moved-file"
            path.rename(moved)
            path.symlink_to(moved)
        else:
            path.write_bytes(b"tampered")
    with pytest.raises(AppError):
        current = read(files)
        files.credentials(current, guard=mutate, cancel=threading.Event())


def test_stale_receipts_and_metadata_replacement_refuse_authority(tmp_path):
    files = CatalogFiles(tmp_path / "catalog")
    original = publish(files, read(files))
    second = publish(files, original, name="second")
    with pytest.raises(AppError):
        publish(files, original)
    with pytest.raises(AppError):
        files.credentials(original, guard=mutate, cancel=threading.Event())
    metadata = tmp_path / "catalog/catalog.json"
    replacement = tmp_path / "replacement"
    replacement.write_bytes(metadata.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(metadata)
    with pytest.raises(AppError):
        publish(files, second)


def test_failed_atomic_publication_and_precommit_cancellation_remove_owned_staging(
    tmp_path, monkeypatch
):
    files = CatalogFiles(tmp_path / "catalog")
    receipt = read(files)

    def refuse(*args, **kwargs):
        raise OSError("synthetic private source must not appear")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(AppError) as error:
        publish(files, receipt)
    assert "synthetic private" not in str(error.value)
    assert not tuple((tmp_path / "catalog").iterdir())
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(AppError):
        files.write(CatalogSnapshot(1), {}, read(files), guard=mutate, cancel=cancelled)
    assert not tuple((tmp_path / "catalog").iterdir())


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "schema",
        "repository-kind",
        "chart-type",
        "credential-path",
        "credential-schema",
    ],
)
def test_stored_schema_is_typed_bounded_and_never_treated_as_execution_input(tmp_path, fault):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    receipt = publish(files, read(files))
    metadata = root / "catalog.json"
    value = json.loads(metadata.read_bytes())
    if fault == "duplicate":
        metadata.write_bytes(b'{"schema":1,"schema":1}')
    else:
        if fault == "schema":
            value["schema"] = 2
        elif fault == "repository-kind":
            value["repositories"][0]["kind"] = "foreign"
        elif fault == "chart-type":
            value["charts"] = ["foreign"]
        elif fault == "credential-path":
            value["credentials_file"] = "../foreign.json"
        else:
            secret = root / receipt.credentials_file
            secret.write_bytes(b'{"foreign":{}}')
        if fault != "credential-schema":
            metadata.write_text(json.dumps(value))
    with pytest.raises(AppError):
        current = read(files)
        files.credentials(current, guard=mutate, cancel=threading.Event())


def test_forged_credential_receipt_cannot_publish_or_escape_directory(tmp_path):
    files = CatalogFiles(tmp_path / "catalog")
    original = publish(files, read(files))
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain")
    outside.chmod(0o600)
    forged = replace(original, credentials_file="../outside")
    before = (tmp_path / "catalog/catalog.json").read_bytes()
    with pytest.raises(AppError):
        publish(files, forged, name="replacement")
    assert outside.read_bytes() == b"must remain"
    assert (tmp_path / "catalog/catalog.json").read_bytes() == before


@pytest.mark.parametrize(
    "fault",
    [
        "repositories-type",
        "charts-type",
        "repository-shape",
        "ca-type",
        "token-origins-type",
        "download-origins-type",
        "boolean-schema",
        "empty-root",
        "large-credential",
        "many-files",
    ],
)
def test_bounded_stored_inventory_and_field_types_fail_before_authority(tmp_path, fault):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    receipt = publish(files, read(files))
    metadata = root / "catalog.json"
    value = json.loads(metadata.read_bytes())
    if fault == "repositories-type":
        value["repositories"] = {}
    elif fault == "charts-type":
        value["charts"] = {}
    elif fault == "repository-shape":
        value["repositories"] = [{}]
    elif fault == "ca-type":
        value["repositories"][0]["ca_file"] = 4
    elif fault == "token-origins-type":
        value["repositories"][0]["token_origins"] = "foreign"
    elif fault == "download-origins-type":
        value["repositories"][0]["download_origins"] = "foreign"
    elif fault == "boolean-schema":
        value["schema"] = True
    elif fault == "empty-root":
        metadata.unlink()
        (root / receipt.credentials_file).unlink()
        assert read(files).snapshot == CatalogSnapshot()
        return
    elif fault == "large-credential":
        (root / receipt.credentials_file).write_bytes(b" " * (1024 * 1024 + 1))
    elif fault == "many-files":
        for index in range(130):
            path = root / ("credentials-" + f"{index:064x}" + ".json")
            path.write_bytes(b"{}")
            path.chmod(0o600)
    if fault not in {"large-credential", "many-files"}:
        metadata.write_text(json.dumps(value))
    with pytest.raises(AppError):
        read(files)


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b'{"foreign":{}}',
        b'{"owned":{}}',
        b'{"owned":{"username":null,"password":null,"token":4}}',
    ],
)
def test_selfconsistent_credential_hash_never_bypasses_its_typed_schema(tmp_path, body):
    import hashlib

    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    receipt = publish(files, read(files))
    (root / receipt.credentials_file).write_bytes(body)
    metadata = root / "catalog.json"
    value = json.loads(metadata.read_bytes())
    value["credentials_sha256"] = hashlib.sha256(body).hexdigest()
    metadata.write_text(json.dumps(value))
    current = read(files)
    with pytest.raises(AppError):
        files.credentials(current, guard=mutate, cancel=threading.Event())


def test_public_store_rejects_invalid_root_and_generation_without_staged_files(tmp_path):
    for path in ("not-a-path", tmp_path / ".." / "escape"):
        with pytest.raises(AppError):
            CatalogFiles(path)
    files = CatalogFiles(tmp_path / "catalog")
    receipt = publish(files, read(files))
    before = (tmp_path / "catalog/catalog.json").read_bytes()
    for snapshot, credentials in (
        (CatalogSnapshot(9), {}),
        (CatalogSnapshot(2), {"foreign": RepositoryCredentials()}),
    ):
        with pytest.raises(AppError):
            files.write(snapshot, credentials, receipt, guard=mutate, cancel=threading.Event())
    assert (tmp_path / "catalog/catalog.json").read_bytes() == before
    assert len(tuple((tmp_path / "catalog").iterdir())) == 2


def test_changed_named_root_during_read_is_detected_before_return(tmp_path, monkeypatch):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    publish(files, read(files))
    selected = (root / "catalog.json").stat().st_ino
    original = os.read
    changed = False

    def swap(descriptor, limit):
        nonlocal changed
        data = original(descriptor, limit)
        if not changed and os.fstat(descriptor).st_ino == selected:
            changed = True
            root.rename(tmp_path / "retired")
            root.mkdir(mode=0o700)
        return data

    monkeypatch.setattr(os, "read", swap)
    with pytest.raises(AppError):
        read(files)
    assert not tuple(root.iterdir())


def test_cancelled_after_staging_does_not_replace_existing_catalog(tmp_path):
    root = tmp_path / "catalog"
    files = CatalogFiles(root)
    receipt = publish(files, read(files))
    before = (root / "catalog.json").read_bytes()
    cancel = threading.Event()

    def cancel_staged():
        mutate()
        if len(tuple(root.iterdir())) > 2:
            cancel.set()

    with pytest.raises(AppError):
        files.write(CatalogSnapshot(2), {}, receipt, guard=cancel_staged, cancel=cancel)
    assert (root / "catalog.json").read_bytes() == before
    assert len(tuple(root.iterdir())) == 2
