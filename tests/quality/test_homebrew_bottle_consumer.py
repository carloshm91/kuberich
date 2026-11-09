"""Run the public-consumer YAML with owned shell functions, never host Homebrew."""

import subprocess

import pytest
import yaml

from tests.support.distribution import ROOT

OWNED_COMMANDS = r"""
# Functions take precedence over PATH, including the workflow's absolute
# Linuxbrew prepend. This shell cannot invoke a host brew or kuberich binary.
function [() {
  if [[ $# == 3 && $1 == -x && $2 == /home/linuxbrew/.linuxbrew/bin/brew && $3 == ']' ]]; then
    [[ $OWNED_LINUXBREW == 1 ]]
  else
    builtin [ "$@"
  fi
}
brew() {
  builtin printf 'brew %s\n' "$*" >> "$OWNED_TRACE"
  case "$*" in
    'install kuberich/tap/kuberich')
      if [[ $PATH == /home/linuxbrew/.linuxbrew/bin:* ]]; then
        builtin printf 'linuxbrew-prepended\n' >> "$OWNED_PATH_TRACE"
      else
        builtin printf 'owned-system-path\n' >> "$OWNED_PATH_TRACE"
      fi
      builtin printf 'Pouring kuberich-0.4.0.%s.bottle.tar.gz\n' "$OWNED_TAG"
      if [[ $OWNED_FAIL_INSTALL == 1 ]]; then return 23; fi
      ;;
    'trust --formula kuberich/tap/kuberich'|'test kuberich/tap/kuberich'|'uninstall kuberich/tap/kuberich') ;;
    *) return 97 ;;
  esac
}
kuberich() {
  builtin printf 'kuberich %s\n' "$*" >> "$OWNED_TRACE"
  [[ $* == --version ]] || return 98
  builtin printf 'kuberich 0.4.0\n'
}
"""

CONTEXTS = [
    ("ubuntu-24.04", "x86_64_linux", False),
    ("ubuntu-24.04", "x86_64_linux", True),
    ("macos-15", "arm64_sequoia", False),
    ("macos-15-intel", "sequoia", False),
]


def run_consumer(tmp_path, os_name, tag, linuxbrew_present, *, fail_install):
    job = yaml.safe_load((ROOT / ".github/workflows/bottles.yml").read_text())["jobs"]["verify"]
    step = next(
        step
        for step in job["steps"]
        if step.get("name") == "Install like a user and confirm the bottle is poured"
    )
    shell = step.get("shell", job.get("defaults", {}).get("run", {}).get("shell"))
    assert shell in (None, "bash"), "This control models GitHub's default or explicit Bash."
    command = ["/bin/bash", "--noprofile", "--norc", "-e"]
    if shell == "bash":
        command += ["-o", "pipefail"]
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    config = tmp_path / "empty-kubeconfig"
    config.write_bytes(b"")
    config.chmod(0o600)
    trace = tmp_path / "commands.txt"
    path_trace = tmp_path / "path-selection.txt"
    environment = {
        "HOME": str(home),
        "KUBECONFIG": str(config),
        "PATH": "/usr/bin:/bin",
        "BOTTLE_VERSION": "0.4.0",
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "OWNED_TRACE": str(trace),
        "OWNED_PATH_TRACE": str(path_trace),
        "OWNED_TAG": tag,
        "OWNED_LINUXBREW": "1" if linuxbrew_present else "0",
        "OWNED_FAIL_INSTALL": "1" if fail_install else "0",
    }
    # Only the runner-label expression is rendered; the actual run body,
    # public Pouring check, version, trust, test and uninstall stay unchanged.
    script = OWNED_COMMANDS + step["run"].replace("${{ matrix.os }}", os_name)
    (tmp_path / "executed.sh").write_text(script)
    result = subprocess.run(
        [*command, "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    (tmp_path / "stdout.txt").write_text(result.stdout)
    (tmp_path / "stderr.txt").write_text(result.stderr)
    (tmp_path / "returncode.txt").write_text(str(result.returncode) + "\n")
    assert config.read_bytes() == b""
    assert path_trace.read_text().splitlines() == [
        "linuxbrew-prepended" if linuxbrew_present else "owned-system-path"
    ]
    assert f"Pouring kuberich-0.4.0.{tag}.bottle.tar.gz" in (tmp_path / "install.log").read_text()
    return result, trace.read_text().splitlines()


@pytest.mark.parametrize(("os_name", "tag", "linuxbrew_present"), CONTEXTS)
def test_failed_public_pour_cannot_pass_via_tee_and_later_successes(
    tmp_path, os_name, tag, linuxbrew_present
):
    result, calls = run_consumer(tmp_path, os_name, tag, linuxbrew_present, fail_install=True)
    assert result.returncode != 0, f"Failed install was hidden; downstream calls: {calls}"
    assert calls == ["brew install kuberich/tap/kuberich"]


@pytest.mark.parametrize(("os_name", "tag", "linuxbrew_present"), CONTEXTS)
def test_successful_public_pour_keeps_version_formula_test_and_uninstall(
    tmp_path, os_name, tag, linuxbrew_present
):
    result, calls = run_consumer(tmp_path, os_name, tag, linuxbrew_present, fail_install=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == [
        "brew install kuberich/tap/kuberich",
        "kuberich --version",
        "brew trust --formula kuberich/tap/kuberich",
        "brew test kuberich/tap/kuberich",
        "brew uninstall kuberich/tap/kuberich",
    ]
