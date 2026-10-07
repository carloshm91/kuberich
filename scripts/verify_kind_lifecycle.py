"""Real local-kind cleanup after setup cancellation, body cancellation and failure."""

import argparse
import json
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.owned_kind import capture_docker, owned_cluster, run_owned


def inventory(environment: dict[str, str], name: str | None = None) -> set[str]:
    label = "io.x-k8s.kind.cluster" + ("=" + name if name else "")
    return set(
        run_owned(
            ["docker", "ps", "--all", "--filter", "label=" + label, "--format", "{{.ID}}"],
            environment,
        ).splitlines()
    )


def verify(kind: str, output: Path) -> None:
    environment = capture_docker()
    before = inventory(environment)
    records = []
    with TemporaryDirectory(prefix="kubetrol-kind-cancellation-") as temporary:
        directory = Path(temporary)
        sentinel = directory / "caller-kubeconfig"
        sentinel.write_bytes(b"owned caller sentinel; never read as Kubernetes credentials\n")
        environment["KUBECONFIG"] = str(sentinel)
        for phase in ("creating", "ready", "failure"):
            log = directory / (phase + ".log")
            ready = directory / (phase + ".ready")
            with (
                log.open("w") as handle,
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "scripts.verify_kind_lifecycle",
                        "--kind",
                        kind,
                        "--child",
                        phase,
                        "--ready",
                        str(ready),
                    ],
                    env=environment,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                ) as process,
            ):
                name = None
                started = time.monotonic()
                try:
                    while process.poll() is None:
                        matches = re.findall(
                            r"Creating owned disposable kind cluster: (kubetrol-test-[a-f0-9]{32})",
                            log.read_text(),
                        )
                        name = matches[0] if matches else None
                        if phase == "creating" and name and inventory(environment, name):
                            process.send_signal(signal.SIGTERM)
                            break
                        if phase == "ready" and ready.exists():
                            process.send_signal(signal.SIGTERM)
                            break
                        if time.monotonic() - started > 330:
                            raise TimeoutError("Owned kind lifecycle trial timed out.")
                        time.sleep(0.1)
                    code = process.wait(timeout=120)
                    expected = 1 if phase == "failure" else 143
                    if code != expected or not name:
                        raise ValueError("Owned kind lifecycle did not reach its expected outcome.")
                finally:
                    if process.poll() is None:
                        process.send_signal(signal.SIGTERM)
                        try:
                            process.wait(timeout=120)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            if (
                inventory(environment) != before
                or sentinel.read_bytes()
                != b"owned caller sentinel; never read as Kubernetes credentials\n"
            ):
                raise ValueError("Cancellation changed an unowned cluster or caller configuration.")
            output.parent.mkdir(parents=True, exist_ok=True)
            (output.parent / ("kind-lifecycle-" + phase + ".log")).write_bytes(log.read_bytes())
            records.append(
                {
                    "phase": phase,
                    "exit_code": code,
                    "owned_cluster_absent": True,
                    "unowned_inventory_unchanged": True,
                    "caller_kubeconfig_unchanged": True,
                }
            )
            print("Real kind lifecycle passed: " + phase, flush=True)
    output.write_text(json.dumps({"result": "passed", "scenarios": records}, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--evidence", default="artifacts/cluster/kind-lifecycle.json")
    parser.add_argument("--child", choices=("creating", "ready", "failure"), help=argparse.SUPPRESS)
    parser.add_argument("--ready", type=Path, help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.child:
        if arguments.ready is None:
            parser.error("The owned child requires its ready file.")
        with owned_cluster(arguments.kind) as cluster:
            arguments.ready.write_text(cluster.name)
            if arguments.child == "failure":
                raise RuntimeError("Intentionally injected owned-cluster body failure.")
            signal.pause()
    else:
        verify(arguments.kind, Path(arguments.evidence))


if __name__ == "__main__":
    main()
