"""Qualify every offline CLI path and the real terminal's first frame in fresh processes."""

import argparse
import errno
import fcntl
import hashlib
import json
import os
import platform
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from types import FrameType
from typing import Any

from scripts.startup_policy import (
    OFFLINE_CASES,
    Measurement,
    check_cli,
    check_importtime,
    check_paint,
    rss_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20.0


def inputs() -> dict[str, str]:
    paths = [
        *sorted((ROOT / "src/kuberich").rglob("*.py")),
        *sorted((ROOT / "src/kuberich").rglob("*.tcss")),
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        *(
            ROOT / "scripts" / name
            for name in ("check_startup.py", "startup_policy.py", "startup_probe.py")
        ),
    ]
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def environment(output: Path) -> dict[str, str]:
    selected = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR")
        if key in os.environ
    }
    selected.update(
        {
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "KUBERICH_CONFIG": str(output / "preferences.yaml"),
            "KUBECONFIG": str(output / "empty-kubeconfig.yaml"),
            "KUBERICH_LOG_FILE": str(output / "kuberich.log"),
            "KUBERICH_CLIPBOARD": "osc52",
            "XDG_CONFIG_HOME": str(output / "config"),
            "XDG_CACHE_HOME": str(output / "cache"),
            "XDG_DATA_HOME": str(output / "data"),
            "XDG_STATE_HOME": str(output / "state"),
            "TMPDIR": str(output / "tmp"),
            "PYTHONNOUSERSITE": "1",
        }
    )
    return selected


def kill_group(process: subprocess.Popen[bytes]) -> None:
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)


@dataclass
class Cancellation:
    requested_signal: int | None = None

    def check(self) -> None:
        if self.requested_signal is not None:
            raise InterruptedError(
                f"Startup qualification interrupted by signal {self.requested_signal}."
            )


def run_plain(
    argv: list[str],
    output: Path,
    env: dict[str, str],
    name: str,
    *,
    cancellation: Cancellation | None = None,
) -> Measurement:
    token = cancellation if cancellation is not None else Cancellation()
    done = threading.Event()
    expired = threading.Event()
    process: subprocess.Popen[bytes] | None = None
    watchdog: threading.Thread | None = None
    with (
        (output / f"{name}.stdout").open("wb") as stdout,
        (output / f"{name}.stderr").open("wb") as stderr,
    ):
        try:
            token.check()
            launched = time.perf_counter_ns()
            process = subprocess.Popen(
                argv, cwd=output, env=env, stdout=stdout, stderr=stderr, start_new_session=True
            )
            owned = process
            deadline = time.monotonic() + TIMEOUT

            def observe() -> None:
                while not done.wait(0.005):
                    if token.requested_signal is not None:
                        kill_group(owned)
                        return
                    if time.monotonic() >= deadline:
                        expired.set()
                        kill_group(owned)
                        return

            watchdog = threading.Thread(target=observe)
            watchdog.start()
            _, status, usage = os.wait4(process.pid, 0)
            elapsed = time.perf_counter_ns() - launched
            process.returncode = os.waitstatus_to_exitcode(status)
        finally:
            done.set()
            if watchdog is not None:
                watchdog.join()
            if process is not None:
                if process.returncode is None:
                    kill_group(process)
                    _, status, _ = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                kill_group(process)
    token.check()
    if expired.is_set():
        raise TimeoutError("Owned startup command exceeded its process timeout.")
    return Measurement(
        process.returncode,
        elapsed,
        rss_bytes(usage.ru_maxrss, sys.platform),
        (output / f"{name}.stdout").read_text(),
        (output / f"{name}.stderr").read_text(),
    )


