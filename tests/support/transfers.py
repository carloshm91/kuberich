"""An owned literal kubectl-shaped child backed by an isolated synthetic filesystem."""

import os
import sys
from pathlib import Path

CHILD = r"""
import io,json,os,shutil,stat,sys,tarfile,time
from pathlib import Path
home=Path(__file__).parent
(home/'pid').write_text(str(os.getpid()))
args=sys.argv[1:]
with (home/'arguments').open('a') as out:out.write(json.dumps(args)+'\n')
config=Path(args[0].split('=',1)[1])
assert stat.S_IMODE(config.stat().st_mode)==0o600
assert json.loads(config.read_text())['current-context']=='kuberich-test-one'
assert args[1:3]==['--context=kuberich-test-one','--namespace=team']
mode=os.environ.get('COPY_CASE','')
root=home/'remote';root.mkdir(exist_ok=True)
def remote(path):return root/path.lstrip('/')
if args[3]=='exec':
 command=args[7:]
 assert args[4:7]==['--container=app','api','--']
 if command[0]=='test':
  if mode=='missing-test':sys.exit(127)
  target=remote(command[2]);flag=command[1]
  if command[2]=='/':target=root
  value=target.is_symlink() if flag=='-L' else target.is_dir() if flag=='-d' else target.is_file() if flag=='-f' else target.exists()
  if not value:print('command terminated with exit code 1',file=sys.stderr)
  sys.exit(0 if value else 1)
 assert command[:3]==['tar','cf','-'] and command[3]=='-C' and command[5]=='--'
 if mode=='missing-tar':
  print('synthetic-private-stderr',file=sys.stderr);sys.exit(127)
 if mode=='cancel-download':
  os.write(1,b'partial');(home/'started').touch();time.sleep(60)
 if mode=='stderr-limit':
  os.write(2,b'x'*(1024*1024+1));sys.exit(1)
 if mode=='exit-failure':sys.exit(23)
 if mode=='malicious':
  with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as out:
   item=tarfile.TarInfo('../outside');item.size=3;out.addfile(item,io.BytesIO(b'bad'))
 elif mode=='wire-limit':
  os.write(1,b'x'*8192);sys.exit(0)
 else:
  value=remote(command[4])/command[6]
  with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as out:
   out.add(value,arcname=command[6],recursive=True)
elif args[3]=='cp':
 assert args[4:7]==['--retries=0','--no-preserve','--container=app']
 target=remote(args[8].split(':',1)[1])
 source=Path(args[7])
 if mode=='cancel-upload':
  target.write_bytes(b'partial');(home/'started').touch();time.sleep(60)
 if mode=='missing-tar':sys.exit(127)
 if source.is_dir():shutil.copytree(source,target)
 else:shutil.copyfile(source,target)
else:raise AssertionError(args)
"""


def executable(directory: Path, *, failure: str = "") -> dict[str, str]:
    directory.mkdir(exist_ok=True)
    binary = directory / "kubectl"
    binary.write_text(f"#!{sys.executable}\n" + CHILD)
    binary.chmod(0o700)
    remote = directory / "remote/tmp"
    remote.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "PATH": str(directory),
        "COPY_CASE": failure,
        "KUBECONFIG": "ambient-wrong",
    }
