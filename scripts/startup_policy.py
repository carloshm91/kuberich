"""Fixed startup budgets and fail-closed decisions over actual child observations."""

import json
from dataclasses import dataclass
from typing import Any, TypedDict

from packaging.version import Version

CLI_BUDGET_NS = 150_000_000
RSS_BUDGET_BYTES = 40_000_000
IMPORT_BUDGET_US = 150_000
PAINT_BUDGET_NS = 600_000_000
OFFLINE_CASES = {
    "version": ("--version",),
    "help": ("--help",),
    "info": ("info",),
    "config-check": ("config", "check"),
}


@dataclass(frozen=True)
class Measurement:
    exit_code: int
    elapsed_ns: int
    rss_bytes: int
    stdout: str
    stderr: str


class ImportEvent(TypedDict):
    module: str
    self_us: int
    cumulative_us: int


def rss_bytes(value: int, platform: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Missing positive child peak RSS.")
    if platform == "darwin":
        return value
    if platform.startswith("linux"):
        return value * 1024
    raise ValueError("Startup RSS qualification requires Linux or macOS.")


def check_cli(case: str, measurement: Measurement, version: str) -> None:
    if (
        case not in OFFLINE_CASES
        or type(measurement.exit_code) is not int
        or measurement.exit_code != 0
        or measurement.stderr
    ):
        raise ValueError("Offline command did not complete cleanly.")
    if type(measurement.elapsed_ns) is not int or not 0 < measurement.elapsed_ns < CLI_BUDGET_NS:
        raise ValueError("Offline command exceeds the 150 ms startup budget.")
    if type(measurement.rss_bytes) is not int or not 0 < measurement.rss_bytes < RSS_BUDGET_BYTES:
        raise ValueError("Offline command exceeds the 40,000,000-byte RSS budget.")
    if case == "version" and measurement.stdout != f"kuberich {version}\n":
        raise ValueError("Version command did not execute the installed CLI.")
    if case == "help" and not all(
        text in measurement.stdout for text in ("usage: kuberich", "--context", "--readonly")
    ):
        raise ValueError("Help command did not expose the actual launch interface.")
    if case == "config-check" and measurement.stdout != (
        "KubeRich preferences are valid. No files were changed.\n"
    ):
        raise ValueError("Configuration check did not validate the owned preferences.")
    if case == "info":
        information = json.loads(measurement.stdout)
        if (
            not isinstance(information, dict)
            or not isinstance(information.get("preferences"), dict)
            or not isinstance(information.get("dependencies"), dict)
            or information.get("version") != version
            or information.get("terminal_ui_available") is not True
            or information.get("cluster_connected") is not False
            or information.get("preferences", {}).get("theme") != "k9s"
            or set(information.get("dependencies", {}))
            != {"textual", "kubernetes-asyncio", "platformdirs", "pyyaml"}
        ):
            raise ValueError("Info did not report the complete offline diagnostic contract.")


def check_importtime(text: str) -> dict[str, Any]:
    events: list[ImportEvent] = []
    for line in text.splitlines():
        if line == "import time: self [us] | cumulative | imported package":
            continue
        if not line.startswith("import time:"):
            raise ValueError("Unexpected diagnostic text in the import-time capture.")
        fields = line.removeprefix("import time:").split("|")
        if len(fields) != 3:
            raise ValueError("Malformed import-time observation.")
        own, cumulative = int(fields[0]), int(fields[1])
        name = fields[2].strip()
        if own < 0 or cumulative < own or not name:
            raise ValueError("Invalid import-time observation.")
        if name.split(".")[0] in {"textual", "kubernetes_asyncio"}:
            raise ValueError("Offline startup imported Textual or kubernetes_asyncio.")
        events.append({"module": name, "self_us": own, "cumulative_us": cumulative})
    if sum(event["module"] == "kuberich.cli" for event in events) != 1:
        raise ValueError("Import-time evidence must cover the actual CLI exactly once.")
    total = sum(event["self_us"] for event in events)
    if (
        total >= IMPORT_BUDGET_US
        or max(event["cumulative_us"] for event in events) >= IMPORT_BUDGET_US
    ):
        raise ValueError("Offline imports exceed the 150 ms aggregate self-time budget.")
    return {"self_us": total, "modules": events}


def enforce_paint_budget(version: str, *, strict: bool = False) -> bool:
    """The maintainer made only 0.x UI latency advisory on 2026-11-01."""
    major = Version(version).major
    return strict or major >= 1


def observe_paint(observation: dict[str, Any], launched_ns: int, visible_ns: int | None) -> int:
    """Require a real complete, safely closed frame in every release mode."""
    painted_ns = observation.get("first_paint_ns")
    frames = observation.get("table_frames")
    table = frames.get("resources") if isinstance(frames, dict) else None
    if not isinstance(table, dict):
        raise ValueError("Missing actual mounted resource-table evidence.")
    region = table.get("region")
    if (
        type(launched_ns) is not int
        or launched_ns <= 0
        or observation.get("painted") is not True
        or type(painted_ns) is not int
        or type(visible_ns) is not int
        or painted_ns <= launched_ns
        or visible_ns <= launched_ns
        or not isinstance(observation.get("shown_tables"), list)
        or "resources" not in observation["shown_tables"]
        or table.get("mounted") is not True
        or type(table.get("columns")) is not int
        or table["columns"] <= 0
        or not isinstance(region, list)
        or len(region) != 4
        or any(type(value) is not int for value in region)
        or region[0] < 0
        or region[1] < 0
        or region[2] <= 0
        or region[3] <= 0
        or region[0] + region[2] > 120
        or region[1] + region[3] > 36
        or observation.get("exit") != 0
        or observation.get("client_closed") is not True
        or observation.get("viewport") != [120, 36]
        or observation.get("sdk_before_paint") != []
        or observation.get("sdk_models_at_exit") != 0
        or observation.get("violations") != []
        or observation.get("events") != [{"kind": "paint", "painted": True}]
    ):
        raise ValueError("Missing actual first-frame, shutdown or deferred-SDK evidence.")
    return max(painted_ns, visible_ns) - launched_ns


def check_paint(observation: dict[str, Any], launched_ns: int, visible_ns: int | None) -> int:
    """Keep the unchanged strict 600 ms decision available in every release."""
    elapsed = observe_paint(observation, launched_ns, visible_ns)
    if not 0 < elapsed < PAINT_BUDGET_NS:
        raise ValueError("Actual first paint exceeds the 600 ms startup budget.")
    return elapsed
