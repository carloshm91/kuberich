"""Select complete test layers and keep shared evidence in one xdist worker."""

import fcntl
import os
import tempfile
from collections.abc import Generator, Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Protocol

import pytest

from tests.support.parts import GROUPS, UNKNOWN_SECONDS, load_timings

LAYERS = frozenset({"unit", "contract", "ui", "terminal", "packaging", "quality", "kind"})
FAST_LAYERS = frozenset({"unit", "contract", "ui"})
RUN_DIRECTORY = pytest.StashKey[tempfile.TemporaryDirectory[str]]()
WINDOW = "KUBERICH_TEST_REFERENCE_WINDOW"
ORCHESTRATOR = "KUBERICH_TEST_REFERENCE_OWNER"
HELD = "KUBERICH_TEST_REFERENCE_HELD"
RUNTIME_MODES = ("KUBERICH_TEST_BACKEND_RUNTIME", "KUBERICH_TEST_AGGREGATE_RUNTIME")


class WorkerNode(Protocol):
    """Public fields passed to pytest-xdist's configure-node hook."""

    config: pytest.Config
    workerinput: dict[str, object]


def pytest_configure(config: pytest.Config) -> None:
    config.stash[RUN_DIRECTORY] = tempfile.TemporaryDirectory(prefix="kuberich-test-window-")
    directory = getattr(config, "workerinput", {}).get("kuberich_reference_window")
    if directory is None:
        inherited = (
            os.environ.get(WINDOW) if any(name in os.environ for name in RUNTIME_MODES) else None
        )
        directory = inherited or config.stash[RUN_DIRECTORY].name
    os.environ[WINDOW] = directory


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node: WorkerNode) -> None:
    node.workerinput["kuberich_reference_window"] = node.config.stash[RUN_DIRECTORY].name


def pytest_unconfigure(config: pytest.Config) -> None:
    if RUN_DIRECTORY in config.stash:
        config.stash[RUN_DIRECTORY].cleanup()


@contextmanager
def reference_window(directory: Path, *, exclusive: bool) -> Iterator[None]:
    """Drain ordinary tests before a timing control, without starving the writer.

    The entrance lock stops new readers while the timing owner waits for existing
    readers to finish. Locks are released by the kernel even if a worker dies.
    This directory belongs to one pytest controller, never to another test run.
    """
    with (directory / "entrance").open("a") as entrance, (directory / "active").open("a") as active:
        fcntl.flock(entrance, fcntl.LOCK_EX)
        fcntl.flock(active, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        if not exclusive:
            fcntl.flock(entrance, fcntl.LOCK_UN)
        try:
            yield
        finally:
            fcntl.flock(active, fcntl.LOCK_UN)
            fcntl.flock(entrance, fcntl.LOCK_UN)


class ReferenceBatch:
    """Keep adjacent timing controls isolated; share the coverage replay window."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.stack = ExitStack()
        self.exclusive: bool | None = None

    def acquire(self, *, exclusive: bool) -> None:
        if exclusive != self.exclusive:
            self.stack.close()
            self.stack.enter_context(reference_window(self.directory, exclusive=exclusive))
            self.exclusive = exclusive


ACTIVE_BATCH: ContextVar[ReferenceBatch | None] = ContextVar("reference_batch", default=None)


@contextmanager
def runtime_environment(
    environment: dict[str, str], *, exclusive: bool
) -> Iterator[dict[str, str]]:
    """Reserve CPU before the subprocess deadline starts; the child inherits it.

    Only the actual runtime orchestrators set this owner. Mocked tooling tests
    hold an ordinary read lock and must not try to upgrade it recursively.
    """
    directory = os.environ.get(ORCHESTRATOR)
    if directory is None:
        yield environment
        return
    if (batch := ACTIVE_BATCH.get()) is not None:
        batch.acquire(exclusive=exclusive)
        yield {**environment, HELD: "1"}
        return
    with reference_window(Path(directory), exclusive=exclusive):
        yield {**environment, HELD: "1"}


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Generator[None, bool | None, bool | None]:
    directory = os.environ.get(WINDOW)
    if directory is None:
        return (yield)
    mode = next((os.environ[name] for name in RUNTIME_MODES if name in os.environ), None)
    if mode is not None and os.environ.get(HELD) == "1":
        return (yield)
    if item.get_closest_marker("runtime_control") is not None and mode is None:
        # Acquire around each child, before its original subprocess deadline.
        previous = os.environ.get(ORCHESTRATOR)
        os.environ[ORCHESTRATOR] = directory
        batch = ReferenceBatch(Path(directory))
        token = ACTIVE_BATCH.set(batch)
        try:
            return (yield)
        finally:
            batch.stack.close()
            ACTIVE_BATCH.reset(token)
            if previous is None:
                os.environ.pop(ORCHESTRATOR, None)
            else:
                os.environ[ORCHESTRATOR] = previous
    with reference_window(
        Path(directory),
        exclusive=item.get_closest_marker("performance") is not None and mode != "coverage",
    ):
        return (yield)


def group_for(name: str) -> str:
    """Keep every file together, including session fixtures shared across files."""
    return next(("+".join(sorted(group)) for group in GROUPS if name in group), name)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark before pytest's -m deselection and xdist's loadgroup collection hook."""
    timings = load_timings()
    for item in items:
        name = item.path.relative_to(config.rootpath).as_posix()
        parts = Path(name).parts
        if len(parts) >= 3 and parts[0] == "tests" and parts[1] in LAYERS:
            layer = parts[1]
            item.add_marker(getattr(pytest.mark, layer))
            if layer in FAST_LAYERS:
                item.add_marker(pytest.mark.fast)
        if config.getoption("numprocesses", default=0) or hasattr(config, "workerinput"):
            group = (
                "runtime-controls"
                if item.get_closest_marker("runtime_control")
                else group_for(name)
            )
            item.add_marker(pytest.mark.xdist_group(group))

    # Start runtime owners and long files first. The orchestrators share one
    # worker so a waiting timing writer cannot serialize the coverage replay.
    # Each other file keeps its original order and one evidence owner.
    def cost(item: pytest.Item) -> tuple[bool, float]:
        name = item.path.relative_to(config.rootpath).as_posix()
        if (control := item.get_closest_marker("runtime_control")) is not None:
            order = control.kwargs.get("order", 0)
            if type(order) is not int:
                raise pytest.UsageError("A runtime control order must be an integer.")
            return True, -float(order)
        return (
            False,
            sum(timings.get(member, UNKNOWN_SECONDS) for member in group_for(name).split("+")),
        )

    items.sort(key=cost, reverse=True)
