"""Canonical exports retain actual HTTP receipts and honest uncertain outcomes."""

import hashlib
import json
from pathlib import Path

import pytest

from tests.quality.test_qualification import checkout as checkout
from tests.support import resource_creation_cli as helper


def receipt(mode="success"):
    return {
        "initially_offline": True,
        "source_capture_network_absent": True,
        "wrapped": False,
        "server_validation": "Owned synthetic retention fixture",
        "dry_runs": 2 if mode == "cancel" else 1,
        "later_item_unsent": mode == "cancel",
        "external_tool_executed": False,
        "complete_ansi_and_log_private_value_absent": True,
        "mode": mode,
        "persistent_posts": 1,
        "created_uid": "owned-uid",
        "created_version": "17",
        "request_bytes_identical": True,
        "no_replay": True,
        "source_and_kubeconfig_unchanged": True,
        "known_application_receipt": mode == "success",
        "application_result": "Succeeded" if mode == "success" else "Write outcome uncertain",
        "api_handlers_drained": True,
    }


def owned_source(checkout, monkeypatch):
    monkeypatch.setattr(helper, "ROOT", checkout)
    for caller in (
        "tests/terminal/test_resource_creation_cli.py",
        "tests/packaging/test_resource_creation_cli.py",
    ):
        path = checkout / caller
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Owned caller fixture\n")


@pytest.mark.parametrize("producer", ["source", "installed"])
@pytest.mark.parametrize("mode", ["success", "cancel"])
def test_canonical_receipt_is_byte_identical_unique_and_provenanced(
    checkout, tmp_path, monkeypatch, producer, mode
):
    owned_source(checkout, monkeypatch)
    original = tmp_path / "creation-cli-receipt.json"
    raw = (json.dumps(receipt(mode), indent=4) + "\n\n").encode()
    original.write_bytes(raw)
    first = helper.retain_creation_cli_receipt(tmp_path, producer, "owned-" + mode)
    second = helper.retain_creation_cli_receipt(tmp_path, producer, "owned-" + mode)
    assert first != second and first.read_bytes() == second.read_bytes() == raw
    assert first.relative_to(checkout).parts[:4] == (
        "artifacts",
        "resource-creation",
        producer,
        "owned-" + mode,
    )
    provenance = json.loads((first.parent / "provenance.json").read_text())
    assert provenance["original_path"] == str(original)
    assert (
        provenance["size"] == len(raw) and provenance["sha256"] == hashlib.sha256(raw).hexdigest()
    )
    assert provenance["commit"] and provenance["tree"] and provenance["producer_sha256"]
    assert provenance["application_result"] == receipt(mode)["application_result"]
    assert provenance["known_application_receipt"] is (mode == "success")
    assert provenance["status"] == "retained_original"


