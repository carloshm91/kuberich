"""Real offline creation import/editor, cleanup barriers and terminal restoration."""

import os
import sys

import pytest

from tests.support.resource_creation_terminal import terminal_resource_creation

CLEANUP_LAUNCHER = """import asyncio,json,os,pathlib,sys
from kuberich.adapters.editing import ManifestFile
from kuberich.ui.resource_creation import ResourceCreationScreen
from kuberich.cli import main
receipt,release=map(pathlib.Path,sys.argv[1:3])
owner={}
original_mount=ResourceCreationScreen.on_mount
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
ResourceCreationScreen.on_mount=mount
ManifestFile.close=close
raise SystemExit(main(sys.argv[3:]))
"""


@pytest.mark.parametrize(
    "scenario", ["success", "noop", "failure", "invalid", "ctrl_c", "sigterm", "repeat"]
)
def test_actual_creation_editor_and_terminal_restore(tmp_path, scenario):
    terminal_resource_creation(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "resource-creation-" + scenario,
        scenario=scenario,
        size=(80, 24) if scenario == "success" else (120, 36),
    )


def test_escape_waits_for_creation_private_draft_cleanup(tmp_path):
    launcher = tmp_path / "owned-creation-close-launcher.py"
    launcher.write_text(CLEANUP_LAUNCHER)
    receipt = tmp_path / "owned-creation-close-receipt"
    release = tmp_path / "zz-owned-creation-close-release"
    os.mkfifo(release, 0o600)
    terminal_resource_creation(
        [sys.executable, str(launcher), str(receipt), str(release)],
        tmp_path,
        "resource-creation-held-cleanup",
        scenario="noop",
        cleanup_gate=(receipt, release),
    )


@pytest.mark.parametrize("scenario", ["success", "ctrl_c", "repeat"])
def test_creation_shell_editor_needs_no_external_interpreter(tmp_path, scenario):
    receipt = terminal_resource_creation(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        "resource-creation-shell-" + scenario,
        scenario=scenario,
        shell_editor=True,
        size=(80, 24),
    )
    assert receipt["private_files_absent"] and receipt["source_unchanged"]
