"""Real source/installed curated-resource terminals over one owned async HTTP API."""

import asyncio
import copy
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path

import yaml

from kuberich.domain.registry import STANDARD_RESOURCES
from kuberich.services.ownership import finish_owned
from tests.support.container_inspection_terminal import _AUDIT, _audit_controls
from tests.support.curated_access import CANARY as ACCESS_CANARY
from tests.support.curated_admission import CANARIES as ADMISSION_CANARIES
from tests.support.curated_events import CuratedEventsApi
from tests.support.curated_policy import ANNOTATION_CANARY, CA_CANARY, URL_CANARIES
from tests.support.curated_resources import ERROR_CANARY, PRINTER_CANARY, curated_resources_api
from tests.support.events import EVENT_CANARY
from tests.support.terminal_api import config
from tests.terminal.pty_support import ROOT, TerminalSession

_CASES = {
    "horizontalpodautoscalers": ("desired", ("2", "10"), (0, 1)),
    "verticalpodautoscalers": ("recommended-containers", ("1", "10"), (0, 1)),
    "poddisruptionbudgets": ("current-healthy", ("2", "10"), (0, 1)),
    "priorityclasses": ("priority", ("-10", "20"), (0, 1)),
    "runtimeclasses": ("overhead-memory", ("64Mi", "1Gi"), (0, 1)),
    "leases": ("duration-seconds", ("0", "30"), (0, 1)),
    "networkpolicies": ("ingress-rules", ("1", "0"), (1, 0)),
    "endpointslices": ("endpoints", ("3", "0"), (1, 0)),
    "ingressclasses": ("default", ("true", "false"), (1, 0)),
    "resourcequotas": ("exceeded", ("1", "0"), (1, 0)),
    "limitranges": ("items", ("2", "1"), (1, 0)),
    "mutatingwebhookconfigurations": ("timeout-max", ("20", "7"), (1, 0)),
    "validatingwebhookconfigurations": ("timeout-max", ("20", "7"), (1, 0)),
    "serviceaccounts": ("secrets", ("1", "2"), (0, 1)),
    "roles": ("rules", ("1", "2"), (0, 1)),
    "clusterroles": ("rules", ("1", "2"), (0, 1)),
    "rolebindings": ("users", ("0", "2"), (0, 1)),
    "clusterrolebindings": ("users", ("0", "2"), (0, 1)),
    "validatingadmissionpolicies": ("validations", ("1", "2"), (0, 1)),
    "validatingadmissionpolicybindings": ("match-rules", ("1", "2"), (0, 1)),
    "mutatingadmissionpolicies": ("mutations", ("1", "2"), (0, 1)),
    "mutatingadmissionpolicybindings": ("match-rules", ("1", "2"), (0, 1)),
}
_CANARIES = (
    ACCESS_CANARY,
    ANNOTATION_CANARY,
    CA_CANARY,
    ERROR_CANARY,
    PRINTER_CANARY,
    EVENT_CANARY,
    *ADMISSION_CANARIES,
    *URL_CANARIES,
    "synthetic-curated-pty",
)
_BINDING_AUDIT = """
if _record and sys.argv[0] != "-c":
    import atexit
    import hashlib
    from pathlib import Path
    def _source_binding():
        modules = {}
        for name, module in tuple(sys.modules.items()):
            if name != "kuberich" and not name.startswith("kuberich."):
                continue
            filename = getattr(module, "__file__", None)
            if not filename or not filename.endswith(".py"):
                continue
            path = Path(filename).resolve()
            relative = "src/" + name.replace(".", "/")
            relative += "/__init__.py" if path.name == "__init__.py" else ".py"
            modules[relative] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        _write({"event": "source-binding", "modules": modules})
    atexit.register(_source_binding)
"""


class CuratedTerminalApi(CuratedEventsApi):
    def __init__(self):
        super().__init__()
        resource = self.resource("deployments", group="apps")
        target = self.objects(resource)[0]
        target["metadata"].update(name="owned-workload", uid="owned-curated-target")
        self.put(resource, target)
        self.authenticated_reads = 0

    async def handle(self, request):
        assert request.headers.get("Authorization") == "Bearer synthetic-curated-pty"
        self.authenticated_reads += 1
        return await super().handle(request)