def own_terminal() -> None:
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def run_terminal(
    output: Path,
    env: dict[str, str],
    name: str,
    *,
    negative: bool = False,
    cancellation: Cancellation | None = None,
) -> dict[str, Any]:
    token = cancellation if cancellation is not None else Cancellation()
    report = output / f"{name}.json"
    argv = [
        sys.executable,
        str(ROOT / "scripts/startup_probe.py"),
        "--report",
        str(report),
        "--preferences",
        env["KUBERICH_CONFIG"],
        "--kubeconfig",
        env["KUBECONFIG"],
        "--measure",
    ]
    if negative:
        argv.append("--negative-control")
    master, slave = pty.openpty()
    transcript = bytearray()
    process: subprocess.Popen[bytes] | None = None
    first_visible = None
    launched = time.perf_counter_ns()
    try:
        token.check()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 36, 120, 0, 0))
        launched = time.perf_counter_ns()
        process = subprocess.Popen(
            argv,
            cwd=output,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
            preexec_fn=own_terminal,
        )
        os.close(slave)
        slave = -1
        deadline = time.monotonic() + TIMEOUT
        while True:
            token.check()
            if select.select([master], [], [], 0.005)[0]:
                try:
                    transcript.extend(os.read(master, 65536))
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                if first_visible is None and b"Context:" in transcript:
                    first_visible = time.perf_counter_ns()
                if len(transcript) > 2 * 1024 * 1024:
                    raise ValueError("Unbounded startup terminal output.")
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                process.returncode = os.waitstatus_to_exitcode(status)
                while select.select([master], [], [], 0)[0]:
                    try:
                        remaining = os.read(master, 65536)
                    except OSError as error:
                        if error.errno == errno.EIO:
                            break
                        raise
                    if not remaining:
                        break
                    transcript.extend(remaining)
                    if first_visible is None and b"Context:" in transcript:
                        first_visible = time.perf_counter_ns()
                    if len(transcript) > 2 * 1024 * 1024:
                        raise ValueError("Unbounded final startup terminal output.")
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Owned startup terminal exceeded its process timeout.")
    finally:
        if process is not None:
            if process.returncode is None:
                kill_group(process)
                _, status, _ = os.wait4(process.pid, 0)
                process.returncode = os.waitstatus_to_exitcode(status)
            kill_group(process)
        os.close(master)
        if slave != -1:
            os.close(slave)
        (output / f"{name}.ansi").write_bytes(transcript)
    if process.returncode != 0:
        raise ValueError("The actual startup terminal did not exit cleanly.")
    if b"\x1b[?1049h" not in transcript or b"\x1b[?1049l" not in transcript:
        raise ValueError("Missing real alternate-screen creation/restoration.")
    observed: dict[str, Any] = json.loads(report.read_text())
    return {
        "observation": observed,
        "launched_ns": launched,
        "visible_ns": first_visible,
        "peak_rss_bytes": rss_bytes(usage.ru_maxrss, sys.platform),
        "transcript_bytes": len(transcript),
    }


