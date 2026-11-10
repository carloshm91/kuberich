"""Real offline entry, editor handoff, local save and native terminal restoration."""

import os
import sys

import pytest

from tests.support.local_manifest_terminal import terminal_local_manifests

CLEANUP_LAUNCHER = """import asyncio,json,os,pathlib,sys
from kuberich.adapters.editing import ManifestFile
from kuberich.ui.manifest_editor import ManifestEditorScreen
from kuberich.cli import main
receipt,release=map(pathlib.Path,sys.argv[1:3])
owner={}
original_mount=ManifestEditorScreen.on_mount
original_close=ManifestFile.close
def mount(screen):
 owner['app']=screen.app
 owner['loop']=asyncio.get_running_loop()
 original_mount(screen)
def close(draft):
 descriptor=os.open(release,os.O_RDWR)
 try:
  def observe():
   stage=receipt.with_suffix('.stage')
   stage.write_text(json.dumps({'foreground':type(owner['app'].screen).__name__}))
   stage.replace(receipt)
  owner['loop'].call_soon_threadsafe(observe)
  assert os.read(descriptor,1)==b'1'
 finally:
  os.close(descriptor)
 original_close(draft)
ManifestEditorScreen.on_mount=mount
ManifestFile.close=close
raise SystemExit(main(sys.argv[3:]))
"""


@pytest.mark.parametrize(
    "scenario", ["success", "noop", "failure", "invalid", "ctrl_c", "sigterm", "repeat"]
)
def test_actual_local_manifest_editor_and_terminal_restore(tmp_path, scenario):
    terminal_local_manifests(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "local-manifest-" + scenario,
        scenario=scenario,
        size=(80, 24) if scenario == "success" else (120, 36),
    )


def test_actual_escape_waits_for_owned_private_draft_cleanup(tmp_path):
    launcher = tmp_path / "owned-close-launcher.py"
    launcher.write_text(CLEANUP_LAUNCHER)
    receipt = tmp_path / "owned-close-receipt"
    release = tmp_path / "zz-owned-close-release"
    os.mkfifo(release, 0o600)
    terminal_local_manifests(
        [sys.executable, str(launcher), str(receipt), str(release)],
        tmp_path,
        "local-manifest-held-cleanup",
        scenario="noop",
        cleanup_gate=(receipt, release),
    )
