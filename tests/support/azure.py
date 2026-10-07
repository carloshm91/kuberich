"""Owned Azure-shaped helper; no provider CLI, cache or tenant access."""

import json
import sys
from datetime import UTC, datetime, timedelta

VERSION = "client.authentication.k8s.io/v1"
TOKEN = "synthetic.azure.access-token"


def azure_entry(directory, *, login="azurecli", version=VERSION, command=None, mode="Never"):
    executable = directory / "bin" / "kubelogin"
    executable.parent.mkdir(exist_ok=True)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys, time\nfrom pathlib import Path\n"
        "info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\n"
        "record={'args':sys.argv[1:], 'interactive':info['spec']['interactive'], "
        "'stdin_tty':os.isatty(0), 'stderr_tty':os.isatty(2), 'version':info['apiVersion'], "
        "'environment':{name:os.environ.get(name) for name in "
        "['HOME','AZURE_CONFIG_DIR','AZURE_TENANT_ID','AZURE_CLIENT_ID','AAD_LOGIN_METHOD', "
        "'AZURE_CLIENT_SECRET','AZURE_CLIENT_CERTIFICATE_PATH','AZURE_CLIENT_CERTIFICATE_PASSWORD',"
        "'AZURE_FEDERATED_TOKEN_FILE','AZURE_AUTHORITY_HOST','KUBECACHEDIR']}}\n"
        "with Path('azure-calls').open('a') as stream: stream.write(json.dumps(record)+'\\n')\n"
        "control=json.loads(Path('azure-control').read_text())\n"
        "Path('azure-pid').write_text(str(os.getpid()))\n"
        "if control.get('error'):\n print(control['error'], file=sys.stderr)\n sys.exit(1)\n"
        "if control.get('sleep'): time.sleep(30)\n"
        "if control.get('prompt'):\n"
        " print('To sign in, use a web browser and enter the code SYNTHETIC-ONLY', file=sys.stderr, flush=True)\n"
        " if not os.isatty(2): time.sleep(30)\n"
        " if os.isatty(0):\n"
        "  print('AZURE LOGIN READY',file=sys.stderr,flush=True)\n"
        "  assert sys.stdin.readline().strip() == 'complete'\n"
        "if control.get('invalid'):\n print('private-invalid-credential')\n sys.exit(0)\n"
        "print(json.dumps({'kind':'ExecCredential','apiVersion':info['apiVersion'],"
        "'status':{'token':control['token'],'expirationTimestamp':control['expires']}}))\n"
    )
    executable.chmod(0o700)
    azure_control(directory)
    return {
        "exec": {
            "apiVersion": version,
            "interactiveMode": mode,
            "command": command or str(executable),
            "args": ["get-token", "--server-id", "synthetic-server", "--login", login],
            "env": [{"name": "AZURE_TENANT_ID", "value": "declared-synthetic-tenant"}],
        }
    }


def azure_control(directory, **changes):
    (directory / "azure-control").write_text(
        json.dumps(
            {
                "token": TOKEN,
                "expires": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                **changes,
            }
        )
    )


def azure_calls(directory):
    return [json.loads(line) for line in (directory / "azure-calls").read_text().splitlines()]
