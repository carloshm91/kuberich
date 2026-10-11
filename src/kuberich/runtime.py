"""Frozen entry and child environment; retain the application's own loader state."""

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

PTY_OPTION = "--kuberich-pty-child"


def _outside_bundle(value: str, bundle: Path) -> str:
    return os.pathsep.join(
        part
        for part in value.split(os.pathsep)
        if not Path(os.path.normpath(part)).is_relative_to(bundle)
    )


def external_environment(inherited: Mapping[str, str]) -> dict[str, str]:
    """Restore external tools' libraries without mutating captured or ambient state."""
    environment = dict(inherited)
    directory = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not isinstance(directory, str):
        return environment
    bundle = Path(directory)
    if not bundle.is_absolute() or sys.platform not in {"linux", "darwin"}:
        return environment
    if sys.platform == "linux":
        original = environment.pop("LD_LIBRARY_PATH_ORIG", None)
        current = environment.get("LD_LIBRARY_PATH", "")
        if _outside_bundle(current, bundle) != current:
            if original is None:
                environment.pop("LD_LIBRARY_PATH", None)
            else:
                environment["LD_LIBRARY_PATH"] = _outside_bundle(original, bundle)
    for name in ("PATH", "DYLD_LIBRARY_PATH"):
        if name in environment:
            current = environment[name]
            filtered = _outside_bundle(current, bundle)
            if filtered != current:
                if filtered:
                    environment[name] = filtered
                else:
                    environment.pop(name)
    return {key: value for key, value in environment.items() if not key.startswith("_PYI_")}


def pty_argv(argv: Sequence[str]) -> tuple[str, ...]:
    """Re-exec the frozen launcher, or the installed stdlib-only Python launcher."""
    if getattr(sys, "frozen", False):
        return (sys.executable, PTY_OPTION, *argv)
    return (
        sys.executable,
        "-I",
        str(Path(__file__).parent / "adapters" / "pty_child.py"),
        *argv,
    )


def main() -> int:
    """Dispatch the owned PTY child before loading the UI or its dependencies."""
    if getattr(sys, "frozen", False) and sys.argv[1:2] == [PTY_OPTION]:
        from kuberich.adapters.pty_child import main as run_pty

        return run_pty(sys.argv[2:], environment=external_environment(os.environ))
    from kuberich.cli import main as run_cli

    return run_cli()