@pytest.mark.parametrize("value", [None, b"[]", b"{}", b'{"mode":"success"}'])
def test_missing_partial_controls_never_gain_success_exports(
    checkout, tmp_path, monkeypatch, value
):
    owned_source(checkout, monkeypatch)
    if value is not None:
        (tmp_path / "creation-cli-receipt.json").write_bytes(value)
    with pytest.raises(ValueError):
        helper.retain_creation_cli_receipt(tmp_path, "source", "owned")
    assert not (checkout / "artifacts/resource-creation").exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_handlers_drained", False),
        ("persistent_posts", 0),
        ("created_uid", ""),
        ("request_bytes_identical", False),
        ("known_application_receipt", True),
        ("application_result", "Succeeded"),
    ],
)
def test_uncertain_controls_cannot_be_promoted_to_success(
    checkout, tmp_path, monkeypatch, field, value
):
    owned_source(checkout, monkeypatch)
    data = receipt("cancel")
    data[field] = value
    (tmp_path / "creation-cli-receipt.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="partial"):
        helper.retain_creation_cli_receipt(tmp_path, "installed", "cancelled")
    assert not (checkout / "artifacts/resource-creation").exists()


@pytest.mark.parametrize("mode", ["success", "cancel"])
@pytest.mark.parametrize("field", ["persistent_posts", "dry_runs"])
@pytest.mark.parametrize("corrupt", [bool, float])
def test_count_controls_require_exact_integers(
    checkout, tmp_path, monkeypatch, mode, field, corrupt
):
    owned_source(checkout, monkeypatch)
    data = receipt(mode)
    data[field] = corrupt(data[field])
    original = tmp_path / "creation-cli-receipt.json"
    raw = (json.dumps(data, indent=3) + "\n").encode()
    original.write_bytes(raw)
    with pytest.raises(ValueError, match="partial"):
        helper.retain_creation_cli_receipt(tmp_path, "source", "owned-counts")
    assert original.read_bytes() == raw
    assert not (checkout / "artifacts/resource-creation").exists()


@pytest.mark.parametrize("scenario", ["../escape", "/absolute", "nested/path", "", "x" * 101])
def test_scenario_cannot_escape_owned_canonical_root(tmp_path, scenario):
    with pytest.raises(ValueError, match="identity"):
        helper.retain_creation_cli_receipt(tmp_path, "source", scenario)


def test_symlinked_original_or_destination_is_refused(checkout, tmp_path, monkeypatch):
    owned_source(checkout, monkeypatch)
    other = tmp_path / "other.json"
    other.write_text(json.dumps(receipt()))
    original = tmp_path / "creation-cli-receipt.json"
    original.symlink_to(other)
    with pytest.raises(ValueError, match="regular owned"):
        helper.retain_creation_cli_receipt(tmp_path, "source", "owned")
    original.unlink()
    original.write_bytes(other.read_bytes())
    (checkout / "artifacts").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        helper.retain_creation_cli_receipt(tmp_path, "source", "owned")


def test_exclusive_export_collision_keeps_original(checkout, tmp_path, monkeypatch):
    owned_source(checkout, monkeypatch)
    (tmp_path / "creation-cli-receipt.json").write_text(json.dumps(receipt()))
    monkeypatch.setattr(helper, "uuid4", lambda: type("Nonce", (), {"hex": "fixed"})())
    first = helper.retain_creation_cli_receipt(tmp_path, "source", "owned")
    before = first.read_bytes()
    with pytest.raises(FileExistsError):
        helper.retain_creation_cli_receipt(tmp_path, "source", "owned")
    assert first.read_bytes() == before


def test_original_receipts_survive_part_collection_and_canonical_archive(
    checkout, tmp_path, monkeypatch
):
    import shutil

    from scripts.combine_test_parts import collect
    from scripts.qualification_runner import archive

    owned_source(checkout, monkeypatch)
    original = tmp_path / "creation-cli-receipt.json"
    original.write_text(json.dumps(receipt("cancel"), indent=3) + "\n")
    retained = helper.retain_creation_cli_receipt(tmp_path, "source", "cancelled")
    parts = tmp_path / "parts"
    part = parts / "owned-part-1"
    part.mkdir(parents=True)
    (part / "coverage-part.data").write_bytes(b"owned coverage fixture; collection only")
    shutil.copytree(checkout / "artifacts", part / "artifacts")
    combined = tmp_path / "combined"
    assert collect(parts, "owned-part-", 1, combined) == [part / "coverage-part.data"]
    combined_receipt = combined / retained.relative_to(checkout)
    assert combined_receipt.read_bytes() == original.read_bytes()
    archive(combined, combined / "artifacts/qualification/after")
    archived = (
        combined
        / "artifacts/qualification/after/resource-creation"
        / retained.relative_to(checkout / "artifacts/resource-creation")
    )
    assert archived.read_bytes() == original.read_bytes()


@pytest.mark.parametrize("producer", ["source", "installed"])
def test_real_callers_enroll_only_after_completed_helper(checkout, tmp_path, monkeypatch, producer):
    from tests.packaging import test_resource_creation_cli as installed
    from tests.terminal import test_resource_creation_cli as source

    owned_source(checkout, monkeypatch)
    caller = source if producer == "source" else installed

    def complete(command, directory, evidence, **kwargs):
        raw = receipt(kwargs.get("mode", "success"))
        (directory / "creation-cli-receipt.json").write_text(json.dumps(raw))
        return raw

    monkeypatch.setattr(caller, "terminal_resource_creation_cli", complete)
    if producer == "source":
        source.test_public_creation_cli_records_actual_uid_or_uncertain_committed_write(
            tmp_path, "cancel", False
        )
    else:
        installed.test_installed_creation_public_dryrun_review_and_created_uid(
            (Path("/owned/bin"), None), tmp_path, "console"
        )
    exported = list(
        (checkout / "artifacts/resource-creation" / producer).rglob("creation-cli-receipt.json")
    )
    assert (
        len(exported) == 1
        and exported[0].read_bytes() == (tmp_path / "creation-cli-receipt.json").read_bytes()
    )

    def fail(*args, **kwargs):
        raise RuntimeError("owned helper failed before receipt completion")

    monkeypatch.setattr(caller, "terminal_resource_creation_cli", fail)
    with pytest.raises(RuntimeError, match="before receipt"):
        if producer == "source":
            source.test_public_creation_cli_records_actual_uid_or_uncertain_committed_write(
                tmp_path, "success", False
            )
        else:
            installed.test_installed_creation_public_dryrun_review_and_created_uid(
                (Path("/owned/bin"), None), tmp_path, "module"
            )
    assert (
        list(
            (checkout / "artifacts/resource-creation" / producer).rglob("creation-cli-receipt.json")
        )
        == exported
    )
