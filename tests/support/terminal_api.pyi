"""Typed boundary for the owned API fixture shared by installed-artifact verifiers."""

import queue
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

def config(path: Path, server: str, user: dict[str, Any]) -> Path: ...

class Server(ThreadingHTTPServer):
    fail_watches: threading.Event
    stopping: threading.Event
    quiet_watches: threading.Event
    renewed: threading.Event
    watch_versions: list[str]
    watch_durations: list[int]
    watch_lock: threading.Lock
    pod_events: queue.Queue[dict[str, Any]]
    pod_table: threading.Event
    shell_containers: tuple[str, ...]
    pod_get_status: int
    pod_requested: threading.Event
    pod_gate: threading.Event
    namespace_requested: threading.Event
    namespace_gate: threading.Event
    impersonation: tuple[str, tuple[str, ...]] | None
    identity_verified: threading.Event
    def __init__(self) -> None: ...
