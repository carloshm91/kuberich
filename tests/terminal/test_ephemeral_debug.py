"""Actual source CLI debugging reviews, append outcomes and terminal restoration."""

import sys

import pytest

from tests.support.ephemeral_debug_terminal import terminal_ephemeral_debug


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


def test_owned_kind_cli_driver_selects_its_new_row_and_reaps_the_exec_wrapper(
    tmp_path, monkeypatch
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
        result = terminal_real_ephemeral_debug(
            [sys.executable, "-m", "kuberich"],
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
