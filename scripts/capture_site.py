"""Capture real preview UI with owned synthetic data; never use ambient kubeconfig."""

import argparse
import asyncio
import hashlib
import json
import logging
import re
import subprocess
import tomllib
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from aiohttp import web

import kuberich
from kuberich.config.catalog import Entry, KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.views import ViewStatus
from kuberich.ui.app import KubeRichApp
from kuberich.ui.logs import LogScreen
from tests.support.connections import namespaces
from tests.support.pods import NOW, pod
from tests.support.resources import collection
from tests.support.workspace import stable_watch, wait_for, workspace_api

ROOT = Path(__file__).resolve().parents[1]


def source_snapshot(root: Path) -> tuple[str, str, str]:
    """Use existing committed source information, refusing dirty capture inputs."""
    status = subprocess.check_output(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        text=True,
        timeout=10,
    )
    if status:
        raise ValueError("Capture source must be clean and committed")
    commit = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True, timeout=10
    ).strip()
    tree = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD:src"], text=True, timeout=10
    ).strip()
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    return commit, tree, str(project["version"])


def offline_svg(svg: str) -> str:
    # Keep the rendered vector screenshot; use local fonts without CDN requests.
    return re.sub(r"@font-face\s*\{[^}]*\}", "", svg)


def historical_svg(path: Path) -> str:
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("Historical screenshot must be a regular SVG smaller than 2 MiB")
    svg = offline_svg(path.read_text())
    try:
        tree = ElementTree.fromstring(svg)
    except ElementTree.ParseError as error:
        raise ValueError("Historical screenshot must be valid SVG") from error
    prefix = "{http://www.w3.org/2000/svg}"
    if tree.tag != prefix + "svg" or "KubeRich" not in svg:
        raise ValueError("Historical screenshot must identify KubeRich")
    allowed = {
        "svg",
        "defs",
        "clipPath",
        "g",
        "rect",
        "text",
        "tspan",
        "style",
        "path",
        "title",
        "desc",
        "line",
        "polyline",
        "polygon",
        "circle",
        "ellipse",
        "use",
    }
    for element in tree.iter():
        if not element.tag.startswith(prefix) or element.tag.removeprefix(prefix) not in allowed:
            raise ValueError("Historical screenshot contains active content")
        for key, value in element.attrib.items():
            name = key.rsplit("}", 1)[-1].lower()
            if name.startswith("on") or (name in {"href", "src"} and not value.startswith("#")):
                raise ValueError("Historical screenshot contains active references")
            check_local_styles(value)
        if element.tag == prefix + "style":
            check_local_styles(element.text or "")
    return svg


def check_local_styles(value: str) -> None:
    if "\\" in value:
        raise ValueError("Historical screenshot must not use escaped CSS references")
    if re.search(r"@import|@font-face", value, re.I):
        raise ValueError("Historical screenshot must use local fonts")
    for target in re.findall(r"url\s*\(\s*([^)]*)\)", value, re.I):
        if not target.strip(" \"'").startswith("#"):
            raise ValueError("Historical screenshot must be an offline vector")