def _hashes():
    paths = {
        *ROOT.glob("src/kuberich/**/*.py"),
        *ROOT.glob("tests/support/**/*.py"),
        *(
            ROOT / name
            for name in (
                "tests/support/curated_terminal.py",
                "tests/support/curated_resources.py",
                "tests/support/curated_events.py",
                "tests/support/events.py",
                "tests/support/curated_access.py",
                "tests/support/curated_scaling.py",
                "tests/support/curated_policy.py",
                "tests/support/container_inspection_terminal.py",
                "tests/terminal/pty_support.py",
                "tests/terminal/test_curated_resources.py",
                "tests/packaging/test_curated_terminal.py",
                "tests/packaging/conftest.py",
                "pyproject.toml",
                "uv.lock",
            )
        ),
    }
    for path in paths:
        relative = path.relative_to(ROOT)
        assert not path.is_symlink() and not any(
            parent.is_symlink() for parent in path.parents if parent.is_relative_to(ROOT)
        ), relative
        details = path.stat(follow_symlinks=False)
        assert stat.S_ISREG(details.st_mode) and details.st_uid == os.geteuid(), relative
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def _preferences(api):
    views = {}
    for definition in STANDARD_RESOURCES:
        if definition.name not in _CASES:
            continue
        resource = api.resource(definition.name, group=definition.group)
        field = _CASES[definition.name][0]
        views[resource.api_version + "/" + resource.name] = {
            "columns": [{"key": "name", "width": 12}, {"key": field, "width": 28}],
            "sort": {"key": field, "descending": False},
        }
    return {"schema_version": 1, "navigation": {"schema_version": 1, "views": views}}


def _preserve(output, evidence):
    existing = tuple(
        path
        for suffix in (".ansi", ".json", "-curated.json", "-api-cleanup.json")
        if (path := output / (evidence + suffix)).exists()
    )
    if existing:
        archive = output / "preserved" / (evidence + "-" + str(time.time_ns()))
        archive.mkdir(parents=True)
        for path in existing:
            shutil.copy2(path, archive / path.name)


