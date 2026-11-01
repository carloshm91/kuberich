"""Harmless kubectl stand-in shared by original-manifest contract and PTY tests."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples/plugins"


PROGRAM = """import json,os,sys,time
from pathlib import Path
args=sys.argv[1:]
assert args[0]=='--kubeconfig='+os.environ['KUBECONFIG']
assert args[1]=='--context='+os.environ['KUBERICH_CONTEXT']
assert args[2]=='--namespace='+os.environ['KUBERICH_NAMESPACE']
private=Path(os.environ['KUBECONFIG'])
assert private.is_file() and private.stat().st_mode & 0o777 == 0o600
kind='shell' if 'exec' in args else 'events' if 'events' in args else 'inspect'
receipt=Path(os.environ['EXAMPLE_RECEIPT']+'-'+kind)
pending=receipt.with_name(receipt.name+'.'+str(os.getpid())+'.tmp')
pending.write_text(json.dumps({'argv':args,'private':str(private)}))
pending.replace(receipt)
if kind=='shell':
    assert '--stdin' in args and '--tty' in args and args[-2:]==['--','sh']
    print('EXAMPLE_SHELL_READY',flush=True)
    print('EXAMPLE_INPUT '+sys.stdin.readline().strip(),flush=True)
elif kind=='events':
    print('EXAMPLE_EVENTS',flush=True)
    while os.environ.get('EXAMPLE_HOLD'): time.sleep(0.05)
else:
    assert args[-4:]==['get','pod',args[-2],'--output=json']
    print('EXAMPLE_INSPECTION',flush=True)
"""


def executable(directory):
    tool = directory / "kubectl"
    tool.write_text(f"#!{sys.executable}\n" + PROGRAM)
    tool.chmod(0o700)
    return tool