async def capture(output: Path, logs_source: Path | None = None) -> None:
    if output.exists():
        raise ValueError("Capture destination must be new")
    imported_logs = None if logs_source is None else historical_svg(logs_source)
    source_commit, source_tree, source_version = source_snapshot(ROOT)
    if Path(kuberich.__file__).resolve() != ROOT / "src/kuberich/__init__.py":
        raise ValueError("Capture requires the actual application from this source checkout")
    if version("kuberich") != source_version:
        raise ValueError("Installed application metadata differs from capture source")
    logs_closed = asyncio.Event()
    active_handlers = requests = log_requests = 0
    values = []
    for name, ready, restarts in (
        ("api-7b6d8fc4d9-h9t2n", True, 0),
        ("api-7b6d8fc4d9-x8c4m", True, 0),
        ("web-6df8c4b7d5-q2s9k", True, 0),
        ("worker-5b8f9d7c64-a6j3r", True, 1),
        ("queue-0", False, 3),
    ):
        value = pod(name, namespace="demo-apps", restarts=restarts, ready=ready, created=NOW)
        if not ready:
            value["status"]["containerStatuses"][0]["state"] = {
                "waiting": {"reason": "CrashLoopBackOff"}
            }
        value["spec"]["containers"][0]["image"] = "demo-api:1.0"
        values.append(value)

    async def resource_response(request: web.Request) -> web.StreamResponse:
        nonlocal log_requests
        if request.path.endswith("/log"):
            log_requests += 1
            response = web.StreamResponse(headers={"Content-Type": "text/plain; charset=utf-8"})
            await response.prepare(request)
            try:
                for number, message in enumerate(
                    (
                        "INFO KubeRich demo service is ready",
                        "INFO request-started method=GET path=/health",
                        "INFO request-finished status=200 duration=12ms",
                        "INFO worker completed demo-task-17",
                        "Authorization: Bearer synthetic-capture-secret",
                        "INFO waiting for the next demo request",
                    )
                ):
                    await response.write(f"2026-01-01T12:00:{number:02}Z {message}\n".encode())
                while request.transport is not None and not request.transport.is_closing():
                    await asyncio.sleep(0.005)
            finally:
                logs_closed.set()
            return response
        if "watch" in request.query:
            return await stable_watch(request)
        if request.path.endswith("/pods"):
            return web.json_response(collection(*values))
        return web.json_response(
            next(
                (
                    value
                    for value in values
                    if request.path.endswith("/" + value["metadata"]["name"])
                ),
                values[0],
            )
        )

    async def resources(request: web.Request) -> web.StreamResponse:
        nonlocal active_handlers, requests
        assert request.method == "GET"
        assert request.headers.get("Authorization") == "Bearer synthetic"
        active_handlers += 1
        requests += 1
        try:
            return await resource_response(request)
        finally:
            active_handlers -= 1

    with TemporaryDirectory(prefix="kuberich-site-capture-") as temporary:
        async with workspace_api(lambda _: async_response(), resources) as url:
            directory = Path(temporary)
            catalog = KubeCatalog(
                current="demo-lab",
                contexts={
                    "demo-lab": Entry(
                        {
                            "cluster": "demo-cluster",
                            "user": "demo-reader",
                            "namespace": "demo-apps",
                        },
                        directory,
                    )
                },
                clusters={"demo-cluster": Entry({"server": url}, directory)},
                users={"demo-reader": Entry({"token": "synthetic"}, directory)},
            )
            app = KubeRichApp(
                Settings(read_only=True, theme="k9s"),
                logging.Logger("site-demo", level=100),
                catalog=catalog,
            )
            async with app.run_test(size=(120, 30)) as pilot:
                await wait_for(lambda: app.workspace.store.observation.status is ViewStatus.LIVE)
                await wait_for(lambda: app.resources.row_count == 5)
                client = app.sessions.client
                assert client is not None and client.api is not None
                pool = client.api.rest_client.pool_manager
                await pilot.press("colon")
                app.command_input.value = "de"
                await pilot.pause()
                screenshot = app.export_screenshot(title="KubeRich · owned local demo")
                assert "CrashLoopBackOff" in screenshot and "KubeRich" in screenshot
                assert "synthetic" not in screenshot and "127.0.0.1" not in screenshot
                await pilot.press("escape")
                await pilot.resize_terminal(100, 30)
                await pilot.press("l")
                await wait_for(lambda: isinstance(app.screen, LogScreen))
                log_screen = app.screen
                assert isinstance(log_screen, LogScreen)
                await wait_for(lambda: len(log_screen.body.rows) == 6)
                await pilot.pause()
                logs = app.export_screenshot(title="KubeRich · local demo logs")
                assert "request-finished" in logs and "demo-apps" in logs
                assert "synthetic" not in logs and "127.0.0.1" not in logs
            assert app.sessions.client is None and client.api is None and pool.closed
            await wait_for(logs_closed.is_set)
            await wait_for(lambda: active_handlers == 0)
    assert active_handlers == 0 and log_requests >= 1 and requests >= 3
    assert not directory.exists()
    if source_snapshot(ROOT) != (source_commit, source_tree, source_version):
        raise ValueError("Capture source changed during rendering")
    output.mkdir(parents=True)
    (output / "workspace.svg").write_text(offline_svg(screenshot))
    (output / "logs.svg").write_text(offline_svg(logs if imported_logs is None else imported_logs))
    inventory = {
        "source_commit": source_commit,
        "source_clean": True,
        "application_tree": source_tree,
        "application_version": source_version,
        "imported_application_matches_source": True,
        "redaction_verified": imported_logs is None,
        "cleanup": {
            "application_client_released": app.sessions.client is None,
            "client_api_released": client.api is None,
            "client_pool_closed": pool.closed,
            "log_stream_handler_closed": logs_closed.is_set(),
            "resource_handlers_active": active_handlers,
            "loopback_api_context_closed": True,
            "temporary_directory_removed": not directory.exists(),
        },
        "owned_requests": requests,
        "owned_log_requests": log_requests,
        "capture_command": "env -u NO_COLOR uv run python -m scripts.capture_site --output NEW_MEDIA_DIRECTORY",
        "private_data_used": False if imported_logs is None else None,
        "external_fonts_removed": True,
        "images": {
            "workspace.svg": {
                "sha256": hashlib.sha256((output / "workspace.svg").read_bytes()).hexdigest(),
                "source": "Actual Textual render against owned loopback API with synthetic pods",
                "terminal_cells": [120, 30],
            },
            "logs.svg": {
                "sha256": hashlib.sha256((output / "logs.svg").read_bytes()).hexdigest(),
                "source": (
                    "Actual Textual log viewer against owned loopback API with synthetic logs"
                    if imported_logs is None
                    else "Imported existing SVG; not regenerated or qualified by this command"
                ),
                "terminal_cells": [100, 30] if imported_logs is None else None,
            },
        },
    }
    (output / "media.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")


async def async_response() -> web.Response:
    return namespaces("default", "demo-apps")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--logs-source",
        type=Path,
        help="Optionally import an existing reviewed SVG; marked as imported, with unknown privacy/source status",
    )
    args = parser.parse_args()
    asyncio.run(capture(args.output, args.logs_source))