@contextmanager
def interruptible() -> Iterator[Cancellation]:
    token = Cancellation()

    def stop(signum: int, frame: FrameType | None) -> None:
        # Keep cleanup non-interruptible, including the Popen creation window.
        if token.requested_signal is None:
            token.requested_signal = signum

    previous = {signum: signal.signal(signum, stop) for signum in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield token
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def qualify(
    output: Path, samples: int, result: dict[str, Any], cancellation: Cancellation | None = None
) -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    env = environment(output)
    (output / "tmp").mkdir()
    (output / "preferences.yaml").write_text("schema_version: 1\n")
    (output / "empty-kubeconfig.yaml").write_text(
        "apiVersion: v1\nkind: Config\ncontexts: []\nclusters: []\nusers: []\n"
    )
    identity = run_plain(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import kuberich; print(Path(kuberich.__file__).resolve())",
        ],
        output,
        env,
        "installed-source",
        cancellation=cancellation,
    )
    if (
        identity.exit_code
        or identity.stderr
        or identity.stdout.strip() != str((ROOT / "src/kuberich/__init__.py").resolve())
    ):
        raise ValueError("Startup qualification must exercise the exact source checkout.")
    result["installed_source"] = identity.stdout.strip()
    observations: list[dict[str, Any]] = []
    result["offline"] = observations
    for case, arguments in OFFLINE_CASES.items():
        for sample in range(samples):
            measured = run_plain(
                [sys.executable, "-m", "kuberich", *arguments],
                output,
                env,
                f"{case}-{sample}",
                cancellation=cancellation,
            )
            observations.append({"case": case, "sample": sample, **asdict(measured)})
            try:
                check_cli(case, measured, version)
            except ValueError:
                try:
                    diagnostic = run_plain(
                        [sys.executable, "-X", "importtime", "-m", "kuberich", *arguments],
                        output,
                        env,
                        f"{case}-failure-importtime",
                        cancellation=cancellation,
                    )
                    result["failed_case_importtime"] = {"case": case, **asdict(diagnostic)}
                except (OSError, ValueError) as error:
                    result["failed_case_importtime"] = {"case": case, "error": str(error)}
                raise
        profiled = run_plain(
            [sys.executable, "-X", "importtime", "-m", "kuberich", *arguments],
            output,
            env,
            f"{case}-importtime",
            cancellation=cancellation,
        )
        if profiled.exit_code:
            raise ValueError("Import-time command failed.")
        observations.append({"case": case, "importtime": check_importtime(profiled.stderr)})
    paints: list[dict[str, Any]] = []
    result["first_paint"] = paints
    for sample in range(samples):
        observed = run_terminal(output, env, f"paint-{sample}", cancellation=cancellation)
        paints.append(observed)
        observed["elapsed_ns"] = check_paint(
            observed["observation"], observed["launched_ns"], observed["visible_ns"]
        )
    late = run_terminal(
        output, env, "negative-late-paint", negative=True, cancellation=cancellation
    )
    result["negative_late_paint"] = late
    try:
        check_paint(late["observation"], late["launched_ns"], late["visible_ns"])
    except ValueError as error:
        if "600 ms" not in str(error):
            raise
        late["rejected"] = True
    else:
        raise ValueError("The deliberate late first frame escaped the unchanged budget.")
    forbidden = run_plain(
        [sys.executable, "-X", "importtime", "-c", "import kuberich.cli; import textual"],
        output,
        env,
        "negative-textual-import",
        cancellation=cancellation,
    )
    if forbidden.exit_code:
        raise ValueError("The explicit import negative control did not execute.")
    try:
        check_importtime(forbidden.stderr)
    except ValueError as error:
        if "Textual" not in str(error):
            raise
        result["negative_import_rejected"] = True
    else:
        raise ValueError("The deliberate terminal import escaped the offline boundary.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5, choices=range(3, 11))
    arguments = parser.parse_args()
    output = arguments.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    before = inputs()
    result: dict[str, Any] = {
        "passed": False,
        "source_inputs": before,
        "source_commit": None,
        "python": sys.version,
        "platform": [platform.system(), platform.release(), platform.machine()],
        "cpu_count": os.cpu_count(),
        "samples_per_case": arguments.samples,
        "scope": "Fresh-process startup; no release or provider certification.",
    }
    code = 1
    try:
        with interruptible() as cancellation:
            revision = run_plain(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                output,
                environment(output),
                "source-commit",
                cancellation=cancellation,
            )
            if revision.exit_code or revision.stderr or len(revision.stdout.strip()) != 40:
                raise ValueError("Missing exact Git source identity for startup qualification.")
            result["source_commit"] = revision.stdout.strip()
            qualify(output, arguments.samples, result, cancellation)
            cancellation.check()
        if inputs() != before:
            raise ValueError("Startup source inputs changed during qualification.")
        result["passed"] = True
        code = 0
    except (OSError, ValueError) as error:
        result["error"] = str(error)
        print(f"Startup gate failed: {error}", file=sys.stderr)
    finally:
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    if code == 0:
        print(f"Startup gate passed: {output / 'report.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
