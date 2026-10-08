"""Capture real preview UI with owned synthetic data; never use ambient kubeconfig."""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from aiohttp import web

from kuberich.config.schema import Settings
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from tests.support.connections import catalog_fixture, namespaces
from tests.support.pods import NOW, pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api


def offline_svg(svg: str) -> str:
    # Keep the rendered vector screenshot; use local fonts without CDN requests.
    return re.sub(r"@font-face\s*\{[^}]*\}", "", svg)


async def capture(output: Path, logs_source: Path) -> None:
    if output.exists():
        raise ValueError("Capture destination must be new")
    logs = logs_source.read_text()
    if "KubeRich" not in logs or "CoreDNS" not in logs:
        raise ValueError("Expected the qualified owned-kind KubeRich log screenshot")
    values = []
    for name, ready, restarts in (
        ("api-7b6d8fc4d9-h9t2n", True, 0),
        ("api-7b6d8fc4d9-x8c4m", True, 0),
        ("web-6df8c4b7d5-q2s9k", True, 0),
        ("worker-5b8f9d7c64-a6j3r", True, 1),
        ("queue-0", False, 3),
    ):
        value = pod(name, namespace="team", restarts=restarts, ready=ready, created=NOW)
        if not ready:
            value["status"]["containerStatuses"][0]["state"] = {
                "waiting": {"reason": "CrashLoopBackOff"}
            }
        values.append(value)

    async def resources(request: web.Request) -> web.StreamResponse:
        if "watch" in request.query:
            return await stable_watch(request)
        return web.json_response(collection(*values))

    with TemporaryDirectory(prefix="kuberich-site-capture-") as temporary:
        async with workspace_api(lambda _: async_response(), resources) as url:
            app = KubeRichApp(
                Settings(read_only=True, theme="k9s"),
                logging.Logger("site-demo", level=100),
                catalog=catalog_fixture(Path(temporary), url),
            )
            async with app.run_test(size=(120, 30)) as pilot:
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
                await wait_for(lambda: app.resources.row_count == 5)
                await pilot.press("colon")
                app.command_input.value = "de"
                await pilot.pause()
                screenshot = app.export_screenshot(title="KubeRich · owned local demo")
                assert "CrashLoopBackOff" in screenshot and "KubeRich" in screenshot
                assert "synthetic" not in screenshot and "127.0.0.1" not in screenshot
            assert app.sessions.client is None
    output.mkdir(parents=True)
    (output / "workspace.svg").write_text(offline_svg(screenshot))
    (output / "logs.svg").write_text(offline_svg(logs))
    source_tree = subprocess.check_output(["git", "rev-parse", "HEAD:src"], text=True).strip()
    inventory = {
        "application_tree": source_tree,
        "capture_command": "env -u NO_COLOR uv run python -m scripts.capture_site --output NEW_MEDIA_DIRECTORY --logs-source artifacts/ui/logs-owned-kind.svg",
        "private_data_used": False,
        "external_fonts_removed": True,
        "images": {
            "workspace.svg": {
                "sha256": hashlib.sha256((output / "workspace.svg").read_bytes()).hexdigest(),
                "source": "Actual Textual render against owned loopback API with synthetic pods",
                "terminal_cells": [120, 30],
            },
            "logs.svg": {
                "sha256": hashlib.sha256((output / "logs.svg").read_bytes()).hexdigest(),
                "source": "Qualified owned-kind logs screenshot retained in artifacts/ui; cluster deleted",
                "original_sha256": hashlib.sha256(logs_source.read_bytes()).hexdigest(),
                "qualification": "docs/acceptance/identity-migration.md",
                "terminal_cells": [100, 30],
            },
        },
    }
    (output / "media.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")


async def async_response() -> web.Response:
    return namespaces("default", "team")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--logs-source", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(capture(args.output, args.logs_source))
