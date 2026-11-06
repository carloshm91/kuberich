"""Fresh source/installed offline browser geometry with owned files and terminal."""

import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from uuid import uuid4

from kuberich.domain.exports import DocumentSource, ExportCapture, ExportScope, prepare_capture
from tests.support.local_exports import _AUDIT
from tests.support.terminal_api import config
from tests.terminal.pty_support import ROOT, TerminalSession


def seed_browser_artifact(directory, name="owned-export.txt"):
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    prepared = prepare_capture(
        ExportCapture(
            scope=ExportScope(
                export_at=datetime.now(UTC),
                source_at=None,
                context="owned-saved-context",
                header_namespace=None,
                collection_namespace=None,
                namespace_mode="local",
            ),
            source=DocumentSource(page="evidence", text="owned-export-body\n"),
        ),
        "screen",
        artifact_id=uuid4(),
    )
    path = directory / name
    path.write_bytes(prepared.payload)
    path.chmod(0o600)
    return path


def source_binding():
    return {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in (
            "src/kuberich/ui/app.py",
            "src/kuberich/ui/artifact_browser.py",
            "src/kuberich/ui/presentation.py",
            "src/kuberich/ui/table_cache.py",
            "src/kuberich/ui/logs.py",
            "src/kuberich/ui/aggregate_logs.py",
            "src/kuberich/domain/exports.py",
            "src/kuberich/services/exports.py",
            "src/kuberich/adapters/artifact_files.py",
            "tests/support/export_browser_geometry.py",
            "tests/support/local_exports.py",
            "tests/terminal/test_export_browser_geometry.py",
            "pyproject.toml",
            "uv.lock",
        )
    }


def terminal_export_browser_geometry(
    command, directory, *, evidence, resize=False, wheel_sha256=None
):
    """Retain the 15s visible-name deadline; compare native and resized geometry."""
    directory.mkdir(parents=True, exist_ok=True)
    directory = directory.resolve(strict=True)
    output = ROOT / "artifacts/terminal"
    output.mkdir(parents=True, exist_ok=True)
    existing = tuple(
        path
        for suffix in (".ansi", ".json", "-geometry.json")
        if (path := output / (evidence + suffix)).exists()
    )
    if existing:
        archive = output / "preserved" / (evidence + "-" + str(time.time_ns()))
        archive.mkdir(parents=True)
        for path in existing:
            shutil.copy2(path, archive / path.name)
    exports = directory / "exports"
    artifact = seed_browser_artifact(exports)
    preferences = directory / "preferences.yaml"
    preferences.write_text("schema_version: 1\nappearance:\n  check_updates: true\n")
    kubeconfig = config(
        directory / "owned-kubeconfig", "http://127.0.0.1:1", {"token": "synthetic-offline-width"}
    )
    kubeconfig.chmod(0o600)
    original_config = kubeconfig.read_bytes()
    hooks = directory / "hooks"
    hooks.mkdir(mode=0o700)
    (hooks / "sitecustomize.py").write_text(_AUDIT)
    audit = directory / "network.jsonl"
    source = source_binding()
    arguments = [
        *command,
        "--config",
        str(preferences),
        "--kubeconfig",
        str(kubeconfig),
        "--context",
        "kuberich-test-pty",
        "--readonly",
        "--command",
        "exports",
        "--screen-dump-dir",
        str(exports),
    ]
    with TerminalSession(
        arguments,
        directory,
        size=(40, 12) if resize else (100, 30),
        environment={"PYTHONPATH": str(hooks), "KUBERICH_EXPORT_NETWORK_AUDIT": str(audit)},
    ) as terminal:
        terminal.wait_for_screen("Saved artifacts")
        terminal.wait_for_screen("1 shown")
        initial_name = artifact.name in "\n".join(terminal.screen.display)
        terminal.wait_for_screen(artifact.name)
        if resize:
            terminal.resize(100, 30)
            terminal.wait_for_screen(artifact.name)
        # Rebuild the actual table through literal filter keys and an observable
        # filesystem refresh, preserving the full name on the normal viewport.
        marker = terminal.send(b"\x1b[Zno-match")
        terminal.wait_for_screen("0 shown", since=marker)
        marker = terminal.send(b"\x15")
        terminal.wait_for_screen("1 shown", since=marker)
        terminal.wait_for_screen(artifact.name)
        refreshed = seed_browser_artifact(exports, "refresh-export.txt")
        marker = terminal.send(b"\x12")
        terminal.wait_for_screen("2 shown", since=marker)
        terminal.wait_for_screen(refreshed.name)
        terminal.wait_for_screen(artifact.name)
        terminal.send(b"\x11")
        terminal.finish()
        terminal.save_evidence(evidence)
        (output / (evidence + ".ansi")).chmod(0o600)
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert any(item["event"] == "loaded" for item in events)
    assert not any(item["event"].startswith("socket.") for item in events)
    assert kubeconfig.read_bytes() == original_config
    assert source_binding() == source, "Browser geometry source changed during the trial."
    receipt = {
        "initial_name_present": initial_name,
        "resize_to_100x30": resize,
        "full_name_after_filter_clear_and_refresh": True,
        "network_events": 0,
        "kubeconfig_unchanged": True,
        "wheel_sha256": wheel_sha256,
        "entry_command": command,
        "source": source,
        "original_geometry_failure": "Retained and unreproduced; these passes do not identify its cause.",
    }
    (output / (evidence + "-geometry.json")).write_text(json.dumps(receipt, indent=2) + "\n")