def _private_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def _drive(command, directory, url, api, *, evidence, flow, size, source, installed, stopping):
    output = ROOT / "artifacts" / "terminal"
    output.mkdir(parents=True, exist_ok=True)
    _preserve(output, evidence)
    kubeconfig = config(directory / "curated-kubeconfig", url, {"token": "synthetic-curated-pty"})
    kubeconfig.chmod(0o600)
    before = kubeconfig.read_bytes()
    preferences = directory / "preferences.yaml"
    preferences.write_text(yaml.safe_dump(_preferences(api)))
    preferences.chmod(0o600)
    hooks = directory / "curated-hooks"
    hooks.mkdir(mode=0o700)
    (hooks / "sitecustomize.py").write_text(_AUDIT + _BINDING_AUDIT)
    audit = directory / "curated-audit.jsonl"
    environment = {
        "PYTHONPATH": str(hooks),
        "KUBERICH_INSPECTION_AUDIT": str(audit),
        "KUBERICH_INSPECTION_PORT": url.rsplit(":", 1)[1],
    }
    witnesses, families = [], []
    stage = "terminal-start"
    terminal = None
    passed = normal_finish = False

    def wait(label, required, *, since=-1, absent=(), predicate=lambda display: True, scroll=False):
        nonlocal stage
        stage = label
        deadline = time.monotonic() + 15
        while True:
            if stopping.is_set():
                raise asyncio.CancelledError
            display = "\n".join(terminal.screen.display)
            if (
                len(terminal.transcript) > since
                and all(text in display for text in required)
                and all(text not in display for text in absent)
                and predicate(terminal.screen.display)
            ):
                witnesses.append(
                    {
                        "stage": label,
                        "required": required,
                        "absent": absent,
                        "screen": terminal.screen.display.copy(),
                        "deadline_seconds": 15,
                    }
                )
                return
            assert terminal.completion is None and terminal.process.poll() is None, (
                f"CLI exited at {label}"
            )
            assert time.monotonic() < deadline, (
                f"Missing complete native frame at {label}: {terminal.screen.display!r}"
            )
            if scroll:
                terminal.send(b"\x1b[C")
            terminal.read(0.05)

    def route_command(text):
        return terminal.send(b":" + text.encode() + b"\r")

    def parent(title, selected):
        marker = terminal.send(b"\x1b")
        wait("parent:" + title, (title, selected), since=marker, absent=("details(", "links("))

    def pair_order(display, values, order):
        lines = [
            next((line for line in display if name in line), "") for name in ("owned-a", "owned-b")
        ]
        return all(
            line and line.split(name, 1)[1].strip(" │") == value
            for name, line, value in zip(("owned-a", "owned-b"), lines, values, strict=True)
        ) and display.index(lines[order[0]]) < display.index(lines[order[1]])

    try:
        with TerminalSession(
            [*command, "--kubeconfig", str(kubeconfig), "--readonly", "-n", "team"],
            directory,
            size=size,
            environment=environment,
        ) as terminal:
            wait("initial-connected-pod", ("pods(team)[1]", "owned-start", "live"))
            marker = terminal.resize(100, 30)
            wait("initial-wide-frame", ("pods(team)[1]", "owned-start", "live"), since=marker)
            if flow == "families":
                for definition in (item for item in STANDARD_RESOURCES if item.name in _CASES):
                    name = definition.name
                    field, values, order = _CASES[name]
                    title = f"{name}({'team' if definition.namespaced else 'cluster'})[2]"
                    marker = route_command(name + (" team" if definition.namespaced else ""))
                    wait(
                        "family:" + name,
                        (title, field.upper(), "owned-a", "owned-b", "live"),
                        since=marker,
                        predicate=lambda display, v=values, o=order: pair_order(display, v, o),
                    )
                    families.append(name)
                    if name in {
                        "horizontalpodautoscalers",
                        "serviceaccounts",
                        "roles",
                        "networkpolicies",
                        "mutatingwebhookconfigurations",
                    }:
                        selected = "owned-" + ("a" if order[0] == 0 else "b")
                        resource = api.resource(name, group=definition.group)
                        namespace = "team" if definition.namespaced else None
                        selected_uid = next(
                            body["metadata"]["uid"]
                            for body in api.objects(resource, namespace)
                            if body["metadata"]["name"] == selected
                        )
                        target_path = resource.path(namespace) + "/" + selected
                        read_from = len(api.requests)
                        marker = terminal.send(b"g\r")
                        location = ("team/" if definition.namespaced else "Cluster/") + selected
                        wait(
                            "details:" + name,
                            (
                                f"details({location})",
                                "kind: " + resource.kind,
                                "apiVersion: " + resource.api_version,
                                "uid: " + selected_uid,
                                "sections:",
                            ),
                            since=marker,
                            predicate=lambda display, path=target_path, start=read_from: any(
                                entry.method == "GET"
                                and entry.path == path
                                and "watch" not in entry.query
                                for entry in api.requests[start:]
                            ),
                        )
                        marker = terminal.send(b"L")
                        link = {
                            "horizontalpodautoscalers": "Scale target",
                            "serviceaccounts": "Explain ServiceAccount grants",
                            "roles": "Explain role and aggregation",
                            "networkpolicies": "Selected namespace Pods",
                            "mutatingwebhookconfigurations": "Declared owners and references",
                        }[name]
                        wait("links:" + name, (f"links({location})", link), since=marker)
                        if name == "horizontalpodautoscalers":
                            marker = terminal.send(b"\r")
                            wait(
                                "fresh-scale-target",
                                ("deployments(team)[1]", "owned-workload"),
                                since=marker,
                                absent=("links(",),
                            )
                            parent(title, "owned-a")
                        else:
                            parent(title, selected)
                marker = route_command("clusterrolebindings")
                wait(
                    "ordinary-family-resize-source",
                    ("clusterrolebindings(cluster)[2]", "USERS", "owned-a", "owned-b"),
                    since=marker,
                )
                marker = terminal.resize(40, 12)
                wait(
                    "compact-curated-family",
                    ("clusterrolebindings(cluster)[2]", "owned-a"),
                    since=marker,
                )
                marker = terminal.resize(100, 30)
                wait(
                    "wide-curated-family-return",
                    ("clusterrolebindings(cluster)[2]", "USERS", "owned-a", "owned-b"),
                    since=marker,
                )
            elif flow == "admission":
                for plural, bindings, kind, field in (
                    (
                        "validatingadmissionpolicies",
                        "validatingadmissionpolicybindings",
                        "ValidatingAdmissionPolicy",
                        "validations",
                    ),
                    (
                        "mutatingadmissionpolicies",
                        "mutatingadmissionpolicybindings",
                        "MutatingAdmissionPolicy",
                        "mutations",
                    ),
                ):
                    title = plural + "(cluster)[2]"
                    marker = route_command(
                        "resource " + plural + ".admissionregistration.k8s.io/v1"
                    )
                    wait(
                        "admission-policy:" + plural,
                        (title, field.upper(), "owned-a", "owned-b", "live"),
                        since=marker,
                        predicate=lambda display: pair_order(display, ("1", "2"), (0, 1)),
                    )
                    marker = terminal.send(b"g\r")
                    wait(
                        "admission-policy-details:" + plural,
                        (
                            "details(Cluster/owned-a)",
                            "kind: " + kind,
                            "apiVersion: admissionregistration.k8s.io/v1",
                            "sections:",
                        ),
                        since=marker,
                    )
                    marker = terminal.send(b"L")
                    wait(
                        "admission-bindings-link:" + plural,
                        ("links(Cluster/owned-a)", "Bindings declaring this policy", "Available"),
                        since=marker,
                    )
                    marker = terminal.send(b"\r")
                    binding_title = bindings + "(cluster)[1]"
                    wait(
                        "admission-binding-membership:" + plural,
                        (binding_title, "MATCH-RULES", "owned-a", "live"),
                        since=marker,
                        absent=("owned-b", "links("),
                    )
                    marker = terminal.send(b"g\r")
                    wait(
                        "admission-binding-details:" + plural,
                        ("details(Cluster/owned-a)", "kind: " + kind + "Binding", "sections:"),
                        since=marker,
                    )
                    marker = terminal.send(b"L")
                    wait(
                        "admission-current-policy-link:" + plural,
                        ("links(Cluster/owned-a)", "Current named policy", "Available"),
                        since=marker,
                    )
                    marker = terminal.send(b"\r")
                    wait(
                        "admission-current-policy:" + plural,
                        (plural + "(cluster)[1]", "owned-a", "live"),
                        since=marker,
                        absent=("owned-b", "links("),
                    )
                    parent(binding_title, "owned-a")
                    parent(title, "owned-a")
                    families.extend((plural, bindings))
                marker = terminal.resize(40, 12)
                wait(
                    "compact-admission-policy",
                    ("mutatingadmissionpolic", "owned-a"),
                    since=marker,
                )
                marker = terminal.resize(100, 30)
                wait(
                    "wide-admission-policy-return",
                    ("mutatingadmissionpolicies(cluster)[2]", "MUTATIONS", "owned-a", "owned-b"),
                    since=marker,
                )
            else:
                marker = route_command("events")
                wait(
                    "modern-raw-events",
                    ("events(team)[7]", "Raw Events", "Observed", "BackOff"),
                    since=marker,
                )
                marker = terminal.send(b"w")
                wait("warning-filter", ("events(team)[6]", "Warnings", "Raw Events"), since=marker)
                marker = terminal.send(b"t")
                wait("warning-groups", ("events(team)[4]", "Warnings", "Grouped"), since=marker)
                deadline = time.monotonic() + 15
                while not all(
                    text in "\n".join(terminal.screen.display)
                    for text in ("OCCURRENCES", "8 known", "unknown members")
                ):
                    if stopping.is_set():
                        raise asyncio.CancelledError
                    assert time.monotonic() < deadline, (
                        "Native horizontal navigation did not expose occurrence evidence"
                    )
                    terminal.send(b"\x1b[C")
                    terminal.read(0.05)
                wait(
                    "unknown-member-counts",
                    ("events(team)[4]", "OCCURRENCES", "8 known", "unknown members"),
                )
                display = terminal.screen.display
                header = next(index for index, line in enumerate(display) if "OCCURRENCES" in line)
                ordinal = (
                    next(index for index, line in enumerate(display) if "8 known" in line)
                    - header
                    - 1
                )
                assert 0 <= ordinal < 4
                marker = terminal.send(b"g" + b"\x1b[B" * ordinal + b"\x1b[H")
                wait(
                    "selected-group-left-edge",
                    ("events(team)[4]", "NAMESPACE", "BackOff"),
                    since=marker,
                    absent=("OCCURRENCES",),
                )
                wait(
                    "selected-group-complete-counts",
                    ("events(team)[4]", "OCCURRENCES", "8 known", "unknown members"),
                    scroll=True,
                )
                marker = terminal.send(b"\r")
                wait(
                    "exact-real-group-members",
                    ("events(team)[3]", "Group members", "Raw Events", "3 · series", "5 · series"),
                    since=marker,
                    scroll=True,
                )
                marker = terminal.send(b"\x1b")
                wait(
                    "group-parent-restored",
                    ("events(team)[4]", "Grouped", "8 known", "unknown members"),
                    since=marker,
                    absent=("Group members",),
                )
                marker = terminal.send(b"\r")
                wait(
                    "restored-group-selection",
                    ("events(team)[3]", "Group members", "3 · series", "5 · series"),
                    since=marker,
                    scroll=True,
                )
                marker = terminal.send(b"\x1b")
                wait(
                    "second-group-parent",
                    ("events(team)[4]", "Grouped", "8 known"),
                    since=marker,
                    absent=("Group members",),
                )
                marker = terminal.send(b"w")
                wait("all-type-groups", ("events(team)[5]", "All types", "Grouped"), since=marker)
                marker = terminal.send(b"t")
                wait("raw-event-return", ("events(team)[7]", "Raw Events"), since=marker)
                terminal.send(b"\x1b[Hg")
                marker = terminal.send(b"\r")
                wait(
                    "raw-event-inspector",
                    ("details(team/owned-event-0)", "Reported Event observation", "sections:"),
                    since=marker,
                )
                marker = terminal.send(b"L")
                wait(
                    "regarding-link",
                    ("links(team/owned-event-0)", "Regarding object", "Available"),
                    since=marker,
                )
                marker = terminal.send(b"\r")
                wait(
                    "fresh-regarding-pod",
                    ("pods(team)[1]", "owned-start"),
                    since=marker,
                    absent=("links(",),
                )
                parent("events(team)[7]", "BackOff")
                marker = terminal.resize(40, 12)
                wait("compact-events", ("events(team)[7]", "Warning"), since=marker)
                marker = terminal.resize(100, 30)
                wait(
                    "wide-events-return",
                    ("events(team)[7]", "Observed", "Raw Events"),
                    since=marker,
                )
            stage = "quit-and-terminal-restoration"
            terminal.send(b"\x03" if flow == "admission" else b"\x11")
            terminal.finish()
            normal_finish = True
            terminal.save_evidence(evidence)
        stage = "positive-audit-and-actual-module-bindings"
        assert kubeconfig.read_bytes() == before
        assert all(value.encode() not in terminal.transcript for value in _CANARIES)
        log = directory / "kuberich.log"
        if log.exists():
            assert all(value.encode() not in log.read_bytes() for value in _CANARIES)
        audit_events = [json.loads(line) for line in audit.read_text().splitlines()]
        assert audit_events[0] == {"event": "loaded"}
        assert any(event["event"] == "socket.connect" for event in audit_events)
        assert all(event.get("accepted", True) for event in audit_events)
        assert all(event["event"] != "subprocess.Popen" for event in audit_events)
        binding = next(
            event["modules"] for event in audit_events if event["event"] == "source-binding"
        )
        for relative, observed in binding.items():
            assert source[relative] == observed["sha256"], relative
            assert Path(observed["path"]).is_relative_to(ROOT.resolve()) is not installed
        assert "src/kuberich/ui/app.py" in binding
        expected_module = (
            "src/kuberich/ui/events.py"
            if flow == "events"
            else "src/kuberich/domain/curated_admission.py"
            if flow == "admission"
            else "src/kuberich/domain/curated_access.py"
        )
        assert expected_module in binding
        if flow == "families":
            assert "src/kuberich/domain/curated_admission.py" in binding
        controls = _audit_controls(command, directory, environment)
        passed = True
        return {
            "families": families,
            "witnesses": witnesses,
            "audit": audit_events,
            "audit_controls": controls,
            "actual_module_bindings": binding,
            "kubeconfig_unchanged": True,
            "normal_exit": normal_finish,
            "cleanup": terminal.cleanup,
        }
    finally:
        original_failure = sys.exception()
        try:
            if terminal is not None:
                path = output / (evidence + ".ansi")
                path.write_bytes(terminal.transcript)
                path.chmod(0o600)
                if not passed:
                    _private_json(
                        output / (evidence + "-curated.json"),
                        {
                            "result": "failed",
                            "failed_stage": stage,
                            "normal_finish_observed": normal_finish,
                            "screen": terminal.screen.display,
                            "witnesses": witnesses,
                            "completion": terminal.completion,
                            "cleanup": terminal.cleanup,
                            "source": source,
                        },
                    )
                for path in output.glob(evidence + "*.json"):
                    path.chmod(0o600)
        except BaseException as archive_error:
            if original_failure is None:
                raise
            original_failure.add_note(
                "Curated terminal archive failed: " + type(archive_error).__name__
            )


