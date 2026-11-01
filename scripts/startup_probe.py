"""Observe the real terminal's first refresh through public Textual lifecycle APIs."""

import argparse
import json
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--preferences", type=Path, required=True)
    parser.add_argument("--kubeconfig", type=Path, required=True)
    parser.add_argument("--initial", default="")
    parser.add_argument("--mode", choices=("paint", "observe", "cancel"), default="paint")
    parser.add_argument("--replace-context")
    parser.add_argument("--owned-api-port", type=int)
    parser.add_argument("--updates-endpoint")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--negative-control", action="store_true")
    arguments = parser.parse_args()
    if arguments.negative_control and not arguments.measure:
        parser.error("The deliberate timing fault requires measurement mode.")
    if arguments.updates_endpoint is not None:
        endpoint = urlsplit(arguments.updates_endpoint)
        if (
            endpoint.scheme != "http"
            or endpoint.hostname != "127.0.0.1"
            or endpoint.port != arguments.owned_api_port
            or endpoint.username is not None
            or endpoint.password is not None
        ):
            parser.error("Update observations require an explicitly owned loopback endpoint.")

    painted = threading.Event()
    events: list[dict[str, object]] = []
    violations: list[str] = []
    observation: dict[str, Any] = {"painted": False, "first_paint_ns": None}
    code = 1

    def audit(event: str, values: tuple[object, ...]) -> None:
        kind = (
            "sdk-import"
            if event == "import"
            and values
            and isinstance(values[0], str)
            and (values[0] == "kubernetes_asyncio" or values[0].startswith("kubernetes_asyncio."))
            else "network"
            if event == "socket.connect"
            else "resolve"
            if event in {"socket.getaddrinfo", "socket.gethostbyname"}
            else "helper"
            if event == "subprocess.Popen"
            else None
        )
        if kind is None:
            return
        if kind == "resolve" and values[0] not in {"127.0.0.1", "::1"}:
            violations.append("unowned-resolve")
            raise RuntimeError("External DNS is unavailable in the owned startup probe.")
        if kind == "network":
            address = values[1] if len(values) > 1 else None
            if (
                not isinstance(address, tuple)
                or len(address) < 2
                or address[0] not in {"127.0.0.1", "::1"}
                or address[1] != arguments.owned_api_port
            ):
                violations.append("unowned-network")
                raise RuntimeError("The probe only permits its explicitly owned loopback API.")
        already_observed_sdk = kind == "sdk-import" and any(
            item.get("kind") == "sdk-import" for item in events
        )
        if len(events) < 32 and not (painted.is_set() and already_observed_sdk):
            events.append(
                {
                    "kind": kind,
                    "painted": painted.is_set(),
                    **(
                        {
                            "stack": [
                                f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                                for frame in traceback.extract_stack(limit=7)
                            ]
                        }
                        if kind == "sdk-import"
                        else {}
                    ),
                }
            )
        if not painted.is_set():
            violations.append(kind)
            raise RuntimeError("Connection work preceded the first real terminal refresh.")

    sys.addaudithook(audit)
    try:
        from unittest.mock import patch

        from textual.events import Mount, Unmount
        from textual.widgets import DataTable

        from kuberich.cli import main as cli
        from kuberich.ui import launch
        from kuberich.ui.app import KubeRichApp

        if arguments.measure:
            observation["imports_finished_ns"] = time.perf_counter_ns()

        class ObservedApp(KubeRichApp):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                if arguments.measure:
                    observation["constructor_started_ns"] = time.perf_counter_ns()
                if arguments.updates_endpoint is not None:
                    from importlib.metadata import version

                    from kuberich.services.updates import UpdateService

                    kwargs["updates"] = UpdateService(
                        version("kuberich"),
                        arguments.report.with_suffix(".update-cache.json"),
                        endpoint=arguments.updates_endpoint,
                    )
                super().__init__(*args, **kwargs)
                if arguments.measure:
                    observation["constructor_finished_ns"] = time.perf_counter_ns()

            def on_mount(self, event: Mount | None = None) -> None:
                if arguments.measure:
                    observation["mount_started_ns"] = time.perf_counter_ns()
                if event is not None:
                    event.prevent_default()
                # Enqueue before the production readiness callback. Both callbacks
                # run after the actual screen refresh, in their recorded order.
                self.call_after_refresh(self.first_paint)
                if arguments.mode == "cancel":

                    async def cancel_before_release() -> None:
                        await self.workspace.close()
                        self.exit()

                    # Run actual owned cleanup before the production readiness
                    # callback. A stranded waiter would deadlock this callback.
                    self.call_after_refresh(cancel_before_release)
                if arguments.negative_control:
                    time.sleep(0.7)
                super().on_mount()
                observation["probe_mode"] = arguments.mode
                if arguments.replace_context is not None:
                    self.workspace.connect(arguments.replace_context)
                if arguments.measure:
                    observation["mount_returned_ns"] = time.perf_counter_ns()

            def first_paint(self) -> None:
                tables = tuple(self.query(DataTable))
                observation.update(
                    {
                        "painted": True,
                        "first_paint_ns": time.perf_counter_ns() if arguments.measure else None,
                        "viewport": [self.screen.size.width, self.screen.size.height],
                        "sdk_before_paint": sorted(
                            name for name in sys.modules if name.startswith("kubernetes_asyncio")
                        ),
                        "shown_tables": [
                            table.id
                            for table in tables
                            if table.display and table.size.width and table.size.height
                        ],
                        "context_rows": next(
                            (table.row_count for table in tables if table.id == "contexts"), None
                        ),
                        "table_frames": {
                            table.id: {
                                "mounted": self.is_mounted(table) and table.is_mounted,
                                "columns": len(table.columns),
                                "region": list(table.region),
                            }
                            for table in tables
                            if table.display and table.size.width and table.size.height
                        },
                    }
                )
                painted.set()
                events.append({"kind": "paint", "painted": True})
                arguments.report.with_suffix(".painted.json").write_text(json.dumps(observation))
                if arguments.mode == "paint":
                    self.exit()

            async def on_unmount(self, event: Unmount | None = None) -> None:
                if event is not None:
                    event.prevent_default()
                await super().on_unmount()
                identity = self.sessions.observation.identity
                observation["last_context"] = identity.context if identity is not None else None
                observation["last_state"] = self.sessions.observation.state.name
                observation["client_closed"] = self.sessions.client is None

        options = [
            "--config",
            str(arguments.preferences),
            "--kubeconfig",
            str(arguments.kubeconfig),
        ]
        if arguments.initial:
            options.extend(("--command", arguments.initial))
        # Replace only the public constructor in this owned observation process;
        # all production setup, render and shutdown methods still execute.
        with patch.object(launch, "KubeRichApp", ObservedApp):
            code = cli(options)
    finally:
        arguments.report.write_text(
            json.dumps(
                {
                    **observation,
                    "events": events,
                    "violations": violations,
                    "exit": code,
                    "sdk_models_at_exit": sum(
                        name.startswith("kubernetes_asyncio.client.models.") for name in sys.modules
                    ),
                },
                indent=2,
            )
            + "\n"
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
