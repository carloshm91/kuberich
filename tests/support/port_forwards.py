"""Owned fake kubectl with actual TCP sockets for process/lifetime contracts."""

import os
import sys
from pathlib import Path

from kubetrol.domain.targets import ResourceTarget, SessionIdentity
from kubetrol.services.access import AccessPolicy
from kubetrol.services.port_forwards import ForwardService

PROGRAM = r"""
import json, os, select, socket, sys, time
from pathlib import Path
arguments=sys.argv[1:]
path=Path(arguments[0].split('=',1)[1])
assert path.stat().st_mode & 0o777 == 0o600
config=json.loads(path.read_text())
assert config['current-context']=='kubetrol-test-one'
assert config['clusters'][0]['cluster']['server'].startswith('http://127.0.0.1:')
assert os.environ['KUBECONFIG']==str(path)
Path('forward-child.pid').write_text(str(os.getpid()))
Path('forward-argv.json').write_text(json.dumps(arguments))
mode=os.environ.get('OWNED_FORWARD_MODE','normal')
if mode=='fail':
    print('Forbidden opaque-private-body token=private-synthetic',file=sys.stderr,flush=True)
    raise SystemExit(1)
listeners=[]
address=next(value.split('=',1)[1] for value in arguments if value.startswith('--address='))
for mapping in arguments[arguments.index('port-forward')+4:]:
    local,remote=map(int,mapping.split(':'))
    listener=socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET)
    listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    listener.bind((address,local))
    listener.listen()
    listeners.append(listener)
    observed=remote+1 if 'service/' in ' '.join(arguments) else remote
    host='0.0.0.0' if mode=='wrong' else '['+address+']' if ':' in address else address
    line=f'Forwarding from {host}:{listener.getsockname()[1]} -> {observed}\n'
    if mode!='silent':
        if mode=='partial':
            print(line[:17],end='',flush=True);time.sleep(.06);print(line[17:],end='',flush=True)
        else: print(line,end='',flush=True)
if mode=='flood': os.write(1,b'x'*(2*1024*1024))
while True:
    readable,_,_=select.select(listeners,[],[],.1)
    for listener in readable:
        peer,_=listener.accept()
        with peer:
            peer.settimeout(1)
            data=peer.recv(64)
            peer.sendall(b'owned-response:'+data)
        print('Handling connection for '+str(listener.getsockname()[1]),flush=True)
"""


def executable(directory: Path, mode: str = "normal") -> dict[str, str]:
    path = directory / "kubectl"
    path.write_text(f"#!{sys.executable}\n" + PROGRAM)
    path.chmod(0o700)
    return {**os.environ, "PATH": str(directory), "OWNED_FORWARD_MODE": mode}


def source(
    reader, directory, *, mode="normal", resource="pods", current=lambda: True, readonly=False
):
    selected = ResourceTarget(
        SessionIdentity(reader.session.context.name, 1), "", resource, "team", "web", "web-uid"
    )
    return ForwardService(
        reader.session,
        selected,
        AccessPolicy(readonly),
        current,
        environment=executable(directory, mode),
        directory=directory,
    )


def manifest(resource="pods", *, uid="web-uid"):
    return {
        "apiVersion": "v1",
        "kind": "Pod" if resource == "pods" else "Service",
        "metadata": {"name": "web", "namespace": "team", "uid": uid},
        "status": {"phase": "Running"},
    }
