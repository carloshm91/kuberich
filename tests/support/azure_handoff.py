"""Actual native Azure helper handoff with an owned loopback API and PTY."""

import json
import os
import signal
from contextlib import suppress
from pathlib import Path

from tests.support.azure import TOKEN, azure_entry
from tests.support.resources import collection, legacy_roots
from tests.terminal.pty_support import TerminalSession

APP = """
import asyncio, json, logging, os, signal, sys
from pathlib import Path
from aiohttp import web
from kubetrol.config.catalog import load_catalog
from kubetrol.config.schema import Settings
from kubetrol.domain.connections import ConnectionRequest
from kubetrol.ui.app import KubetrolApp

directory=Path.cwd()
scenario=sys.argv[1]
roots=json.loads((directory/'azure-api').read_text())
async def handler(request):
    if request.headers.get('Authorization') != 'Bearer synthetic.azure.access-token':
        return web.Response(status=401)
    if 'watch' in request.query:
        response=web.StreamResponse(); await response.prepare(request)
        while request.transport is not None and not request.transport.is_closing():
            await asyncio.sleep(.01)
        return response
    return web.json_response(roots.get(request.path, roots['collection']))

class LoginApp(KubetrolApp):
    async def _credential_login(self, credentials):
        self.login_owner=asyncio.current_task()
        return await super()._credential_login(credentials)

async def main():
    server=web.Application(); server.router.add_get('/{path:.*}',handler)
    runner=web.AppRunner(server,shutdown_timeout=.1); await runner.setup()
    site=web.TCPSite(runner,'127.0.0.1',0); await site.start()
    data=json.loads((directory/'azure-config').read_text())
    data['clusters'][0]['cluster']['server']='http://127.0.0.1:'+str(runner.addresses[0][1])
    (directory/'azure-config').write_text(json.dumps(data))
    request=ConnectionRequest(kubeconfig=str(directory/'azure-config'))
    app=LoginApp(Settings(read_only=True),logging.getLogger('azure-owned-terminal'),catalog=load_catalog(request,{}),connection=request)
    def cancel(signum,frame): asyncio.get_running_loop().call_soon(app.login_owner.cancel)
    signal.signal(signal.SIGUSR1,cancel)
    (directory/'azure-parent.pid').write_text(str(os.getpid()))
    try:
        await app.run_async()
        assert app.sessions.client is None and app.processes.active_count == 0
    finally:
        await runner.cleanup()
    raise SystemExit(app.return_code or 0)
asyncio.run(main())
"""


def azure_terminal_trial(python: str, parent: Path, scenario: str, *, name: str) -> None:
    directory = parent / name
    directory.mkdir()
    user = azure_entry(
        directory, login="devicecode", mode="Never" if scenario == "never" else "IfAvailable"
    )
    # Ensure the installed trial uses its isolated interpreter for the helper.
    executable = directory / "bin" / "kubelogin"
    source = executable.read_text().splitlines(keepends=True)
    executable.write_text("#!" + python + "\n" + "".join(source[1:]))
    control_path = directory / "azure-control"
    control = json.loads(control_path.read_text())
    control["prompt"] = True
    control_path.write_text(json.dumps(control))
    namespaces = {
        "metadata": {"resourceVersion": "owned-list"},
        "items": [{"metadata": {"name": "team", "uid": "owned-team"}}],
    }
    (directory / "azure-api").write_text(
        json.dumps({**legacy_roots(), "/api/v1/namespaces": namespaces, "collection": collection()})
    )
    (directory / "azure-config").write_text(
        json.dumps(
            {
                "current-context": "kubetrol-test-azure",
                "clusters": [{"name": "owned", "cluster": {"server": "http://127.0.0.1:1"}}],
                "users": [{"name": "owned", "user": user}],
                "contexts": [
                    {
                        "name": "kubetrol-test-azure",
                        "context": {"cluster": "owned", "user": "owned", "namespace": "team"},
                    }
                ],
            }
        )
    )
    script = directory / "azure-app.py"
    script.write_text(APP)
    with TerminalSession([python, str(script), scenario], directory) as terminal:
        terminal.wait_for_screen("Auth Error")
        for _ in range(2 if scenario == "success" else 1):
            marker = terminal.send(b":login\r")
            terminal.wait_for(b"configured Azure authentication", since=marker)
            terminal.wait_for(b"SYNTHETIC-ONLY", since=marker)
            if scenario != "never":
                terminal.wait_for(b"AZURE LOGIN READY", since=marker)
            pid = int((directory / "azure-pid").read_text())
            if scenario == "parent_shutdown":
                os.kill(int((directory / "azure-parent.pid").read_text()), signal.SIGTERM)
                terminal.finish(expected=143)
                terminal.save_evidence(name)
                with suppress(ProcessLookupError):
                    os.kill(pid, 0)
                    raise AssertionError("Authentication helper survived parent shutdown")
                assert TOKEN.encode() not in terminal.transcript
                return
            if scenario == "cancel":
                os.kill(int((directory / "azure-parent.pid").read_text()), signal.SIGUSR1)
                terminal.wait_for_screen("Auth Error", since=marker)
            elif scenario == "ctrl_c":
                terminal.send(b"\x03")
                terminal.wait_for_screen("Auth Error", since=marker)
            else:
                if scenario != "never":
                    terminal.send(b"complete\n")
                terminal.wait_for_screen("Live", since=marker)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("Completed authentication helper was not reaped")
            terminal.resize(80, 25)
            terminal.send(b"?")
            terminal.wait_for_screen("Keyboard help")
            marker = terminal.send(b"\x1b")
            terminal.wait_for_screen(
                "Auth Error" if scenario in {"cancel", "ctrl_c"} else "Live",
                since=marker,
                absent=("Keyboard help",),
            )
        terminal.send(b"\x11")
        terminal.finish()
        assert TOKEN.encode() not in terminal.transcript
        assert b'"kind": "ExecCredential"' not in terminal.transcript
        terminal.save_evidence(name)