async def terminal_curated(
    command, directory, *, evidence, flow, size=(100, 30), wheel_sha256=None
):
    """Own HTTP and a blocking PTY without blocking the fixture's async server."""
    assert flow in {"families", "events", "admission"}
    directory.mkdir(parents=True, exist_ok=True)
    source = _hashes()
    api = CuratedTerminalApi()
    with tempfile.TemporaryDirectory(prefix="kuberich-curated-pty-", dir="/tmp") as temporary:
        outside = Path(temporary).resolve()
        assert not outside.is_relative_to(ROOT.resolve())
        async with curated_resources_api(directory, api) as (url, _):
            stopping = threading.Event()
            worker = asyncio.create_task(
                asyncio.to_thread(
                    _drive,
                    list(command),
                    outside,
                    url,
                    api,
                    evidence=evidence,
                    flow=flow,
                    size=size,
                    source=source,
                    installed=wheel_sha256 is not None,
                    stopping=stopping,
                )
            )
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                stopping.set()
                await finish_owned(asyncio.gather(worker, return_exceptions=True))
                raise
        requests = [
            {"method": item.method, "path": item.path, "query": item.query, "accept": item.accept}
            for item in api.requests
        ]
        assert all(item["method"] == "GET" for item in requests)
        assert api.authenticated_reads == len(requests) and requests
        assert not api.active_requests and not any(watch.queues for watch in api.watches.values())
        if flow == "families":
            for name in _CASES:
                resource = api.resource(name)
                path = resource.path("team" if resource.namespaced else None)
                assert any(
                    item["path"] == path and "watch" not in item["query"] for item in requests
                ), name
                assert any(
                    item["path"] == path and item["query"].get("watch") == "true"
                    for item in requests
                ), name
            target = api.resource("deployments", group="apps").path("team") + "/owned-workload"
            assert any(item["path"] == target for item in requests)
        elif flow == "admission":
            for plural in (
                "validatingadmissionpolicies",
                "validatingadmissionpolicybindings",
                "mutatingadmissionpolicies",
                "mutatingadmissionpolicybindings",
            ):
                resource = api.resource(plural, version="v1")
                path = resource.path(None)
                assert any(
                    item["path"] == path and "watch" not in item["query"] for item in requests
                )
                assert any(
                    item["path"] == path and item["query"].get("watch") == "true"
                    for item in requests
                )
                assert any(
                    item["path"] == path + "/owned-a" and "watch" not in item["query"]
                    for item in requests
                )
        else:
            modern = "/apis/events.k8s.io/v1/namespaces/team/events"
            assert any(item["path"] == modern and "watch" in item["query"] for item in requests)
            assert any(item["path"] == modern + "/owned-event-0" for item in requests)
            assert any(
                item["path"] == "/api/v1/namespaces/team/pods/owned-start" for item in requests
            )
        assert _hashes() == source, "Curated terminal inputs changed during qualification"
        result.update(
            {
                "result": "passed",
                "flow": flow,
                "size": size,
                "wheel_sha256": wheel_sha256,
                "entry_command": command,
                "cwd_outside_checkout": True,
                "source": source,
                "requests": requests,
                "http_drained": True,
                "native_availability": "Synthetic owned HTTP schema vectors only",
            }
        )
        _private_json(ROOT / "artifacts" / "terminal" / (evidence + "-curated.json"), result)
        return copy.deepcopy(result)
