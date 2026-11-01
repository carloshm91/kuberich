"""The unmodified SDK loads only for an explicitly owned session, in a worker."""

import json
import subprocess
import sys

from tests.support.distribution import clean_environment

PROBE = r"""
import asyncio
import importlib.abc
import json
import socket
import sys
import threading
from pathlib import Path

observed = []
http_observed = []
class SdkImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'kubernetes_asyncio':
            observed.append(threading.current_thread() is threading.main_thread())
        if fullname == 'aiohttp':
            http_observed.append(threading.current_thread() is threading.main_thread())

def refuse_network(event, arguments):
    if event == 'socket.connect':
        raise AssertionError('Session preparation must not perform network I/O')

sys.addaudithook(refuse_network)
sys.meta_path.insert(0, SdkImports())
from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.catalog import ContextConfig, Entry
assert not observed and not http_observed
root = Path.cwd()
context = ContextConfig('owned-startup', 'default', Entry({'server': 'http://127.0.0.1:9'}, root), Entry({}, root))
session = KubernetesSession(context, 1.0)
directory = Path(session.directory.name)
assert not observed and not http_observed
async def prepare():
    try:
        await session.open()
        assert session.api is not None
    finally:
        await session.close()

asyncio.run(prepare())
assert observed == [False], observed
assert http_observed == [False], http_observed
assert not directory.exists()
assert any(name.startswith('kubernetes_asyncio.client.models.') for name in sys.modules)
print(json.dumps({'sdk_imported_on_main_thread': observed, 'closed': True, 'network_requests': 0}))
"""


def test_sdk_is_deferred_through_construction_and_prepared_off_the_event_loop(tmp_path):
    environment = clean_environment(tmp_path)
    environment["TMPDIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "sdk_imported_on_main_thread": [False],
        "closed": True,
        "network_requests": 0,
    }


def test_tui_import_keeps_connection_http_and_sdk_graphs_deferred(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; import kuberich.ui.app; "
            "print(json.dumps(sorted(name for name in sys.modules "
            "if name.split('.')[0] in {'aiohttp','aiohttp_socks','kubernetes_asyncio','regex'} "
            "or name in {'kuberich.ui.aggregate_logs','kuberich.ui.containers',"
            "'kuberich.ui.terminal','kuberich.ui.logs','kuberich.ui.inspection',"
            "'kuberich.ui.editing','kuberich.ui.transfers','kuberich.ui.configuration_data',"
            "'kuberich.ui.context_admin','kuberich.ui.workloads','kuberich.ui.mutations',"
            "'kuberich.domain.editing','kuberich.services.editing','kuberich.services.inspection',"
            "'kuberich.services.transfers','kuberich.services.aggregate_logs','kuberich.services.logs',"
            "'kuberich.services.attach','kuberich.services.shell','kuberich.services.workloads',"
            "'kuberich.ui.read_only_text','textual.widgets._text_area','textual.document',"
            "'kuberich.ui.plugin_screens','kuberich.ui.port_forwards'})))",
        ],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == "" and json.loads(result.stdout) == []


def test_scroll_navigation_does_not_import_editor_and_legacy_text_export_is_canonical(tmp_path):
    script = r"""
import importlib.abc,json,sys
attempts=[]
allow_editor=False
class Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'textual.widgets._text_area' or fullname.startswith('textual.document'):
            attempts.append(fullname)
            if not allow_editor:
                raise AssertionError('Scrolling attempted an unused editor import')
sys.meta_path.insert(0, Imports())
from kuberich.ui import text_navigation
from kuberich.ui.text_navigation import ReadOnlyScroll
assert ReadOnlyScroll.BINDING_PROFILE == 'text'
assert not attempts
allow_editor=True
from kuberich.ui.read_only_text import ReadOnlyText
assert text_navigation.ReadOnlyText is ReadOnlyText
assert attempts
try:
    text_navigation.unknown_owned_export
except AttributeError:
    pass
else:
    raise AssertionError('Unknown navigation export was accepted')
print(json.dumps({'deferred':True,'canonical':True,'unknown_rejected':True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "deferred": True,
        "canonical": True,
        "unknown_rejected": True,
    }


def test_plugin_owner_preserves_public_screen_aliases_without_eager_modal_imports(tmp_path):
    script = r"""
import importlib.abc,json,sys
attempts=[]
allow_screens=False
class Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'kuberich.ui.plugin_screens':
            attempts.append(fullname)
            if not allow_screens:
                raise AssertionError('Plugin ownership attempted an unused modal import')
sys.meta_path.insert(0, Imports())
from kuberich.ui import plugins
assert plugins.PluginController.__module__ == 'kuberich.ui.plugins'
assert callable(plugins.load_plugins)
assert not attempts
allow_screens=True
from kuberich.ui.plugin_screens import PluginCatalogue,PluginJobs,PluginScreen
assert plugins.PluginCatalogue is PluginCatalogue
assert plugins.PluginJobs is PluginJobs
assert plugins.PluginScreen is PluginScreen
try:
    plugins.unknown_owned_export
except AttributeError:
    pass
else:
    raise AssertionError('Unknown plugin export was accepted')
print(json.dumps({'deferred':True,'canonical':True,'loader_port':True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "deferred": True,
        "canonical": True,
        "loader_port": True,
    }


def test_regex_engine_loads_only_for_actual_regex_and_on_the_owned_filter_worker(tmp_path):
    script = r"""
import asyncio,importlib.abc,json,sys,threading
observed=[]
class Imports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'regex':
            observed.append(threading.current_thread() is threading.main_thread())
sys.meta_path.insert(0, Imports())
from kuberich.services.filtering import filter_rows,apply_filter
for query in ('', 'literal', 'fuzzy:api'):
    assert filter_rows((),query).rows == ()
assert not observed and 'regex' not in sys.modules
async def exercise():
    assert (await apply_filter((), 're:api')).rows == ()
    assert 'Invalid regex' in (await apply_filter((), 're:[')).problem
asyncio.run(exercise())
assert observed == [False], observed
print(json.dumps({'regex_imported_on_main_thread': observed}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=clean_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"regex_imported_on_main_thread": [False]}
