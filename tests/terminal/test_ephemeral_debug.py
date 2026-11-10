"""Actual source CLI debugging reviews, append outcomes and terminal restoration."""

import sys

import pytest

from tests.support.ephemeral_debug_terminal import terminal_ephemeral_debug

DELAYED_ROW_ENTRY = r"""
import json,os,sys
from pathlib import Path
from textual.widgets import Button,DataTable
from kuberich.cli import main
post=DataTable.post_message
def delayed(self,message):
 if isinstance(message,DataTable.RowHighlighted) and message.row_key.value=='debug-real-cli':
  button=self.screen.query_one('#debug-attach',Button)
  button.proof_row_pending=True;button.disabled=True
  def deliver():
   button.proof_row_pending=False
   with Path(os.environ['DEBUG_ROW_AUDIT']).open('a') as output:output.write('delivered\n')
   post(self,message)
  self.set_timer(.5,deliver)
  return True
 return post(self,message)
def pending(self,value):return value or getattr(self,'proof_row_pending',False)
Button.validate_disabled=pending
DataTable.post_message=delayed
sys.exit(main())
"""

ACTIVE_ATTACH_ENTRY = r"""
import sys
from textual.widgets import Button
from kuberich.cli import main
initialize=Button.__init__
def active(self,*args,**kwargs):
 initialize(self,*args,**kwargs)
 if self.id=='debug-attach':self.active_effect_duration=1
Button.__init__=active
sys.exit(main())
"""


@pytest.mark.parametrize(
    "scenario",
    [
        "completion",
        "interrupt",
        "detach",
        "close",
        "quit",
        "terminate",
        "disconnect",
        "missing",
        "startup",
        "uncertain",
        "context",
        "repeat",
        "cancel",
        "denied",
        "read-only",
    ],
)
def test_ephemeral_debug_cli_restores_and_keeps_remote_outcome_independent(tmp_path, scenario):
    terminal_ephemeral_debug(
        [sys.executable, "-m", "kuberich"],
        tmp_path,
        scenario,
        evidence="ephemeral-debug-source-" + scenario,
    )


@pytest.mark.parametrize("entry", ["module", "delayed-row"])
def test_owned_kind_cli_driver_selects_its_new_row_and_reaps_the_exec_wrapper(
    tmp_path, monkeypatch, entry
):
    from tests.support.ephemeral_debug_terminal import debug_api, terminal_real_ephemeral_debug
    from tests.support.terminal_api import config

    with debug_api() as api:
        api.pod["spec"]["ephemeralContainers"] = [{"name": "debug-old", "image": "synthetic"}]
        api.pod["status"]["ephemeralContainerStatuses"] = [
            {"name": "debug-old", "state": {"terminated": {"exitCode": 0}}}
        ]
        endpoint = f"http://127.0.0.1:{api.server_port}"
        kubeconfig = config(
            tmp_path / "owned-kubeconfig", endpoint, {"token": "synthetic-driver-token"}
        )
        binary = tmp_path / "owned-kubectl"
        binary.write_text(
            f"#!{sys.executable}\n"
            "import json,os,sys,tty,urllib.request\n"
            "tty.setraw(0)\n"
            "name=next(a.split('=',1)[1] for a in sys.argv if a.startswith('--container='))\n"
            "assert name=='debug-real-cli'\n"
            "data=b''\n"
            "while True:\n"
            " data+=os.read(0,4096)\n"
            " if b'printf' in data:os.write(1,b'OWNED-REAL-CLI\\r\\n');data=b''\n"
            " if b'exit 7' in data:\n"
            "  request=urllib.request.Request(os.environ['DEBUG_CONTROL_URL']+'/owned-helper/'+name,data=json.dumps({'exitCode':7}).encode(),method='POST')\n"
            "  urllib.request.urlopen(request,timeout=2).close();sys.exit(0)\n"
        )
        binary.chmod(0o700)
        monkeypatch.setenv("DEBUG_CONTROL_URL", endpoint)
        monkeypatch.setenv("DEBUG_ROW_AUDIT", str(tmp_path / "row-delivery.txt"))
        result = terminal_real_ephemeral_debug(
            [sys.executable, "-m", "kuberich"]
            if entry == "module"
            else [sys.executable, "-c", DELAYED_ROW_ENTRY],
            tmp_path / "driver",
            kubeconfig,
            "kuberich-test-pty",
            "team",
            binary,
            evidence="ephemeral-debug-real-driver-contract",
        )
        assert result["terminal_restored"] and result["real_kubectl_process_reaped"]
        assert [entry["name"] for entry in api.pod["spec"]["ephemeralContainers"]] == [
            "debug-old",
            "debug-real-cli",
        ]
        if entry == "delayed-row":
            assert (tmp_path / "row-delivery.txt").read_text() == "delivered\n"


def test_repeat_attach_waits_for_the_existing_button_active_effect(tmp_path):
    terminal_ephemeral_debug(
        [sys.executable, "-c", ACTIVE_ATTACH_ENTRY],
        tmp_path,
        "repeat",
        evidence="ephemeral-debug-active-effect",
    )
