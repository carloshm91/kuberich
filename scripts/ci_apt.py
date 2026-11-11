"""Bound Ubuntu CI package setup while retaining APT signature and TLS checks.

Runner mirror stalls and the effective Acquire keys are documented upstream:
https://github.com/actions/runner-images/issues/14594
https://github.com/actions/runner-images/pull/14643
"""

import argparse
import os
import platform
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from scripts.ci_apt_sources import MIRRORS as MIRRORS
from scripts.ci_apt_sources import mirror_for_architecture as mirror_for_architecture
from scripts.ci_apt_sources import source_bytes, source_changes

MIRROR_FILE = Path("/etc/apt/apt-mirrors.txt")
SOURCE_LIST = Path("/etc/apt/sources.list")
SOURCE_DIRECTORY = Path("/etc/apt/sources.list.d")
PACKAGES = frozenset({"openssh-server", "tmux", "xclip", "xvfb", "gcc", "libc6-dev", "binutils"})
APT_OPTIONS = (
    "-o",
    "Acquire::Languages=none",
    "-o",
    "Acquire::Retries=1",
    "-o",
    "Acquire::http::Timeout=15",
    "-o",
    "Acquire::https::Timeout=15",
    "-o",
    "DPkg::Lock::Timeout=60",
)


def _root_command(command: tuple[str, ...], seconds: int) -> tuple[str, ...]:
    # GNU timeout runs as root and owns the privileged command's process group.
    # The Python bound leaves time for its TERM -> KILL escalation and reap.
    return (
        "/usr/bin/sudo",
        "--non-interactive",
        "--",
        "/usr/bin/timeout",
        "--signal=TERM",
        "--kill-after=5s",
        f"{seconds}s",
        *command,
    )


def bootstrap(packages: Sequence[str]) -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Linux"
        or platform.system() != "Linux"
    ):
        raise ValueError("CI APT bootstrap requires a Linux GitHub Actions runner.")
    if isinstance(packages, (str, bytes)):
        raise ValueError("CI APT requires an explicit package argument list.")
    selected = tuple(packages)
    if (
        not selected
        or any(not isinstance(package, str) or package not in PACKAGES for package in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("CI APT accepts each declared package once, without options or overrides.")

    result = subprocess.run(
        ("/usr/bin/dpkg", "--print-architecture"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        check=True,
        timeout=10,
    )
    if not isinstance(result.stdout, bytes) or not 1 <= len(result.stdout) <= 32:
        raise ValueError("CI APT architecture response is missing or oversized.")
    architecture = result.stdout.decode("ascii").strip()
    mirror = mirror_for_architecture(architecture)
    changes = source_changes(architecture, SOURCE_LIST, SOURCE_DIRECTORY, MIRROR_FILE)
    print(
        f"CI APT: selecting reviewed MIT SIPB HTTPS mirror for {architecture}: {mirror}", flush=True
    )
    for change in changes:
        if source_bytes(change.path) != change.original:
            raise ValueError("CI APT source configuration changed before preparation.")
    for change in changes:
        subprocess.run(
            _root_command(("/usr/bin/tee", str(change.path)), 5),
            input=change.replacement,
            stdout=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )

    print(
        "CI APT: updating signed indexes without translations (120-second command deadline).",
        flush=True,
    )
    subprocess.run(
        _root_command(("/usr/bin/apt-get", *APT_OPTIONS, "update", "--error-on=any"), 120),
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=130,
    )
    print("CI APT: installing declared packages (180-second command deadline).", flush=True)
    subprocess.run(
        _root_command(
            (
                "/usr/bin/env",
                "DEBIAN_FRONTEND=noninteractive",
                "/usr/bin/apt-get",
                *APT_OPTIONS,
                "install",
                "--yes",
                "--",
                *selected,
            ),
            180,
        ),
        stdin=subprocess.DEVNULL,
        check=True,
        timeout=190,
    )


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="+", choices=sorted(PACKAGES))
    args = parser.parse_args(arguments)
    try:
        bootstrap(args.packages)
    except subprocess.CalledProcessError as error:
        print(f"CI APT bootstrap failed (command exit {error.returncode}).", file=sys.stderr)
        return error.returncode if 1 <= error.returncode <= 255 else 1
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"CI APT bootstrap failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
