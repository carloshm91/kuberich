"""Install actual local wheel/sdist bytes with uv tool and pip-backed pipx."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.distribution import PROJECT, ROOT, clean_environment, run
from tests.support.navigation import terminal_navigation
from tests.support.shell import terminal_shell

PROBE = """
import importlib.metadata as metadata
import importlib.resources as resources
import json
from pathlib import Path
import sys
import kuberich
package=resources.files('kuberich')
print(json.dumps({
    'version':metadata.version('kuberich'),
    'python':list(sys.version_info[:2]),
    'prefix':sys.prefix,
    'module':str(Path(kuberich.__file__).resolve()),
    'typed':package.joinpath('py.typed').is_file(),
    'css':package.joinpath('ui/kuberich.tcss').read_text(),
    'dependencies':{name:metadata.version(name) for name in ('textual','kubernetes-asyncio','pyte','aiohttp','platformdirs','pyyaml','regex')},
}))
"""


@pytest.mark.parametrize("artifact", ["wheel", "sdist"])
@pytest.mark.parametrize("installer", ["uv", "pipx"])
def test_real_isolated_tool_install_and_execution(artifacts, tmp_path, installer, artifact):
    uv = shutil.which("uv")
    assert uv is not None
    environment = clean_environment(tmp_path)
    package = artifacts[0 if artifact == "wheel" else 1]
    if installer == "uv":
        manager = [uv, "tool"]
        install = [*manager, "install", "--python", sys.executable, str(package)]
        venv = Path(environment["UV_TOOL_DIR"]) / "kuberich"
        binary = Path(environment["UV_TOOL_BIN_DIR"])
    else:
        manager = [sys.executable, "-m", "pipx"]
        install = [
            *manager,
            "install",
            "--backend",
            "pip",
            "--python",
            sys.executable,
            str(package),
        ]
        venv = Path(environment["PIPX_HOME"]) / "venvs/kuberich"
        binary = Path(environment["PIPX_BIN_DIR"])
    version_command = [uv, "--version"] if installer == "uv" else [*manager, "--version"]
    installer_version = run(version_command, tmp_path).stdout.strip()
    assert installer_version
    assert not venv.exists() and not binary.exists()
    records = []
    installed = False
    try:
        output = run(install, tmp_path, 240)
        records.append({"command": install, "exit": output.returncode})
        installed = True
        command = binary / "kuberich"
        python = venv / "bin/python"
        assert command.is_file() and python.is_file()
        environment["PATH"] = str(binary) + os.pathsep + os.environ["PATH"]
        assert shutil.which("kuberich", path=environment["PATH"]) == str(command)
        probe = json.loads(run([str(python), "-I", "-c", PROBE], tmp_path).stdout)
        assert probe["version"] == PROJECT["version"]
        assert probe["python"] == list(sys.version_info[:2])
        assert Path(probe["prefix"]) == venv
        assert Path(probe["module"]).is_relative_to(venv)
        assert not Path(probe["module"]).is_relative_to(ROOT)
        assert (
            probe["typed"] and probe["css"] == (ROOT / "src/kuberich/ui/kuberich.tcss").read_text()
        )
        assert all(probe["dependencies"].values())
        for argv in (
            ["kuberich", "--help"],
            ["kuberich", "--version"],
            [str(python), "-I", "-m", "kuberich", "--version"],
        ):
            result = run(argv, tmp_path, 15, environment=environment)
            assert result.stderr == ""
            assert (
                "usage: kuberich" in result.stdout
                if argv[-1] == "--help"
                else result.stdout == f"kuberich {PROJECT['version']}\n"
            )
            records.append({"command": argv, "exit": result.returncode})
        missing = run(["kuberich", "info"], tmp_path, check=False, environment=environment)
        assert missing.returncode == 3 and missing.stdout == ""
        (tmp_path / "preferences.yaml").write_text("schema_version: 1\n")
        info = json.loads(run(["kuberich", "info"], tmp_path, environment=environment).stdout)
        assert info["terminal_ui_available"] and not info["cluster_connected"]
        assert info["config_file"] == environment["KUBERICH_CONFIG"]
        result = run(["kuberich"], tmp_path, 15, check=False, environment=environment)
        assert result.returncode == 2 and result.stdout == ""
        assert "interactive terminal" in result.stderr
        terminal_navigation(
            [str(command)], tmp_path, evidence=f"installed-{installer}-{artifact}-navigation"
        )
        if artifact == "wheel":
            terminal_shell(
                [str(command)], tmp_path, "success", evidence=f"installed-{installer}-shell"
            )
        record = {
            "result": "passed",
            "installer": installer,
            "installer_version": installer_version,
            "pipx_backend": "pip" if installer == "pipx" else None,
            "artifact": package.name,
            "sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "installed_probe": probe,
            "commands": records,
            "actual_owned_api_navigation": True,
            "actual_embedded_shell": artifact == "wheel",
        }
    finally:
        result = run([*manager, "uninstall", "kuberich"], tmp_path, 60, check=False)
        if installed:
            assert result.returncode == 0, result.stderr
            assert not (binary / "kuberich").exists() and not venv.exists()
            records.append(
                {"command": [*manager, "uninstall", "kuberich"], "exit": result.returncode}
            )
    record["uninstalled"] = True
    output = ROOT / "artifacts/packaging"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{installer}-{artifact}.json").write_text(json.dumps(record, indent=2) + "\n")


def test_installer_timeout_reaps_its_owned_child_group(tmp_path):
    script = """
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
def stop(signum,frame):
    child.wait()
    raise SystemExit(143)
signal.signal(signal.SIGTERM,stop)
Path('child.pid').write_text(str(child.pid))
time.sleep(60)
"""
    with pytest.raises(subprocess.TimeoutExpired):
        run([sys.executable, "-c", script], tmp_path, timeout=1)
    pid = int((tmp_path / "child.pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
