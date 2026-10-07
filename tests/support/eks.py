"""Local AWS-shaped credential helpers; never contact AWS or read real credentials."""

import json
import sys
from datetime import UTC, datetime, timedelta

VERSION = "client.authentication.k8s.io/v1"
TOKEN = "k8s-aws-v1.synthetic-test-only"
ROLE = "arn:aws:iam::000000000000:role/synthetic;$(never-executed)"


def aws_entry(directory, *, version=VERSION, command=None, mode="Never"):
    executable = directory / "bin" / "aws"
    executable.parent.mkdir(exist_ok=True)
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\nfrom pathlib import Path\n"
        "info=json.loads(os.environ['KUBERNETES_EXEC_INFO'])\n"
        "assert info['spec']['interactive'] is False\nassert sys.stdin.read() == ''\n"
        "record={'args':sys.argv[1:], 'profile':os.environ.get('AWS_PROFILE'), "
        "'pager':os.environ.get('AWS_PAGER'), "
        "'config':os.environ.get('AWS_CONFIG_FILE'), 'home':os.environ.get('HOME'), "
        "'version':info['apiVersion']}\n"
        "with Path('calls').open('a') as stream: stream.write(json.dumps(record)+'\\n')\n"
        "control=json.loads(Path('control').read_text())\n"
        "if control.get('error'):\n print(control['error'], file=sys.stderr)\n sys.exit(255)\n"
        "if control.get('sleep'):\n import time\n Path('pid').write_text(str(os.getpid()))\n"
        " time.sleep(30)\n"
        "if control.get('invalid'):\n print('private-invalid-response')\n sys.exit(0)\n"
        "print(json.dumps({'kind':'ExecCredential', 'apiVersion':info['apiVersion'], "
        "'status':{'token':control['token'], 'expirationTimestamp':control['expires']}}))\n"
    )
    executable.chmod(0o700)
    control(directory)
    return {
        "exec": {
            "apiVersion": version,
            "interactiveMode": mode,
            "command": command or str(executable),
            "args": [
                "--region",
                "us-east-1",
                "eks",
                "get-token",
                "--cluster-name",
                "synthetic",
                "--output",
                "json",
                "--role-arn",
                ROLE,
            ],
            "env": [{"name": "AWS_PROFILE", "value": "synthetic-declared"}],
        }
    }


def control(directory, **changes):
    (directory / "control").write_text(
        json.dumps(
            {
                "token": TOKEN,
                "expires": (datetime.now(UTC) + timedelta(minutes=14)).isoformat(),
                **changes,
            }
        )
    )


def calls(directory):
    return [json.loads(line) for line in (directory / "calls").read_text().splitlines()]
